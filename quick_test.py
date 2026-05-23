"""Quick multi-seed test with eod/stop stats."""
import os, json
import pandas as pd
from data_feed import generate_synthetic_ohlcv, resample, compute_atr
from signal_engine import generate_signal
from risk_manager import RiskManager
from trade_memory import TradeMemory
from config import ENTRY_TF, CONFIRM_TF, TREND_TF, SWING_LOOKBACK, ATR_PERIOD

WARMUP = max(SWING_LOOKBACK * 4 + 5, ATR_PERIOD + 5, 50)

def run_once(seed, run_num, shared_memory_file):
    raw = generate_synthetic_ohlcv(seed=seed)
    df5 = raw.copy(); df5["atr"] = compute_atr(df5)
    data = {ENTRY_TF: df5}
    for tf in (CONFIRM_TF, TREND_TF):
        df = resample(raw, tf).copy(); df["atr"] = compute_atr(df)
        data[tf] = df

    memory = TradeMemory(shared_memory_file)
    rm = RiskManager(memory=memory)

    for i in range(WARMUP, len(df5)):
        ts = df5.index[i]
        price = df5["close"].iloc[i]
        hi = df5["high"].iloc[i]; lo = df5["low"].iloc[i]
        s5 = df5.iloc[:i+1]
        s15 = data[CONFIRM_TF].loc[:ts]; s1h = data[TREND_TF].loc[:ts]
        if s15.empty or s1h.empty: continue
        atr_now = s5["atr"].iloc[-1]
        if pd.isna(atr_now): atr_now = 1.0
        for t in list(rm.open_trades):
            rm.update_trailing_stop(t, price, atr_now)
            rm.check_close(t, price, ts, hi, lo)
        if rm.can_open():
            sig = generate_signal({ENTRY_TF:s5, CONFIRM_TF:s15, TREND_TF:s1h}, ts, memory=memory)
            if sig: rm.open_trade(sig, atr_now)

    lp = df5["close"].iloc[-1]; lt = df5.index[-1]
    eod_losses = []
    for t in list(rm.open_trades):
        rm._close(t, lp, lt, "end_of_data")
        eod_losses.append(round(t.pnl, 2))

    st = rm.stats()
    eod_n = len(eod_losses)
    stop_n = sum(1 for t in rm.closed_trades if t.status == "stopped")
    tp_n   = sum(1 for t in rm.closed_trades if t.status == "tp_hit")
    bal    = round(rm.balance, 2)
    wr     = st.get("win_rate", 0)
    pf     = st.get("profit_factor", 0)
    dd     = st.get("max_drawdown", 0)
    total  = st.get("total_trades", 0)
    print(f"{seed:>6}  {run_num:>4}  {total:>6}  {wr:>8.2f}  {pf:>8.3f}  "
          f"{dd:>8.2f}  ${bal:>12,.2f}  eod={eod_n} tp={tp_n} stp={stop_n}"
          + (f"  eod_pnl={eod_losses}" if eod_losses else ""))

SEEDS = [42, 99, 777, 123]
RUNS  = 3
MEM   = "trade_memory.json"

# wipe memory for clean test
if os.path.exists(MEM): os.remove(MEM)

print(f"{'Seed':>6}  {'Run':>4}  {'Trades':>6}  {'WR%':>8}  {'PF':>8}  {'DD%':>8}  {'Balance':>14}  detail")
print("-"*90)
for seed in SEEDS:
    for run in range(1, RUNS+1):
        run_once(seed, run, MEM)
    print()
