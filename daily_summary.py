"""
GRIWD Forex Bot — Daily Trade Summary
Connects to MT5 and prints a full summary of today's closed trades.

Usage:
  python daily_summary.py              # today's summary
  python daily_summary.py --date 2026-05-21   # specific date
  python daily_summary.py --days 7    # last 7 days
"""

import argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import MetaTrader5 as mt5

from credentials import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH, MT5_SERVER_FALLBACKS


# ── MT5 Connection ─────────────────────────────────────────────────────────────

def connect() -> bool:
    if not mt5.initialize(MT5_PATH):
        print(f"[MT5] initialize() failed: {mt5.last_error()}")
        return False
    servers = [MT5_SERVER] + [s for s in MT5_SERVER_FALLBACKS if s != MT5_SERVER]
    for server in servers:
        if mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=server):
            return True
    print("[MT5] Login failed. Is MT5 terminal open and logged in?")
    return False


# ── Fetch Deals ────────────────────────────────────────────────────────────────

def fetch_deals(from_dt: datetime, to_dt: datetime) -> list:
    """Return all closed deals in the given UTC datetime range."""
    deals = mt5.history_deals_get(from_dt, to_dt)
    if deals is None:
        return []
    # Filter: only OUT deals (entries are IN, exits are OUT) and skip deposits/withdrawals
    return [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.type in (
        mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL
    )]


# ── Summary Printer ────────────────────────────────────────────────────────────

def print_summary(deals: list, label: str):
    W = 65
    print("\n" + "=" * W)
    print(f"  GRIWD FOREX BOT — {label}")
    print("=" * W)

    if not deals:
        print("  No closed trades found for this period.")
        print("=" * W)
        return

    # ── Per-symbol breakdown ───────────────────────────────────────────────────
    by_symbol = defaultdict(list)
    for d in deals:
        by_symbol[d.symbol].append(d)

    total_trades = len(deals)
    wins         = [d for d in deals if d.profit > 0]
    losses       = [d for d in deals if d.profit <= 0]
    total_pnl    = sum(d.profit for d in deals)
    gross_profit = sum(d.profit for d in wins)
    gross_loss   = abs(sum(d.profit for d in losses))
    win_rate     = len(wins) / total_trades * 100 if total_trades else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win      = gross_profit / len(wins)   if wins   else 0
    avg_loss     = gross_loss   / len(losses) if losses else 0
    best_trade   = max(deals, key=lambda d: d.profit)
    worst_trade  = min(deals, key=lambda d: d.profit)

    # ── Overview ───────────────────────────────────────────────────────────────
    print(f"  {'Total Trades':<22}: {total_trades}")
    print(f"  {'Wins':<22}: {len(wins)}  ({win_rate:.1f}%)")
    print(f"  {'Losses':<22}: {len(losses)}")
    pnl_sign = "+" if total_pnl >= 0 else ""
    print(f"  {'Total P&L':<22}: {pnl_sign}${total_pnl:.2f}")
    print(f"  {'Gross Profit':<22}: +${gross_profit:.2f}")
    print(f"  {'Gross Loss':<22}: -${gross_loss:.2f}")
    print(f"  {'Profit Factor':<22}: {profit_factor:.3f}")
    print(f"  {'Avg Win':<22}: +${avg_win:.2f}")
    print(f"  {'Avg Loss':<22}: -${avg_loss:.2f}")
    print(f"  {'Best Trade':<22}: +${best_trade.profit:.2f}  ({best_trade.symbol})")
    print(f"  {'Worst Trade':<22}: -${abs(worst_trade.profit):.2f}  ({worst_trade.symbol})")

    # ── Per-symbol table ───────────────────────────────────────────────────────
    print(f"\n  {'Symbol':<18}  {'Trades':>6}  {'W/L':>6}  {'WR%':>6}  {'P&L':>10}")
    print("  " + "-" * 52)
    for sym, sym_deals in sorted(by_symbol.items()):
        sw = [d for d in sym_deals if d.profit > 0]
        sl = [d for d in sym_deals if d.profit <= 0]
        sr = len(sw) / len(sym_deals) * 100 if sym_deals else 0
        sp = sum(d.profit for d in sym_deals)
        sign = "+" if sp >= 0 else ""
        print(f"  {sym:<18}  {len(sym_deals):>6}  {len(sw)}/{len(sl):<3}  "
              f"{sr:>5.1f}%  {sign}{sp:>8.2f}")

    # ── Trade log ─────────────────────────────────────────────────────────────
    print(f"\n  {'#':<4}  {'Time (UTC)':<20}  {'Symbol':<14}  {'Dir':<5}  "
          f"{'Lots':>5}  {'P&L':>9}  Comment")
    print("  " + "-" * 75)
    for i, d in enumerate(sorted(deals, key=lambda x: x.time), 1):
        t    = datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        side = "BUY"  if d.type == mt5.DEAL_TYPE_BUY  else "SELL"
        sign = "+" if d.profit >= 0 else ""
        comment = d.comment[:20] if d.comment else ""
        print(f"  {i:<4}  {t:<20}  {d.symbol:<14}  {side:<5}  "
              f"{d.volume:>5.2f}  {sign}{d.profit:>8.2f}  {comment}")

    # ── Result banner ──────────────────────────────────────────────────────────
    print("\n" + "=" * W)
    if total_pnl > 0:
        print(f"  ✅  PROFITABLE DAY  — Net: +${total_pnl:.2f}  |  PF: {profit_factor:.2f}  |  WR: {win_rate:.1f}%")
    elif total_pnl < 0:
        print(f"  ❌  LOSING DAY     — Net: -${abs(total_pnl):.2f}  |  PF: {profit_factor:.2f}  |  WR: {win_rate:.1f}%")
    else:
        print(f"  ➖  BREAKEVEN DAY  — Net: $0.00")
    print("=" * W + "\n")


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GRIWD Daily Trade Summary")
    parser.add_argument("--date",  type=str, default=None,
                        help="Date to summarise (YYYY-MM-DD). Default: today.")
    parser.add_argument("--days",  type=int, default=1,
                        help="Number of past days to include (default 1 = today only).")
    args = parser.parse_args()

    if not connect():
        return

    now_utc = datetime.now(tz=timezone.utc)

    if args.date:
        base = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        from_dt = base
        to_dt   = base + timedelta(days=args.days)
        label   = f"SUMMARY  {args.date}" + (f" to {(base + timedelta(days=args.days-1)).date()}" if args.days > 1 else "")
    else:
        # Default: from midnight UTC today
        from_dt = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=args.days - 1)
        to_dt   = now_utc + timedelta(seconds=1)
        if args.days == 1:
            label = f"TODAY'S SUMMARY  ({now_utc.strftime('%Y-%m-%d')})"
        else:
            label = f"LAST {args.days} DAYS SUMMARY"

    deals = fetch_deals(from_dt, to_dt)
    print_summary(deals, label)

    mt5.shutdown()


if __name__ == "__main__":
    main()
