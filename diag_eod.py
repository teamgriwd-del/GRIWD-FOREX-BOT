"""
Diagnostic: trace end-of-data losses on seeds 99 and 777.
Prints every trade open/close event + trailing stop evolution.
"""
import pandas as pd
from data_feed import generate_synthetic_ohlcv, resample, compute_atr
from signal_engine import generate_signal
from risk_manager import RiskManager, Trade
from trade_memory import TradeMemory
from config import (
    ENTRY_TF, CONFIRM_TF, TREND_TF,
    SWING_LOOKBACK, ATR_PERIOD,
)

WARMUP_BARS = max(SWING_LOOKBACK * 4 + 5, ATR_PERIOD + 5, 50)


def run_diag(seed: int):
    df_5m_raw = generate_synthetic_ohlcv(seed=seed)
    df_5m = df_5m_raw.copy()
    df_5m["atr"] = compute_atr(df_5m)
    data = {ENTRY_TF: df_5m}
    for tf in (CONFIRM_TF, TREND_TF):
        df = resample(df_5m_raw, tf).copy()
        df["atr"] = compute_atr(df)
        data[tf] = df

    memory = TradeMemory(":memory:")  # in-memory only, no file
    rm = RiskManager(memory=memory)

    print(f"\n{'='*70}")
    print(f"  SEED {seed} — Trade Diagnostics")
    print(f"{'='*70}")

    for i in range(WARMUP_BARS, len(df_5m)):
        ts       = df_5m.index[i]
        price    = df_5m["close"].iloc[i]
        bar_high = df_5m["high"].iloc[i]
        bar_low  = df_5m["low"].iloc[i]

        slice_5m  = df_5m.iloc[:i + 1]
        slice_15m = data[CONFIRM_TF].loc[:ts]
        slice_1h  = data[TREND_TF].loc[:ts]
        if slice_15m.empty or slice_1h.empty:
            continue

        atr_now = slice_5m["atr"].iloc[-1]
        if pd.isna(atr_now):
            atr_now = 1.0

        # Track trailing stop movement on open trades
        for trade in rm.open_trades:
            old_sl = trade.stop_loss
            rm.update_trailing_stop(trade, price, atr_now)
            new_sl = trade.stop_loss
            if abs(new_sl - old_sl) > 0.001:
                direction_ok = (trade.direction == "buy" and new_sl > old_sl) or \
                               (trade.direction == "sell" and new_sl < old_sl)
                flag = "" if direction_ok else " *** WRONG DIRECTION ***"
                print(f"  [TS {ts}] T#{trade.id} {trade.direction} "
                      f"SL moved: {old_sl:.4f} → {new_sl:.4f} "
                      f"(price={price:.4f}, atr={atr_now:.4f}){flag}")

        for trade in list(rm.open_trades):
            if rm.check_close(trade, price, ts, bar_high, bar_low):
                pnl_str = f"+{trade.pnl:.2f}" if trade.pnl > 0 else f"{trade.pnl:.2f}"
                print(f"  CLOSED [{trade.status:12s}] T#{trade.id} "
                      f"{trade.direction.upper()} entry={trade.entry:.4f} "
                      f"close={trade.close_price:.4f} PnL={pnl_str}")

        if rm.can_open():
            current_data = {
                ENTRY_TF  : slice_5m,
                CONFIRM_TF: slice_15m,
                TREND_TF  : slice_1h,
            }
            signal = generate_signal(current_data, ts, memory=memory)
            if signal is not None:
                trade = rm.open_trade(signal, atr_now)
                if trade:
                    print(f"  OPEN  [{ts}] T#{trade.id} {trade.direction.upper()} "
                          f"entry={trade.entry:.4f} SL={trade.stop_loss:.4f} "
                          f"TP={trade.take_profit:.4f} score={signal.score:.2f}")

    last_price = df_5m["close"].iloc[-1]
    last_ts    = df_5m.index[-1]
    print(f"\n  End of data  price={last_price:.4f}")
    for trade in list(rm.open_trades):
        old_sl = trade.stop_loss
        init_sl_dir_ok = (trade.direction == "buy" and old_sl < trade.entry) or \
                         (trade.direction == "sell" and old_sl > trade.entry)
        pnl_eod = ((last_price - trade.entry) if trade.direction == "buy"
                   else (trade.entry - last_price)) * trade.lot_size
        print(f"  EOD-OPEN  T#{trade.id} {trade.direction.upper()} "
              f"entry={trade.entry:.4f} SL={trade.stop_loss:.4f} "
              f"TP={trade.take_profit:.4f} "
              f"curr_price={last_price:.4f} "
              f"unreal_pnl={pnl_eod:.2f} "
              f"SL_above_entry={not init_sl_dir_ok}")
        rm._close(trade, last_price, last_ts, "end_of_data")
        print(f"  EOD-CLOSE T#{trade.id} final_pnl={trade.pnl:.2f}")

    stats = rm.stats()
    print(f"\n  Trades={stats.get('total_trades',0)}  "
          f"WR={stats.get('win_rate',0)}%  "
          f"PF={stats.get('profit_factor',0)}  "
          f"DD={stats.get('max_drawdown',0)}%  "
          f"Balance=${stats.get('final_balance',0):.2f}")


if __name__ == "__main__":
    for seed in (99, 777):
        run_diag(seed)
