"""SQLite 缓存层：把抓取到的后复权日线落地，避免重复请求腾讯接口。

后复权序列的特性是「历史值不随新的分红除权而改变」，因此增量抓取是安全的；
但仍会在合并后做接缝校验，一旦发现异常跳变即回退为全量重抓。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Dict, List, Optional, Tuple

from config import CACHE_TTL_HOURS, CONTINUITY_JUMP, DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kline (
                code   TEXT NOT NULL,
                date   TEXT NOT NULL,
                open   REAL, close REAL, high REAL, low REAL, volume REAL,
                PRIMARY KEY (code, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                code       TEXT PRIMARY KEY,
                name       TEXT,
                first_date TEXT,
                last_date  TEXT,
                bar_count  INTEGER,
                warnings   TEXT,
                updated_at TEXT
            )
            """
        )


def load_bars(code: str) -> List[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, open, close, high, low, volume FROM kline "
            "WHERE code = ? ORDER BY date",
            (code,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_bars(code: str, name: str, bars: List[dict], warnings: Optional[List[str]] = None) -> None:
    if not bars:
        return
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute("DELETE FROM kline WHERE code = ?", (code,))
        conn.executemany(
            "INSERT OR REPLACE INTO kline (code, date, open, close, high, low, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (code, b["date"], b["open"], b["close"], b["high"], b["low"], b.get("volume", 0.0))
                for b in bars
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (code, name, first_date, last_date, bar_count, warnings, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                code,
                name,
                bars[0]["date"],
                bars[-1]["date"],
                len(bars),
                " | ".join(warnings or []),
                now,
            ),
        )


def merge_bars(code: str, name: str, tail: List[dict]) -> Tuple[List[dict], bool]:
    """把新抓到的尾部数据合并进缓存。返回 (合并后的bars, 是否发生接缝异常)。"""
    cached = load_bars(code)
    if not cached or not tail:
        return (tail or cached), False

    merged: Dict[str, dict] = {b["date"]: b for b in cached}
    cached_last = cached[-1]["date"]
    # 新数据必须能覆盖缓存末尾，否则说明中间有缺口
    if tail[0]["date"] > cached_last:
        return cached, True
    for b in tail:
        merged[b["date"]] = b

    bars = [merged[d] for d in sorted(merged)]

    # 接缝校验：新老数据交界处若跳变异常，判定为因子不一致，需要全量重抓
    seam_prev = None
    for b in bars:
        if seam_prev is not None and seam_prev > 0:
            if abs(b["close"] / seam_prev - 1) > CONTINUITY_JUMP:
                return cached, True
        seam_prev = b["close"]

    save_bars(code, name, bars)
    return bars, False


def get_meta(code: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM meta WHERE code = ?", (code,)).fetchone()
    return dict(row) if row else None


def is_fresh(code: str, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    meta = get_meta(code)
    if not meta or not meta.get("bar_count"):
        return False
    last_date = meta.get("last_date") or ""
    try:
        updated = dt.datetime.fromisoformat(meta["updated_at"])
    except (TypeError, ValueError):
        return False
    if dt.datetime.now() - updated > dt.timedelta(hours=ttl_hours):
        return False
    # 若缓存最后一天距离今天已超过 4 个自然日，视为需要更新
    try:
        gap = (dt.date.today() - dt.date.fromisoformat(last_date)).days
    except (TypeError, ValueError):
        return False
    return gap <= 4


def clear(code: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM kline WHERE code = ?", (code,))
        conn.execute("DELETE FROM meta WHERE code = ?", (code,))
