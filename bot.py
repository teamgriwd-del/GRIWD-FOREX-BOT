"""
GRIWD Forex Bot — Main Entry Point

Usage:
  python bot.py                         # single backtest (synthetic data)
  python bot.py --csv my_data.csv       # backtest from CSV file
  python bot.py --verbose               # print every trade during backtest
  python bot.py --charts                # show charts after backtest

  python bot.py --test                  # learning-curve test (5 runs × 4 seeds)
  python bot.py --test --runs 10        # 10 runs per seed
  python bot.py --test --quick          # fast test with 1 000 candles per run
  python bot.py --test --candles 2000   # custom candle count

  python bot.py --live                  # connect MT5 and trade live
  python bot.py --live --dry-run        # signals only, no real orders
  python bot.py --live --symbol R_75    # override symbol
"""

import argparse
import os
import sys
import time

# ── Argument Parser ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="GRIWD Forex Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Backtest
    p.add_argument("--csv",      type=str,  default=None,
                   help="CSV file path for backtest (datetime,o,h,l,c[,v])")
    p.add_argument("--verbose",  action="store_true",
                   help="Print every trade during backtest")
    p.add_argument("--charts",   action="store_true",
                   help="Show equity/trade charts after backtest")
    # Learning-curve test
    p.add_argument("--test",     action="store_true",
                   help="Run multi-seed learning-curve test")
    p.add_argument("--runs",     type=int,  default=5,
                   help="Runs per seed in test mode (default 5)")
    p.add_argument("--candles",  type=int,  default=None,
                   help="Candles per backtest run (default 5000)")
    p.add_argument("--quick",    action="store_true",
                   help="Test mode shorthand: use 1000 candles for speed")
    p.add_argument("--fresh",    action="store_true",
                   help="Wipe trade memory before test (start from zero)")
    # Live
    p.add_argument("--live",     action="store_true",
                   help="Connect to MT5 and trade live")
    p.add_argument("--dry-run",  action="store_true",
                   help="Live mode — generate signals but skip real orders")
    p.add_argument("--symbol",   type=str,  default=None,
                   help="MT5 symbol override (comma-separated for multiple)")
    p.add_argument("--retries",  type=int,  default=3,
                   help="MT5 connection retry attempts (default 3)")
    return p.parse_args()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner(title: str, subtitle: str = ""):
    w = 65
    print("\n" + "=" * w)
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print("=" * w)


def _ascii_bar(value: float, lo: float, hi: float, width: int = 20) -> str:
    span = hi - lo or 1
    filled = int((value - lo) / span * width)
    return "█" * filled + "░" * (width - filled)


def _print_curve(results_by_seed: dict, metric: str = "win_rate", label: str = "WR%"):
    """Print a simple ASCII chart of a metric across runs for each seed."""
    all_vals = [v for runs in results_by_seed.values() for v in runs]
    if not all_vals:
        return
    lo, hi = min(all_vals), max(all_vals)
    lo = lo * 0.98
    hi = hi * 1.02
    print(f"\n  {label} learning curve  (lo={lo:.1f}  hi={hi:.1f})")
    print(f"  {'Seed':>6}  " + "  ".join(f"R{i+1:<2}" for i in range(len(next(iter(results_by_seed.values()))))))
    print("  " + "-" * 60)
    for seed, vals in results_by_seed.items():
        bars = "  ".join(f"{v:>4.1f}" for v in vals)
        trend = "↑" if len(vals) > 1 and vals[-1] > vals[0] else ("↓" if len(vals) > 1 and vals[-1] < vals[0] else "→")
        print(f"  {seed:>6}  {bars}  {trend}")


# ── Backtest Mode ─────────────────────────────────────────────────────────────

