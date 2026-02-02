from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
import math

from . import db
from .indicators import sma_last, rsi_sma_last, atr_sma_last, clamp
from .evaluator import backtest_price_plan, score_metrics
from .config import (
    LOOKBACK_1D, LOOKBACK_INTRA, MAX_LEVERAGE, RISK_PCT_DEFAULT, STOP_ATR_MULT,
    ENTRY_ATR_K_30, ENTRY_ATR_K_60, ENTRY_ATR_K_180,
    EVAL_LOOKBACK_BARS, ENTRY_K_GRID, STOP_MULT_GRID, MIN_ATR_PCT, MAX_ATR_PCT,
)

_EVAL_CACHE: Dict[tuple, Dict[str, Any]] = {}

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
    if s in ("1", "1M", "1MIN", "1MINUTE"):
        return "1m"
    if s in ("5", "5M", "5MIN", "5MINUTE"):
        return "5m"
    if s in ("15", "15M", "15MIN", "15MINUTE"):
        return "15m"
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

def _ease_score(side: str, close: float, sma5: float, sma200: float, rsi2: float, regime_bias: str) -> Tuple[float, Dict[str, Any]]:
    # Hard trend filter (SMA200) to reduce MDD.
    if side == "long":
        trend_ok = close > sma200
        trigger = trend_ok and (close < sma5) and (rsi2 <= 5.0)

        dist_sma5 = max(0.0, (close - sma5) / close) * 100.0
        dist_rsi = max(0.0, (rsi2 - 5.0) / 5.0) * 100.0
        dist_trend = max(0.0, (sma200 - close) / close) * 100.0

        base = 100.0 if trigger else 100.0 - (dist_sma5 * 200.0 + dist_rsi * 1.0 + dist_trend * 300.0)

        if regime_bias == "long_favored":
            base += 10.0
        elif regime_bias == "short_favored":
            base -= 25.0

        return clamp(base, 0.0, 110.0), {
            "trigger_now": trigger,
            "trend_ok": trend_ok,
            "distance_close_to_sma5_pct": round(dist_sma5, 4),
            "distance_close_to_sma200_pct": round(dist_trend, 4),
            "distance_rsi_to_threshold": round(max(0.0, rsi2 - 5.0), 4),
        }
    else:
        trend_ok = close < sma200
        trigger = trend_ok and (close > sma5) and (rsi2 >= 95.0)

        dist_sma5 = max(0.0, (sma5 - close) / close) * 100.0
        dist_rsi = max(0.0, (95.0 - rsi2) / 95.0) * 100.0
        dist_trend = max(0.0, (close - sma200) / close) * 100.0

        base = 100.0 if trigger else 100.0 - (dist_sma5 * 200.0 + dist_rsi * 1.0 + dist_trend * 300.0)

        if regime_bias == "short_favored":
            base += 10.0
        elif regime_bias == "long_favored":
            base -= 25.0

        return clamp(base, 0.0, 110.0), {
            "trigger_now": trigger,
            "trend_ok": trend_ok,
            "distance_close_to_sma5_pct": round(dist_sma5, 4),
            "distance_close_to_sma200_pct": round(dist_trend, 4),
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
    sma200 = sma_last(closes, 200)
    rsi2 = rsi_sma_last(closes, 2)
    atr14 = atr_sma_last(highs, lows, closes, 14)
    if sma5 is None or sma200 is None or rsi2 is None or atr14 is None:
        return None

    last = rows[-1]
    close = float(last["close"])
    ts = int(last["ts"])
    score, detail = _ease_score(side, close, float(sma5), float(sma200), float(rsi2), regime_bias)
    atr_pct = (float(atr14) / close * 100.0) if close else 0.0
    vol_ok = (atr_pct >= MIN_ATR_PCT) and (atr_pct <= MAX_ATR_PCT)

    now = int(time.time())
    tf_sec = TF_MINUTES[tf] * 60
    next_ts = ts + tf_sec
    time_to_next = max(0, next_ts - now)

    return {
        "tf": tf,
        "ts": ts,
        "close": close,
        "sma5": float(sma5),
        "sma200": float(sma200),
        "rsi2": float(rsi2),
        "atr14": float(atr14),
        "atr_pct": round(atr_pct, 4),
        "vol_ok": bool(vol_ok),
        "entry_ease_score": round(float(score), 2),
        "time_to_next_sec": int(time_to_next),
        **detail,
    }

def _norm_backtest_score(x: float) -> float:
    # Compress to 0..1 range for UI scoring.
    if x is None or not math.isfinite(x):
        return 0.5
    return 0.5 + 0.5 * math.tanh(float(x) / 3.0)

def _grid_from_cfg(s: str) -> List[float]:
    out: List[float] = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out or [0.5]

def _best_params_for_tf(tf: str, side: str) -> Dict[str, Any]:
    """Return best (entry_mode, entry_k, stop_mult) by recent backtest score for this tf/side.
    Cached by latest candle ts to avoid heavy recomputation.
    """
    latest = db.fetch_latest(tf)
    if not latest:
        return {"ok": False, "reason": "no_data"}
    latest_ts = int(latest["ts"])
    cache_key = (tf, side)
    cached = _EVAL_CACHE.get(cache_key)
    if cached and cached.get("latest_ts") == latest_ts:
        return cached["best"]

    rows = db.fetch_recent(tf, EVAL_LOOKBACK_BARS)
    rows_dicts = [dict(r) for r in rows]

    entry_ks = _grid_from_cfg(ENTRY_K_GRID)
    stop_mults = _grid_from_cfg(STOP_MULT_GRID)

    best_score = -1e18
    best = None
    best_metrics = None

    # Evaluate: market baseline + limit_atr grid
    # Use a small fee_bps by default (0) - user can add later
    m_market, det_market = backtest_price_plan(rows_dicts, side=side, entry_mode="market", entry_k=0.0, stop_mult=stop_mults[0])
    s_market = score_metrics(m_market)
    best_score, best, best_metrics = s_market, {"entry_mode": "market", "entry_k": 0.0, "stop_mult": stop_mults[0], "metrics": m_market.__dict__}, m_market

    for k in entry_ks:
        for sm in stop_mults:
            m, det = backtest_price_plan(rows_dicts, side=side, entry_mode="limit_atr", entry_k=k, stop_mult=sm)
            s = score_metrics(m)
            if s > best_score:
                best_score = s
                best_metrics = m
                best = {
                    "entry_mode": "limit_atr",
                    "entry_k": float(k),
                    "stop_mult": float(sm),
                    "metrics": m.__dict__,
                }

    out = {"ok": True, "score": float(best_score), **best}
    _EVAL_CACHE[cache_key] = {"latest_ts": latest_ts, "best": out}
    return out

def build_plan(candidate: Dict[str, Any], side: str, best_params: Optional[Dict[str, Any]] = None, risk_pct: Optional[float]=None) -> Dict[str, Any]:
    risk_pct = RISK_PCT_DEFAULT if risk_pct is None else float(risk_pct)
    tf = candidate["tf"]
    price = float(candidate["close"])
    atr = float(candidate["atr14"])
    # Choose parameters (either from evaluator or static config)
    if best_params and best_params.get('ok'):
        entry_mode = best_params.get('entry_mode', 'limit_atr')
        k = float(best_params.get('entry_k', entry_k_for_tf(tf)))
        stop_mult = float(best_params.get('stop_mult', STOP_ATR_MULT))
    else:
        entry_mode = 'limit_atr'
        k = entry_k_for_tf(tf)
        stop_mult = STOP_ATR_MULT

    # For UI recommendation, we anchor to current close (not future next_open)
    entry = price if entry_mode == 'market' else (price - k * atr if side == 'long' else price + k * atr)
    stop = entry - stop_mult * atr if side == 'long' else entry + stop_mult * atr
    # TP anchored to SMA5 mean reversion
    tp1 = float(candidate["sma5"])
    # Optional RR-based targets for swing/runner management
    risk_unit = abs(entry - stop)
    if side == "long":
        tp2 = entry + risk_unit * 1.5
        tp3 = entry + risk_unit * 2.5
    else:
        tp2 = entry - risk_unit * 1.5
        tp3 = entry - risk_unit * 2.5

    stop_dist = abs(entry - stop)
    stop_pct = stop_dist / entry * 100.0 if entry != 0 else 0.0
    max_lev = risk_pct / stop_pct if stop_pct > 0 else 0.0
    max_lev = min(MAX_LEVERAGE, max_lev)
    max_lev = round(max_lev, 2)

    rr = None
    rr2 = None
    if side == "long":
        if entry > stop:
            rr = (tp1 - entry) / (entry - stop)
            rr2 = (tp2 - entry) / (entry - stop)
    else:
        if stop > entry:
            rr = (entry - tp1) / (stop - entry)
            rr2 = (entry - tp2) / (stop - entry)
    rr = float(rr) if rr is not None else None
    rr2 = float(rr2) if rr2 is not None else None

    return {
        "side": side,
        "tf": tf,
        "entry_type": entry_mode,
        "entry_price": round(entry, 2),
        "stop_price": round(stop, 2),
        "tp1_price": round(tp1, 2),
        "tp2_price": round(tp2, 2),
        "tp3_price": round(tp3, 2),
        "tp_rule": "exit when close crosses SMA5, then exit next bar open",
        "risk_pct": risk_pct,
        "stop_distance_pct": round(stop_pct, 3),
        "entry_distance_pct": round(abs(entry - price) / price * 100.0, 3) if price else None,
        "max_leverage_by_risk": max_lev,
        "reward_risk_to_tp1": round(rr, 3) if rr is not None else None,
        "reward_risk_to_tp2": round(rr2, 3) if rr2 is not None else None,
        "params": {"entry_atr_k": k, "stop_atr_mult": stop_mult},
        "recent_metrics": best_params.get('metrics') if (best_params and best_params.get('ok')) else None,
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

    # Score each candidate with composite score
    scored: List[Dict[str, Any]] = []
    for c in candidates:
        p = _best_params_for_tf(c["tf"], side)
        eval_score = float(p.get("score", 0.0)) if p.get("ok") else None
        bt_norm = _norm_backtest_score(eval_score if eval_score is not None else 0.0)

        reg_conf = float(reg.get("confidence", 0.0) or 0.0)
        regime_bonus = 0.0
        if regime_bias == "long_favored" and side == "long":
            regime_bonus = 1.0
        elif regime_bias == "short_favored" and side == "short":
            regime_bonus = 1.0
        elif regime_bias in ("long_favored", "short_favored"):
            regime_bonus = -0.5

        vol_penalty = -12.0 if not c.get("vol_ok", True) else 0.0
        trigger_bonus = 6.0 if c.get("trigger_now") else 0.0
        trend_bonus = 4.0 if c.get("trend_ok") else -4.0

        composite = (
            float(c["entry_ease_score"])
            + (bt_norm * 20.0)
            + (reg_conf * 10.0)
            + (regime_bonus * 6.0)
            + trigger_bonus
            + trend_bonus
            + vol_penalty
        )

        confidence = clamp(
            (float(c["entry_ease_score"]) / 110.0) * 0.5
            + bt_norm * 0.3
            + reg_conf * 0.2
            + (0.05 if c.get("vol_ok") else -0.1),
            0.0,
            1.0,
        )

        c = dict(c)
        c["backtest_score"] = round(float(eval_score), 4) if eval_score is not None else None
        c["backtest_score_norm"] = round(bt_norm, 4)
        c["composite_score"] = round(float(composite), 2)
        c["confidence"] = round(confidence * 100.0, 1)
        c["status"] = "ready" if (c.get("trigger_now") and c.get("trend_ok") and c.get("vol_ok")) else "wait"
        c["best_params"] = p if p.get("ok") else None
        scored.append(c)

    candidates_sorted = sorted(
        scored,
        key=lambda x: (x["composite_score"], x["entry_ease_score"], x["trigger_now"], -x["time_to_next_sec"]),
        reverse=True
    )

    chosen = candidates_sorted[0]
    best_params_map = chosen.get("best_params") or None
    plan = build_plan(chosen, side, best_params=best_params_map, risk_pct=risk_pct)

    # Provide chart-overlay hints for the UI.
    # The UI fetches the full candles separately via /api/candles?tf=...
    tf_sec = int(TF_MINUTES.get(plan["tf"], 60) * 60)
    last_ts = int(chosen.get("ts", int(time.time())))
    last_close = float(chosen.get("close", plan.get("entry_price", 0.0)))
    entry_v = float(plan.get("entry_price"))
    tp_v = float(plan.get("tp1_price"))

    # A simple 3-point guide line: last_close -> entry (next bar) -> tp (few bars ahead)
    scenario_points = [
        {"ts": last_ts, "value": round(last_close, 2)},
        {"ts": last_ts + tf_sec, "value": round(entry_v, 2)},
        {"ts": last_ts + tf_sec * 5, "value": round(tp_v, 2)},
    ]
    plan["scenario"] = {
        "tf_sec": tf_sec,
        "path": scenario_points,
        "levels": {
            "entry": float(plan.get("entry_price")),
            "stop": float(plan.get("stop_price")),
            "tp1": float(plan.get("tp1_price")),
            "tp2": float(plan.get("tp2_price")),
        },
    }

    notes: List[str] = []
    if reg.get("bias") == "unknown":
        notes.append("1D 레짐 불확실 (데이터 부족)")
    if not chosen.get("vol_ok", True):
        notes.append(f"변동성(ATR%) 범위 이탈: {chosen.get('atr_pct')}%")
    if chosen.get("status") != "ready":
        notes.append("진입 조건 미충족(대기)")

    return {
        "ok": True,
        "regime": reg,
        "selected": chosen,
        "best_params": best_params_map,
        "plan": plan,
        "candidates": candidates_sorted,
        "notes": notes,
    }
