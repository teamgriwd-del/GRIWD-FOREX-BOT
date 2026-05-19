"""
MT5 Live Overlay — draws strategy zones on every Vol symbol chart in MT5.
Run this alongside bot.py --live, or standalone just to see the zones.

Usage:
  python mt5_overlay.py                      # draw on all 10 Vol symbols
  python mt5_overlay.py --symbol "FX Vol 60" # single symbol
  python mt5_overlay.py --once               # draw once and exit
  python mt5_overlay.py --tf 15m             # use 15m charts instead
"""

import argparse
import time
import sys
import MetaTrader5 as mt5

import mt5_connector as mt5c
from mt5_draw import redraw_chart, get_or_open_chart, TF_CONST
from signal_engine import generate_signal
from config import ENTRY_TF, CONFIRM_TF, TREND_TF, SYMBOL_KEYWORDS

REFRESH_SECONDS = 60    # redraw every 60s (1 bar on 5m chart)


def draw_symbol(symbol: str, tf_str: str):
    """Fetch live data, detect signal, draw all zones on MT5 chart."""
    tf_const = TF_CONST.get(tf_str, mt5.TIMEFRAME_M5)

    # Fetch OHLCV for all three timeframes
    df_entry   = mt5c.get_ohlcv(symbol, ENTRY_TF,   350)
    df_confirm = mt5c.get_ohlcv(symbol, CONFIRM_TF, 200)
    df_trend   = mt5c.get_ohlcv(symbol, TREND_TF,   150)

    if df_entry is None or df_entry.empty:
        print(f"  [{symbol}] No data, skipping")
        return

    # Detect signal
    signal = None
    try:
        data   = {ENTRY_TF: df_entry, CONFIRM_TF: df_confirm, TREND_TF: df_trend}
        signal = generate_signal(data)
        if signal:
            print(f"  [{symbol}] Signal: {signal.direction.upper()}  "
                  f"score={signal.score}  {' | '.join(signal.reasons)}")
        else:
            print(f"  [{symbol}] No signal")
    except Exception as e:
        print(f"  [{symbol}] Signal error: {e}")

    # Get or open the chart in MT5
    chart_id = get_or_open_chart(symbol, tf_const)
    if not chart_id or chart_id == -1:
        print(f"  [{symbol}] Could not open chart (id={chart_id})")
        return

    # Draw everything
    redraw_chart(chart_id, df_entry, signal)
    print(f"  [{symbol}] Zones drawn on chart_id={chart_id}")


def main():
    parser = argparse.ArgumentParser(description="MT5 Zone Overlay")
    parser.add_argument("--symbol", type=str,  default=None,
                        help="Single symbol (default: all Vol symbols)")
    parser.add_argument("--tf",     type=str,  default=ENTRY_TF,
                        help=f"Chart timeframe (default: {ENTRY_TF})")
    parser.add_argument("--once",   action="store_true",
                        help="Draw once and exit instead of looping")
    args = parser.parse_args()

    if not mt5c.connect():
        print("Cannot connect to MT5. Open terminal and log in first.")
        sys.exit(1)

    if args.symbol:
        symbols = [args.symbol]
        mt5.symbol_select(args.symbol, True)
    else:
        symbols = mt5c.discover_symbols(SYMBOL_KEYWORDS)

    if not symbols:
        print("No symbols found. Run python check_mt5.py first.")
        mt5c.disconnect()
        sys.exit(1)

    print(f"\nDrawing zones on {len(symbols)} symbol(s) | TF={args.tf} | "
          f"refresh={REFRESH_SECONDS}s")
    print("Press Ctrl+C to stop.\n")

    while True:
        print(f"--- Redrawing {len(symbols)} charts ---")
        for sym in symbols:
            try:
                draw_symbol(sym, args.tf)
            except Exception as e:
                print(f"  [{sym}] Draw error: {e}")

        if args.once:
            break

        print(f"  Next refresh in {REFRESH_SECONDS}s ...\n")
        time.sleep(REFRESH_SECONDS)

    mt5c.disconnect()
    print("Overlay stopped.")


if __name__ == "__main__":
    main()
