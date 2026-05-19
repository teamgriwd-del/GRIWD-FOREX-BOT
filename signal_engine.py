"""
Signal Engine: Multi-Timeframe Confluence Scoring
Combines 1h trend, 15m structure, 5m candlestick/chart patterns.
Scores each potential trade and fires only when score >= SIGNAL_THRESHOLD.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

import market_structure as ms_module
import candlestick_patterns as cp_module
import chart_patterns as chart_module
from config import SIGNAL_THRESHOLD, SCORE_WEIGHTS, REWARD_RISK_RATIO


@dataclass
class TradeSignal:
    direction: str           # "buy" | "sell"
    entry: float
    stop_loss: float
    take_profit: float
    score: int
    reasons: list = field(default_factory=list)
    pattern: str = ""
    chart_pattern: str = ""
    timestamp: Optional[pd.Timestamp] = None

    @property
    def rr_ratio(self) -> float:
        if self.direction == "buy":
            risk   = self.entry - self.stop_loss
            reward = self.take_profit - self.entry
        else:
            risk   = self.stop_loss - self.entry
            reward = self.entry - self.take_profit
        return (reward / risk) if risk > 0 else 0.0


def _price_in_fvg(price: float, ms: ms_module.MarketStructure, direction: str) -> bool:
    for fvg in ms.fvgs:
        if fvg.filled:
            continue
        if fvg.direction == direction and fvg.bottom <= price <= fvg.top:
            return True
    return False


def _near_equilibrium(price: float, ms: ms_module.MarketStructure,
                      atr: float) -> bool:
    if ms.equilibrium is None:
        return False
    return abs(price - ms.equilibrium) < atr * 0.5


def generate_signal(data: dict, timestamp: pd.Timestamp = None) -> Optional[TradeSignal]:
    """
    data: {"1h": df_1h, "15m": df_15m, "5m": df_5m}
    Each df has "atr" column. Returns TradeSignal or None.
    """
    df_1h  = data["1h"]
    df_15m = data["15m"]
    df_5m  = data["5m"]

    if df_5m.empty or df_15m.empty or df_1h.empty:
        return None

    atr_5m  = df_5m["atr"].iloc[-1]  if not df_5m["atr"].isna().all()  else 1.0
    atr_1h  = df_1h["atr"].iloc[-1]  if not df_1h["atr"].isna().all()  else 1.0

    # ── Market structure on each timeframe ────────────────────────────────────
    ms_1h  = ms_module.analyze(df_1h,  df_1h["atr"])
    ms_15m = ms_module.analyze(df_15m, df_15m["atr"])
    ms_5m  = ms_module.analyze(df_5m,  df_5m["atr"])

    current_price = df_5m["close"].iloc[-1]
    ts = timestamp or df_5m.index[-1]

    # ── Candlestick patterns on 5m ─────────────────────────────────────────────
    cs_patterns = cp_module.scan_all(df_5m, atr_5m)
    bullish_cs  = [p for p in cs_patterns if p["direction"] == "bullish"]
    bearish_cs  = [p for p in cs_patterns if p["direction"] == "bearish"]

    # ── Chart patterns on 15m ─────────────────────────────────────────────────
    chart_sigs   = chart_module.scan_all(df_15m, atr_5m)
    bull_charts  = [s for s in chart_sigs if s.direction == "bullish" and s.confirmed]
    bear_charts  = [s for s in chart_sigs if s.direction == "bearish" and s.confirmed]

    # ── Score both buy and sell scenarios ─────────────────────────────────────
    for direction in ("buy", "sell"):
        cs_dir       = "bullish" if direction == "buy" else "bearish"
        ms_trend_ok  = (ms_1h.trend == "uptrend"   if direction == "buy"
                        else ms_1h.trend == "downtrend")
        bos_ok       = (ms_15m.last_bos == "bullish_bos" if direction == "buy"
                        else ms_15m.last_bos == "bearish_bos")
        sweep_ok     = (ms_5m.liquidity_swept == "lows"  if direction == "buy"
                        else ms_5m.liquidity_swept == "highs")
        cs_ok        = bool(bullish_cs if direction == "buy" else bearish_cs)
        chart_ok     = bool(bull_charts if direction == "buy" else bear_charts)
        fvg_ok       = _price_in_fvg(current_price, ms_1h, cs_dir)
        eq_ok        = _near_equilibrium(current_price, ms_5m, atr_5m)
        consol_break = (ms_1h.trend == "consolidation" and
                        ms_15m.last_bos in ("bullish_bos", "bearish_bos"))

        score = 0
        reasons = []
        if ms_trend_ok:
            score += SCORE_WEIGHTS["trend_align"]
            reasons.append(f"1h trend: {ms_1h.trend}")
        if bos_ok:
            score += SCORE_WEIGHTS["structure_break"]
            reasons.append(f"15m BOS: {ms_15m.last_bos}")
        if fvg_ok:
            score += SCORE_WEIGHTS["fvg_entry"]
            reasons.append("Price inside FVG")
        if cs_ok:
            score += SCORE_WEIGHTS["pattern_reversal"]
            p_list = bullish_cs if direction == "buy" else bearish_cs
            reasons.append(f"Candle: {p_list[0]['pattern']}")
        if chart_ok:
            score += SCORE_WEIGHTS["chart_pattern"]
            c_list = bull_charts if direction == "buy" else bear_charts
            reasons.append(f"Chart: {c_list[0].pattern}")
        if consol_break:
            score += SCORE_WEIGHTS["consolidation_break"]
            reasons.append("Consolidation breakout")
        if sweep_ok:
            score += SCORE_WEIGHTS["liquidity_sweep"]
            reasons.append(f"Liquidity sweep: {ms_5m.liquidity_swept}")
        if eq_ok:
            score += SCORE_WEIGHTS["equilibrium_zone"]
            reasons.append("Price at equilibrium")

        if score < SIGNAL_THRESHOLD:
            continue

        # ── Build trade levels ────────────────────────────────────────────────
        if direction == "buy":
            stop_loss   = current_price - atr_5m * 1.5
            take_profit = current_price + atr_5m * 1.5 * REWARD_RISK_RATIO
        else:
            stop_loss   = current_price + atr_5m * 1.5
            take_profit = current_price - atr_5m * 1.5 * REWARD_RISK_RATIO

        # Override stop/TP from chart pattern if stronger signal
        if chart_ok:
            cs_ref = bull_charts[0] if direction == "buy" else bear_charts[0]
            if cs_ref.confirmed:
                stop_loss   = cs_ref.stop
                take_profit = cs_ref.target

        sig = TradeSignal(
            direction=direction,
            entry=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            score=score,
            reasons=reasons,
            pattern=(bullish_cs[0]["pattern"] if direction == "buy" and bullish_cs
                     else bearish_cs[0]["pattern"] if direction == "sell" and bearish_cs
                     else ""),
            chart_pattern=(bull_charts[0].pattern if direction == "buy" and bull_charts
                           else bear_charts[0].pattern if direction == "sell" and bear_charts
                           else ""),
            timestamp=ts,
        )

        if sig.rr_ratio >= REWARD_RISK_RATIO:
            return sig

    return None
