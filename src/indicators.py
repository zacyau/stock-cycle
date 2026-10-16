"""指标计算层。

包含：
  1. 后复权净值序列（起点归一化为 1.0）
  2. 长期年化收益 CAGR
  3. 回撤水下曲线、历史最大回撤的幅度 / 区间 / 时长 / 修复情况
  4. 牛熊摆动法阶段划分（阈值可调，对齐参考图二的 ±20% 摆动口径）
  5. 多时间尺度涨跌统计
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from config import PERIOD_CARDS


# ------------------------------------------------------------------ 基础工具
def to_frame(bars: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date"]).set_index("date").sort_index()
    return df[["open", "close", "high", "low", "volume"]].astype(float)


def months_between(d1: str, d2: str) -> int:
    a, b = dt.date.fromisoformat(d1), dt.date.fromisoformat(d2)
    return (b.year - a.year) * 12 + (b.month - a.month)


def days_between(d1: str, d2: str) -> int:
    return (dt.date.fromisoformat(d2) - dt.date.fromisoformat(d1)).days


def _round(value: Optional[float], nd: int = 4) -> Optional[float]:
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(fv) or math.isinf(fv):
        return None
    return round(fv, nd)


# ------------------------------------------------------------------ ① 净值与年化
def build_nav(close: pd.Series) -> pd.Series:
    """归一化净值：起点 = 1.0。"""
    return close / float(close.iloc[0])


def compute_cagr(nav: pd.Series) -> Dict[str, Optional[float]]:
    start_date = nav.index[0].date()
    end_date = nav.index[-1].date()
    span_days = (end_date - start_date).days
    total = float(nav.iloc[-1])
    years = span_days / 365.25 if span_days > 0 else 0.0
    cagr = (total ** (1 / years) - 1) if years > 0 and total > 0 else None
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "years": _round(years, 2),
        "total_multiple": _round(total, 3),
        "total_return_pct": _round((total - 1) * 100, 2),
        "cagr_pct": _round(cagr * 100, 2) if cagr is not None else None,
    }


# ------------------------------------------------------------------ ② 回撤
def compute_drawdown(nav: pd.Series) -> Dict:
    """返回水下曲线与历史最大回撤的完整信息。"""
    running_peak = nav.cummax()
    dd = nav / running_peak - 1.0

    trough_ts = dd.idxmin()
    max_dd = float(dd.loc[trough_ts])

    # 该回撤对应的峰值日：谷底之前净值最高的那一天
    peak_ts = nav.loc[:trough_ts].idxmax()
    peak_value = float(nav.loc[peak_ts])

    # 修复日：谷底之后净值首次重新站上峰值
    after = nav.loc[trough_ts:]
    recovered = after[after >= peak_value]
    recover_ts = recovered.index[0] if len(recovered) else None

    end_ts = recover_ts or nav.index[-1]
    duration_days = (end_ts.date() - peak_ts.date()).days
    decline_days = (trough_ts.date() - peak_ts.date()).days

    # 当前所处水位的参照峰值：最后一个「创出历史新高」的交易日
    peak_now = float(running_peak.iloc[-1])
    now_peak_ts = running_peak[running_peak >= peak_now - 1e-12].index[-1]

    return {
        "series": [round(float(v) * 100, 2) for v in dd.values],
        "max_drawdown_pct": _round(max_dd * 100, 2),
        "peak_date": peak_ts.date().isoformat(),
        "peak_nav": _round(peak_value, 3),
        "trough_date": trough_ts.date().isoformat(),
        "trough_nav": _round(float(nav.loc[trough_ts]), 3),
        "recover_date": recover_ts.date().isoformat() if recover_ts is not None else None,
        "recovered": recover_ts is not None,
        "duration_days": duration_days,
        "duration_months": round(duration_days / 30.44, 1),
        "decline_days": decline_days,
        "decline_months": round(decline_days / 30.44, 1),
        "current_drawdown_pct": _round(float(dd.iloc[-1]) * 100, 2),
        "current_peak_date": now_peak_ts.date().isoformat(),
        "days_since_peak": (nav.index[-1].date() - now_peak_ts.date()).days,
    }


# ------------------------------------------------------------------ ③ 牛熊摆动法
def swing_phases(points: Sequence[Tuple[str, float]], threshold: float) -> List[Dict]:
    """±threshold 摆动法划分牛熊阶段。

    规则（对齐参考图二）：
      · 自峰值下跌超过 threshold → 确认进入熊市，前一段在峰值处结束
      · 自谷底上涨超过 threshold → 确认进入牛市，前一段在谷底处结束
      · 末尾尚未被反向摆动确认的一段，按自身涨跌方向归类，confirmed=False
    """
    n = len(points)
    if n < 2:
        return []

    raw: List[Dict] = []

    def make(kind: str, i: int, j: int, confirmed: bool) -> Dict:
        d0, p0 = points[i]
        d1, p1 = points[j]
        change = (p1 / p0 - 1.0) if p0 else 0.0
        span_days = max(days_between(d0, d1), 1)
        years = span_days / 365.25
        annualized = (p1 / p0) ** (1 / years) - 1 if p0 > 0 and p1 > 0 and years > 0 else 0.0
        return {
            "type": kind,
            "start": d0,
            "end": d1,
            "months": months_between(d0, d1),
            "days": span_days,
            "change_pct": _round(change * 100, 2),
            "annualized_pct": _round(annualized * 100, 2),
            "confirmed": confirmed,
            "_i": i,
            "_j": j,
        }

    state = "bull"
    start_idx = 0
    peak_idx = 0
    trough_idx = 0

    for i in range(n):
        px = points[i][1]
        if state == "bull":
            if px >= points[peak_idx][1]:
                peak_idx = i
            elif points[peak_idx][1] > 0 and px / points[peak_idx][1] - 1 <= -threshold:
                raw.append(make("bull", start_idx, peak_idx, True))
                state = "bear"
                start_idx = peak_idx
                trough_idx = i
        else:  # bear
            if px <= points[trough_idx][1]:
                trough_idx = i
            elif points[trough_idx][1] > 0 and px / points[trough_idx][1] - 1 >= threshold:
                raw.append(make("bear", start_idx, trough_idx, True))
                state = "bull"
                start_idx = trough_idx
                peak_idx = i

    # 收尾：末段尚未被反向摆动确认，按自身涨跌方向归类
    last_idx = n - 1
    if last_idx > start_idx:
        seg_up = points[last_idx][1] >= points[start_idx][1]
        raw.append(make("bull" if seg_up else "bear", start_idx, last_idx, False))

    # 标注每个牛市段是否创出历史新高（段内最高 > 该段开始前的历史最高）
    prev_max = points[0][1]
    phases: List[Dict] = []
    for ph in raw:
        i, j = ph.pop("_i"), ph.pop("_j")
        seg_max = max(p for _d, p in points[i: j + 1])
        if ph["type"] == "bull":
            ph["new_high"] = bool(seg_max > prev_max)
            ph["peak_price"] = _round(seg_max, 4)
        else:
            ph["new_high"] = False
            ph["peak_price"] = _round(seg_max, 4)
        prev_max = max(prev_max, seg_max)
        phases.append(ph)

    return phases


def swing_stats(phases: List[Dict], total_months: int) -> Dict:
    bulls = [p for p in phases if p["type"] == "bull"]
    bears = [p for p in phases if p["type"] == "bear"]
    bull_months = sum(p["months"] for p in bulls)
    bear_months = sum(p["months"] for p in bears)
    span = bull_months + bear_months or 1
    return {
        "bull_count": len(bulls),
        "bear_count": len(bears),
        "bull_months": bull_months,
        "bear_months": bear_months,
        "total_months": total_months,
        "bull_avg_months": round(bull_months / len(bulls), 1) if bulls else 0.0,
        "bear_avg_months": round(bear_months / len(bears), 1) if bears else 0.0,
        "bear_share_pct": round(bear_months / span * 100, 1),
        "bull_new_high_count": sum(1 for p in bulls if p.get("new_high")),
    }


# ------------------------------------------------------------------ ④ 多时间尺度涨跌
def _base_index(close: pd.Series, target: dt.date) -> int:
    """找到 <= target 的最后一个交易日下标；若全都晚于 target 则返回 0。"""
    idx = int(close.index.searchsorted(pd.Timestamp(target), side="right")) - 1
    return max(idx, 0)


def period_returns(close: pd.Series, cards: List[dict]) -> List[Dict]:
    asof: dt.date = close.index[-1].date()
    current = float(close.iloc[-1])
    first_date = close.index[0].date()
    out: List[Dict] = []

    def unavailable(card: dict, note: str) -> Dict:
        return {
            "key": card["key"], "label": card["label"], "available": False,
            "note": note, "pct": None, "base_date": None, "base_price": None,
            "direction": "flat",
        }

    for card in cards:
        kind = card["kind"]
        base_idx: Optional[int] = None
        note = ""

        if kind == "window":
            target = asof - dt.timedelta(days=int(card["days"]))
            if target < first_date:
                out.append(unavailable(card, "数据不足"))
                continue
            base_idx = _base_index(close, target)
            note = f"基准 {close.index[base_idx].date().isoformat()}"

        elif kind == "ytd":
            jan1 = dt.date(asof.year, 1, 1)
            if jan1 <= first_date:
                out.append(unavailable(card, "数据不足"))
                continue
            base_idx = _base_index(close, jan1 - dt.timedelta(days=1))
            note = f"{asof.year - 1} 年末"

        elif kind == "ath":
            base_idx = int(np.argmax(close.values))
            note = "历史最高收盘"

        elif kind == "since":
            raw_date = card.get("date") or card.get("default")
            try:
                target = dt.date.fromisoformat(str(raw_date))
            except (TypeError, ValueError):
                out.append(unavailable(card, "日期无效"))
                continue
            if target < first_date or target > asof:
                out.append(unavailable(card, "日期超出区间"))
                continue
            base_idx = _base_index(close, target)
            note = f"基准 {close.index[base_idx].date().isoformat()}"

        if base_idx is None:
            continue

        base_price = float(close.iloc[base_idx])
        pct = (current / base_price - 1) * 100 if base_price else 0.0
        out.append({
            "key": card["key"],
            "label": card["label"],
            "available": True,
            "pct": _round(pct, 2),
            "base_date": close.index[base_idx].date().isoformat(),
            "base_price": _round(base_price, 4),
            "current": _round(current, 4),
            "note": note,
            "direction": "up" if pct > 0 else ("down" if pct < 0 else "flat"),
        })

    return out


# ------------------------------------------------------------------ 汇总
def build_payload(bars: List[dict], thresholds: List[int], custom_since: Optional[str] = None) -> Dict:
    """把原始日线加工成模板所需的全部数据。"""
    df = to_frame(bars)
    close = df["close"]
    nav = build_nav(close)
    dates = [d.date().isoformat() for d in nav.index]

    # 月线：每月最后一个交易日的收盘价（对齐参考图二的月度数据口径）
    monthly_close = close.resample("ME").last().dropna()
    # 最后一个未走完的月份，索引改用真实最后交易日，避免时间轴超出实际数据
    if len(monthly_close) and monthly_close.index[-1].date() > close.index[-1].date():
        stamps = list(monthly_close.index)
        stamps[-1] = close.index[-1]
        monthly_close.index = pd.DatetimeIndex(stamps)
    monthly_nav = build_nav(monthly_close)
    monthly_points = [(d.date().isoformat(), float(v)) for d, v in monthly_nav.items()]
    daily_points = [(d.date().isoformat(), float(v)) for d, v in nav.items()]

    dd = compute_drawdown(nav)

    # 预先算好所有「频率 × 阈值」组合，前端切换时零请求
    swings: Dict[str, Dict] = {}
    for freq, pts in (("month", monthly_points), ("day", daily_points)):
        for th in thresholds:
            phases = swing_phases(pts, th / 100.0)
            swings[f"{freq}_{th}"] = {
                "freq": freq,
                "threshold": th,
                "phases": phases,
                "stats": swing_stats(phases, len(pts)),
            }

    cards = []
    for c in PERIOD_CARDS:
        item = dict(c)
        if c["kind"] == "since" and custom_since:
            item["date"] = custom_since
        cards.append(item)

    since_card = next((c for c in cards if c["kind"] == "since"), None)

    return {
        "dates": dates,
        "nav": [_round(v, 4) for v in nav.values],
        "m_dates": [d for d, _ in monthly_points],
        "m_nav": [_round(v, 4) for _, v in monthly_points],
        "drawdown": dd,
        "cagr": compute_cagr(nav),
        "swings": swings,
        "periods": period_returns(close, cards),
        "since_default": (since_card or {}).get("date") or (since_card or {}).get("default"),
        "bar_count": len(nav),
    }
