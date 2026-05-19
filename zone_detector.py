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
                     lookback: int = SWING_LOOKBACK) -> list:
    """
    Connect the last 2 swing lows  → support trend line.
    Connect the last 2 swing highs → resistance trend line.
    """
    swing_highs, swing_lows = find_swings(df, lookback)
    lines = []

    if len(swing_lows) >= 2:
        l1, l2 = swing_lows[-2], swing_lows[-1]
        lines.append(TrendLine(
            x1=l1.index, x2=l2.index,
            y1=l1.price, y2=l2.price,
            kind="support_tl",
            ts1=l1.timestamp, ts2=l2.timestamp,
        ))

    if len(swing_highs) >= 2:
        h1, h2 = swing_highs[-2], swing_highs[-1]
        lines.append(TrendLine(
            x1=h1.index, x2=h2.index,
            y1=h1.price, y2=h2.price,
            kind="resistance_tl",
            ts1=h1.timestamp, ts2=h2.timestamp,
        ))

    return lines


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
    zm.trend_lines   = find_trend_lines(df)
    zm.sweep_markers = find_sweep_markers(df, atr)

    # Equilibrium of visible range
    zm.equilibrium = (df["high"].max() + df["low"].min()) / 2.0
    return zm
