from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from . import db
from .indicators import sma_last, rsi_sma_last, atr_sma_last, clamp
from .config import (
    LOOKBACK_1D, LOOKBACK_INTRA, MAX_LEVERAGE, RISK_PCT_DEFAULT, STOP_ATR_MULT,
    ENTRY_ATR_K_30, ENTRY_ATR_K_60, ENTRY_ATR_K_180,
)

TF_MINUTES = {
    "30m": 30,
    "60m": 60,
    "180m": 180,
    "1D": 1440,
}

def tf_key(minutes_or_str: str) -> Optional[str]:
    s = str(minutes_or_str).strip()
    s = s.upper()
    # Accept TradingView formats: "30", "60", "180", "1D", "D"
    if s in ("30", "30M", "0.5H"):
        return "30m"
    if s in ("60", "60M", "1H"):
        return "60m"
    if s in ("180", "180M", "3H"):
        return "180m"
    if s in ("1D", "D", "1DAY", "DAY"):
        return "1D"
    return None

def entry_k_for_tf(tf: str) -> float:
    if tf == "30m":
        return ENTRY_ATR_K_30
    if tf == "60m":
        return ENTRY_ATR_K_60
    if tf == "180m":
        return ENTRY_ATR_K_180
    return 0.5

def regime_1d() -> Dict[str, Any]:
    rows = db.fetch_recent("1D", LOOKBACK_1D)
    if len(rows) < 210:
        return {"bias": "unknown", "confidence": 0.0, "detail": "not_enough_1D_data"}
    closes = [r["close"] for r in rows]
    sma200 = sma_last(closes, 200)
    if sma200 is None:
        return {"bias": "unknown", "confidence": 0.0, "detail": "no_sma200"}
    last_close = closes[-1]
    # simple confidence: distance from sma200 (%), capped
    dist = abs(last_close - sma200) / last_close
    conf = clamp(dist * 5.0, 0.0, 1.0)  # 0~1
    bias = "long_favored" if last_close > sma200 else "short_favored"
    return {
        "bias": bias,
        "confidence": round(conf, 3),
        "last_close": last_close,
        "sma200": sma200,
        "ts": int(rows[-1]["ts"]),
    }

def _ease_score(side: str, close: float, sma5: float, rsi2: float, regime_bias: str) -> Tuple[float, Dict[str, Any]]:
    if side == "long":
        trigger = (close < sma5) and (rsi2 <= 5.0)
        dist_sma = max(0.0, (close - sma5) / close) * 100.0  # need drop below sma5
        dist_rsi = max(0.0, (rsi2 - 5.0) / 5.0) * 100.0
        base = 100.0 if trigger else 100.0 - (dist_sma * 200.0 + dist_rsi * 1.0)  # sma distance is more important
        # regime alignment
        if regime_bias == "long_favored":
            base += 10.0
        elif regime_bias == "short_favored":
            base -= 25.0
        return clamp(base, 0.0, 110.0), {
            "trigger_now": trigger,
            "distance_close_to_sma5_pct": round(dist_sma, 4),
            "distance_rsi_to_threshold": round(max(0.0, rsi2 - 5.0), 4),
        }
    else:
        # short
        trigger = (close > sma5) and (rsi2 >= 95.0)
        dist_sma = max(0.0, (sma5 - close) / close) * 100.0  # need rise above sma5
        dist_rsi = max(0.0, (95.0 - rsi2) / 95.0) * 100.0
        base = 100.0 if trigger else 100.0 - (dist_sma * 200.0 + dist_rsi * 1.0)
        if regime_bias == "short_favored":
            base += 10.0
        elif regime_bias == "long_favored":
            base -= 25.0
        return clamp(base, 0.0, 110.0), {
            "trigger_now": trigger,
            "distance_close_to_sma5_pct": round(dist_sma, 4),
            "distance_rsi_to_threshold": round(max(0.0, 95.0 - rsi2), 4),
        }

