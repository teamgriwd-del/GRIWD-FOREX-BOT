"""
Chart Pattern Detector
Patterns: Double Top/Bottom, Triple Top/Bottom, Rectangle, Triangles
          (Symmetrical, Ascending, Descending), Wedges, Head & Shoulders,
          Inverse H&S, Cup & Handle.
Returns signals with breakout direction and projected targets.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from market_structure import find_swings
from config import (
    MIN_PATTERN_BARS, BREAKOUT_CONFIRM_BARS, BREAKOUT_THRESHOLD
)


@dataclass
class ChartSignal:
    pattern: str
    direction: str        # "bullish" | "bearish"
    breakout_level: float
    target: float
    stop: float
    confidence: float     # 0.0 – 1.0
    confirmed: bool = False


# ── Utility ───────────────────────────────────────────────────────────────────

def _confirmed_breakout(df: pd.DataFrame, level: float, direction: str,
                        n: int = BREAKOUT_CONFIRM_BARS,
                        threshold: float = BREAKOUT_THRESHOLD) -> bool:
    recent = df["close"].iloc[-n:]
    if direction == "bullish":
        return all(c > level * (1 + threshold) for c in recent)
    return all(c < level * (1 - threshold) for c in recent)


def _swing_highs_prices(df: pd.DataFrame) -> list:
    highs, _ = find_swings(df)
    return [s.price for s in highs]


def _swing_lows_prices(df: pd.DataFrame) -> list:
    _, lows = find_swings(df)
    return [s.price for s in lows]


# ── Double Top / Bottom ───────────────────────────────────────────────────────

def double_top(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Two swing highs at similar levels, neckline = intervening swing low."""
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs, lows = find_swings(df)
    if len(highs) < 2 or len(lows) < 1:
        return None
    h1, h2 = highs[-2], highs[-1]
    tol = atr * 1.5
    if abs(h1.price - h2.price) > tol:
        return None
    # Neckline: lowest swing low between h1 and h2
    between_lows = [l for l in lows if h1.index < l.index < h2.index]
    if not between_lows:
        return None
    neckline = min(l.price for l in between_lows)
    height = (h1.price + h2.price) / 2.0 - neckline
    target = neckline - height
    confirmed = _confirmed_breakout(df, neckline, "bearish")
    return ChartSignal(
        pattern="Double Top", direction="bearish",
        breakout_level=neckline, target=target,
        stop=(h1.price + h2.price) / 2.0,
        confidence=0.75 if confirmed else 0.45,
        confirmed=confirmed,
    )