def run_backtest_mode(args):
    from data_feed import get_data, load_csv, resample, compute_atr
    from backtest import run_backtest, print_report
    from config import ENTRY_TF, CONFIRM_TF, TREND_TF

    _banner("GRIWD FOREX BOT  [BACKTEST]",
            "Strategy: ICT/SMC | Candlestick + Chart Pattern Confluence")

    if args.csv:
        print(f"\nLoading CSV: {args.csv}")
        from data_feed import load_csv, resample, compute_atr
        df_5m = load_csv(args.csv)
        df_5m["atr"] = compute_atr(df_5m)
        data = {}
        for tf in [ENTRY_TF, CONFIRM_TF, TREND_TF]:
            df_tf = resample(df_5m, tf).copy()
            df_tf["atr"] = compute_atr(df_tf)
            data[tf] = df_tf
    else:
        print("\nGenerating synthetic Volatility data ...")
        data = get_data("synthetic")

    print(f"Data: {len(data[ENTRY_TF])} × 5m candles\n")

    stats, rm, memory = run_backtest(data=data, verbose=args.verbose)
    print_report(stats)

    if rm.closed_trades:
        from collections import Counter
        counts = Counter(t.pattern for t in rm.closed_trades if t.pattern)
        print("\n  Top Entry Patterns:")
        for pat, cnt in counts.most_common(5):
            wins = sum(1 for t in rm.closed_trades if t.pattern == pat and t.pnl > 0)
            print(f"    {pat:30s}  {cnt:3d} trades  {wins/cnt*100:.0f}% WR")

    memory.print_summary()

    if args.charts:
        try:
            from visualizer import run_all_charts
            run_all_charts(stats, rm, data[ENTRY_TF])
        except ImportError:
            print("\nmatplotlib not installed — pip install matplotlib")
    print()


# ── Learning-Curve Test Mode ──────────────────────────────────────────────────

def run_learning_test(args):
    import pandas as pd
    from data_feed import generate_synthetic_ohlcv, resample, compute_atr
    from signal_engine import generate_signal
    from risk_manager import RiskManager
    from trade_memory import TradeMemory
    from config import ENTRY_TF, CONFIRM_TF, TREND_TF, SWING_LOOKBACK, ATR_PERIOD, MEMORY_FILE

    WARMUP  = max(SWING_LOOKBACK * 4 + 5, ATR_PERIOD + 5, 50)
    candles = args.candles or (1000 if args.quick else 5000)
    n_runs  = args.runs
    seeds   = [42, 99, 777, 123]
    mem_file = MEMORY_FILE

    _banner(
        "GRIWD FOREX BOT  [LEARNING CURVE TEST]",
        f"{n_runs} runs × {len(seeds)} seeds × {candles} candles/run",
    )

    if args.fresh and os.path.exists(mem_file):
        os.remove(mem_file)
        print("  Trade memory wiped — starting fresh.\n")
    else:
        from trade_memory import TradeMemory as TM
        existing = TM(mem_file)
        n_existing = existing._data.get("total_trades", 0)
        if n_existing:
            print(f"  Continuing from existing memory ({n_existing} trades).\n")

    print(f"  {'Seed':>6}  {'Run':>3}  {'Trades':>6}  {'WR%':>6}  {'PF':>6}  "
          f"{'DD%':>6}  {'Balance':>12}  eod")
    print("  " + "-" * 68)

    wr_by_seed  = {s: [] for s in seeds}
    pf_by_seed  = {s: [] for s in seeds}
    bal_by_seed = {s: [] for s in seeds}

    def _one_run(seed, run_num):
        raw = generate_synthetic_ohlcv(n_candles=candles, seed=seed)
        df5 = raw.copy()
        df5["atr"] = compute_atr(df5)
        data = {ENTRY_TF: df5}
        for tf in (CONFIRM_TF, TREND_TF):
            df = resample(raw, tf).copy()
            df["atr"] = compute_atr(df)
            data[tf] = df

        memory = TradeMemory(mem_file)
        rm = RiskManager(memory=memory)

        WIN      = 150  # analysis window — keeps each analyze() call O(1) not O(n)
        COOLDOWN = 10   # minimum bars between new entries (prevents signal stacking)
        last_entry_bar = -COOLDOWN
        for i in range(WARMUP, len(df5)):
            ts = df5.index[i]
            pr = df5["close"].iloc[i]
            hi = df5["high"].iloc[i]
            lo = df5["low"].iloc[i]
            s5  = df5.iloc[max(0, i - WIN + 1):i + 1]
            s15 = data[CONFIRM_TF].loc[:ts].iloc[-WIN:]
            s1h = data[TREND_TF].loc[:ts].iloc[-WIN:]
            if s15.empty or s1h.empty:
                continue
            atr = s5["atr"].iloc[-1]
            if pd.isna(atr):
                atr = 1.0
            for t in list(rm.open_trades):
                rm.update_trailing_stop(t, pr, atr)
                rm.check_close(t, pr, ts, hi, lo)
            if rm.can_open() and (i - last_entry_bar) >= COOLDOWN:
                sig = generate_signal(
                    {ENTRY_TF: s5, CONFIRM_TF: s15, TREND_TF: s1h},
                    ts, memory=memory,
                )
                if sig:
                    rm.open_trade(sig, atr)
                    last_entry_bar = i

        lp = df5["close"].iloc[-1]
        lt = df5.index[-1]
        eod = 0
        for t in list(rm.open_trades):
            rm._close(t, lp, lt, "end_of_data")
            eod += 1

        st = rm.stats()
        return st, eod

    for seed in seeds:
        for run in range(1, n_runs + 1):
            st, eod = _one_run(seed, run)
            wr  = st.get("win_rate", 0)
            pf  = st.get("profit_factor", 0)
            dd  = st.get("max_drawdown", 0)
            bal = st.get("final_balance", 0)
            tot = st.get("total_trades", 0)
            wr_by_seed[seed].append(wr)
            pf_by_seed[seed].append(pf)
            bal_by_seed[seed].append(bal)
            eod_flag = f"⚠ eod={eod}" if eod else "✓"
            print(f"  {seed:>6}  {run:>3}  {tot:>6}  {wr:>6.2f}  {pf:>6.3f}  "
                  f"{dd:>6.2f}  ${bal:>11,.2f}  {eod_flag}")
            sys.stdout.flush()
        print()

    # ── Learning curves ───────────────────────────────────────────────────────
    _print_curve(wr_by_seed,  label="WR%")
    _print_curve(pf_by_seed,  label="PF ")
    _print_curve(bal_by_seed, label="Bal")

    # ── Lessons ───────────────────────────────────────────────────────────────
    from trade_memory import TradeMemory as TM
    mem = TM(mem_file)
    lessons = mem.get_lessons()
    if lessons:
        print("\n\n  === Lessons Learned ===")
        for lesson in lessons:
            print(f"    • {lesson}")

    mem.print_summary()
    print()


