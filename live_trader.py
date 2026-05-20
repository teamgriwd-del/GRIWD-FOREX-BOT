"""
Live Trading Engine — Multi-Symbol
Connects to MT5, auto-discovers all Vol symbols, and scans every one
on each cycle. Manages positions per symbol independently.
"""

import time
import logging
from datetime import datetime, timezone
from collections import defaultdict

import mt5_connector as mt5c
from signal_engine import generate_signal
from trade_memory import TradeMemory
from config import (
    ENTRY_TF, CONFIRM_TF, TREND_TF,
    ACCOUNT_BALANCE, RISK_PER_TRADE_PCT, LIVE_RISK_PER_TRADE,
    MAX_OPEN_TRADES, LIVE_MAX_OPEN_TRADES, MAX_TRADES_PER_SYMBOL,
    TRAILING_STOP, TRAILING_ATR_MULT,
    AUTO_DISCOVER_SYMBOLS, INSTRUMENTS, SYMBOL_KEYWORDS,
    MEMORY_FILE, MODE,
    SIGNAL_THRESHOLD, LIVE_SIGNAL_THRESHOLD,
    MICRO_BALANCE_THRESHOLD,
)

# Shared learning memory — loads prior backtest knowledge and accumulates live data
_memory = TradeMemory(MEMORY_FILE)

# ── Logging ───────────────────────────────────────────────────────────────────
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler("live_trading.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),   # stdout avoids PowerShell NativeCommandError
    ],
)
log = logging.getLogger("CTCFx")

SCAN_INTERVAL = 60      # seconds between full multi-symbol scans
BARS_PER_TF   = {ENTRY_TF: 300, CONFIRM_TF: 200, TREND_TF: 150}