def double_bottom(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Two swing lows at similar levels, neckline = intervening swing high."""
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs, lows = find_swings(df)
    if len(lows) < 2 or len(highs) < 1:
        return None
    l1, l2 = lows[-2], lows[-1]
    tol = atr * 1.5
    if abs(l1.price - l2.price) > tol:
        return None
    between_highs = [h for h in highs if l1.index < h.index < l2.index]
    if not between_highs:
        return None
    neckline = max(h.price for h in between_highs)
    height = neckline - (l1.price + l2.price) / 2.0
    target = neckline + height
    confirmed = _confirmed_breakout(df, neckline, "bullish")
    return ChartSignal(
        pattern="Double Bottom", direction="bullish",
        breakout_level=neckline, target=target,
        stop=(l1.price + l2.price) / 2.0,
        confidence=0.75 if confirmed else 0.45,
        confirmed=confirmed,
    )


# ── Triple Top / Bottom ───────────────────────────────────────────────────────

def triple_top(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    if len(df) < MIN_PATTERN_BARS + 10:
        return None
    highs, lows = find_swings(df)
    if len(highs) < 3:
        return None
    h1, h2, h3 = highs[-3], highs[-2], highs[-1]
    tol = atr * 1.5
    if max(abs(h1.price - h2.price), abs(h2.price - h3.price)) > tol:
        return None
    between_lows = [l for l in lows if h1.index < l.index < h3.index]
    if not between_lows:
        return None
    neckline = min(l.price for l in between_lows)
    height = sum(h.price for h in [h1, h2, h3]) / 3.0 - neckline
    target = neckline - height
    confirmed = _confirmed_breakout(df, neckline, "bearish")
    return ChartSignal(
        pattern="Triple Top", direction="bearish",
        breakout_level=neckline, target=target,
        stop=max(h1.price, h2.price, h3.price),
        confidence=0.85 if confirmed else 0.55,
        confirmed=confirmed,
    )


def triple_bottom(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    if len(df) < MIN_PATTERN_BARS + 10:
        return None
    highs, lows = find_swings(df)
    if len(lows) < 3:
        return None
    l1, l2, l3 = lows[-3], lows[-2], lows[-1]
    tol = atr * 1.5
    if max(abs(l1.price - l2.price), abs(l2.price - l3.price)) > tol:
        return None
    between_highs = [h for h in highs if l1.index < h.index < l3.index]
    if not between_highs:
        return None
    neckline = max(h.price for h in between_highs)
    height = neckline - sum(l.price for l in [l1, l2, l3]) / 3.0
    target = neckline + height
    confirmed = _confirmed_breakout(df, neckline, "bullish")
    return ChartSignal(
        pattern="Triple Bottom", direction="bullish",
        breakout_level=neckline, target=target,
        stop=min(l1.price, l2.price, l3.price),
        confidence=0.85 if confirmed else 0.55,
        confirmed=confirmed,
    )


# ── Rectangle ─────────────────────────────────────────────────────────────────

def rectangle(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Horizontal range. Breakout above resistance = bullish. Below support = bearish."""
    if len(df) < MIN_PATTERN_BARS:
        return None
    recent = df.iloc[-MIN_PATTERN_BARS:]
    resistance = recent["high"].max()
    support    = recent["low"].min()
    height     = resistance - support
    if height < atr * 0.5:
        return None  # too tight = noise

    last_close = df["close"].iloc[-1]
    if _confirmed_breakout(df, resistance, "bullish"):
        return ChartSignal(
            pattern="Rectangle", direction="bullish",
            breakout_level=resistance, target=resistance + height,
            stop=support, confidence=0.65, confirmed=True,
        )
    if _confirmed_breakout(df, support, "bearish"):
        return ChartSignal(
            pattern="Rectangle", direction="bearish",
            breakout_level=support, target=support - height,
            stop=resistance, confidence=0.65, confirmed=True,
        )
    return None


# ── Triangle Patterns ─────────────────────────────────────────────────────────

def _trendline_slope(prices: list) -> float:
    if len(prices) < 2:
        return 0.0
    x = np.arange(len(prices), dtype=float)
    return np.polyfit(x, prices, 1)[0]


def symmetrical_triangle(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs_p = _swing_highs_prices(df)[-5:]
    lows_p  = _swing_lows_prices(df)[-5:]
    if len(highs_p) < 3 or len(lows_p) < 3:
        return None
    upper_slope = _trendline_slope(highs_p)
    lower_slope = _trendline_slope(lows_p)
    # Converging: upper falling, lower rising
    if upper_slope >= 0 or lower_slope <= 0:
        return None
    apex = df["close"].iloc[-1]
    height = highs_p[0] - lows_p[0]
    if _confirmed_breakout(df, highs_p[-1], "bullish"):
        return ChartSignal(
            pattern="Symmetrical Triangle", direction="bullish",
            breakout_level=highs_p[-1], target=highs_p[-1] + height * 0.75,
            stop=lows_p[-1], confidence=0.60, confirmed=True,
        )
    if _confirmed_breakout(df, lows_p[-1], "bearish"):
        return ChartSignal(
            pattern="Symmetrical Triangle", direction="bearish",
            breakout_level=lows_p[-1], target=lows_p[-1] - height * 0.75,
            stop=highs_p[-1], confidence=0.60, confirmed=True,
        )
    return None


def ascending_triangle(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs_p = _swing_highs_prices(df)[-5:]
    lows_p  = _swing_lows_prices(df)[-5:]
    if len(highs_p) < 3 or len(lows_p) < 3:
        return None
    upper_slope = _trendline_slope(highs_p)
    lower_slope = _trendline_slope(lows_p)
    # Flat resistance, rising support
    if not (-atr * 0.01 < upper_slope < atr * 0.01) or lower_slope <= 0:
        return None
    resistance = np.mean(highs_p)
    height = resistance - lows_p[0]
    if _confirmed_breakout(df, resistance, "bullish"):
        return ChartSignal(
            pattern="Ascending Triangle", direction="bullish",
            breakout_level=resistance, target=resistance + height,
            stop=lows_p[-1], confidence=0.70, confirmed=True,
        )
    return None


def descending_triangle(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs_p = _swing_highs_prices(df)[-5:]
    lows_p  = _swing_lows_prices(df)[-5:]
    if len(highs_p) < 3 or len(lows_p) < 3:
        return None
    upper_slope = _trendline_slope(highs_p)
    lower_slope = _trendline_slope(lows_p)
    # Falling resistance, flat support
    if upper_slope >= 0 or not (-atr * 0.01 < lower_slope < atr * 0.01):
        return None
    support = np.mean(lows_p)
    height = highs_p[0] - support
    if _confirmed_breakout(df, support, "bearish"):
        return ChartSignal(
            pattern="Descending Triangle", direction="bearish",
            breakout_level=support, target=support - height,
            stop=highs_p[-1], confidence=0.70, confirmed=True,
        )
    return None


# ── Wedge Patterns ────────────────────────────────────────────────────────────

def rising_wedge(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Both trendlines rising but converging. Bearish reversal pattern."""
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs_p = _swing_highs_prices(df)[-5:]
    lows_p  = _swing_lows_prices(df)[-5:]
    if len(highs_p) < 3 or len(lows_p) < 3:
        return None
    upper = _trendline_slope(highs_p)
    lower = _trendline_slope(lows_p)
    if upper > 0 and lower > 0 and lower > upper:
        height = highs_p[0] - lows_p[0]
        if _confirmed_breakout(df, lows_p[-1], "bearish"):
            return ChartSignal(
                pattern="Rising Wedge", direction="bearish",
                breakout_level=lows_p[-1], target=lows_p[-1] - height * 0.75,
                stop=highs_p[-1], confidence=0.65, confirmed=True,
            )
    return None


def falling_wedge(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Both trendlines falling but converging. Bullish reversal pattern."""
    if len(df) < MIN_PATTERN_BARS:
        return None
    highs_p = _swing_highs_prices(df)[-5:]
    lows_p  = _swing_lows_prices(df)[-5:]
    if len(highs_p) < 3 or len(lows_p) < 3:
        return None
    upper = _trendline_slope(highs_p)
    lower = _trendline_slope(lows_p)
    if upper < 0 and lower < 0 and upper < lower:
        height = highs_p[0] - lows_p[0]
        if _confirmed_breakout(df, highs_p[-1], "bullish"):
            return ChartSignal(
                pattern="Falling Wedge", direction="bullish",
                breakout_level=highs_p[-1], target=highs_p[-1] + height * 0.75,
                stop=lows_p[-1], confidence=0.65, confirmed=True,
            )
    return None


# ── Head and Shoulders ────────────────────────────────────────────────────────

def head_and_shoulders(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """3 peaks: L shoulder < Head > R shoulder. Neckline = connecting troughs."""
    if len(df) < MIN_PATTERN_BARS + 15:
        return None
    highs, lows = find_swings(df)
    if len(highs) < 3 or len(lows) < 2:
        return None
    ls, head, rs = highs[-3], highs[-2], highs[-1]
    tol = atr * 2.0
    if not (head.price > ls.price and head.price > rs.price):
        return None
    if abs(ls.price - rs.price) > tol:
        return None
    between_lows = [l for l in lows if ls.index < l.index < rs.index]
    if not between_lows:
        return None
    neckline = np.mean([l.price for l in between_lows])
    height = head.price - neckline
    confirmed = _confirmed_breakout(df, neckline, "bearish")
    return ChartSignal(
        pattern="Head & Shoulders", direction="bearish",
        breakout_level=neckline, target=neckline - height,
        stop=rs.price, confidence=0.80 if confirmed else 0.50,
        confirmed=confirmed,
    )


def inverse_head_and_shoulders(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """3 troughs: L shoulder > Head < R shoulder. Bullish reversal."""
    if len(df) < MIN_PATTERN_BARS + 15:
        return None
    highs, lows = find_swings(df)
    if len(lows) < 3 or len(highs) < 2:
        return None
    ls, head, rs = lows[-3], lows[-2], lows[-1]
    tol = atr * 2.0
    if not (head.price < ls.price and head.price < rs.price):
        return None
    if abs(ls.price - rs.price) > tol:
        return None
    between_highs = [h for h in highs if ls.index < h.index < rs.index]
    if not between_highs:
        return None
    neckline = np.mean([h.price for h in between_highs])
    height = neckline - head.price
    confirmed = _confirmed_breakout(df, neckline, "bullish")
    return ChartSignal(
        pattern="Inv. Head & Shoulders", direction="bullish",
        breakout_level=neckline, target=neckline + height,
        stop=rs.price, confidence=0.80 if confirmed else 0.50,
        confirmed=confirmed,
    )


# ── Cup & Handle ──────────────────────────────────────────────────────────────

def cup_and_handle(df: pd.DataFrame, atr: float) -> Optional[ChartSignal]:
    """Rounded bottom (cup) followed by small consolidation (handle). Bullish."""
    if len(df) < MIN_PATTERN_BARS * 3:
        return None
    # Cup: price drops then recovers to near prior high
    cup_region = df.iloc[-MIN_PATTERN_BARS * 3: -MIN_PATTERN_BARS]
    handle_region = df.iloc[-MIN_PATTERN_BARS:]
    cup_low = cup_region["low"].min()
    cup_rim_left  = cup_region["high"].iloc[0]
    cup_rim_right = cup_region["high"].iloc[-1]
    handle_high = handle_region["high"].max()
    handle_low  = handle_region["low"].min()
    # Rim heights similar
    if abs(cup_rim_left - cup_rim_right) > atr * 3:
        return None
    # Handle consolidates below rim
    resistance = (cup_rim_left + cup_rim_right) / 2.0
    if handle_high > resistance or handle_low < cup_low:
        return None
    height = resistance - cup_low
    if _confirmed_breakout(df, resistance, "bullish"):
        return ChartSignal(
            pattern="Cup & Handle", direction="bullish",
            breakout_level=resistance, target=resistance + height,
            stop=handle_low, confidence=0.72, confirmed=True,
        )
    return None


# ── Master Scanner ─────────────────────────────────────────────────────────────

def scan_all(df: pd.DataFrame, atr: float) -> list:
    """Run all chart pattern detectors, return confirmed signals."""
    detectors = [
        double_top, double_bottom,
        triple_top, triple_bottom,
        rectangle,
        symmetrical_triangle, ascending_triangle, descending_triangle,
        rising_wedge, falling_wedge,
        head_and_shoulders, inverse_head_and_shoulders,
        cup_and_handle,
    ]
    results = []
    for fn in detectors:
        try:
            sig = fn(df, atr)
            if sig is not None:
                results.append(sig)
        except Exception:
            pass
    return results
