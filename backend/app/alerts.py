from __future__ import annotations

import statistics
from typing import Any, Dict, Optional

from . import db
from .config import (
    SPIKE_VOL_LOOKBACK,
    SPIKE_VOL_MULT,
    SPIKE_RANGE_LOOKBACK,
    SPIKE_RANGE_MULT,
    SPIKE_MIN_RANGE_PCT,
)


def _range_pct(row: Any) -> float:
    close = float(row["close"] or 0.0)
    if close <= 0:
        return 0.0
    return (float(row["high"]) - float(row["low"])) / close * 100.0


def detect_volume_volatility_spike(timeframe: str, ts: int) -> Optional[Dict[str, Any]]:
    """Detect a "volume spike + volatility spike" on the latest candle.

    Returns a context dict if triggered, otherwise None.
    """
    lookback = max(int(SPIKE_VOL_LOOKBACK), int(SPIKE_RANGE_LOOKBACK))
    if lookback < 5:
        return None

    rows = db.fetch_recent(timeframe, lookback + 1)
    if len(rows) < lookback + 1:
        return None

    last = rows[-1]
    if int(last["ts"]) != int(ts):
        return None

    # Volume spike (vs median of previous N bars)
    vol_hist_rows = rows[-(int(SPIKE_VOL_LOOKBACK) + 1):-1]
    vols = [float(r["volume"] or 0.0) for r in vol_hist_rows]
    vols = [v for v in vols if v > 0.0]
    if len(vols) < max(5, int(SPIKE_VOL_LOOKBACK) // 2):
        return None
    vol_base = float(statistics.median(vols))
    vol_now = float(last["volume"] or 0.0)
    vol_ratio = (vol_now / vol_base) if vol_base > 0 else 0.0

    # Volatility spike (current bar range% vs median of previous N bars)
    range_hist_rows = rows[-(int(SPIKE_RANGE_LOOKBACK) + 1):-1]
    ranges = [_range_pct(r) for r in range_hist_rows]
    if len(ranges) < max(5, int(SPIKE_RANGE_LOOKBACK) // 2):
        return None
    range_base = float(statistics.median(ranges))
    range_now = _range_pct(last)
    range_ratio = (range_now / range_base) if range_base > 0 else 0.0

    triggered = (
        (vol_ratio >= float(SPIKE_VOL_MULT))
        and (range_ratio >= float(SPIKE_RANGE_MULT))
        and (range_now >= float(SPIKE_MIN_RANGE_PCT))
    )
    if not triggered:
        return None

    return {
        "kind": "volume_volatility_spike",
        "timeframe": timeframe,
        "ts": int(ts),
        "volume": vol_now,
        "volume_base": vol_base,
        "volume_ratio": round(vol_ratio, 3),
        "range_pct": round(range_now, 4),
        "range_base": round(range_base, 4),
        "range_ratio": round(range_ratio, 3),
        "close": float(last["close"]),
    }