# ticket -> metadata dict, keyed per symbol
open_tickets: dict[str, dict] = defaultdict(dict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_balance() -> float:
    acct = mt5c.account_info()
    return acct.get("balance", ACCOUNT_BALANCE)


def calc_lot(entry: float, stop_loss: float, balance: float) -> float:
    risk_pct = LIVE_RISK_PER_TRADE if MODE.mode != "backtest" else RISK_PER_TRADE_PCT
    risk = balance * risk_pct
    dist = abs(entry - stop_loss)
    if dist == 0:
        return 0.01
    return max(0.01, round(risk / dist, 2))


def fetch_data(symbol: str) -> dict | None:
    data = {}
    for tf, n in BARS_PER_TF.items():
        df = mt5c.get_ohlcv(symbol, tf, n)
        if df is None or df.empty:
            return None
        data[tf] = df
    return data


# ── Position Management ───────────────────────────────────────────────────────

def sync_positions(symbols: list):
    """Remove tickets that MT5 already closed (SL/TP hit)."""
    live = {p.ticket for p in mt5c.get_open_positions()}
    for sym in symbols:
        closed = [t for t in open_tickets[sym] if t not in live]
        for t in closed:
            meta = open_tickets[sym].pop(t)
            log.info(f"  [{sym}] Position closed by MT5: ticket={t} dir={meta['direction']}")


def update_trailing(symbols: list):
    if not TRAILING_STOP:
        return
    for sym in symbols:
        tick = mt5c.get_tick(sym)
        if tick is None:
            continue
        price = tick["mid"]
        for ticket, meta in list(open_tickets[sym].items()):
            atr       = meta.get("atr", 1.0)
            trail     = atr * TRAILING_ATR_MULT
            direction = meta["direction"]
            entry     = meta.get("entry", price)
            if direction == "buy":
                if price > entry:                    # only trail once in profit
                    new_sl = price - trail
                    if new_sl > meta["sl"]:
                        if mt5c.modify_sl(ticket, new_sl, sym):
                            open_tickets[sym][ticket]["sl"] = new_sl
                            log.info(f"  [{sym}] Trail SL UP  ticket={ticket}  sl={new_sl:.5f}")
            else:
                if price < entry:                    # only trail once in profit
                    new_sl = price + trail
                    if new_sl < meta["sl"]:
                        if mt5c.modify_sl(ticket, new_sl, sym):
                            open_tickets[sym][ticket]["sl"] = new_sl
                            log.info(f"  [{sym}] Trail SL DOWN ticket={ticket}  sl={new_sl:.5f}")


# ── Per-Symbol Scan ───────────────────────────────────────────────────────────

def scan_symbol(symbol: str, balance: float, dry_run: bool, now: datetime):
    """Run full signal analysis on one symbol and place trade if signal fires."""
    sym_positions = len(open_tickets[symbol])
    if sym_positions >= MAX_TRADES_PER_SYMBOL:
        return   # already at max for this symbol

    max_trades      = LIVE_MAX_OPEN_TRADES if MODE.mode != "backtest" else MAX_OPEN_TRADES
    total_positions = sum(len(v) for v in open_tickets.values())
    if total_positions >= max_trades:
        return   # global cap reached

    data = fetch_data(symbol)
    if data is None:
        log.warning(f"  [{symbol}] Data fetch failed, skipping")
        return

    atr_now = data[ENTRY_TF]["atr"].iloc[-1]
    price   = data[ENTRY_TF]["close"].iloc[-1]

    signal = generate_signal(data, timestamp=now, memory=_memory)
    if signal is None:
        return   # no confluence — stay silent

    log.info(f"  [{symbol}] SIGNAL {signal.direction.upper()}  "
             f"score={signal.score}  RR={signal.rr_ratio:.2f}  "
             f"entry={signal.entry:.5f}  SL={signal.stop_loss:.5f}  TP={signal.take_profit:.5f}")
    log.info(f"    reasons : {' | '.join(signal.reasons)}")
    if signal.pattern:
        log.info(f"    candle  : {signal.pattern}")
    if signal.chart_pattern:
        log.info(f"    chart   : {signal.chart_pattern}")

    lot = calc_lot(signal.entry, signal.stop_loss, balance)

    if dry_run:
        log.info(f"  [{symbol}] [DRY RUN] {signal.direction.upper()} "
                 f"{lot} lots  SL={signal.stop_loss:.5f}  TP={signal.take_profit:.5f}")
        return

    result = mt5c.place_market_order(
        symbol      = symbol,
        direction   = signal.direction,
        lot         = lot,
        stop_loss   = signal.stop_loss,
        take_profit = signal.take_profit,
        comment     = f"CTCFx|{signal.pattern or 'sig'}|sc{signal.score}",
    )
    if result:
        open_tickets[symbol][result["ticket"]] = {
            "direction": signal.direction,
            "sl"       : signal.stop_loss,
            "tp"       : signal.take_profit,
            "atr"      : atr_now,
            "entry"    : signal.entry,
            "lot"      : lot,
            "time"     : now,
        }


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_live(symbols: list = None, dry_run: bool = False):
    """
    Main live trading loop — multi-symbol.
    symbols: explicit list of symbol strings, or None to auto-discover.
    dry_run: generate signals but skip order placement.
    """
    # ── Resolve symbol list ────────────────────────────────────────────────────
    if symbols:
        active_symbols = symbols
    elif AUTO_DISCOVER_SYMBOLS:
        active_symbols = mt5c.discover_symbols(SYMBOL_KEYWORDS)
    else:
        active_symbols = list(INSTRUMENTS)

    if not active_symbols:
        log.error("No symbols found. Check SYMBOL_KEYWORDS in config.py "
                  "or pass --symbol explicitly.")
        return

    log.info("=" * 65)
    log.info("  CTCFx LIVE TRADING ENGINE — MULTI-SYMBOL")
    if dry_run:
        log.info("  *** DRY RUN — signals only, no real orders ***")
    log.info(f"  Symbols  : {active_symbols}")
    log.info(f"  Interval : {SCAN_INTERVAL}s")
    log.info(f"  Max trades per symbol: {MAX_TRADES_PER_SYMBOL}")
    log.info(f"  Max total trades     : {MAX_OPEN_TRADES}")
    log.info("=" * 65)

    acct = mt5c.account_info()
    balance_now = acct.get("balance", ACCOUNT_BALANCE)
    # MT5 trade_mode: 0 = demo, 1 = real/live
    is_live = acct.get("trade_mode", 0) == 1
    is_demo = not is_live
    MODE.configure(balance=balance_now, is_live=is_live, is_demo=is_demo)

    acct_label = "LIVE" if MODE.mode == "live" else "DEMO"
    threshold  = LIVE_SIGNAL_THRESHOLD if MODE.mode != "backtest" else SIGNAL_THRESHOLD
    max_trades = LIVE_MAX_OPEN_TRADES  if MODE.mode != "backtest" else MAX_OPEN_TRADES
    risk_pct   = LIVE_RISK_PER_TRADE   if MODE.mode != "backtest" else RISK_PER_TRADE_PCT

    log.info(f"  Account  : {balance_now:.2f} {acct.get('currency', 'USD')}  "
             f"[{acct_label}]  type={MODE.account_type.upper()}")
    log.info(f"  Signal threshold : {threshold}  "
             f"Risk/trade : {risk_pct*100:.1f}%  "
             f"Max trades : {max_trades}")

    lessons = _memory.get_lessons()
    if lessons:
        log.info("  Learned lessons from trade memory:")
        for lesson in lessons:
            log.info(f"    • {lesson}")

    consecutive_errors = 0

    while True:
        try:
            now = datetime.now(tz=timezone.utc)
            balance = get_balance()

            # ── Housekeeping ───────────────────────────────────────────────────
            sync_positions(active_symbols)
            update_trailing(active_symbols)

            total_open = sum(len(v) for v in open_tickets.values())
            max_trades = LIVE_MAX_OPEN_TRADES if MODE.mode != "backtest" else MAX_OPEN_TRADES
            log.info(f"--- Scan cycle | balance=${balance:.2f}  "
                     f"open={total_open}/{max_trades} [{MODE.mode}] ---")

            # ── Scan every symbol ──────────────────────────────────────────────
            for sym in active_symbols:
                try:
                    scan_symbol(sym, balance, dry_run, now)
                except Exception as sym_err:
                    log.error(f"  [{sym}] Error: {sym_err}")

            consecutive_errors = 0

        except KeyboardInterrupt:
            log.info("Interrupted. Shutting down.")
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"Loop error: {e}", exc_info=True)
            if consecutive_errors >= 5:
                log.critical("5 consecutive errors — stopping bot for safety.")
                break
            time.sleep(30)
            continue

        time.sleep(SCAN_INTERVAL)

    log.info("Live trader stopped.")