# ── Live Mode ─────────────────────────────────────────────────────────────────

def _connect_mt5(max_attempts: int = 3) -> bool:
    """Try to connect to MT5, retrying on failure."""
    import mt5_connector as mt5c
    for attempt in range(1, max_attempts + 1):
        print(f"\n  Connecting to MT5 (attempt {attempt}/{max_attempts}) ...")
        if mt5c.connect():
            return True
        if attempt < max_attempts:
            wait = attempt * 5
            print(f"  Retrying in {wait}s  (make sure MT5 terminal is open and logged in)")
            time.sleep(wait)
    print("\n  [ERROR] Could not connect to MT5 after {max_attempts} attempts.")
    print("  ┌─ Check list ──────────────────────────────────────────────┐")
    print("  │  1. MetaTrader 5 terminal is open                         │")
    print("  │  2. You are logged in to your account                     │")
    print("  │  3. MT5_LOGIN / MT5_PASSWORD / MT5_SERVER in credentials.py│")
    print("  │  4. MT5 path in credentials.py matches your installation  │")
    print("  │  Run: python check_mt5.py  for a detailed diagnosis       │")
    print("  └───────────────────────────────────────────────────────────┘")
    return False


def run_live_mode(args):
    import mt5_connector as mt5c
    from live_trader import run_live

    _banner(
        "GRIWD FOREX BOT  [LIVE MODE]",
        "*** DRY RUN — No real orders ***" if args.dry_run else "",
    )

    if not _connect_mt5(max_attempts=args.retries):
        return

    # Resolve symbols
    if args.symbol:
        symbols = [s.strip() for s in args.symbol.split(",")]
        import MetaTrader5 as mt5
        for s in symbols:
            mt5.symbol_select(s, True)
    else:
        symbols = mt5c.discover_symbols()
        if not symbols:
            print("\n  [ERROR] No volatility symbols found on this account.")
            print("  Run: python check_mt5.py  to see all available symbols.")
            mt5c.disconnect()
            return

    print(f"\n  Trading {len(symbols)} symbol(s):")
    for s in symbols:
        tick = mt5c.get_tick(s)
        price_str = f"bid={tick['bid']:.5f}" if tick else "no tick"
        print(f"    {s:35s}  {price_str}")
    print()

    try:
        run_live(symbols=symbols, dry_run=args.dry_run)
    finally:
        mt5c.disconnect()


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    if args.live:
        run_live_mode(args)
    elif args.test:
        run_learning_test(args)
    else:
        run_backtest_mode(args)


if __name__ == "__main__":
    main()
