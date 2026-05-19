"""
CTCFx Synthetic Trading Bot - Configuration
Strategy: Multi-timeframe ICT/SMC with candlestick + chart pattern confluence
"""

# ── Timeframes ──────────────────────────────────────────────────────────────
TREND_TF    = "1h"    # Higher timeframe: trend context
CONFIRM_TF  = "15m"   # Mid timeframe: structure confirmation
ENTRY_TF    = "5m"    # Entry timeframe: pattern triggers

# ── Market Structure ─────────────────────────────────────────────────────────
SWING_LOOKBACK         = 5     # candles each side to confirm swing high/low
CONSOLIDATION_CANDLES  = 20    # min candles to declare a consolidation range
CONSOLIDATION_ATR_MULT = 0.5   # range height must be < X * ATR to be "tight"
ATR_PERIOD             = 14

# ── Pattern Detection ─────────────────────────────────────────────────────────
# Doji: body is <= X% of the full candle range
DOJI_BODY_RATIO        = 0.10
# Shadow ratios for Gravestone / Dragonfly
GRAVESTONE_UPPER_RATIO = 0.65  # upper shadow >= 65% of total range
DRAGONFLY_LOWER_RATIO  = 0.65
# Harami: baby body must be inside mother and <= X% of mother body
HARAMI_BODY_RATIO      = 0.50
# Tweezer: lows/highs match within X ticks (fraction of ATR)
TWEEZER_TOLERANCE      = 0.15  # fraction of ATR
# Engulfing: body must engulf previous body fully
ENGULF_BODY_RATIO      = 1.0
# Morning Star: third candle must close above midpoint of first candle body
MORNING_STAR_CLOSE_PCT = 0.50

# ── Chart Patterns ────────────────────────────────────────────────────────────
MIN_PATTERN_BARS       = 10    # minimum bars to form chart pattern
BREAKOUT_CONFIRM_BARS  = 2     # candles that must close beyond level
BREAKOUT_THRESHOLD     = 0.003 # 0.3% beyond level for valid breakout
FALSE_BREAKOUT_BARS    = 3     # bars before reversal = fakeout

# ── Multi-Timeframe Signal Scoring ────────────────────────────────────────────
# Each confluence factor adds to score; trade fires when >= threshold
SIGNAL_THRESHOLD       = 3     # minimum score to take a trade
SCORE_WEIGHTS = {
    "trend_align"       : 2,   # 1h trend matches trade direction
    "structure_break"   : 1,   # 15m structure break / BOS
    "fvg_entry"         : 1,   # entry inside Fair Value Gap
    "pattern_reversal"  : 1,   # candlestick reversal pattern on 5m
    "chart_pattern"     : 1,   # confirmed chart pattern
    "consolidation_break": 1,  # impulse out of consolidation range
    "liquidity_sweep"   : 1,   # sweep of prior high/low before entry
    "equilibrium_zone"  : 1,   # price at 50% of range (EQ)
    "tl_bounce"         : 1,   # price bouncing off validated trend line
    "tl_break"          : 1,   # momentum entry after trend line break
}

# ── Trend Line Quality ────────────────────────────────────────────────────────
TL_BOUNCE_TOLERANCE    = 0.4    # price must be within X * ATR of trend line
TL_QUALITY_THRESHOLD   = 0.3    # min quality score (0-1) to use a trend line

# ── Adaptive Learning ─────────────────────────────────────────────────────────
MEMORY_FILE            = "trade_memory.json"

# ── Risk Management ───────────────────────────────────────────────────────────
ACCOUNT_BALANCE        = 10_000.0   # starting balance USD
RISK_PER_TRADE_PCT     = 0.01       # 1% risk per trade
MAX_OPEN_TRADES        = 3
REWARD_RISK_RATIO      = 2.0        # minimum RR required to take trade
STOP_ATR_MULT          = 1.5        # fallback stop = X * ATR beyond entry
SWING_SL_BUFFER        = 0.3        # ATR buffer beyond swing point for SL
MAX_SL_ATR             = 3.0        # hard cap: SL never wider than X * ATR
TRAILING_STOP          = True
TRAILING_ATR_MULT      = 1.0

# ── Broker / Instruments ──────────────────────────────────────────────────────
# Set AUTO_DISCOVER_SYMBOLS = True to let the bot find all Vol symbols itself.
# Or list specific symbols below to trade only those.
AUTO_DISCOVER_SYMBOLS  = True
SYMBOL_KEYWORDS        = ["FX Vol", "SFX Vol", "Vol"]   # words used to find Vol symbols
INSTRUMENTS            = [    # used only when AUTO_DISCOVER_SYMBOLS = False
    "FX Vol 20",
    "FX Vol 40",
    "FX Vol 60",
    "FX Vol 80",
    "FX Vol 99",
    "SFX Vol 20",
    "SFX Vol 40",
    "SFX Vol 60",
    "SFX Vol 80",
    "SFX Vol 99",
]
INSTRUMENT             = "FX Vol 75"    # legacy single-symbol fallback
SPREAD_PIPS            = 0.5
PIP_VALUE              = 1.0        # USD per pip per lot
CONTRACT_SIZE          = 1.0        # lot size
COMMISSION             = 0.0        # per trade USD

# Max open trades PER SYMBOL (total = MAX_OPEN_TRADES * num_symbols)
MAX_TRADES_PER_SYMBOL  = 1

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_START         = "2024-01-01"
BACKTEST_END           = "2025-01-01"
DATA_SOURCE            = "synthetic"  # "synthetic" | "csv" | "mt5"
SYNTHETIC_SEED         = 42
SYNTHETIC_CANDLES      = 5000
