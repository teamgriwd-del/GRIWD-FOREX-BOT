"""
MetaTrader 5 Connector
Handles: login, live OHLCV data, order placement, position management.
Instrument: Volatility 75 Index (Deriv Synthetic)
"""

import time
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5

from credentials import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH, MT5_SERVER_FALLBACKS
from data_feed import compute_atr
from config import ATR_PERIOD, INSTRUMENT

# Map config timeframe strings to MT5 timeframe constants
TF_MAP = {
    "1m" : mt5.TIMEFRAME_M1,
    "5m" : mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h" : mt5.TIMEFRAME_H1,
    "4h" : mt5.TIMEFRAME_H4,
    "1d" : mt5.TIMEFRAME_D1,
}

# Weltrade Volatility 75 symbol variants to try
# Exact name is visible in MT5 under Market Watch after login
SYMBOL_CANDIDATES = [
    "Volatility 75 Index",
    "Volatility 75 (1s) Index",
    "R_75",
    "Vol75",
    "VOLX75",
    "VIX75",
    "Volatility_75",
    "Vol 75",
    "VOLATILITY75",
    "Synth75",
]


# ── Connection ────────────────────────────────────────────────────────────────

def connect() -> bool:
    """Initialize MT5 terminal and log in. Tries fallback servers if needed."""
    if not mt5.initialize(MT5_PATH):
        print(f"[MT5] initialize() failed: {mt5.last_error()}")
        return False

    # Try primary server first, then fallbacks
    servers = [MT5_SERVER] + [s for s in MT5_SERVER_FALLBACKS if s != MT5_SERVER]
    for server in servers:
        result = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=server)
        if result:
            info = mt5.account_info()
            print(f"[MT5] Connected to {server}")
            print(f"      Account : {info.login}")
            print(f"      Name    : {info.name}")
            print(f"      Balance : ${info.balance:.2f}  Equity: ${info.equity:.2f}")
            print(f"      Currency: {info.currency}")
            return True
        print(f"[MT5] Login failed on {server}: {mt5.last_error()}")

    print("[MT5] All server attempts failed. Is MT5 terminal open and logged in?")
    return False


def disconnect():
    mt5.shutdown()
    print("[MT5] Disconnected.")


def account_info() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance"    : info.balance,
        "equity"     : info.equity,
        "margin"     : info.margin,
        "free_margin": info.margin_free,
        "profit"     : info.profit,
        "currency"   : info.currency,
        "leverage"   : info.leverage,
        "trade_mode" : info.trade_mode,   # 0=demo, 1=real/live
    }


# ── Symbol Resolution ─────────────────────────────────────────────────────────

def resolve_symbol(candidates: list = SYMBOL_CANDIDATES) -> Optional[str]:
    """Find the first matching volatility symbol on this broker."""
    all_symbols = {s.name for s in (mt5.symbols_get() or [])}
    for candidate in candidates:
        if candidate in all_symbols:
            mt5.symbol_select(candidate, True)
            return candidate
    for sym in all_symbols:
        if "vol" in sym.lower():
            mt5.symbol_select(sym, True)
            print(f"[MT5] Resolved symbol: {sym}")
            return sym
    return None


def discover_symbols(keywords: list = None) -> list:
    """
    Auto-discover all tradeable volatility symbols from the broker.
    Returns a list of symbol name strings, sorted alphabetically.
    keywords: list of strings — symbol name must contain at least one.
    """
    from config import SYMBOL_KEYWORDS
    if keywords is None:
        keywords = SYMBOL_KEYWORDS

    all_syms = mt5.symbols_get() or []
    matched = []
    for s in all_syms:
        name_lower = s.name.lower()
        if any(kw.lower() in name_lower for kw in keywords):
            mt5.symbol_select(s.name, True)   # enable in Market Watch
            matched.append(s.name)

    matched.sort()
    print(f"[MT5] Auto-discovered {len(matched)} symbol(s): {matched}")
    return matched


# ── Live Price Data ───────────────────────────────────────────────────────────

