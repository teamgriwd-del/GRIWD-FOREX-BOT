"""
Zone Detector — ICT/SMC
Detects: Order Blocks, Support/Resistance Zones, Trend Lines,
         FVGs (already in market_structure), Swing Highs/Lows,
         Liquidity Sweeps, Buy/Sell Zones, Equilibrium.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from market_structure import find_swings, find_fvgs, detect_liquidity_sweep
from config import ATR_PERIOD, SWING_LOOKBACK


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class OrderBlock:
    index: int
    timestamp: pd.Timestamp
    top: float
    bottom: float
    kind: str        # "bullish" | "bearish"
    broken: bool = False
    tested: bool = False


@dataclass
class Zone:
    top: float
    bottom: float
    kind: str        # "support" | "resistance" | "buy_zone" | "sell_zone"
    strength: int = 1   # how many times price has respected it


@dataclass
class TrendLine:
    x1: int          # bar index
    x2: int
    y1: float
    y2: float
    kind: str        # "support_tl" | "resistance_tl"
    ts1: Optional[pd.Timestamp] = None
    ts2: Optional[pd.Timestamp] = None
    touches: int = 2        # how many swing points validate this line
    quality: float = 0.4    # 0.0–1.0; driven by touch count
    broken: bool = False    # True when price closed through the line


def trendline_price_at(tl: "TrendLine", bar_idx: int) -> float:
    """Project (extrapolate) a trend line to any bar index."""
    if tl.x2 == tl.x1:
        return tl.y1
    slope = (tl.y2 - tl.y1) / (tl.x2 - tl.x1)
    return tl.y1 + slope * (bar_idx - tl.x1)


@dataclass
class SweepMarker:
    index: int
    timestamp: pd.Timestamp
    price: float
    kind: str        # "sweep_high" | "sweep_low"


@dataclass
class ZoneMap:
    order_blocks: list = field(default_factory=list)
    support_zones: list = field(default_factory=list)
    resistance_zones: list = field(default_factory=list)
    buy_zones: list = field(default_factory=list)
    sell_zones: list = field(default_factory=list)
    trend_lines: list = field(default_factory=list)
    sweep_markers: list = field(default_factory=list)
    fvgs: list = field(default_factory=list)
    swing_highs: list = field(default_factory=list)
    swing_lows: list = field(default_factory=list)
    equilibrium: Optional[float] = None


# ── Order Block Detection ─────────────────────────────────────────────────────

def find_order_blocks(df: pd.DataFrame, atr: pd.Series,
                      lookback: int = SWING_LOOKBACK) -> list:
    """
    Bullish OB: last bearish candle before a strong bullish impulse (3+ ATR move up).
    Bearish OB: last bullish candle before a strong bearish impulse (3+ ATR move down).
    """
    obs = []
    close = df["close"].values
    open_ = df["open"].values
    high  = df["high"].values
    low   = df["low"].values
    atr_v = atr.values
    ts    = df.index

    for i in range(2, len(df) - lookback):
        if pd.isna(atr_v[i]) or atr_v[i] == 0:
            continue
        # Measure impulse over next few candles
        future_high = max(high[i+1 : i+lookback+1])
        future_low  = min(low[i+1  : i+lookback+1])
        impulse_up   = future_high - close[i]
        impulse_down = close[i] - future_low

        # Bullish OB: bearish candle, then big move up
        if (close[i] < open_[i] and                    # bearish candle
                impulse_up > atr_v[i] * 2.0):          # strong bullish impulse follows
            ob = OrderBlock(
                index=i, timestamp=ts[i],
                top=open_[i], bottom=close[i],
                kind="bullish",
            )
            # Check if later price broke back below the OB
            if any(close[j] < ob.bottom for j in range(i+1, min(i+30, len(df)))):
                ob.broken = True
            obs.append(ob)

        # Bearish OB: bullish candle, then big move down
        elif (close[i] > open_[i] and                  # bullish candle
                impulse_down > atr_v[i] * 2.0):        # strong bearish impulse follows
            ob = OrderBlock(
                index=i, timestamp=ts[i],
                top=close[i], bottom=open_[i],
                kind="bearish",
            )
            if any(close[j] > ob.top for j in range(i+1, min(i+30, len(df)))):
                ob.broken = True
            obs.append(ob)

    return obs


# ── Support / Resistance Zones ────────────────────────────────────────────────

def find_sr_zones(df: pd.DataFrame, atr: pd.Series,
                  lookback: int = SWING_LOOKBACK) -> tuple[list, list]:
    """
    Build support and resistance zones from clusters of swing highs/lows.
    Returns (support_zones, resistance_zones).
    """
    swing_highs, swing_lows = find_swings(df, lookback)
    atr_val = atr.dropna().iloc[-1] if not atr.dropna().empty else 1.0

    def cluster(points, tolerance):
        zones = []
        used  = [False] * len(points)
        for i, p in enumerate(points):
            if used[i]:
                continue
            group = [p.price]
            used[i] = True
            for j, q in enumerate(points):
                if not used[j] and abs(p.price - q.price) <= tolerance:
                    group.append(q.price)
                    used[j] = True
            mid    = np.mean(group)
            spread = atr_val * 0.5
            zones.append(Zone(top=mid + spread, bottom=mid - spread,
                              kind="", strength=len(group)))
        return zones

    tol = atr_val * 1.0
    support_zones    = cluster(swing_lows,  tol)
    resistance_zones = cluster(swing_highs, tol)
    for z in support_zones:
        z.kind = "support"
    for z in resistance_zones:
        z.kind = "resistance"

    return support_zones, resistance_zones


# ── Buy / Sell Zones ──────────────────────────────────────────────────────────

def derive_buy_sell_zones(order_blocks: list,
                          support_zones: list,
                          resistance_zones: list,
                          fvgs: list) -> tuple[list, list]:
    """
    Buy Zone  = unbroken bullish OBs + support zones + unfilled bullish FVGs.
    Sell Zone = unbroken bearish OBs + resistance zones + unfilled bearish FVGs.
    """
    buy_zones  = []
    sell_zones = []

    for ob in order_blocks:
        if ob.broken:
            continue
        z = Zone(top=ob.top, bottom=ob.bottom,
                 kind="buy_zone" if ob.kind == "bullish" else "sell_zone")
        if ob.kind == "bullish":
            buy_zones.append(z)
        else:
            sell_zones.append(z)

    for sz in support_zones:
        buy_zones.append(Zone(top=sz.top, bottom=sz.bottom, kind="buy_zone",
                              strength=sz.strength))
    for rz in resistance_zones:
        sell_zones.append(Zone(top=rz.top, bottom=rz.bottom, kind="sell_zone",
                               strength=rz.strength))

    for fvg in fvgs:
        if fvg.filled:
            continue
        z = Zone(top=fvg.top, bottom=fvg.bottom,
                 kind="buy_zone" if fvg.direction == "bullish" else "sell_zone")
        if fvg.direction == "bullish":
            buy_zones.append(z)
        else:
            sell_zones.append(z)

    return buy_zones, sell_zones


# ── Trend Lines ───────────────────────────────────────────────────────────────

def find_trend_lines(df: pd.DataFrame,
                     atr: pd.Series = None,
                     lookback: int = SWING_LOOKBACK) -> list:
    """
    Build validated trend lines from swing highs/lows.

    For each candidate pair of swing points the line is scored by how many
    *other* swing points fall within ATR*0.4 of it (multi-touch validation).
    Lines are also tagged as broken when recent closes crossed through them.

    Returns up to 2 support + 2 resistance lines, ranked by quality.
    """
    swing_highs, swing_lows = find_swings(df, lookback)

    if atr is not None and not atr.dropna().empty:
        atr_val = float(atr.dropna().iloc[-1])
    elif "atr" in df.columns and not df["atr"].dropna().empty:
        atr_val = float(df["atr"].dropna().iloc[-1])
    else:
        atr_val = float((df["high"] - df["low"]).mean())

    tolerance   = atr_val * 0.4
    current_bar = len(df) - 1
    results     = []

    def _build(p1, p2, all_swings, kind):
        if p2.index == p1.index:
            return None
        slope = (p2.price - p1.price) / (p2.index - p1.index)

        # Count how many other swings lie on this line (within tolerance)
        touches = 2
        for pt in all_swings:
            if pt is p1 or pt is p2:
                continue
            expected = p1.price + slope * (pt.index - p1.index)
            if abs(pt.price - expected) <= tolerance:
                touches += 1

        tl_now = p1.price + slope * (current_bar - p1.index)
        recent_closes = df["close"].values[-5:]

        if kind == "support_tl":
            broken = bool(np.any(recent_closes < tl_now - tolerance))
        else:
            broken = bool(np.any(recent_closes > tl_now + tolerance))

        # quality: 2 touches → 0.25, 5 touches → 1.0
        quality = min(1.0, (touches - 1) / 4.0)

        return TrendLine(
            x1=p1.index, x2=p2.index,
            y1=p1.price, y2=p2.price,
            kind=kind,
            ts1=p1.timestamp, ts2=p2.timestamp,
            touches=touches,
            quality=quality,
            broken=broken,
        )

    def _collect(swings, kind):
        recent = swings[-10:]
        for i in range(len(recent) - 1, 0, -1):
            for j in range(i - 1, max(i - 5, -1), -1):
                tl = _build(recent[j], recent[i], swings, kind)
                if tl is not None:
                    results.append(tl)

    if len(swing_lows)  >= 2:
        _collect(swing_lows,  "support_tl")
    if len(swing_highs) >= 2:
        _collect(swing_highs, "resistance_tl")

    def _top2(kind):
        subset = [t for t in results if t.kind == kind]
        subset.sort(key=lambda t: (t.quality, t.touches), reverse=True)
        return subset[:2]

    return _top2("support_tl") + _top2("resistance_tl")


# ── Sweep Markers ─────────────────────────────────────────────────────────────

def find_sweep_markers(df: pd.DataFrame, atr: pd.Series,
                       lookback: int = SWING_LOOKBACK) -> list:
    """Mark bars where a liquidity sweep occurred."""
    swing_highs, swing_lows = find_swings(df, lookback)
    markers = []
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    ts = df.index

    for i in range(1, len(df)):
        atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 1.0
        tol     = atr_val * 0.1

        for sh in swing_highs:
            if sh.index >= i:
                continue
            if hi[i] > sh.price + tol and cl[i] < sh.price:
                markers.append(SweepMarker(i, ts[i], hi[i], "sweep_high"))
                break

        for sl in swing_lows:
            if sl.index >= i:
                continue
            if lo[i] < sl.price - tol and cl[i] > sl.price:
                markers.append(SweepMarker(i, ts[i], lo[i], "sweep_low"))
                break

    return markers


# ── Master Builder ─────────────────────────────────────────────────────────────

def build_zone_map(df: pd.DataFrame, atr: pd.Series) -> ZoneMap:
    zm = ZoneMap()
    zm.swing_highs, zm.swing_lows = find_swings(df)
    zm.fvgs        = find_fvgs(df)
    zm.order_blocks = find_order_blocks(df, atr)
    zm.support_zones, zm.resistance_zones = find_sr_zones(df, atr)
    zm.buy_zones, zm.sell_zones = derive_buy_sell_zones(
        zm.order_blocks, zm.support_zones, zm.resistance_zones, zm.fvgs
    )
    zm.trend_lines   = find_trend_lines(df, atr)
    zm.sweep_markers = find_sweep_markers(df, atr)

    # Equilibrium of visible range
    zm.equilibrium = (df["high"].max() + df["low"].min()) / 2.0
    return zm
