"""
Candlestick Pattern Detector
Patterns: Gravestone Doji, Dragonfly Doji, Bullish/Bearish Harami,
          Tweezer Tops/Bottoms, Morning Star, Engulfing, Hammer, Shooting Star.
Each function takes a slice of a DataFrame and returns a dict with:
  "pattern": str | None, "direction": "bullish"|"bearish"|None
"""

import pandas as pd
from config import (
    DOJI_BODY_RATIO, GRAVESTONE_UPPER_RATIO, DRAGONFLY_LOWER_RATIO,
    HARAMI_BODY_RATIO, TWEEZER_TOLERANCE, MORNING_STAR_CLOSE_PCT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _body(row) -> float:
    return abs(row["close"] - row["open"])

def _range(row) -> float:
    return row["high"] - row["low"]

def _upper_shadow(row) -> float:
    return row["high"] - max(row["open"], row["close"])

def _lower_shadow(row) -> float:
    return min(row["open"], row["close"]) - row["low"]

def _is_bullish(row) -> bool:
    return row["close"] > row["open"]

def _is_bearish(row) -> bool:
    return row["close"] < row["open"]

def _is_doji(row) -> bool:
    r = _range(row)
    return r > 0 and _body(row) / r <= DOJI_BODY_RATIO


# ── Single-Candle Patterns ────────────────────────────────────────────────────

def gravestone_doji(df: pd.DataFrame) -> dict:
    """Long upper shadow, open == close at bottom. Bearish reversal at top."""
    c = df.iloc[-1]
    r = _range(c)
    if r == 0 or not _is_doji(c):
        return {"pattern": None, "direction": None}
    if _upper_shadow(c) / r >= GRAVESTONE_UPPER_RATIO and _lower_shadow(c) / r < 0.10:
        return {"pattern": "Gravestone Doji", "direction": "bearish"}
    return {"pattern": None, "direction": None}


def dragonfly_doji(df: pd.DataFrame) -> dict:
    """Long lower shadow, open == close at top. Bullish reversal at bottom."""
    c = df.iloc[-1]
    r = _range(c)
    if r == 0 or not _is_doji(c):
        return {"pattern": None, "direction": None}
    if _lower_shadow(c) / r >= DRAGONFLY_LOWER_RATIO and _upper_shadow(c) / r < 0.10:
        return {"pattern": "Dragonfly Doji", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def hammer(df: pd.DataFrame) -> dict:
    """Long lower shadow (>=2x body), small upper shadow. Bullish reversal."""
    c = df.iloc[-1]
    b = _body(c)
    ls = _lower_shadow(c)
    us = _upper_shadow(c)
    if b == 0:
        return {"pattern": None, "direction": None}
    if ls >= 2 * b and us <= 0.3 * b:
        return {"pattern": "Hammer", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def shooting_star(df: pd.DataFrame) -> dict:
    """Long upper shadow (>=2x body), small lower shadow. Bearish reversal."""
    c = df.iloc[-1]
    b = _body(c)
    us = _upper_shadow(c)
    ls = _lower_shadow(c)
    if b == 0:
        return {"pattern": None, "direction": None}
    if us >= 2 * b and ls <= 0.3 * b:
        return {"pattern": "Shooting Star", "direction": "bearish"}
    return {"pattern": None, "direction": None}


def doji(df: pd.DataFrame) -> dict:
    """Generic doji: indecision, must be confirmed by context."""
    c = df.iloc[-1]
    if _is_doji(c):
        return {"pattern": "Doji", "direction": "neutral"}
    return {"pattern": None, "direction": None}


# ── Two-Candle Patterns ───────────────────────────────────────────────────────

def bullish_harami(df: pd.DataFrame) -> dict:
    """
    Mother (big bearish) then Baby (small bullish inside mother body).
    Bullish reversal at bottom of downtrend.
    """
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    mother, baby = df.iloc[-2], df.iloc[-1]
    if not _is_bearish(mother):
        return {"pattern": None, "direction": None}
    mb = _body(mother)
    if mb == 0:
        return {"pattern": None, "direction": None}
    bb = _body(baby)
    baby_in_mother = (baby["close"] >= mother["close"] and
                      baby["open"]  <= mother["open"])
    if baby_in_mother and bb / mb <= HARAMI_BODY_RATIO:
        return {"pattern": "Bullish Harami", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def bearish_harami(df: pd.DataFrame) -> dict:
    """
    Mother (big bullish) then Baby (small bearish inside mother body).
    Bearish reversal at top of uptrend.
    """
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    mother, baby = df.iloc[-2], df.iloc[-1]
    if not _is_bullish(mother):
        return {"pattern": None, "direction": None}
    mb = _body(mother)
    if mb == 0:
        return {"pattern": None, "direction": None}
    bb = _body(baby)
    baby_in_mother = (baby["close"] <= mother["close"] and
                      baby["open"]  >= mother["open"])
    if baby_in_mother and bb / mb <= HARAMI_BODY_RATIO:
        return {"pattern": "Bearish Harami", "direction": "bearish"}
    return {"pattern": None, "direction": None}


def tweezer_bottom(df: pd.DataFrame, atr: float) -> dict:
    """Two candles with matching lows, second bullish. Bullish reversal."""
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    c1, c2 = df.iloc[-2], df.iloc[-1]
    tol = atr * TWEEZER_TOLERANCE
    if abs(c1["low"] - c2["low"]) <= tol and _is_bearish(c1) and _is_bullish(c2):
        return {"pattern": "Tweezer Bottom", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def tweezer_top(df: pd.DataFrame, atr: float) -> dict:
    """Two candles with matching highs, second bearish. Bearish reversal."""
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    c1, c2 = df.iloc[-2], df.iloc[-1]
    tol = atr * TWEEZER_TOLERANCE
    if abs(c1["high"] - c2["high"]) <= tol and _is_bullish(c1) and _is_bearish(c2):
        return {"pattern": "Tweezer Top", "direction": "bearish"}
    return {"pattern": None, "direction": None}


def bullish_engulfing(df: pd.DataFrame) -> dict:
    """Bearish candle fully engulfed by larger bullish candle. Bullish reversal."""
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    c1, c2 = df.iloc[-2], df.iloc[-1]
    if (_is_bearish(c1) and _is_bullish(c2) and
            c2["close"] > c1["open"] and c2["open"] < c1["close"]):
        return {"pattern": "Bullish Engulfing", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def bearish_engulfing(df: pd.DataFrame) -> dict:
    """Bullish candle fully engulfed by larger bearish candle. Bearish reversal."""
    if len(df) < 2:
        return {"pattern": None, "direction": None}
    c1, c2 = df.iloc[-2], df.iloc[-1]
    if (_is_bullish(c1) and _is_bearish(c2) and
            c2["open"] > c1["close"] and c2["close"] < c1["open"]):
        return {"pattern": "Bearish Engulfing", "direction": "bearish"}
    return {"pattern": None, "direction": None}


# ── Three-Candle Patterns ─────────────────────────────────────────────────────

def morning_star(df: pd.DataFrame) -> dict:
    """
    1) Big bearish candle
    2) Small-body candle (indecision, gaps down ideally)
    3) Big bullish candle closing above midpoint of candle 1.
    Strong bullish reversal at bottom.
    """
    if len(df) < 3:
        return {"pattern": None, "direction": None}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    midpoint_c1 = (c1["open"] + c1["close"]) / 2.0
    if (_is_bearish(c1) and
            _body(c2) < _body(c1) * 0.5 and
            _is_bullish(c3) and
            c3["close"] > midpoint_c1):
        return {"pattern": "Morning Star", "direction": "bullish"}
    return {"pattern": None, "direction": None}


def evening_star(df: pd.DataFrame) -> dict:
    """
    1) Big bullish candle
    2) Small-body candle (indecision, gaps up ideally)
    3) Big bearish candle closing below midpoint of candle 1.
    Strong bearish reversal at top.
    """
    if len(df) < 3:
        return {"pattern": None, "direction": None}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    midpoint_c1 = (c1["open"] + c1["close"]) / 2.0
    if (_is_bullish(c1) and
            _body(c2) < _body(c1) * 0.5 and
            _is_bearish(c3) and
            c3["close"] < midpoint_c1):
        return {"pattern": "Evening Star", "direction": "bearish"}
    return {"pattern": None, "direction": None}


# ── Master Scanner ─────────────────────────────────────────────────────────────

def scan_all(df: pd.DataFrame, atr: float) -> list:
    """
    Run every pattern detector on the last few candles.
    Returns list of {"pattern": str, "direction": str} for detected patterns.
    """
    detectors = [
        gravestone_doji(df),
        dragonfly_doji(df),
        hammer(df),
        shooting_star(df),
        doji(df),
        bullish_harami(df),
        bearish_harami(df),
        tweezer_bottom(df, atr),
        tweezer_top(df, atr),
        bullish_engulfing(df),
        bearish_engulfing(df),
        morning_star(df),
        evening_star(df),
    ]
    return [r for r in detectors if r["pattern"] is not None]
