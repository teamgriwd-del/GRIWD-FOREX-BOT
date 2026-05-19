"""
Signal Engine: Multi-Timeframe Confluence Scoring
Combines 1h trend, 15m structure, 5m candlestick/chart patterns,
trend-line bounce/break signals, and adaptive learning weights.
Scores each potential trade and fires only when score >= SIGNAL_THRESHOLD.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

import market_structure as ms_module
import candlestick_patterns as cp_module
import chart_patterns as chart_module
import zone_detector as zd_module
from config import (
    SIGNAL_THRESHOLD, SCORE_WEIGHTS, REWARD_RISK_RATIO,
    TL_BOUNCE_TOLERANCE, TL_QUALITY_THRESHOLD, TL_BREAK_BUFFER,
    SWING_SL_BUFFER, MAX_SL_ATR, STOP_ATR_MULT,
)


@dataclass
class TradeSignal:
    direction: str           # "buy" | "sell"
    entry: float
    stop_loss: float
    take_profit: float
    score: float
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _price_in_fvg(price: float, ms: ms_module.MarketStructure, direction: str) -> bool:
    for fvg in ms.fvgs:
        if fvg.filled:
            continue
        if fvg.direction == direction and fvg.bottom <= price <= fvg.top:
            return True
    return False


def _near_equilibrium(price: float, ms: ms_module.MarketStructure, atr: float) -> bool:
    if ms.equilibrium is None:
        return False
    return abs(price - ms.equilibrium) < atr * 0.5


def _calculate_levels(direction: str, price: float, atr: float,
                      ms: ms_module.MarketStructure) -> tuple:
    """
    SL placed at the nearest recent swing point with a small ATR buffer,
    capped at MAX_SL_ATR so risk never blows out.
    TP derived from actual risk distance × RR ratio.
    """
    if direction == "buy":
        recent_lows = ms.swing_lows[-5:] if ms.swing_lows else []
        if recent_lows:
            swing_low = min(sl.price for sl in recent_lows)
            sl = swing_low - atr * SWING_SL_BUFFER
            sl = max(sl, price - atr * MAX_SL_ATR)   # hard cap
        else:
            sl = price - atr * STOP_ATR_MULT
        risk = price - sl
        tp   = price + risk * REWARD_RISK_RATIO
    else:
        recent_highs = ms.swing_highs[-5:] if ms.swing_highs else []
        if recent_highs:
            swing_high = max(sh.price for sh in recent_highs)
            sl = swing_high + atr * SWING_SL_BUFFER
            sl = min(sl, price + atr * MAX_SL_ATR)
        else:
            sl = price + atr * STOP_ATR_MULT
        risk = sl - price
        tp   = price - risk * REWARD_RISK_RATIO

    return sl, tp


# ── Signal Generation ─────────────────────────────────────────────────────────

def generate_signal(data: dict, timestamp: pd.Timestamp = None,
                    memory=None) -> Optional[TradeSignal]:
    """
    data   : {"1h": df_1h, "15m": df_15m, "5m": df_5m}
    memory : TradeMemory instance — provides adaptive weight multipliers.
    Returns TradeSignal or None.
    """
    df_1h  = data["1h"]
    df_15m = data["15m"]
    df_5m  = data["5m"]

    if df_5m.empty or df_15m.empty or df_1h.empty:
        return None

    atr_5m = df_5m["atr"].iloc[-1] if not df_5m["atr"].isna().all() else 1.0

    ms_1h  = ms_module.analyze(df_1h,  df_1h["atr"])
    ms_15m = ms_module.analyze(df_15m, df_15m["atr"])
    ms_5m  = ms_module.analyze(df_5m,  df_5m["atr"])

    current_price = df_5m["close"].iloc[-1]
    current_bar   = len(df_5m) - 1
    ts = timestamp or df_5m.index[-1]

    cs_patterns = cp_module.scan_all(df_5m, atr_5m)
    bullish_cs  = [p for p in cs_patterns if p["direction"] == "bullish"]
    bearish_cs  = [p for p in cs_patterns if p["direction"] == "bearish"]

    chart_sigs  = chart_module.scan_all(df_15m, atr_5m)
    bull_charts = [s for s in chart_sigs if s.direction == "bullish" and s.confirmed]
    bear_charts = [s for s in chart_sigs if s.direction == "bearish" and s.confirmed]

    # Build zone map (trend lines, order blocks, etc.) from 5m data
    zone_map = zd_module.build_zone_map(df_5m, df_5m["atr"])

    # Adaptive weights from TradeMemory: reason_string → multiplier
    aw = memory.get_adaptive_weights() if memory else {}

    # ── Macro trend filter via 50-period 1h EMA ───────────────────────────────
    # Prevents selling into a bull market or buying into a bear market when the
    # 1h swing-based classifier returns "unknown" instead of the true trend.
    ema_1h = df_1h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    price_above_ema = current_price > ema_1h

    for direction in ("buy", "sell"):
        # Block counter-EMA entries unless swing structure confirms the direction
        if direction == "sell" and price_above_ema and ms_1h.trend != "downtrend":
            continue
        if direction == "buy" and not price_above_ema and ms_1h.trend != "uptrend":
            continue
        cs_dir      = "bullish" if direction == "buy" else "bearish"
        ms_trend_ok = (ms_1h.trend == "uptrend"        if direction == "buy"
                       else ms_1h.trend == "downtrend")
        bos_ok      = (ms_15m.last_bos == "bullish_bos" if direction == "buy"
                       else ms_15m.last_bos == "bearish_bos")
        sweep_ok    = (ms_5m.liquidity_swept == "lows"  if direction == "buy"
                       else ms_5m.liquidity_swept == "highs")
        cs_ok       = bool(bullish_cs if direction == "buy" else bearish_cs)
        chart_ok    = bool(bull_charts if direction == "buy" else bear_charts)
        fvg_ok      = _price_in_fvg(current_price, ms_1h, cs_dir)
        eq_ok       = _near_equilibrium(current_price, ms_5m, atr_5m)
        consol_break = (ms_1h.trend == "consolidation" and
                        ms_15m.last_bos in ("bullish_bos", "bearish_bos"))

        score   = 0.0
        reasons = []

        # ── Base confluence factors ───────────────────────────────────────────
        if ms_trend_ok:
            r = f"1h trend: {ms_1h.trend}"
            score += SCORE_WEIGHTS["trend_align"] * aw.get(r, 1.0)
            reasons.append(r)

        if bos_ok:
            r = f"15m BOS: {ms_15m.last_bos}"
            score += SCORE_WEIGHTS["structure_break"] * aw.get(r, 1.0)
            reasons.append(r)

        if fvg_ok:
            r = "Price inside FVG"
            score += SCORE_WEIGHTS["fvg_entry"] * aw.get(r, 1.0)
            reasons.append(r)

        if cs_ok:
            p_list = bullish_cs if direction == "buy" else bearish_cs
            r = f"Candle: {p_list[0]['pattern']}"
            score += SCORE_WEIGHTS["pattern_reversal"] * aw.get(r, 1.0)
            reasons.append(r)

        if chart_ok:
            c_list = bull_charts if direction == "buy" else bear_charts
            r = f"Chart: {c_list[0].pattern}"
            score += SCORE_WEIGHTS["chart_pattern"] * aw.get(r, 1.0)
            reasons.append(r)

        if consol_break:
            r = "Consolidation breakout"
            score += SCORE_WEIGHTS["consolidation_break"] * aw.get(r, 1.0)
            reasons.append(r)

        if sweep_ok:
            r = f"Liquidity sweep: {ms_5m.liquidity_swept}"
            score += SCORE_WEIGHTS["liquidity_sweep"] * aw.get(r, 1.0)
            reasons.append(r)

        if eq_ok:
            r = "Price at equilibrium"
            score += SCORE_WEIGHTS["equilibrium_zone"] * aw.get(r, 1.0)
            reasons.append(r)

        # ── Trend-line signals (each signal type fires at most once per direction)
        for tl in zone_map.trend_lines:
            if tl.quality < TL_QUALITY_THRESHOLD:
                continue
            tl_price = zd_module.trendline_price_at(tl, current_bar)
            distance = abs(current_price - tl_price)

            if not tl.broken:
                if distance <= atr_5m * TL_BOUNCE_TOLERANCE:
                    if direction == "buy" and tl.kind == "support_tl":
                        r = "TL bounce: support"
                    elif direction == "sell" and tl.kind == "resistance_tl":
                        r = "TL bounce: resistance"
                    else:
                        r = None
                    if r and r not in reasons:
                        score += SCORE_WEIGHTS.get("tl_bounce", 1) * aw.get(r, 1.0)
                        reasons.append(r)
            else:
                # Require price to be meaningfully beyond the line (anti-fakeout buffer)
                break_min = atr_5m * TL_BREAK_BUFFER
                if direction == "buy" and tl.kind == "resistance_tl" and current_price > tl_price + break_min:
                    r = "TL break: resistance"
                elif direction == "sell" and tl.kind == "support_tl" and current_price < tl_price - break_min:
                    r = "TL break: support"
                else:
                    r = None
                if r and r not in reasons:
                    score += SCORE_WEIGHTS.get("tl_break", 1) * aw.get(r, 1.0)
                    reasons.append(r)

        if score < SIGNAL_THRESHOLD:
            continue

        # ── Build trade levels ────────────────────────────────────────────────
        stop_loss, take_profit = _calculate_levels(
            direction, current_price, atr_5m, ms_5m
        )

        # Override SL/TP with chart-pattern levels only when memory trusts the pattern
        if chart_ok:
            cs_ref   = bull_charts[0] if direction == "buy" else bear_charts[0]
            pat_mult = memory.get_pattern_mult("", cs_ref.pattern) if memory else 1.0
            if cs_ref.confirmed and pat_mult >= 0.5:
                stop_loss   = cs_ref.stop
                take_profit = cs_ref.target

        sig = TradeSignal(
            direction=direction,
            entry=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            score=round(score, 2),
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
