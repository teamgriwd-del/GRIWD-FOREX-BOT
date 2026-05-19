"""
Market Structure Analysis
Detects: Uptrend, Downtrend, Consolidation, Swing Highs/Lows,
         Break of Structure (BOS), Fair Value Gaps (FVG),
         Liquidity Sweeps, Equilibrium zones.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from config import (
    SWING_LOOKBACK, CONSOLIDATION_CANDLES, CONSOLIDATION_ATR_MULT, ATR_PERIOD
)


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str   # "high" | "low"
    timestamp: pd.Timestamp


@dataclass
class FVG:
    start_idx: int
    end_idx: int
    top: float
    bottom: float
    direction: str   # "bullish" | "bearish"
    filled: bool = False
    timestamp: Optional[pd.Timestamp] = None


@dataclass
class MarketStructure:
    trend: str = "unknown"           # "uptrend" | "downtrend" | "consolidation"
    swing_highs: list = field(default_factory=list)
    swing_lows: list  = field(default_factory=list)
    fvgs: list        = field(default_factory=list)
    range_high: Optional[float] = None
    range_low: Optional[float]  = None
    equilibrium: Optional[float] = None
    last_bos: Optional[str] = None   # "bullish_bos" | "bearish_bos"
    liquidity_swept: Optional[str] = None  # "highs" | "lows"


# ── Swing Detection ───────────────────────────────────────────────────────────

def find_swings(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> tuple[list, list]:
    """Return (swing_highs, swing_lows) as SwingPoint lists."""
    highs, lows = [], []
    hi = df["high"].values
    lo = df["low"].values
    ts = df.index

    for i in range(lookback, len(df) - lookback):
        if all(hi[i] > hi[i - j] for j in range(1, lookback + 1)) and \
           all(hi[i] > hi[i + j] for j in range(1, lookback + 1)):
            highs.append(SwingPoint(i, hi[i], "high", ts[i]))

        if all(lo[i] < lo[i - j] for j in range(1, lookback + 1)) and \
           all(lo[i] < lo[i + j] for j in range(1, lookback + 1)):
            lows.append(SwingPoint(i, lo[i], "low", ts[i]))

    return highs, lows


# ── Trend Classification ──────────────────────────────────────────────────────

def classify_trend(swing_highs: list, swing_lows: list,
                   df: pd.DataFrame,
                   atr: pd.Series,
                   n: int = CONSOLIDATION_CANDLES) -> str:
    """
    Uptrend: last 2 swing highs rising AND last 2 swing lows rising.
    Downtrend: last 2 swing highs falling AND last 2 swing lows falling.
    Consolidation: range height < ATR * multiplier over last n candles.
    """
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1].price > swing_highs[-2].price
        hl = swing_lows[-1].price  > swing_lows[-2].price
        ll = swing_lows[-1].price  < swing_lows[-2].price
        lh = swing_highs[-1].price < swing_highs[-2].price

        if hh and hl:
            return "uptrend"
        if ll and lh:
            return "downtrend"

    # Consolidation check: recent range vs ATR
    recent = df.iloc[-n:] if len(df) >= n else df
    recent_atr = atr.iloc[-1] if not atr.empty and not pd.isna(atr.iloc[-1]) else 1.0
    price_range = recent["high"].max() - recent["low"].min()
    if price_range < recent_atr * CONSOLIDATION_ATR_MULT * n ** 0.5:
        return "consolidation"

    return "unknown"


# ── Break of Structure ────────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame,
               swing_highs: list,
               swing_lows: list) -> Optional[str]:
    """
    BOS bullish: current close breaks above the last swing high.
    BOS bearish: current close breaks below the last swing low.
    """
    if not swing_highs or not swing_lows:
        return None
    last_close = df["close"].iloc[-1]
    if last_close > swing_highs[-1].price:
        return "bullish_bos"
    if last_close < swing_lows[-1].price:
        return "bearish_bos"
    return None


# ── Fair Value Gap Detection ──────────────────────────────────────────────────

def find_fvgs(df: pd.DataFrame) -> list:
    """
    Bullish FVG: candle[i-1].high < candle[i+1].low (gap up).
    Bearish FVG: candle[i-1].low  > candle[i+1].high (gap down).
    """
    fvgs = []
    hi = df["high"].values
    lo = df["low"].values
    ts = df.index

    for i in range(1, len(df) - 1):
        # Bullish: gap between candle i-1 top and candle i+1 bottom
        if hi[i - 1] < lo[i + 1]:
            fvgs.append(FVG(
                start_idx=i - 1, end_idx=i + 1,
                top=lo[i + 1], bottom=hi[i - 1],
                direction="bullish",
                timestamp=ts[i],
            ))
        # Bearish: gap between candle i-1 bottom and candle i+1 top
        elif lo[i - 1] > hi[i + 1]:
            fvgs.append(FVG(
                start_idx=i - 1, end_idx=i + 1,
                top=lo[i - 1], bottom=hi[i + 1],
                direction="bearish",
                timestamp=ts[i],
            ))

    # Mark filled FVGs
    close = df["close"].values
    for fvg in fvgs:
        for j in range(fvg.end_idx + 1, len(df)):
            if fvg.direction == "bullish" and close[j] < fvg.bottom:
                fvg.filled = True
                break
            if fvg.direction == "bearish" and close[j] > fvg.top:
                fvg.filled = True
                break

    return fvgs


# ── Liquidity Sweep Detection ─────────────────────────────────────────────────

def detect_liquidity_sweep(df: pd.DataFrame,
                            swing_highs: list,
                            swing_lows: list,
                            atr: pd.Series) -> Optional[str]:
    """
    Sweep: current candle wick pierces last swing high/low then closes back inside.
    Returns "highs" if sweep of highs, "lows" if sweep of lows.
    """
    if df.empty or atr.empty:
        return None
    cur_high  = df["high"].iloc[-1]
    cur_low   = df["low"].iloc[-1]
    cur_close = df["close"].iloc[-1]
    tolerance = atr.iloc[-1] * 0.1

    if swing_highs:
        level = swing_highs[-1].price
        if cur_high > level + tolerance and cur_close < level:
            return "highs"

    if swing_lows:
        level = swing_lows[-1].price
        if cur_low < level - tolerance and cur_close > level:
            return "lows"

    return None


# ── Consolidation Range ───────────────────────────────────────────────────────

def get_consolidation_range(df: pd.DataFrame,
                             n: int = CONSOLIDATION_CANDLES) -> tuple:
    """Returns (range_high, range_low, equilibrium) for last n candles."""
    recent = df.iloc[-n:] if len(df) >= n else df
    rh = recent["high"].max()
    rl = recent["low"].min()
    eq = (rh + rl) / 2.0
    return rh, rl, eq


# ── Main Analyzer ─────────────────────────────────────────────────────────────

def analyze(df: pd.DataFrame, atr: pd.Series) -> MarketStructure:
    """Run full market structure analysis on a DataFrame."""
    ms = MarketStructure()

    swing_highs, swing_lows = find_swings(df)
    ms.swing_highs = swing_highs
    ms.swing_lows  = swing_lows

    ms.trend = classify_trend(swing_highs, swing_lows, df, atr)

    ms.fvgs = find_fvgs(df)

    ms.last_bos = detect_bos(df, swing_highs, swing_lows)

    ms.liquidity_swept = detect_liquidity_sweep(df, swing_highs, swing_lows, atr)

    if ms.trend == "consolidation":
        ms.range_high, ms.range_low, ms.equilibrium = get_consolidation_range(df)

    return ms
