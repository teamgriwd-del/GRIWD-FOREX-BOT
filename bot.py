"""
CTCFx Synthetic Trading Bot — Main Entry Point
Strategy: ICT/SMC multi-timeframe confluence
  1h  -> Trend context (uptrend / downtrend / consolidation)
  15m -> Structure confirmation (BOS, chart patterns)
  5m  -> Entry triggers (candlestick patterns, FVG, liquidity sweeps)

Usage:
  python bot.py                      # backtest with synthetic data
  python bot.py --csv my_data.csv    # backtest with your own CSV
  python bot.py --charts             # show charts after backtest
  python bot.py --verbose            # print every trade in real time

  python bot.py --live               # connect MT5 and trade live
  python bot.py --live --dry-run     # connect MT5 but do NOT place real orders
  python bot.py --live --symbol R_75 # override symbol name
"""

import argparse
from data_feed import get_data, load_csv, resample, compute_atr
from backtest import run_backtest, print_report
from config import ENTRY_TF, CONFIRM_TF, TREND_TF


def parse_args():
    p = argparse.ArgumentParser(description="CTCFx Synthetic Trading Bot")
    # Backtest options
    p.add_argument("--csv",     type=str,  default=None,
                   help="CSV file path (datetime,open,high,low,close[,volume])")
    p.add_argument("--charts",  action="store_true",
                   help="Show equity/trade charts after backtest")
    p.add_argument("--verbose", action="store_true",
                   help="Print each trade to console during backtest")
    # Live trading options
    p.add_argument("--live",    action="store_true",
                   help="Run in live mode, connected to MT5")
    p.add_argument("--dry-run", action="store_true",
                   help="Live mode but do NOT place real orders (signals only)")
    p.add_argument("--symbol",  type=str,  default=None,
                   help="MT5 symbol override (e.g. R_75, Volatility 75 Index)")
    return p.parse_args()


def run_backtest_mode(args):
    print()
    print("=" * 65)
    print("   CTCFx SYNTHETIC TRADING BOT  v1.0  [BACKTEST MODE]")
    print("   Strategy: ICT/SMC | Candlestick + Chart Pattern Confluence")
    print("=" * 65)
    print()

    if args.csv:
        print(f"Loading CSV: {args.csv}")
        df_5m = load_csv(args.csv)
        df_5m["atr"] = compute_atr(df_5m)
        data = {}
        for tf in [ENTRY_TF, CONFIRM_TF, TREND_TF]:
            df_tf = resample(df_5m, tf).copy()
            df_tf["atr"] = compute_atr(df_tf)
            data[tf] = df_tf
    else:
        print("Generating synthetic Volatility 75 data...")
        data = get_data("synthetic")

    df_5m = data[ENTRY_TF]
    print(f"Data loaded: {len(df_5m)} x 5m candles")
    print()

    stats, rm = run_backtest(data=data, verbose=args.verbose)
    print_report(stats)

    if rm.closed_trades:
        from collections import Counter
        pattern_counts = Counter(t.pattern for t in rm.closed_trades if t.pattern)
        print("\n  Top Entry Patterns:")
        for pat, cnt in pattern_counts.most_common(5):
            wins = sum(1 for t in rm.closed_trades if t.pattern == pat and t.pnl > 0)
            wr = wins / cnt * 100 if cnt else 0
            print(f"    {pat:30s}  {cnt:3d} trades  {wr:.1f}% WR")

    if args.charts:
        try:
            from visualizer import run_all_charts
            run_all_charts(stats, rm, df_5m)
        except ImportError:
            print("\nmatplotlib not installed. Run: pip install matplotlib")

    print()


def run_live_mode(args):
    import mt5_connector as mt5c
    from live_trader import run_live

    print()
    print("=" * 65)
    print("   CTCFx SYNTHETIC TRADING BOT  v1.0  [LIVE MODE]")
    if args.dry_run:
        print("   *** DRY RUN — No real orders will be placed ***")
    print("=" * 65)
    print()

    # Connect to MT5
    if not mt5c.connect():
        print("\n[ERROR] Could not connect to MT5.")
        print("  Make sure MetaTrader 5 terminal is open and logged in.")
        print("  Then try again.")
        return

    # Symbol list: explicit override OR auto-discover all Vol symbols
    if args.symbol:
        symbols = [s.strip() for s in args.symbol.split(",")]
        import MetaTrader5 as mt5
        for s in symbols:
            mt5.symbol_select(s, True)
        print(f"Using symbols: {symbols}")
    else:
        symbols = mt5c.discover_symbols()
        if not symbols:
            print("[ERROR] No volatility symbols found on this account.")
            print("  Run: python check_mt5.py  to see all available symbols.")
            mt5c.disconnect()
            return

    print(f"\nTrading {len(symbols)} symbol(s):")
    for s in symbols:
        tick = mt5c.get_tick(s)
        price = f"bid={tick['bid']:.5f}" if tick else "no tick"
        print(f"  {s:30s}  {price}")
    print()

    try:
        run_live(symbols=symbols, dry_run=args.dry_run)
    finally:
        mt5c.disconnect()


def main():
    args = parse_args()
    if args.live:
        run_live_mode(args)
    else:
        run_backtest_mode(args)


if __name__ == "__main__":
    main()
