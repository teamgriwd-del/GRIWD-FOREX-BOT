"""
Data feed: synthetic OHLCV generator and CSV loader.
Generates realistic price data that mimics Fx Volatility Index behavior.
"""

import numpy as np
import pandas as pd
from config import (
    ATR_PERIOD, SYNTHETIC_SEED, SYNTHETIC_CANDLES,
    BACKTEST_START, BACKTEST_END, TREND_TF, CONFIRM_TF, ENTRY_TF
)


def generate_synthetic_ohlcv(n_candles: int = SYNTHETIC_CANDLES,
                              seed: int = SYNTHETIC_SEED,
                              volatility: float = 0.008) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data that mimics Volatility 75 Index.
    Produces trending, consolidating, and reversing regimes.
    """
    rng = np.random.default_rng(seed)
    close = np.zeros(n_candles)
    close[0] = 1000.0

    # Regime schedule: (length_fraction, drift_per_bar, vol_multiplier)
    regimes = [
        (0.10, +0.15, 1.0),   # uptrend
        (0.08, +0.00, 0.4),   # consolidation
        (0.12, -0.20, 1.2),   # downtrend
        (0.06, +0.00, 0.35),  # consolidation
        (0.14, +0.18, 1.1),   # strong uptrend
        (0.10, -0.10, 0.8),   # shallow pullback
        (0.10, +0.00, 0.4),   # consolidation
        (0.15, -0.22, 1.3),   # sharp downtrend
        (0.08, +0.12, 0.9),   # recovery
        (0.07, +0.00, 0.45),  # final consolidation
    ]

    # Fill close prices following regimes
    idx = 1
    for frac, drift, vol_mult in regimes:
        seg_len = max(1, int(n_candles * frac))
        for _ in range(seg_len):
            if idx >= n_candles:
                break
            shock = rng.normal(drift, volatility * vol_mult * close[idx - 1])
            close[idx] = max(1.0, close[idx - 1] + shock)
            idx += 1
    # Fill any remaining candles
    while idx < n_candles:
        shock = rng.normal(0, volatility * close[idx - 1])
        close[idx] = max(1.0, close[idx - 1] + shock)
        idx += 1

    # Build OHLCV from close
    high  = close * (1 + rng.uniform(0.001, 0.006, n_candles))
    low   = close * (1 - rng.uniform(0.001, 0.006, n_candles))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    # Realistic: open near previous close with small gap
    open_ = open_ * (1 + rng.normal(0, 0.001, n_candles))
    open_ = np.clip(open_, low, high)

    volume = rng.integers(100, 10000, n_candles).astype(float)

    dates = pd.date_range(BACKTEST_START, periods=n_candles, freq="5min")

    df = pd.DataFrame({
        "open" : open_,
        "high" : high,
        "low"  : low,
        "close": close,
        "volume": volume,
    }, index=dates)
    return df


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["datetime"], index_col="datetime")
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must contain columns: {required}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["open", "high", "low", "close", "volume"]]


def resample(df_5m: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample 5m base data to higher timeframe."""
    rule_map = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
    rule = rule_map.get(tf, tf)
    agg = {
        "open" : "first",
        "high" : "max",
        "low"  : "min",
        "close": "last",
        "volume": "sum",
    }
    return df_5m.resample(rule).agg(agg).dropna()


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Average True Range."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().rename("atr")


def get_data(source: str = "synthetic") -> dict:
    """Return dict of timeframe -> DataFrame with ATR column added."""
    if source == "synthetic":
        df_5m = generate_synthetic_ohlcv()
    elif source == "csv":
        raise ValueError("Set DATA_SOURCE='csv' and call load_csv(path) directly.")
    else:
        raise ValueError(f"Unknown data source: {source}")

    data = {}
    for tf in [ENTRY_TF, CONFIRM_TF, TREND_TF]:
        df = resample(df_5m, tf).copy()
        df["atr"] = compute_atr(df)
        data[tf] = df

    return data
