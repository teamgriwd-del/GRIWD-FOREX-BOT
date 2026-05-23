"""
GRIWD Forex Bot — Log Viewer
Reads live_trading.log and displays filtered, colour-coded output.

Usage:
  python show_logs.py                  # today's events
  python show_logs.py --date 2026-05-21
  python show_logs.py --days 3         # last 3 days
  python show_logs.py --all            # full log (all time)
  python show_logs.py --signals        # signals + trades only (no scan noise)
  python show_logs.py --tail 50        # last 50 lines of raw log
"""

import argparse
import os
from datetime import datetime, timezone, timedelta

LOG_FILE = "live_trading.log"

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── Classifiers ───────────────────────────────────────────────────────────────

def _classify(line: str) -> str:
    l = line.lower()
    if "signal buy"   in l: return "BUY_SIGNAL"
    if "signal sell"  in l: return "SELL_SIGNAL"
    if "order placed" in l: return "ORDER"
    if "dry run"      in l and ("buy" in l or "sell" in l): return "DRY_TRADE"
    if "trail sl"     in l: return "TRAIL"
    if "closed by mt5"in l: return "CLOSED"
    if "error"        in l or "failed" in l: return "ERROR"
    if "warning"      in l: return "WARNING"
    if "scan cycle"   in l: return "SCAN"
    if "reasons :"    in l or "candle  :" in l or "chart   :" in l: return "DETAIL"
    if "near-miss"    in l or "score=" in l and "/" in l: return "NEAR_MISS"
    if "blocked"      in l: return "BLOCKED"
    if "griwd forex"  in l or "==="   in l: return "HEADER"
    return "INFO"


def _colour(kind: str, line: str) -> str:
    if kind == "BUY_SIGNAL":  return f"{BOLD}{GREEN}{line}{RESET}"
    if kind == "SELL_SIGNAL": return f"{BOLD}{RED}{line}{RESET}"
    if kind == "ORDER":       return f"{BOLD}{YELLOW}{line}{RESET}"
    if kind == "DRY_TRADE":   return f"{YELLOW}{line}{RESET}"
    if kind == "TRAIL":       return f"{CYAN}{line}{RESET}"
    if kind == "CLOSED":      return f"{BOLD}{CYAN}{line}{RESET}"
    if kind == "ERROR":       return f"{BOLD}{RED}{line}{RESET}"
    if kind == "WARNING":     return f"{YELLOW}{line}{RESET}"
    if kind == "DETAIL":      return f"{GREEN}{line}{RESET}"
    if kind == "NEAR_MISS":   return f"{CYAN}{line}{RESET}"
    if kind == "BLOCKED":     return f"{DIM}{line}{RESET}"
    if kind == "HEADER":      return f"{BOLD}{line}{RESET}"
    if kind == "SCAN":        return f"{DIM}{line}{RESET}"
    return line


# ── Filters ───────────────────────────────────────────────────────────────────

SIGNAL_KINDS = {"BUY_SIGNAL", "SELL_SIGNAL", "ORDER", "DRY_TRADE",
                "TRAIL", "CLOSED", "ERROR", "WARNING", "DETAIL", "NEAR_MISS", "HEADER"}


def _parse_ts(line: str):
    """Extract datetime from log line prefix."""
    try:
        return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GRIWD Log Viewer")
    parser.add_argument("--date",    type=str,  default=None,
                        help="Show logs for date YYYY-MM-DD (default: today)")
    parser.add_argument("--days",    type=int,  default=1,
                        help="Number of days back to show (default 1 = today)")
    parser.add_argument("--all",     action="store_true",
                        help="Show entire log file")
    parser.add_argument("--signals", action="store_true",
                        help="Show signals and trades only (hide scan noise)")
    parser.add_argument("--tail",    type=int,  default=None,
                        help="Show last N raw lines from the log file")
    args = parser.parse_args()

    if not os.path.exists(LOG_FILE):
        print(f"Log file not found: {LOG_FILE}")
        print("Make sure you are running this from the GRIWD-FOREX-BOT folder.")
        return

    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # ── Tail mode ─────────────────────────────────────────────────────────────
    if args.tail:
        print(f"\n{'='*65}")
        print(f"  GRIWD LOG — last {args.tail} lines")
        print(f"{'='*65}\n")
        for line in lines[-args.tail:]:
            kind = _classify(line)
            print(_colour(kind, line.rstrip()))
        print()
        return

    # ── Date filter ───────────────────────────────────────────────────────────
    now_utc = datetime.now(tz=timezone.utc)
    if args.all:
        from_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
        to_dt   = datetime(2100, 1, 1, tzinfo=timezone.utc)
        label   = "FULL LOG"
    elif args.date:
        from_dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = from_dt + timedelta(days=args.days)
        label   = args.date
    else:
        from_dt = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) \
                  - timedelta(days=args.days - 1)
        to_dt   = now_utc + timedelta(seconds=1)
        label   = f"TODAY  ({now_utc.strftime('%Y-%m-%d')})" if args.days == 1 \
                  else f"LAST {args.days} DAYS"

    # ── Filter lines ──────────────────────────────────────────────────────────
    filtered = []
    for line in lines:
        ts = _parse_ts(line)
        if ts is None:
            # Continuation line (no timestamp) — attach to previous
            if filtered:
                filtered.append(("DETAIL", line))
            continue
        if ts < from_dt or ts > to_dt:
            continue
        kind = _classify(line)
        if args.signals and kind not in SIGNAL_KINDS:
            continue
        filtered.append((kind, line))

    # ── Stats from filtered lines ─────────────────────────────────────────────
    signals   = [l for k, l in filtered if k in ("BUY_SIGNAL", "SELL_SIGNAL")]
    orders    = [l for k, l in filtered if k == "ORDER"]
    trails    = [l for k, l in filtered if k == "TRAIL"]
    closes    = [l for k, l in filtered if k == "CLOSED"]
    errors    = [l for k, l in filtered if k == "ERROR"]

    print(f"\n{'='*65}")
    print(f"  GRIWD FOREX BOT — LOG VIEWER  [{label}]")
    print(f"{'='*65}")
    print(f"  Lines shown    : {len(filtered)}")
    print(f"  Signals fired  : {len(signals)}")
    print(f"  Orders placed  : {len(orders)}")
    print(f"  Trailing moves : {len(trails)}")
    print(f"  Positions closed: {len(closes)}")
    if errors:
        print(f"  {RED}Errors         : {len(errors)}{RESET}")
    print(f"{'='*65}\n")

    # ── Print lines ───────────────────────────────────────────────────────────
    for kind, line in filtered:
        print(_colour(kind, line.rstrip()))

    print(f"\n{'='*65}")
    print(f"  End of log  |  {len(filtered)} lines shown")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
