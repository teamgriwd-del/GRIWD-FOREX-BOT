"""
Trade Memory — Adaptive Learning Engine
Records every closed trade outcome and dynamically adjusts confluence weights
based on what has historically worked. Persists learning across sessions.
"""

import json
import os
from typing import Dict

MEMORY_FILE   = "trade_memory.json"
MIN_SAMPLES   = 25      # trades needed before adjusting a weight
BOOST_WR      = 0.58    # win rate above this → boost weight
PENALIZE_WR   = 0.42    # win rate below this → penalize weight
MAX_MULT      = 2.0
MIN_MULT      = 0.5     # bonus factors never penalised below 50%


class TradeMemory:
    def __init__(self, filepath: str = MEMORY_FILE):
        self.filepath = filepath
        self._data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "total_trades"       : 0,
            "trades"             : [],
            "reason_stats"       : {},
            "pattern_stats"      : {},
            "chart_pattern_stats": {},
            "score_stats"        : {},
            "adaptive_weights"   : {},
            "lessons"            : [],
        }

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
        except OSError:
            pass

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_trade(self, trade) -> None:
        """Record a closed trade and update adaptive weights every 5 trades.
        end_of_data closes are excluded — artificial P&L skews the learning."""
        if trade.status == "end_of_data":
            return
        won = trade.pnl > 0
        chart_pat = next(
            (r.replace("Chart:", "").strip() for r in trade.reasons
             if r.startswith("Chart:")),
            "",
        )

        self._data["trades"].append({
            "id"           : trade.id,
            "direction"    : trade.direction,
            "pnl"          : round(float(trade.pnl), 4),
            "status"       : trade.status,
            "pattern"      : trade.pattern,
            "chart_pattern": chart_pat,
            "score"        : float(trade.score),
            "reasons"      : list(trade.reasons),
            "won"          : won,
            "open_time"    : str(trade.open_time),
            "close_time"   : str(trade.close_time),
        })
        self._data["total_trades"] += 1

        self._update_stat("reason_stats",        trade.reasons, won, trade.pnl)
        if trade.pattern:
            self._update_stat("pattern_stats",       [trade.pattern], won, trade.pnl)
        if chart_pat:
            self._update_stat("chart_pattern_stats", [chart_pat],     won, trade.pnl)

        sc_key = str(round(float(trade.score)))
        ss = self._data["score_stats"]
        if sc_key not in ss:
            ss[sc_key] = {"wins": 0, "losses": 0, "pnl": 0.0}
        ss[sc_key]["wins" if won else "losses"] += 1
        ss[sc_key]["pnl"] = round(ss[sc_key]["pnl"] + float(trade.pnl), 4)

        if self._data["total_trades"] % 5 == 0:
            self._update_adaptive_weights()
            self._refresh_lessons()

        self._save()

    def _update_stat(self, key: str, items: list, won: bool, pnl: float):
        stats = self._data[key]
        for item in items:
            if item not in stats:
                stats[item] = {"wins": 0, "losses": 0, "pnl": 0.0}
            stats[item]["wins" if won else "losses"] += 1
            stats[item]["pnl"] = round(stats[item]["pnl"] + float(pnl), 4)

    # ── Adaptive Weights ──────────────────────────────────────────────────────

    @staticmethod
    def _wr(stats: dict) -> float:
        n = stats["wins"] + stats["losses"]
        return stats["wins"] / n if n > 0 else 0.5

    @staticmethod
    def _n(stats: dict) -> int:
        return stats["wins"] + stats["losses"]

    def _mult_from_wr(self, wr: float) -> float:
        if wr >= BOOST_WR:
            return min(MAX_MULT, 1.0 + (wr - BOOST_WR) / 0.15)
        if wr <= PENALIZE_WR:
            return max(MIN_MULT, 1.0 - (PENALIZE_WR - wr) / 0.15 * 0.75)
        return 1.0

    def _update_adaptive_weights(self):
        weights = {}
        for reason, stats in self._data["reason_stats"].items():
            if self._n(stats) >= MIN_SAMPLES:
                weights[reason] = round(self._mult_from_wr(self._wr(stats)), 3)
        self._data["adaptive_weights"] = weights

    # ── Lessons ───────────────────────────────────────────────────────────────

    def _refresh_lessons(self):
        lessons = []

        def add_pattern_lesson(label, stats_dict):
            for pat, stats in stats_dict.items():
                if self._n(stats) < MIN_SAMPLES:
                    continue
                wr = self._wr(stats)
                n  = self._n(stats)
                if wr < PENALIZE_WR:
                    lessons.append(f"AVOID {label} '{pat}': {wr*100:.0f}% WR ({n} trades)")
                elif wr > BOOST_WR:
                    lessons.append(f"PREFER {label} '{pat}': {wr*100:.0f}% WR ({n} trades)")

        add_pattern_lesson("candle",     self._data["pattern_stats"])
        add_pattern_lesson("chart pat.", self._data["chart_pattern_stats"])

        for sc_key, stats in self._data["score_stats"].items():
            n  = stats["wins"] + stats["losses"]
            if n < MIN_SAMPLES:
                continue
            wr = stats["wins"] / n
            if wr < PENALIZE_WR:
                lessons.append(
                    f"Low WR ({wr*100:.0f}%) at score~{sc_key} — consider raising threshold")
            elif wr > BOOST_WR:
                lessons.append(f"Good WR ({wr*100:.0f}%) at score~{sc_key}")

        self._data["lessons"] = lessons

    # ── Public API ────────────────────────────────────────────────────────────

    def get_adaptive_weights(self) -> Dict[str, float]:
        """Weight multipliers keyed by reason string. 1.0 = neutral."""
        return dict(self._data.get("adaptive_weights", {}))

    def get_pattern_mult(self, pattern: str, chart_pattern: str = "") -> float:
        """Combined performance multiplier for a candlestick+chart pattern pair."""
        mults = []
        for key, stat_key in [
            (pattern,       "pattern_stats"),
            (chart_pattern, "chart_pattern_stats"),
        ]:
            if not key:
                continue
            stats = self._data[stat_key].get(key)
            if stats and self._n(stats) >= MIN_SAMPLES:
                mults.append(self._mult_from_wr(self._wr(stats)))
        return sum(mults) / len(mults) if mults else 1.0

    def get_lessons(self) -> list:
        return list(self._data.get("lessons", []))

    def print_summary(self):
        print("\n" + "=" * 65)
        print("  TRADE MEMORY — ADAPTIVE LEARNING")
        print("=" * 65)
        print(f"  Trades in memory : {self._data['total_trades']}")

        def show_pattern_table(title, stats_dict):
            if not stats_dict:
                return
            print(f"\n  {title}:")
            for p, s in sorted(stats_dict.items(),
                                key=lambda x: -(x[1]["wins"] + x[1]["losses"])):
                n   = self._n(s)
                wr  = self._wr(s) * 100
                flag = " ↑" if wr > 65 else (" ↓" if wr < 35 else "")
                print(f"    {p:32s}  {n:4d} trades  {wr:5.1f}% WR{flag}")

        show_pattern_table("Candlestick Pattern Performance",
                           self._data["pattern_stats"])
        show_pattern_table("Chart Pattern Performance",
                           self._data["chart_pattern_stats"])

        weights = self._data.get("adaptive_weights", {})
        adjusted = {r: m for r, m in weights.items() if m != 1.0}
        if adjusted:
            print("\n  Weight Adjustments (active):")
            for reason, mult in sorted(adjusted.items(), key=lambda x: -abs(x[1] - 1.0)):
                arrow = "↑ BOOST" if mult > 1.0 else "↓ PENALIZE"
                print(f"    {reason:42s}  x{mult:.2f}  {arrow}")

        lessons = self._data.get("lessons", [])
        if lessons:
            print("\n  Learned Lessons:")
            for lesson in lessons:
                print(f"    • {lesson}")

        print("=" * 65)
