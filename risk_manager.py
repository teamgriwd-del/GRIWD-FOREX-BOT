"""
Risk Manager
Handles position sizing, trade tracking, trailing stops,
drawdown limits, and equity curve management.
"""

from dataclasses import dataclass, field
from typing import Optional
from config import (
    ACCOUNT_BALANCE, RISK_PER_TRADE_PCT, MAX_OPEN_TRADES,
    TRAILING_STOP, TRAILING_ATR_MULT, COMMISSION,
    PIP_VALUE, CONTRACT_SIZE,
)


@dataclass
class Trade:
    id: int
    direction: str        # "buy" | "sell"
    entry: float
    stop_loss: float
    take_profit: float
    lot_size: float
    open_time: object
    close_time: object = None
    close_price: float = 0.0
    pnl: float = 0.0
    status: str = "open"  # "open" | "closed" | "stopped"
    trailing_stop: float = 0.0
    reasons: list = field(default_factory=list)
    pattern: str = ""
    score: float = 0.0


class RiskManager:
    def __init__(self, balance: float = ACCOUNT_BALANCE, memory=None):
        self.balance        = balance
        self.equity         = balance
        self.peak_equity    = balance
        self.open_trades: list[Trade] = []
        self.closed_trades: list[Trade] = []
        self._trade_counter = 0
        self._memory        = memory   # TradeMemory instance (optional)

    # ── Position Sizing ───────────────────────────────────────────────────────

    def position_size(self, entry: float, stop_loss: float) -> float:
        """Calculate lot size based on risk % and stop distance."""
        risk_amount = self.balance * RISK_PER_TRADE_PCT
        stop_distance = abs(entry - stop_loss)
        if stop_distance == 0:
            return 0.01
        # Assume pip_value per lot; stop_distance in price units = pips
        lot_size = risk_amount / (stop_distance * PIP_VALUE * CONTRACT_SIZE)
        return max(0.01, round(lot_size, 2))

    # ── Trade Lifecycle ───────────────────────────────────────────────────────

    def can_open(self) -> bool:
        return len(self.open_trades) < MAX_OPEN_TRADES

    def open_trade(self, signal, atr: float = 1.0) -> Optional[Trade]:
        if not self.can_open():
            return None
        self._trade_counter += 1
        lot = self.position_size(signal.entry, signal.stop_loss)
        trade = Trade(
            id=self._trade_counter,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            lot_size=lot,
            open_time=signal.timestamp,
            trailing_stop=signal.stop_loss,
            reasons=signal.reasons,
            pattern=signal.pattern,
            score=signal.score,
        )
        self.open_trades.append(trade)
        return trade

    def update_trailing_stop(self, trade: Trade, current_price: float, atr: float):
        """Move stop loss in profit direction if TRAILING_STOP enabled."""
        if not TRAILING_STOP:
            return
        trail_dist = atr * TRAILING_ATR_MULT
        if trade.direction == "buy":
            new_stop = current_price - trail_dist
            if new_stop > trade.trailing_stop:
                trade.trailing_stop = new_stop
                trade.stop_loss = new_stop
        else:
            new_stop = current_price + trail_dist
            if new_stop < trade.trailing_stop or trade.trailing_stop == trade.stop_loss:
                trade.trailing_stop = new_stop
                trade.stop_loss = new_stop

    def check_close(self, trade: Trade, current_price: float,
                    current_time, bar_high: float = None,
                    bar_low: float = None) -> bool:
        """
        Returns True if trade should be closed.
        Uses bar high/low for intrabar SL/TP detection so wicks don't slip past stops.
        Falls back to close price when high/low are not provided.
        """
        hi = bar_high if bar_high is not None else current_price
        lo = bar_low  if bar_low  is not None else current_price

        if trade.direction == "buy":
            if lo <= trade.stop_loss:
                self._close(trade, trade.stop_loss, current_time, "stopped")
                return True
            if hi >= trade.take_profit:
                self._close(trade, trade.take_profit, current_time, "tp_hit")
                return True
        else:
            if hi >= trade.stop_loss:
                self._close(trade, trade.stop_loss, current_time, "stopped")
                return True
            if lo <= trade.take_profit:
                self._close(trade, trade.take_profit, current_time, "tp_hit")
                return True
        return False

    def _close(self, trade: Trade, price: float, time, status: str):
        if trade.direction == "buy":
            gross = (price - trade.entry) * trade.lot_size * CONTRACT_SIZE * PIP_VALUE
        else:
            gross = (trade.entry - price) * trade.lot_size * CONTRACT_SIZE * PIP_VALUE
        trade.pnl         = gross - COMMISSION
        trade.close_price = price
        trade.close_time  = time
        trade.status      = status
        self.balance     += trade.pnl
        self.equity       = self.balance
        self.peak_equity  = max(self.peak_equity, self.equity)
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        # Teach the learning engine what this trade looked like
        if self._memory is not None:
            self._memory.record_trade(trade)

    # ── Portfolio Stats ───────────────────────────────────────────────────────

    @property
    def drawdown(self) -> float:
        if self.peak_equity == 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    def stats(self) -> dict:
        trades = self.closed_trades
        if not trades:
            return {"total_trades": 0}
        wins      = [t for t in trades if t.pnl > 0]
        losses    = [t for t in trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in trades)
        win_rate  = len(wins) / len(trades) if trades else 0
        avg_win   = sum(t.pnl for t in wins)   / len(wins)   if wins   else 0
        avg_loss  = sum(t.pnl for t in losses) / len(losses) if losses else 0
        profit_factor = (
            abs(sum(t.pnl for t in wins)) / abs(sum(t.pnl for t in losses))
            if losses and sum(t.pnl for t in losses) != 0 else float("inf")
        )
        return {
            "total_trades"  : len(trades),
            "wins"          : len(wins),
            "losses"        : len(losses),
            "win_rate"      : round(win_rate * 100, 2),
            "total_pnl"     : round(total_pnl, 2),
            "avg_win"       : round(avg_win, 2),
            "avg_loss"      : round(avg_loss, 2),
            "profit_factor" : round(profit_factor, 3),
            "max_drawdown"  : round(self.drawdown * 100, 2),
            "final_balance" : round(self.balance, 2),
        }
