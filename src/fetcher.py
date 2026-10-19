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
    PRIMARY_ATTEMPTS,
    SEGMENT_YEARS,
    TENCENT_HEADERS,
    TENCENT_KLINE_FALLBACK_URL,
    TENCENT_KLINE_URL,
    TENCENT_QUOTE_URL,
)

# 000xxx 是「中证/上证指数」与「深市主板股票」的重叠区段，同一数字两者可并存：
#   000001 -> 上证指数 sh000001 / 平安银行 sz000001
#   000510 -> 中证A500 sh000510 / 新金路  sz000510
# 纯规则与固定白名单都无法覆盖（新指数会不断发布），故改为探测：
# sh 下存在该证券则按沪市指数解释，否则按深市股票解释。探测结果按代码缓存。
_MARKET_CACHE: Dict[str, str] = {}


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
        # 000xxx 为指数/深市股票重叠区，纯规则默认按中证指数（本工具主场景），
        # 精确判定交给 resolve_code() 的市场探测。
        return "sh" + digits
    if digits.startswith(("3", "1", "2", "0")):
        return "sz" + digits
    return "sh" + digits


def lookup_name(code: str) -> Optional[str]:
    """取证券名称。

    返回：证券名称 / ""（该代码确实不存在）/ None（网络或 WAF 导致无法确定）。
    """
    for attempt in range(3):
        try:
            resp = requests.get(
                TENCENT_QUOTE_URL + code, headers=TENCENT_HEADERS, timeout=8
            )
            resp.encoding = "gbk"
            text = (resp.text or "").strip()
        except Exception:  # noqa: BLE001
            time.sleep(0.8 * (attempt + 1))
            continue
        if not text.startswith("v_"):
            time.sleep(0.8 * (attempt + 1))  # 大概率被 WAF 拦截，退避重试
            continue
        body = text.split('"')[1] if '"' in text else ""
        if not body:
            return ""  # 该代码不存在
        parts = body.split("~")
        return parts[1] if len(parts) > 1 and parts[1] else ""
    return None


def _resolve_000_market(digits: str) -> str:
    """判定 000xxx 归属沪市指数还是深市股票，结果按代码缓存，避免重复探测。"""
    cached = _MARKET_CACHE.get(digits)
    if cached:
        return cached
    market = "sh"  # 探测不出结果时按指数兜底
    for _ in range(3):
        name = lookup_name("sh" + digits)
        if name is None:
            continue  # lookup_name 内部已退避重试
        market = "sh" if name else "sz"
        break
    _MARKET_CACHE[digits] = market
    return market


def resolve_code(raw: str) -> str:
    """规范化代码，并对 000xxx 重叠区做市场探测。

    用户显式带 sh/sz 前缀时完全尊重输入，不做探测。
    """
    cleaned = (raw or "").strip().lower().replace(" ", "")
    explicit = cleaned.startswith(("sh", "sz"))
    code = normalize_code(cleaned)
    if explicit or not code[2:].startswith("000"):
        return code
    return _resolve_000_market(code[2:]) + code[2:]


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
    """请求单个区间，带 WAF 重试；主接口受挫时自动切备用接口。

    两个接口的后复权数据已逐日比对一致，可互为备份，避免单一接口被
    腾讯 WAF 拦截时整个查询失败。
    """
    param = f"{code},day,{start},{end},{PAGE_SIZE},hfq"
    last_err = ""
    for idx, base in enumerate((TENCENT_KLINE_URL, TENCENT_KLINE_FALLBACK_URL)):
        tries = PRIMARY_ATTEMPTS if idx == 0 else MAX_RETRIES
        url = f"{base}?param={param}"
        for attempt in range(tries):
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
        # 主接口重试耗尽，换备用接口继续
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
