"""腾讯行情抓取层：后复权日线，分段抓取 + WAF 重试 + 连续性校验。

接口实测结论：
  1) GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
         ?param={code},day,{start},{end},{count},{fq}
  2) 单次最多约 640 根 K 线，必须分段抓取。
  3) 该接口**仅支持 day 频率**，请求 month 会返回 HTTP 501；
     月线数据在本项目内由日线重采样得到。
  4) 早于上市日的区间会返回 {"day": []} 空数组，因此采用
     **从最新一段往前回溯** 的策略，遇到空段即可判定已到上市首日。
  5) 接口存在 WAF 随机拦截（返回 HTML 而非 JSON），需带 Referer 并重试。
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests

from config import (
    CONTINUITY_JUMP,
    EARLIEST_DATE,
    MAX_RETRIES,
    PAGE_SIZE,
    SEGMENT_YEARS,
    TENCENT_HEADERS,
    TENCENT_KLINE_URL,
)

# 6 位代码中以 000 开头但属于「中证/上证指数」的白名单（其余 000xxx 视为深市股票）
_SH_INDEX_PREFIX = {
    "000001", "000016", "000300", "000688", "000852", "000905",
    "000906", "000922", "000985", "000991", "000992", "000993",
}
_SH_INDEX_CODE = {"000009", "000010", "000011", "000012", "000013"}


class FetchError(RuntimeError):
    """抓取失败。"""


def normalize_code(raw: str) -> str:
    """把用户输入的代码规范成 shXXXXXX / szXXXXXX 形式。

    支持：510500 / SH510500 / sh510500 / 000905 / sz159915 等写法。
    """
    if not raw:
        raise FetchError("代码不能为空")
    code = raw.strip().lower().replace(" ", "")
    if code.startswith(("sh", "sz")):
        prefix, digits = code[:2], code[2:]
    else:
        prefix, digits = "", code
    if not digits.isdigit():
        raise FetchError(f"代码格式不正确：{raw}")
    if prefix:
        return prefix + digits
    if len(digits) != 6:
        raise FetchError(f"代码长度应为 6 位：{raw}")
    if digits.startswith(("6", "5", "9")):
        return "sh" + digits
    if digits.startswith("000"):
        # 000xxx 既有深市股票（平安银行 000001 与上证指数同名），
        # 命中白名单按沪市指数处理，其余按深市股票处理
        return ("sh" if digits in _SH_INDEX_PREFIX | _SH_INDEX_CODE else "sz") + digits
    if digits.startswith(("3", "1", "2", "0")):
        return "sz" + digits
    return "sh" + digits


def _iter_segments(start_year: int, end_year: int) -> List[Tuple[str, str]]:
    """按 SEGMENT_YEARS 年切分时间区间，返回 [(start, end), ...] 升序。"""
    segs: List[Tuple[str, str]] = []
    y = start_year
    while y <= end_year:
        seg_end = min(y + SEGMENT_YEARS - 1, end_year)
        segs.append((f"{y}-01-01", f"{seg_end}-12-31"))
        y = seg_end + 1
    return segs


def _request_segment(session: requests.Session, code: str, start: str, end: str) -> Optional[dict]:
    """请求单个区间，带 WAF 重试。返回 data[code] 字典；空段返回 None。"""
    param = f"{code},day,{start},{end},{PAGE_SIZE},hfq"
    url = f"{TENCENT_KLINE_URL}?param={param}"
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=TENCENT_HEADERS, timeout=20)
            text = resp.text
            if not text.lstrip().startswith("{"):
                # 命中了腾讯 WAF 拦截页
                last_err = "WAF拦截"
                time.sleep(0.8 * (attempt + 1))
                continue
            payload = resp.json()
            if payload.get("code") != 0:
                last_err = f"接口返回 code={payload.get('code')} {payload.get('msg')}"
                time.sleep(0.5 * (attempt + 1))
                continue
            return payload.get("data", {}).get(code) or {}
        except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(0.8 * (attempt + 1))
    raise FetchError(f"抓取 {code} {start}~{end} 失败：{last_err}")


def _extract_bars(segment: dict) -> List[list]:
    """从响应片段中取出 K 线数组。优先后复权，其次前复权，最后不复权（指数）。"""
    for key in ("hfqday", "qfqday", "day"):
        rows = segment.get(key)
        if rows:
            return rows
    return []


def _extract_name(segment: dict) -> str:
    try:
        qt = segment.get("qt") or {}
        for _, v in qt.items():
            if isinstance(v, list) and len(v) > 1 and isinstance(v[1], str):
                return v[1]
    except Exception:  # noqa: BLE001
        pass
    return ""


def fetch_daily_bars(
    code: str,
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[List[dict], str, List[str]]:
    """抓取全历史后复权日线。

    返回 (bars, name, warnings)
      bars: [{"date": "2013-03-15", "open":..., "close":..., "high":..., "low":..., "volume":...}, ...] 升序
    """
    log = logger or (lambda _m: None)
    today = dt.date.today()
    segments = _iter_segments(int(EARLIEST_DATE[:4]), today.year)
    session = requests.Session()
    bars_by_date: Dict[str, dict] = {}
    name = ""
    warnings: List[str] = []

    # 从最新一段往回抓：一旦某段为空，说明更早的区间都在上市之前
    for start, end in reversed(segments):
        seg = _request_segment(session, code, start, end)
        rows = _extract_bars(seg or {})
        if not name:
            name = _extract_name(seg or {})
        if not rows:
            log(f"  {start}~{end}: 无数据，判定已早于上市首日，停止回溯")
            break
        log(f"  {start}~{end}: {len(rows)} 根")
        for r in rows:
            if len(r) < 5:
                continue
            try:
                d = str(r[0])[:10]
                bars_by_date[d] = {
                    "date": d,
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "volume": float(r[5]) if len(r) > 5 else 0.0,
                }
            except (TypeError, ValueError):
                continue
        time.sleep(0.35)  # 温和限速，降低被 WAF 拦截概率

    if not bars_by_date:
        raise FetchError(f"未抓取到 {code} 的任何K线数据，请确认代码是否正确")

    bars = [bars_by_date[d] for d in sorted(bars_by_date)]

    # 连续性校验：拼接处若出现异常跳变（>CONTINUITY_JUMP）则告警
    prev = None
    for b in bars:
        if prev is not None and prev > 0:
            jump = abs(b["close"] / prev - 1)
            if jump > CONTINUITY_JUMP:
                warnings.append(
                    f"{b['date']} 前后收盘跳变 {jump * 100:.1f}%，可能存在数据接缝"
                )
        prev = b["close"]

    log(f"  合计 {len(bars)} 根，{bars[0]['date']} ~ {bars[-1]['date']}")
    return bars, name, warnings
