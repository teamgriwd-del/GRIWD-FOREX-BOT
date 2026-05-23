"""
Multi-seed generalization test. Runs N backtests per seed, accumulates learning,
and reports summary stats. Identical to what the earlier sessions used.
"""
import os, sys
import pandas as pd
from data_feed import generate_synthetic_ohlcv, resample, compute_atr
from signal_engine import generate_signal
from risk_manager import RiskManager
from trade_memory import TradeMemory
from config import ENTRY_TF, CONFIRM_TF, TREND_TF, SWING_LOOKBACK, ATR_PERIOD

WARMUP = max(SWING_LOOKBACK * 4 + 5, ATR_PERIOD + 5, 50)
N_CANDLES = int(os.environ.get("N_CANDLES", "5000"))
SEEDS = [42, 99, 777, 123]
RUNS  = int(os.environ.get("RUNS", "5"))
MEM   = os.environ.get("MEM_FILE", "trade_memory.json")


def run_one(seed, run_num, mem_file):
    raw = generate_synthetic_ohlcv(n_candles=N_CANDLES, seed=seed)
    df5 = raw.copy()
    df5["atr"] = compute_atr(df5)
    data = {ENTRY_TF: df5}
    for tf in (CONFIRM_TF, TREND_TF):
        df = resample(raw, tf).copy()
        df["atr"] = compute_atr(df)
        data[tf] = df

    memory = TradeMemory(mem_file)
    rm = RiskManager(memory=memory)

    print(f"Backtesting on {N_CANDLES} x 5m candles | "
          f"from {df5.index[0]} to {df5.index[-1]}")
    print("-" * 65)
    sys.stdout.flush()

    for i in range(WARMUP, len(df5)):
        ts       = df5.index[i]
        price    = df5["close"].iloc[i]
        bar_high = df5["high"].iloc[i]
        bar_low  = df5["low"].iloc[i]
        s5  = df5.iloc[:i + 1]
        s15 = data[CONFIRM_TF].loc[:ts]
        s1h = data[TREND_TF].loc[:ts]
        if s15.empty or s1h.empty:
            continue
        atr_now = s5["atr"].iloc[-1]
        if pd.isna(atr_now):
            atr_now = 1.0

        for t in list(rm.open_trades):
            rm.update_trailing_stop(t, price, atr_now)
            rm.check_close(t, price, ts, bar_high, bar_low)

        if rm.can_open():
            sig = generate_signal({ENTRY_TF: s5, CONFIRM_TF: s15, TREND_TF: s1h},
                                  ts, memory=memory)
            if sig:
                rm.open_trade(sig, atr_now)

    lp = df5["close"].iloc[-1]
    lt = df5.index[-1]
    eod_n = 0
    for t in list(rm.open_trades):
        rm._close(t, lp, lt, "end_of_data")
        eod_n += 1

    st     = rm.stats()
    stop_n = sum(1 for t in rm.closed_trades if t.status == "stopped")
    tp_n   = sum(1 for t in rm.closed_trades if t.status == "tp_hit")
    total  = st.get("total_trades", 0)
    wr     = st.get("win_rate", 0)
    pf     = st.get("profit_factor", 0)
    dd     = st.get("max_drawdown", 0)
    bal    = st.get("final_balance", 0)
    print(f"{seed:<8} {run_num:<5} {total:<8} {wr:<8.2f} {pf:<8.3f} "
          f"{dd:<8.2f} $ {bal:>10,.2f}  eod={eod_n}/tp={tp_n}/stp={stop_n}")
    sys.stdout.flush()
    return st


if __name__ == "__main__":
    if os.path.exists(MEM):
        os.remove(MEM)

    print(f"{'Seed':<8} {'Run':<5} {'Trades':<8} {'WR%':<8} {'PF':<8} "
          f"{'DD%':<8} {'Balance':>14}  eod/tp/stp")
    print("=" * 70)

    all_stats = []
    for seed in SEEDS:
        for run in range(1, RUNS + 1):
            st = run_one(seed, run, MEM)
            all_stats.append(st)
        print()

    print("\n=== Lessons ===")
    mem = TradeMemory(MEM)
    for lesson in mem.get_lessons():
        print(f" • {lesson}")
