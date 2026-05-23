"""
Zone Chart — Interactive Plotly chart for the GRIWD Bot
Draws on the LIVE MT5 5m chart:
  - Candlesticks
  - Buy Zones (green)       - Sell Zones (red)
  - FVGs (teal/orange)      - Order Blocks (blue/crimson)
  - Support/Resistance       - Trend Lines
  - Swing Highs/Lows        - Liquidity Sweeps
  - Equilibrium Line        - Buy/Sell Signals

Usage:
  python zone_chart.py                     # chart FX Vol 60 (5m)
  python zone_chart.py --symbol "FX Vol 40"
  python zone_chart.py --symbol "FX Vol 40" --tf 15m
  python zone_chart.py --all               # open chart for every symbol
"""

import argparse
import webbrowser
import tempfile
import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import mt5_connector as mt5c
from zone_detector import build_zone_map
from signal_engine import generate_signal
from config import ENTRY_TF, CONFIRM_TF, TREND_TF, SYMBOL_KEYWORDS

# ── Color Palette ─────────────────────────────────────────────────────────────
C = {
    "bull_candle"  : "#26a69a",
    "bear_candle"  : "#ef5350",
    "buy_zone"     : "rgba(0, 200, 120, 0.12)",
    "buy_zone_line": "rgba(0, 200, 120, 0.55)",
    "sell_zone"    : "rgba(239, 83, 80, 0.12)",
    "sell_zone_line": "rgba(239, 83, 80, 0.55)",
    "ob_bull"      : "rgba(30, 136, 229, 0.18)",
    "ob_bull_line" : "rgba(30, 136, 229, 0.7)",
    "ob_bear"      : "rgba(183, 28, 28, 0.18)",
    "ob_bear_line" : "rgba(183, 28, 28, 0.7)",
    "fvg_bull"     : "rgba(0, 188, 212, 0.18)",
    "fvg_bull_line": "rgba(0, 188, 212, 0.7)",
    "fvg_bear"     : "rgba(255, 152, 0, 0.18)",
    "fvg_bear_line": "rgba(255, 152, 0, 0.7)",
    "support_tl"   : "rgba(0, 200, 120, 0.9)",
    "resist_tl"    : "rgba(239, 83, 80, 0.9)",
    "swing_high"   : "#ef5350",
    "swing_low"    : "#26a69a",
    "sweep_high"   : "#ff9800",
    "sweep_low"    : "#ab47bc",
    "eq_line"      : "rgba(180, 180, 180, 0.6)",
    "signal_buy"   : "#00e676",
    "signal_sell"  : "#ff1744",
    "bg"           : "#0d1117",
    "grid"         : "rgba(255,255,255,0.05)",
    "text"         : "#c9d1d9",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _shade(fig, x0, x1, y0, y1, fill, line, name, row=1):
    """Add a filled rectangle zone."""
    fig.add_shape(type="rect",
                  x0=x0, x1=x1, y0=y0, y1=y1,
                  fillcolor=fill, line=dict(color=line, width=1),
                  row=row, col=1)
    # Invisible trace for legend entry
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(size=10, color=fill, symbol="square"),
        name=name, showlegend=True,
    ), row=row, col=1)


def _extend_trendline(tl, df, bars_ahead=30):
    """Project a trend line N bars beyond its last point."""
    if tl.x1 == tl.x2:
        return tl.ts1, tl.ts2, tl.y1, tl.y2
    slope = (tl.y2 - tl.y1) / (tl.x2 - tl.x1)
    ext_x = min(tl.x2 + bars_ahead, len(df) - 1)
    ext_y = tl.y2 + slope * (ext_x - tl.x2)
    ts_end = df.index[ext_x]
    return tl.ts1, ts_end, tl.y1, ext_y


# ── Main Chart Builder ────────────────────────────────────────────────────────