def evaluate_timeframe(tf: str, side: str, regime_bias: str) -> Optional[Dict[str, Any]]:
    rows = db.fetch_recent(tf, LOOKBACK_INTRA)
    if len(rows) < 210:
        return None
    closes = [r["close"] for r in rows]
    highs  = [r["high"] for r in rows]
    lows   = [r["low"] for r in rows]
    sma5 = sma_last(closes, 5)
    rsi2 = rsi_sma_last(closes, 2)
    atr14 = atr_sma_last(highs, lows, closes, 14)
    if sma5 is None or rsi2 is None or atr14 is None:
        return None

    last = rows[-1]
    close = float(last["close"])
    ts = int(last["ts"])
    score, detail = _ease_score(side, close, float(sma5), float(rsi2), regime_bias)

    # time to next bar (best-effort)
    now = int(time.time())
    tf_sec = TF_MINUTES[tf] * 60
    next_ts = ts + tf_sec
    time_to_next = max(0, next_ts - now)

    return {
        "tf": tf,
        "ts": ts,
        "close": close,
        "sma5": float(sma5),
        "rsi2": float(rsi2),
        "atr14": float(atr14),
        "entry_ease_score": round(float(score), 2),
        "time_to_next_sec": int(time_to_next),
        **detail,
    }

def build_plan(candidate: Dict[str, Any], side: str, risk_pct: Optional[float]=None) -> Dict[str, Any]:
    risk_pct = RISK_PCT_DEFAULT if risk_pct is None else float(risk_pct)
    tf = candidate["tf"]
    price = float(candidate["close"])
    atr = float(candidate["atr14"])
    k = entry_k_for_tf(tf)
    entry = price - k * atr if side == "long" else price + k * atr
    stop = entry - STOP_ATR_MULT * atr if side == "long" else entry + STOP_ATR_MULT * atr
    # TP anchored to SMA5 mean reversion
    tp1 = float(candidate["sma5"])

    stop_dist = abs(entry - stop)
    stop_pct = stop_dist / entry * 100.0 if entry != 0 else 0.0
    max_lev = risk_pct / stop_pct if stop_pct > 0 else 0.0
    max_lev = min(MAX_LEVERAGE, max_lev)
    max_lev = round(max_lev, 2)

    rr = None
    if side == "long":
        if entry > stop:
            rr = (tp1 - entry) / (entry - stop)
    else:
        if stop > entry:
            rr = (entry - tp1) / (stop - entry)
    rr = float(rr) if rr is not None else None

    return {
        "side": side,
        "tf": tf,
        "entry_type": "limit_atr",
        "entry_price": round(entry, 2),
        "stop_price": round(stop, 2),
        "tp1_price": round(tp1, 2),
        "tp_rule": "exit when close crosses SMA5, then exit next bar open",
        "risk_pct": risk_pct,
        "stop_distance_pct": round(stop_pct, 3),
        "max_leverage_by_risk": max_lev,
        "reward_risk_to_tp1": round(rr, 3) if rr is not None else None,
        "params": {"entry_atr_k": k, "stop_atr_mult": STOP_ATR_MULT},
    }

def recommend(side: str, risk_pct: Optional[float]=None) -> Dict[str, Any]:
    side = side.lower().strip()
    if side not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")

    reg = regime_1d()
    regime_bias = reg["bias"]

    candidates: List[Dict[str, Any]] = []
    for tf in ("30m", "60m", "180m"):
        c = evaluate_timeframe(tf, side, regime_bias)
        if c:
            candidates.append(c)

    if not candidates:
        return {
            "ok": False,
            "error": "not_enough_data_for_30m_60m_180m",
            "regime": reg,
            "candidates": [],
        }

    # choose the best entry-ease score; tie-breaker: shorter time_to_next
    candidates_sorted = sorted(
        candidates,
        key=lambda x: (x["entry_ease_score"], -x["trigger_now"], -x["time_to_next_sec"]),
        reverse=True
    )
    chosen = candidates_sorted[0]
    plan = build_plan(chosen, side, risk_pct=risk_pct)

    return {
        "ok": True,
        "regime": reg,
        "selected": chosen,
        "plan": plan,
        "candidates": candidates_sorted,
    }
