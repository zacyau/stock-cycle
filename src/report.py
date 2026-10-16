"""数据编排：缓存 → 抓取 → 指标 → 模板载荷。"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Dict, Optional

from config import DEFAULT_CODE, SWING_THRESHOLDS
from src import cache, indicators
from src.fetcher import FetchError, fetch_daily_bars, normalize_code


def load_bars(
    code: str,
    refresh: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> Dict:
    """取K线：优先缓存，必要时抓取；抓取失败时回退到已有缓存。"""
    log = logger or (lambda _m: None)
    cache.init_db()

    if refresh:
        cache.clear(code)
        log(f"已清除 {code} 的本地缓存")

    if cache.is_fresh(code):
        bars = cache.load_bars(code)
        meta = cache.get_meta(code) or {}
        if bars:
            log(f"命中缓存：{len(bars)} 根K线")
            return {
                "bars": bars,
                "name": meta.get("name", ""),
                "warnings": [w for w in (meta.get("warnings") or "").split(" | ") if w],
                "from_cache": True,
                "fetched_at": meta.get("updated_at", ""),
            }

    try:
        bars, name, warnings = fetch_daily_bars(code, logger=log)
        cache.save_bars(code, name, bars, warnings)
        return {
            "bars": bars,
            "name": name,
            "warnings": warnings,
            "from_cache": False,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    except FetchError as exc:
        bars = cache.load_bars(code)
        if bars:
            meta = cache.get_meta(code) or {}
            log(f"抓取失败，改用本地缓存：{exc}")
            return {
                "bars": bars,
                "name": meta.get("name", ""),
                "warnings": [f"抓取失败，展示的是本地缓存：{exc}"],
                "from_cache": True,
                "fetched_at": meta.get("updated_at", ""),
            }
        raise


def get_payload(
    code_raw: str = DEFAULT_CODE,
    refresh: bool = False,
    since: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> Dict:
    code = normalize_code(code_raw)
    bundle = load_bars(code, refresh=refresh, logger=logger)
    bars = bundle["bars"]
    if not bars:
        raise FetchError(f"{code} 没有可用数据")

    payload = indicators.build_payload(bars, SWING_THRESHOLDS, since)
    payload["meta"] = {
        "code": code,
        "name": bundle["name"] or code,
        "first_date": bars[0]["date"],
        "last_date": bars[-1]["date"],
        "bar_count": len(bars),
        "from_cache": bundle["from_cache"],
        "fetched_at": bundle["fetched_at"],
        "warnings": bundle["warnings"],
        "source": "腾讯行情（后复权）",
        "thresholds": SWING_THRESHOLDS,
    }
    return payload