def build_chart(df_5m: pd.DataFrame, symbol: str,
                df_15m: pd.DataFrame = None,
                df_1h: pd.DataFrame  = None,
                signal=None) -> go.Figure:

    atr   = df_5m["atr"]
    zm    = build_zone_map(df_5m, atr)
    dates = df_5m.index

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.78, 0.22],
        vertical_spacing=0.02,
    )

    # ── Candlesticks ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=dates,
        open=df_5m["open"], high=df_5m["high"],
        low=df_5m["low"],   close=df_5m["close"],
        increasing_line_color=C["bull_candle"],
        decreasing_line_color=C["bear_candle"],
        increasing_fillcolor=C["bull_candle"],
        decreasing_fillcolor=C["bear_candle"],
        name="Price",
        whiskerwidth=0.3,
        line=dict(width=1),
    ), row=1, col=1)

    # ── Volume bars ────────────────────────────────────────────────────────────
    vol_colors = [C["bull_candle"] if c >= o else C["bear_candle"]
                  for c, o in zip(df_5m["close"], df_5m["open"])]
    fig.add_trace(go.Bar(
        x=dates, y=df_5m["volume"],
        marker_color=vol_colors, marker_line_width=0,
        name="Volume", opacity=0.5,
    ), row=2, col=1)

    # ── BUY ZONES ─────────────────────────────────────────────────────────────
    added_bz = False
    for z in zm.buy_zones[-12:]:
        fig.add_hrect(
            y0=z.bottom, y1=z.top,
            fillcolor=C["buy_zone"],
            line=dict(color=C["buy_zone_line"], width=1, dash="dot"),
            annotation_text="Buy Zone" if not added_bz else "",
            annotation_position="right",
            annotation_font=dict(color=C["buy_zone_line"], size=9),
            row=1, col=1,
        )
        added_bz = True

    # ── SELL ZONES ────────────────────────────────────────────────────────────
    added_sz = False
    for z in zm.sell_zones[-12:]:
        fig.add_hrect(
            y0=z.bottom, y1=z.top,
            fillcolor=C["sell_zone"],
            line=dict(color=C["sell_zone_line"], width=1, dash="dot"),
            annotation_text="Sell Zone" if not added_sz else "",
            annotation_position="right",
            annotation_font=dict(color=C["sell_zone_line"], size=9),
            row=1, col=1,
        )
        added_sz = True

    # ── ORDER BLOCKS ──────────────────────────────────────────────────────────
    for ob in zm.order_blocks[-20:]:
        if ob.broken:
            continue
        if ob.index >= len(dates):
            continue
        x0 = dates[ob.index]
        x1 = dates[-1]
        if ob.kind == "bullish":
            fill, line, label = C["ob_bull"], C["ob_bull_line"], "Bullish OB"
        else:
            fill, line, label = C["ob_bear"], C["ob_bear_line"], "Bearish OB"
        fig.add_shape(type="rect",
                      x0=x0, x1=x1,
                      y0=ob.bottom, y1=ob.top,
                      fillcolor=fill,
                      line=dict(color=line, width=1.5),
                      row=1, col=1)
        fig.add_annotation(
            x=x1, y=(ob.top + ob.bottom) / 2,
            text=label, showarrow=False,
            font=dict(color=line, size=9),
            xanchor="right", bgcolor="rgba(13,17,23,0.7)",
            row=1, col=1,
        )

    # ── FVGs ──────────────────────────────────────────────────────────────────
    for fvg in zm.fvgs[-20:]:
        if fvg.filled:
            continue
        if fvg.end_idx >= len(dates):
            continue
        x0 = dates[fvg.start_idx]
        x1 = dates[-1]
        if fvg.direction == "bullish":
            fill, line, label = C["fvg_bull"], C["fvg_bull_line"], "Bullish FVG"
        else:
            fill, line, label = C["fvg_bear"], C["fvg_bear_line"], "Bearish FVG"
        fig.add_shape(type="rect",
                      x0=x0, x1=x1,
                      y0=fvg.bottom, y1=fvg.top,
                      fillcolor=fill,
                      line=dict(color=line, width=1, dash="dash"),
                      row=1, col=1)
        fig.add_annotation(
            x=x0, y=fvg.top,
            text=label, showarrow=False,
            font=dict(color=line, size=8),
            xanchor="left", yanchor="bottom",
            bgcolor="rgba(13,17,23,0.6)",
            row=1, col=1,
        )

    # ── TREND LINES ───────────────────────────────────────────────────────────
    for tl in zm.trend_lines:
        if tl.x1 >= len(dates) or tl.x2 >= len(dates):
            continue
        ts1, ts2, y1, y2 = _extend_trendline(tl, df_5m, bars_ahead=40)
        color = C["support_tl"] if tl.kind == "support_tl" else C["resist_tl"]
        label = "Support TL" if tl.kind == "support_tl" else "Resistance TL"
        fig.add_shape(type="line",
                      x0=ts1, x1=ts2, y0=y1, y1=y2,
                      line=dict(color=color, width=1.5, dash="dot"),
                      row=1, col=1)
        fig.add_annotation(
            x=ts2, y=y2,
            text=label, showarrow=False,
            font=dict(color=color, size=9),
            xanchor="left",
            bgcolor="rgba(13,17,23,0.6)",
            row=1, col=1,
        )

    # ── SWING HIGHS / LOWS ────────────────────────────────────────────────────
    sh_x = [dates[s.index] for s in zm.swing_highs if s.index < len(dates)]
    sh_y = [s.price         for s in zm.swing_highs if s.index < len(dates)]
    fig.add_trace(go.Scatter(
        x=sh_x, y=sh_y, mode="markers",
        marker=dict(symbol="triangle-down", size=9,
                    color=C["swing_high"], line=dict(width=1, color="#fff")),
        name="Swing High", hovertemplate="%{y:.2f}",
    ), row=1, col=1)

    sl_x = [dates[s.index] for s in zm.swing_lows if s.index < len(dates)]
    sl_y = [s.price         for s in zm.swing_lows if s.index < len(dates)]
    fig.add_trace(go.Scatter(
        x=sl_x, y=sl_y, mode="markers",
        marker=dict(symbol="triangle-up", size=9,
                    color=C["swing_low"], line=dict(width=1, color="#fff")),
        name="Swing Low", hovertemplate="%{y:.2f}",
    ), row=1, col=1)

    # ── LIQUIDITY SWEEPS ──────────────────────────────────────────────────────
    sw_h_x = [dates[s.index] for s in zm.sweep_markers
               if s.kind == "sweep_high" and s.index < len(dates)]
    sw_h_y = [s.price for s in zm.sweep_markers
               if s.kind == "sweep_high" and s.index < len(dates)]
    if sw_h_x:
        fig.add_trace(go.Scatter(
            x=sw_h_x, y=sw_h_y, mode="markers+text",
            marker=dict(symbol="x", size=13,
                        color=C["sweep_high"], line=dict(width=2)),
            text=["sweep" for _ in sw_h_x],
            textposition="top center",
            textfont=dict(color=C["sweep_high"], size=8),
            name="Sweep High",
        ), row=1, col=1)

    sw_l_x = [dates[s.index] for s in zm.sweep_markers
               if s.kind == "sweep_low" and s.index < len(dates)]
    sw_l_y = [s.price for s in zm.sweep_markers
               if s.kind == "sweep_low" and s.index < len(dates)]
    if sw_l_x:
        fig.add_trace(go.Scatter(
            x=sw_l_x, y=sw_l_y, mode="markers+text",
            marker=dict(symbol="x", size=13,
                        color=C["sweep_low"], line=dict(width=2)),
            text=["sweep" for _ in sw_l_x],
            textposition="bottom center",
            textfont=dict(color=C["sweep_low"], size=8),
            name="Sweep Low",
        ), row=1, col=1)

    # ── EQUILIBRIUM LINE ──────────────────────────────────────────────────────
    if zm.equilibrium:
        fig.add_hline(
            y=zm.equilibrium, line_dash="dot",
            line_color=C["eq_line"], line_width=1,
            annotation_text="EQ", annotation_position="right",
            annotation_font=dict(color=C["eq_line"], size=9),
            row=1, col=1,
        )

    # ── SIGNAL MARKER ─────────────────────────────────────────────────────────
    if signal is not None:
        arrow_dir = "triangle-up" if signal.direction == "buy" else "triangle-down"
        sig_color = C["signal_buy"] if signal.direction == "buy" else C["signal_sell"]
        sig_y_offset = -atr.iloc[-1] if signal.direction == "buy" else atr.iloc[-1]
        fig.add_trace(go.Scatter(
            x=[dates[-1]],
            y=[signal.entry + sig_y_offset],
            mode="markers+text",
            marker=dict(symbol=arrow_dir, size=18,
                        color=sig_color, line=dict(width=2, color="#fff")),
            text=[f"{signal.direction.upper()} sc{signal.score}"],
            textposition="bottom center" if signal.direction == "buy" else "top center",
            textfont=dict(color=sig_color, size=10, family="monospace"),
            name=f"Signal: {signal.direction.upper()}",
        ), row=1, col=1)
        # SL line
        fig.add_hline(y=signal.stop_loss,
                      line_dash="dash", line_color="rgba(239,83,80,0.7)",
                      line_width=1,
                      annotation_text=f"SL {signal.stop_loss:.2f}",
                      annotation_font=dict(color="#ef5350", size=9),
                      row=1, col=1)
        # TP line
        fig.add_hline(y=signal.take_profit,
                      line_dash="dash", line_color="rgba(0,230,118,0.7)",
                      line_width=1,
                      annotation_text=f"TP {signal.take_profit:.2f}",
                      annotation_font=dict(color="#00e676", size=9),
                      row=1, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    last_price = df_5m["close"].iloc[-1]
    atr_val    = atr.iloc[-1]

    fig.update_layout(
        title=dict(
            text=f"<b>GRIWD Bot — {symbol} | 5m Entry Chart</b>"
                 f"   <span style='color:#aaa;font-size:13px'>"
                 f"Price: {last_price:.2f}  |  ATR: {atr_val:.2f}  |  "
                 f"TF: 5m entry / 15m confirm / 1h trend</span>",
            font=dict(color=C["text"], size=16),
        ),
        paper_bgcolor=C["bg"],
        plot_bgcolor=C["bg"],
        font=dict(color=C["text"], family="Consolas, monospace"),
        xaxis=dict(
            gridcolor=C["grid"], showgrid=True,
            rangeslider=dict(visible=False),
            type="date",
        ),
        xaxis2=dict(gridcolor=C["grid"], showgrid=True),
        yaxis=dict(
            gridcolor=C["grid"], showgrid=True,
            side="right", tickformat=".2f",
            title="Price",
        ),
        yaxis2=dict(
            gridcolor=C["grid"], showgrid=True,
            side="right", title="Volume",
        ),
        legend=dict(
            bgcolor="rgba(13,17,23,0.85)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
            font=dict(size=10),
            x=0.01, y=0.99,
            xanchor="left", yanchor="top",
        ),
        hovermode="x unified",
        height=820,
        margin=dict(l=10, r=80, t=60, b=10),
    )

    # Zoom to last 150 candles by default
    if len(dates) > 150:
        fig.update_xaxes(range=[dates[-150], dates[-1]])

    return fig


# ── Launcher ──────────────────────────────────────────────────────────────────

def open_chart(symbol: str, tf: str = "5m", n_bars: int = 300):
    """Fetch live data from MT5 and open chart in browser."""
    print(f"Fetching {n_bars} x {tf} bars for {symbol}...")

    df_entry  = mt5c.get_ohlcv(symbol, ENTRY_TF,  n_bars)
    df_confirm = mt5c.get_ohlcv(symbol, CONFIRM_TF, 200)
    df_trend  = mt5c.get_ohlcv(symbol, TREND_TF,  150)

    if df_entry is None or df_entry.empty:
        print(f"  No data for {symbol}")
        return

    # Generate current signal for this symbol
    data = {ENTRY_TF: df_entry, CONFIRM_TF: df_confirm, TREND_TF: df_trend}
    signal = None
    try:
        signal = generate_signal(data)
        if signal:
            print(f"  Active signal: {signal.direction.upper()} "
                  f"score={signal.score}  {' | '.join(signal.reasons)}")
    except Exception:
        pass

    fig  = build_chart(df_entry, symbol, df_confirm, df_trend, signal)
    html = fig.to_html(full_html=True, include_plotlyjs="cdn")

    fname = f"chart_{symbol.replace(' ', '_')}.html"
    fpath = os.path.join(os.getcwd(), fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Chart saved: {fpath}")
    webbrowser.open(f"file:///{fpath}")


def main():
    parser = argparse.ArgumentParser(description="GRIWD Zone Chart")
    parser.add_argument("--symbol", type=str, default="FX Vol 60",
                        help="Symbol to chart (default: FX Vol 60)")
    parser.add_argument("--tf",     type=str, default="5m",
                        help="Entry timeframe (default: 5m)")
    parser.add_argument("--bars",   type=int, default=300,
                        help="Number of bars to show (default: 300)")
    parser.add_argument("--all",    action="store_true",
                        help="Open chart for every Vol symbol")
    args = parser.parse_args()

    if not mt5c.connect():
        print("Cannot connect to MT5. Make sure the terminal is open and logged in.")
        return

    if args.all:
        symbols = mt5c.discover_symbols(SYMBOL_KEYWORDS)
        for sym in symbols:
            open_chart(sym, args.tf, args.bars)
    else:
        open_chart(args.symbol, args.tf, args.bars)

    mt5c.disconnect()


if __name__ == "__main__":
    main()
