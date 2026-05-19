"""
MT5 Chart Drawing Engine
Draws all strategy zones directly onto live MT5 chart windows using
mt5.object_create() — objects appear natively inside the terminal.

Draws:
  - Buy Zones (green filled rectangles)
  - Sell Zones (red filled rectangles)
  - Order Blocks (blue / crimson rectangles with label)
  - FVGs (teal / orange dashed rectangles with label)
  - Support / Resistance trend lines
  - Swing High / Low arrows
  - Liquidity Sweep markers
  - Equilibrium horizontal line
  - Signal arrow + SL/TP lines when a trade fires
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time

from zone_detector import build_zone_map
from data_feed import compute_atr
from config import ENTRY_TF, CONFIRM_TF, TREND_TF, ATR_PERIOD

PREFIX = "CTCFx_"          # all objects use this prefix so we can batch-delete
FAR_FUTURE = datetime(2099, 12, 31, tzinfo=timezone.utc)

# ── Color helpers (MT5 uses 0x00BBGGRR  Windows COLORREF) ─────────────────────
def _col(r, g, b):
    return r | (g << 8) | (b << 16)

CLR = {
    "buy_fill"    : _col(0,  200, 83),    # bright green
    "sell_fill"   : _col(229, 57, 53),    # bright red
    "ob_bull"     : _col(30,  136, 229),  # blue
    "ob_bear"     : _col(183, 28, 28),    # dark red
    "fvg_bull"    : _col(0,  188, 212),   # teal
    "fvg_bear"    : _col(255, 152, 0),    # orange
    "support_tl"  : _col(0,  230, 118),   # lime green
    "resist_tl"   : _col(255, 82,  82),   # coral red
    "swing_hi"    : _col(239, 83,  80),   # red
    "swing_lo"    : _col(38,  166, 154),  # teal green
    "sweep_hi"    : _col(255, 152, 0),    # amber
    "sweep_lo"    : _col(171, 71,  188),  # purple
    "eq_line"     : _col(158, 158, 158),  # grey
    "signal_buy"  : _col(0,  230, 118),   # green
    "signal_sell" : _col(255, 82,  82),   # red
    "sl_line"     : _col(229, 57,  53),   # red
    "tp_line"     : _col(0,  200, 83),    # green
    "white"       : _col(255, 255, 255),
    "label_bg"    : _col(13,  17,  23),   # dark bg
}

# Line style raw values (mt5.STYLE_* not exposed in Python package)
LINE = {
    "solid"  : 0,
    "dash"   : 1,
    "dot"    : 2,
    "dashdot": 3,
}

# Raw MQL5 OBJPROP integer IDs — Python package doesn't expose these as attributes
_PROP = {
    "COLOR"     : 6,      # OBJPROP_COLOR
    "STYLE"     : 7,      # OBJPROP_STYLE
    "WIDTH"     : 8,      # OBJPROP_WIDTH
    "BACK"      : 9,      # OBJPROP_BACK
    "HIDDEN"    : 11,     # OBJPROP_HIDDEN
    "SELECTED"  : 12,     # OBJPROP_SELECTED
    "SELECTABLE": 13,     # OBJPROP_SELECTABLE
    "FONTSIZE"  : 100,    # OBJPROP_FONTSIZE (integer)
    "TEXT"      : 200,    # OBJPROP_TEXT (string)
    "ARROWCODE" : 1000,   # OBJPROP_ARROWCODE
    "RAY_RIGHT" : 1001,   # OBJPROP_RAY_RIGHT
    "FILL"      : 1015,   # OBJPROP_FILL
}


# ── Low-level drawing helpers ─────────────────────────────────────────────────

def _ts(dt) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(dt), tz=timezone.utc)


def _del_all(chart_id: int):
    """Delete every object created by this bot on the given chart."""
    mt5.objects_delete_all(chart_id, PREFIX, 0, -1)


def _rect(chart_id: int, name: str,
          t1, p_top: float, t2, p_bot: float,
          color: int, style: int = LINE["solid"],
          width: int = 1, fill: bool = True, back: bool = True,
          alpha: int = 20):
    """Draw a filled rectangle zone."""
    full_name = PREFIX + name
    if mt5.object_exists(chart_id, full_name):
        mt5.object_delete(chart_id, full_name)
    ok = mt5.object_create(chart_id, full_name, mt5.OBJ_RECTANGLE,
                           0, _ts(t1), p_top, _ts(t2), p_bot)
    if not ok:
        return
    mt5.object_set_integer(chart_id, full_name, _PROP["COLOR"],      color)
    mt5.object_set_integer(chart_id, full_name, _PROP["STYLE"],      style)
    mt5.object_set_integer(chart_id, full_name, _PROP["WIDTH"],      width)
    mt5.object_set_integer(chart_id, full_name, _PROP["FILL"],       int(fill))
    mt5.object_set_integer(chart_id, full_name, _PROP["BACK"],       int(back))
    mt5.object_set_integer(chart_id, full_name, _PROP["SELECTABLE"], 0)
    mt5.object_set_integer(chart_id, full_name, _PROP["HIDDEN"],     1)


def _hline(chart_id: int, name: str, price: float,
           color: int, style: int = LINE["dot"],
           width: int = 1, label: str = ""):
    """Draw a horizontal line across the whole chart."""
    full_name = PREFIX + name
    if mt5.object_exists(chart_id, full_name):
        mt5.object_delete(chart_id, full_name)
    # Use a dummy time — HLINE ignores it
    ok = mt5.object_create(chart_id, full_name, mt5.OBJ_HLINE,
                           0, datetime.now(tz=timezone.utc), price)
    if not ok:
        return
    mt5.object_set_integer(chart_id, full_name, _PROP["COLOR"],      color)
    mt5.object_set_integer(chart_id, full_name, _PROP["STYLE"],      style)
    mt5.object_set_integer(chart_id, full_name, _PROP["WIDTH"],      width)
    mt5.object_set_integer(chart_id, full_name, _PROP["SELECTABLE"], 0)
    mt5.object_set_integer(chart_id, full_name, _PROP["HIDDEN"],     1)
    if label:
        mt5.object_set_string(chart_id, full_name, _PROP["TEXT"],    label)


def _trendline(chart_id: int, name: str,
               t1, p1: float, t2, p2: float,
               color: int, style: int = LINE["dash"], width: int = 2,
               ray: bool = True):
    """Draw a trend / diagonal line."""
    full_name = PREFIX + name
    if mt5.object_exists(chart_id, full_name):
        mt5.object_delete(chart_id, full_name)
    ok = mt5.object_create(chart_id, full_name, mt5.OBJ_TREND,
                           0, _ts(t1), p1, _ts(t2), p2)
    if not ok:
        return
    mt5.object_set_integer(chart_id, full_name, _PROP["COLOR"],      color)
    mt5.object_set_integer(chart_id, full_name, _PROP["STYLE"],      style)
    mt5.object_set_integer(chart_id, full_name, _PROP["WIDTH"],      width)
    mt5.object_set_integer(chart_id, full_name, _PROP["RAY_RIGHT"],  int(ray))
    mt5.object_set_integer(chart_id, full_name, _PROP["SELECTABLE"], 0)
    mt5.object_set_integer(chart_id, full_name, _PROP["HIDDEN"],     1)


def _arrow(chart_id: int, name: str,
           t, price: float, code: int, color: int, size: int = 2):
    """Draw an arrow at a specific bar."""
    full_name = PREFIX + name
    if mt5.object_exists(chart_id, full_name):
        mt5.object_delete(chart_id, full_name)
    ok = mt5.object_create(chart_id, full_name, mt5.OBJ_ARROW,
                           0, _ts(t), price)
    if not ok:
        return
    mt5.object_set_integer(chart_id, full_name, _PROP["ARROWCODE"], code)
    mt5.object_set_integer(chart_id, full_name, _PROP["COLOR"],     color)
    mt5.object_set_integer(chart_id, full_name, _PROP["WIDTH"],     size)
    mt5.object_set_integer(chart_id, full_name, _PROP["SELECTABLE"], 0)
    mt5.object_set_integer(chart_id, full_name, _PROP["HIDDEN"],    1)


def _text(chart_id: int, name: str,
          t, price: float, text: str, color: int, size: int = 8):
    """Draw a text label on the chart."""
    full_name = PREFIX + name
    if mt5.object_exists(chart_id, full_name):
        mt5.object_delete(chart_id, full_name)
    ok = mt5.object_create(chart_id, full_name, mt5.OBJ_TEXT,
                           0, _ts(t), price)
    if not ok:
        return
    mt5.object_set_string (chart_id, full_name, _PROP["TEXT"],      text)
    mt5.object_set_integer(chart_id, full_name, _PROP["COLOR"],     color)
    mt5.object_set_integer(chart_id, full_name, _PROP["FONTSIZE"],  size)
    mt5.object_set_integer(chart_id, full_name, _PROP["SELECTABLE"], 0)
    mt5.object_set_integer(chart_id, full_name, _PROP["HIDDEN"],    1)


# ── High-level zone drawers ───────────────────────────────────────────────────

def draw_zones(chart_id: int, df, zm):
    """Draw all zone types on chart_id."""
    now  = df.index[-1]
    far  = FAR_FUTURE
    atr  = df["atr"].iloc[-1] if not df["atr"].isna().all() else 1.0

    # ── BUY ZONES ─────────────────────────────────────────────────────────────
    for i, z in enumerate(zm.buy_zones[-15:]):
        _rect(chart_id, f"bz_{i}",
              df.index[max(0, len(df) - 150)], z.top,
              far, z.bottom,
              CLR["buy_fill"], LINE["dot"], width=1, fill=True, back=True)

    # ── SELL ZONES ────────────────────────────────────────────────────────────
    for i, z in enumerate(zm.sell_zones[-15:]):
        _rect(chart_id, f"sz_{i}",
              df.index[max(0, len(df) - 150)], z.top,
              far, z.bottom,
              CLR["sell_fill"], LINE["dot"], width=1, fill=True, back=True)

    # ── ORDER BLOCKS ──────────────────────────────────────────────────────────
    for i, ob in enumerate(zm.order_blocks[-20:]):
        if ob.broken or ob.index >= len(df):
            continue
        clr   = CLR["ob_bull"] if ob.kind == "bullish" else CLR["ob_bear"]
        label = "OB+" if ob.kind == "bullish" else "OB-"
        _rect(chart_id, f"ob_{i}",
              ob.timestamp, ob.top,
              far, ob.bottom,
              clr, LINE["solid"], width=2, fill=True, back=True)
        _text(chart_id, f"ob_lbl_{i}",
              ob.timestamp, ob.top + atr * 0.1,
              label, clr, size=8)

    # ── FVGs ──────────────────────────────────────────────────────────────────
    for i, fvg in enumerate(zm.fvgs[-20:]):
        if fvg.filled or fvg.end_idx >= len(df):
            continue
        clr   = CLR["fvg_bull"] if fvg.direction == "bullish" else CLR["fvg_bear"]
        label = "FVG+" if fvg.direction == "bullish" else "FVG-"
        t0    = df.index[fvg.start_idx]
        _rect(chart_id, f"fvg_{i}",
              t0, fvg.top,
              far, fvg.bottom,
              clr, LINE["dash"], width=1, fill=True, back=True)
        _text(chart_id, f"fvg_lbl_{i}",
              t0, fvg.top + atr * 0.05,
              label, clr, size=7)

    # ── SUPPORT TREND LINE ────────────────────────────────────────────────────
    for i, tl in enumerate(zm.trend_lines):
        if tl.x1 >= len(df) or tl.x2 >= len(df):
            continue
        if tl.kind == "support_tl":
            _trendline(chart_id, f"tl_sup_{i}",
                       tl.ts1, tl.y1, tl.ts2, tl.y2,
                       CLR["support_tl"], LINE["dash"], width=2, ray=True)
            _text(chart_id, f"tl_sup_lbl_{i}",
                  tl.ts2, tl.y2 - atr * 0.3,
                  "Support TL", CLR["support_tl"], size=8)
        else:
            _trendline(chart_id, f"tl_res_{i}",
                       tl.ts1, tl.y1, tl.ts2, tl.y2,
                       CLR["resist_tl"], LINE["dash"], width=2, ray=True)
            _text(chart_id, f"tl_res_lbl_{i}",
                  tl.ts2, tl.y2 + atr * 0.1,
                  "Resistance TL", CLR["resist_tl"], size=8)

    # ── SWING HIGHS / LOWS ────────────────────────────────────────────────────
    # Arrow code 217 = down-pointing arrow (swing high)
    # Arrow code 218 = up-pointing arrow (swing low)
    for i, sh in enumerate(zm.swing_highs[-30:]):
        if sh.index >= len(df):
            continue
        _arrow(chart_id, f"sh_{i}",
               sh.timestamp, sh.price + atr * 0.3,
               233, CLR["swing_hi"], size=2)   # 233 = down arrow

    for i, sl in enumerate(zm.swing_lows[-30:]):
        if sl.index >= len(df):
            continue
        _arrow(chart_id, f"sl_{i}",
               sl.timestamp, sl.price - atr * 0.3,
               234, CLR["swing_lo"], size=2)   # 234 = up arrow

    # ── LIQUIDITY SWEEPS ──────────────────────────────────────────────────────
    for i, sw in enumerate(zm.sweep_markers[-20:]):
        if sw.index >= len(df):
            continue
        if sw.kind == "sweep_high":
            _arrow(chart_id, f"sw_h_{i}",
                   sw.timestamp, sw.price + atr * 0.4,
                   251, CLR["sweep_hi"], size=3)   # X mark
            _text(chart_id, f"sw_h_lbl_{i}",
                  sw.timestamp, sw.price + atr * 0.6,
                  "SWEEP", CLR["sweep_hi"], size=7)
        else:
            _arrow(chart_id, f"sw_l_{i}",
                   sw.timestamp, sw.price - atr * 0.4,
                   251, CLR["sweep_lo"], size=3)
            _text(chart_id, f"sw_l_lbl_{i}",
                  sw.timestamp, sw.price - atr * 0.7,
                  "SWEEP", CLR["sweep_lo"], size=7)

    # ── EQUILIBRIUM ───────────────────────────────────────────────────────────
    if zm.equilibrium:
        _hline(chart_id, "eq",
               zm.equilibrium,
               CLR["eq_line"], LINE["dot"], width=1,
               label=f"EQ  {zm.equilibrium:.2f}")


def draw_signal(chart_id: int, signal, atr: float):
    """Draw signal arrow and SL / TP lines on the chart."""
    if signal is None:
        return
    ts = signal.timestamp or datetime.now(tz=timezone.utc)

    if signal.direction == "buy":
        # Up arrow below entry candle
        _arrow(chart_id, "sig_arrow",
               ts, signal.entry - atr * 0.5,
               241, CLR["signal_buy"], size=5)   # 241 = filled up arrow
        _text(chart_id, "sig_lbl",
              ts, signal.entry - atr * 1.2,
              f"BUY  sc:{signal.score}  {signal.pattern}",
              CLR["signal_buy"], size=9)
    else:
        _arrow(chart_id, "sig_arrow",
               ts, signal.entry + atr * 0.5,
               242, CLR["signal_sell"], size=5)  # 242 = filled down arrow
        _text(chart_id, "sig_lbl",
              ts, signal.entry + atr * 1.2,
              f"SELL  sc:{signal.score}  {signal.pattern}",
              CLR["signal_sell"], size=9)

    # SL line
    _hline(chart_id, "sig_sl",
           signal.stop_loss, CLR["sl_line"],
           LINE["dash"], width=2,
           label=f"SL  {signal.stop_loss:.2f}")

    # TP line
    _hline(chart_id, "sig_tp",
           signal.take_profit, CLR["tp_line"],
           LINE["dash"], width=2,
           label=f"TP  {signal.take_profit:.2f}")


# ── Main drawing pipeline ─────────────────────────────────────────────────────

def redraw_chart(chart_id: int, df, signal=None):
    """Full redraw: clear old objects → build zone map → draw everything."""
    _del_all(chart_id)
    atr = df["atr"]
    zm  = build_zone_map(df, atr)
    draw_zones(chart_id, df, zm)
    if signal:
        draw_signal(chart_id, signal, atr.iloc[-1])
    mt5.chart_redraw(chart_id)


def get_or_open_chart(symbol: str, timeframe: int) -> int:
    """Return existing chart ID for symbol/TF, or open a new one."""
    cid = mt5.chart_first()
    while cid and cid != 0 and cid != -1:
        if (mt5.chart_symbol(cid) == symbol and
                mt5.chart_period(cid) == timeframe):
            return cid
        cid = mt5.chart_next(cid)
    # Open a new chart window
    new_id = mt5.chart_open(symbol, timeframe)
    time.sleep(1.0)   # give MT5 time to render it
    return new_id


TF_CONST = {
    "1m" : mt5.TIMEFRAME_M1,
    "5m" : mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h" : mt5.TIMEFRAME_H1,
}