def get_ohlcv(symbol: str, timeframe: str, n_bars: int = 500) -> Optional[pd.DataFrame]:
    """Fetch n_bars of OHLCV from MT5 for given timeframe."""
    tf = TF_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
    if rates is None or len(rates) == 0:
        print(f"[MT5] No data for {symbol} {timeframe}: {mt5.last_error()}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df.rename(columns={
        "open" : "open",
        "high" : "high",
        "low"  : "low",
        "close": "close",
        "tick_volume": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df["atr"] = compute_atr(df, ATR_PERIOD)
    return df


def get_tick(symbol: str) -> Optional[dict]:
    """Get latest bid/ask tick."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {
        "bid"  : tick.bid,
        "ask"  : tick.ask,
        "mid"  : (tick.bid + tick.ask) / 2.0,
        "time" : datetime.fromtimestamp(tick.time, tz=timezone.utc),
        "spread": tick.ask - tick.bid,
    }


# ── Order Execution ───────────────────────────────────────────────────────────

def _symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info unavailable for {symbol}")
    return info


def _round_price(price: float, symbol: str) -> float:
    info = _symbol_info(symbol)
    digits = info.digits
    return round(price, digits)


def _round_lot(lot: float, symbol: str) -> float:
    info = _symbol_info(symbol)
    step = info.volume_step
    lot  = max(info.volume_min, min(info.volume_max, lot))
    return round(round(lot / step) * step, 8)


def _get_filling_mode(symbol: str) -> int:
    """
    Auto-detect the filling mode supported by this symbol.
    filling_mode bitmask: 1=FOK, 2=IOC, 4=RETURN (0 also means FOK on some brokers).
    Weltrade FX Vol symbols typically only support FOK or RETURN.
    """
    info = _symbol_info(symbol)
    fm = info.filling_mode
    if fm & 1:                        # FOK supported
        return mt5.ORDER_FILLING_FOK
    if fm & 2:                        # IOC supported
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN   # fallback: RETURN (partial fills allowed)


def place_market_order(symbol: str, direction: str, lot: float,
                       stop_loss: float, take_profit: float,
                       comment: str = "GRIWD") -> Optional[dict]:
    """
    Place a market order.
    direction: "buy" | "sell"
    Returns order result dict or None on failure.
    """
    tick = get_tick(symbol)
    if tick is None:
        print("[MT5] Cannot place order: no tick data.")
        return None

    order_type   = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
    price        = tick["ask"] if direction == "buy" else tick["bid"]
    filling_mode = _get_filling_mode(symbol)

    lot = _round_lot(lot, symbol)
    sl  = _round_price(stop_loss,   symbol)
    tp  = _round_price(take_profit, symbol)

    request = {
        "action"      : mt5.TRADE_ACTION_DEAL,
        "symbol"      : symbol,
        "volume"      : lot,
        "type"        : order_type,
        "price"       : price,
        "sl"          : sl,
        "tp"          : tp,
        "deviation"   : 20,
        "magic"       : 202400,
        "comment"     : comment,
        "type_time"   : mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    result = mt5.order_send(request)
    if result is None:
        print(f"[MT5] order_send returned None: {mt5.last_error()}")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[MT5] Order failed: retcode={result.retcode} | {result.comment}")
        return None

    print(f"[MT5] Order placed: {direction.upper()} {lot} {symbol} "
          f"@ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}  ticket={result.order}")
    return {
        "ticket"    : result.order,
        "price"     : result.price,
        "volume"    : result.volume,
        "direction" : direction,
        "sl"        : sl,
        "tp"        : tp,
        "symbol"    : symbol,
    }


def modify_sl(ticket: int, new_sl: float, symbol: str) -> bool:
    """Modify stop loss of an open position (trailing stop)."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False
    pos = positions[0]
    request = {
        "action"  : mt5.TRADE_ACTION_SLTP,
        "symbol"  : symbol,
        "sl"      : _round_price(new_sl, symbol),
        "tp"      : pos.tp,
        "position": ticket,
    }
    result = mt5.order_send(request)
    return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE


def close_position(ticket: int, symbol: str) -> bool:
    """Close a specific open position by ticket."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        print(f"[MT5] Position {ticket} not found.")
        return False
    pos = positions[0]
    direction = "sell" if pos.type == mt5.POSITION_TYPE_BUY else "buy"
    tick = get_tick(symbol)
    if tick is None:
        return False
    price = tick["bid"] if direction == "sell" else tick["ask"]
    order_type = mt5.ORDER_TYPE_SELL if direction == "sell" else mt5.ORDER_TYPE_BUY
    request = {
        "action"      : mt5.TRADE_ACTION_DEAL,
        "symbol"      : symbol,
        "volume"      : pos.volume,
        "type"        : order_type,
        "position"    : ticket,
        "price"       : price,
        "deviation"   : 20,
        "magic"       : 202400,
        "comment"     : "GRIWD close",
        "type_time"   : mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[MT5] Closed position {ticket}")
        return True
    print(f"[MT5] Close failed: {result.retcode if result else mt5.last_error()}")
    return False


def get_open_positions(symbol: str = None, magic: int = 202400) -> list:
    """Return list of open positions placed by this bot."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    return [p for p in positions if p.magic == magic]


def get_trade_history(symbol: str, from_date: datetime, to_date: datetime) -> list:
    """Return closed deals history."""
    deals = mt5.history_deals_get(from_date, to_date, group=symbol)
    return list(deals) if deals else []


def list_all_symbols(filter_str: str = "") -> list:
    """Print all available symbols (optionally filtered). Use after login to find correct name."""
    symbols = mt5.symbols_get() or []
    names = sorted(s.name for s in symbols)
    if filter_str:
        names = [n for n in names if filter_str.lower() in n.lower()]
    return names


def print_symbols(filter_str: str = ""):
    """Print available symbols to console. Run once after login to find your instrument."""
    names = list_all_symbols(filter_str)
    print(f"\nAvailable symbols ({len(names)} matched '{filter_str}'):")
    for n in names:
        print(f"  {n}")
    print()
