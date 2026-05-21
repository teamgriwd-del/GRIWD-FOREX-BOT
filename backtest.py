"""
Backtesting Engine
Walks through historical 5m candles bar-by-bar, generates signals,
manages open trades, and collects results.
"""

import pandas as pd
from data_feed import get_data, resample, compute_atr
from signal_engine import generate_signal
from risk_manager import RiskManager
from trade_memory import TradeMemory
from config import (
    DATA_SOURCE, ENTRY_TF, CONFIRM_TF, TREND_TF,
    SWING_LOOKBACK, ATR_PERIOD, MEMORY_FILE,
)

# Minimum bars needed before we start trading
WARMUP_BARS = max(SWING_LOOKBACK * 4 + 5, ATR_PERIOD + 5, 50)


def run_backtest(data: dict = None, verbose: bool = False) -> dict:
    """
    Run the full backtest.
    data: pre-loaded dict {"5m": df, "15m": df, "1h": df}
    Returns the RiskManager stats dict + equity curve list.
    """
    if data is None:
        data = get_data(DATA_SOURCE)

    df_5m  = data[ENTRY_TF]
    memory = TradeMemory(MEMORY_FILE)
    rm     = RiskManager(memory=memory)
    equity_curve = []

    print(f"Backtesting on {len(df_5m)} x 5m candles | "
          f"from {df_5m.index[0]} to {df_5m.index[-1]}")
    print("-" * 65)

    WIN = 300   # analysis window — keeps each analyze() call O(1) not O(n)
    for i in range(WARMUP_BARS, len(df_5m)):
        ts        = df_5m.index[i]
        price     = df_5m["close"].iloc[i]
        bar_high  = df_5m["high"].iloc[i]
        bar_low   = df_5m["low"].iloc[i]

        # Build bounded slices — prevents O(n²) FVG/swing analysis
        slice_5m  = df_5m.iloc[max(0, i - WIN + 1):i + 1]
        slice_15m = data[CONFIRM_TF].loc[:ts].iloc[-WIN:]
        slice_1h  = data[TREND_TF].loc[:ts].iloc[-WIN:]

        if slice_15m.empty or slice_1h.empty:
            continue

        atr_now = slice_5m["atr"].iloc[-1]
        if pd.isna(atr_now):
            atr_now = 1.0

        # Update open trades first
        closed_this_bar = []
        for trade in list(rm.open_trades):
            rm.update_trailing_stop(trade, price, atr_now)
            if rm.check_close(trade, price, ts, bar_high, bar_low):
                closed_this_bar.append(trade)
                if verbose:
                    pnl_str = f"+{trade.pnl:.2f}" if trade.pnl > 0 else f"{trade.pnl:.2f}"
                    print(f"  CLOSED [{trade.status:8s}] {trade.direction.upper():4s} "
                          f"entry={trade.entry:.4f} close={trade.close_price:.4f} "
                          f"PnL={pnl_str}")

        # Look for new signal
        if rm.can_open():
            current_data = {
                ENTRY_TF  : slice_5m,
                CONFIRM_TF: slice_15m,
                TREND_TF  : slice_1h,
            }
            signal = generate_signal(current_data, ts, memory=memory)
            if signal is not None:
                trade = rm.open_trade(signal, atr_now)
                if trade and verbose:
                    print(f"  OPEN  [{ts}] {trade.direction.upper():4s} "
                          f"entry={trade.entry:.4f} "
                          f"SL={trade.stop_loss:.4f} TP={trade.take_profit:.4f} "
                          f"score={signal.score} | {', '.join(signal.reasons)}")

        equity_curve.append({"timestamp": ts, "equity": rm.balance})

    # Close any still-open trades at last price
    last_price = df_5m["close"].iloc[-1]
    last_ts    = df_5m.index[-1]
    for trade in list(rm.open_trades):
        rm._close(trade, last_price, last_ts, "end_of_data")

    stats = rm.stats()
    stats["equity_curve"] = equity_curve
    return stats, rm, memory


def print_report(stats: dict):
    print("\n" + "=" * 65)
    print("  CTCFx SYNTHETIC TRADING BOT — BACKTEST RESULTS")
    print("=" * 65)
    print(f"  Total Trades   : {stats.get('total_trades', 0)}")
    print(f"  Wins           : {stats.get('wins', 0)}")
    print(f"  Losses         : {stats.get('losses', 0)}")
    print(f"  Win Rate       : {stats.get('win_rate', 0)}%")
    print(f"  Total PnL      : ${stats.get('total_pnl', 0):.2f}")
    print(f"  Avg Win        : ${stats.get('avg_win', 0):.2f}")
    print(f"  Avg Loss       : ${stats.get('avg_loss', 0):.2f}")
    print(f"  Profit Factor  : {stats.get('profit_factor', 0):.3f}")
    print(f"  Max Drawdown   : {stats.get('max_drawdown', 0)}%")
    print(f"  Final Balance  : ${stats.get('final_balance', 0):.2f}")
    print("=" * 65)


if __name__ == "__main__":
    results, rm, memory = run_backtest(verbose=True)
    print_report(results)
    memory.print_summary()
