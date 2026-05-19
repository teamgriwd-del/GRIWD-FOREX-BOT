"""
MT5 Diagnostic Script — run this ONCE after logging in to Weltrade MT5.
It will:
  1. Connect to the terminal
  2. Show your account details
  3. List every available symbol (so you can find the correct Vol 75 name)
  4. Fetch a live tick if the symbol is found

Usage:
  python check_mt5.py
  python check_mt5.py --filter vol
  python check_mt5.py --filter 75
"""

import argparse
import MetaTrader5 as mt5
from credentials import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH, MT5_SERVER_FALLBACKS

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="", help="Filter symbol list (e.g. '75', 'vol')")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  WELTRADE MT5 Diagnostic")
    print("=" * 60)

    # ── Initialize ──────────────────────────────────────────────
    print(f"\nInitializing MT5 terminal...")
    if not mt5.initialize(MT5_PATH):
        print(f"  FAILED: {mt5.last_error()}")
        print("\n  Make sure MetaTrader 5 is open and you are logged in.")
        return

    print(f"  Terminal version: {mt5.version()}")

    # ── Login ────────────────────────────────────────────────────
    servers = [MT5_SERVER] + [s for s in MT5_SERVER_FALLBACKS if s != MT5_SERVER]
    logged_in = False
    for server in servers:
        print(f"  Trying server: {server} ... ", end="", flush=True)
        if mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=server):
            print("OK")
            logged_in = True
            break
        else:
            print(f"FAILED ({mt5.last_error()})")

    if not logged_in:
        print("\n  Could not log in on any server.")
        print("  Open MT5, go to File -> Login to Trade Account, and log in manually.")
        print("  Then check File -> Open an Account for the exact server name.")
        mt5.shutdown()
        return

    # ── Account Info ──────────────────────────────────────────────
    info = mt5.account_info()
    print(f"\n  Account   : {info.login}")
    print(f"  Name      : {info.name}")
    print(f"  Server    : {info.server}")
    print(f"  Balance   : ${info.balance:.2f}")
    print(f"  Equity    : ${info.equity:.2f}")
    print(f"  Currency  : {info.currency}")
    print(f"  Leverage  : 1:{info.leverage}")

    # ── Symbol List ───────────────────────────────────────────────
    all_symbols = sorted(s.name for s in (mt5.symbols_get() or []))
    filt = args.filter.lower()
    if filt:
        matched = [s for s in all_symbols if filt in s.lower()]
    else:
        matched = all_symbols

    print(f"\n  Available symbols: {len(all_symbols)} total")
    if filt:
        print(f"  Filtered by '{filt}': {len(matched)} matched")
    print()
    for sym in matched[:80]:   # cap at 80 to keep readable
        print(f"    {sym}")
    if len(matched) > 80:
        print(f"    ... and {len(matched) - 80} more")

    # ── Try to get a tick on likely Vol75 symbols ─────────────────
    candidates = [s for s in all_symbols
                  if any(x in s.lower() for x in ["75", "vol", "vix", "synth"])]
    if candidates:
        print(f"\n  Possible Vol-75 symbols found:")
        for sym in candidates[:10]:
            mt5.symbol_select(sym, True)
            tick = mt5.symbol_info_tick(sym)
            if tick:
                print(f"    {sym:35s}  bid={tick.bid:.5f}  ask={tick.ask:.5f}")
            else:
                print(f"    {sym:35s}  (no tick data)")

    # ── Recommendation ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ACTION: Copy the correct symbol name from the list above,")
    print("  then run the bot with:")
    print()
    print('    python bot.py --live --dry-run --symbol "PASTE_SYMBOL_HERE"')
    print()
    print("  Or update INSTRUMENT in config.py with that symbol name.")
    print("=" * 60 + "\n")

    mt5.shutdown()

if __name__ == "__main__":
    main()
