from __future__ import annotations
from typing import Optional, Sequence, Tuple
import numpy as np

def sma_last(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    arr = np.asarray(values, dtype=float)
    return float(arr[-period:].mean())

def rsi_sma_last(closes: Sequence[float], period: int = 2) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    arr = np.asarray(closes, dtype=float)
    delta = np.diff(arr)
    gains = np.clip(delta, 0, None)
    losses = np.clip(-delta, 0, None)
    g = gains[-period:].mean()
    l = losses[-period:].mean()
    if l == 0 and g == 0:
        return 50.0
    if l == 0:
        return 100.0
    rs = g / l
    return float(100 - (100 / (1 + rs)))

def atr_sma_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1 or len(highs) != len(lows) or len(highs) != len(closes):
        return None
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    prev_close = np.roll(c, 1)
    prev_close[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_close), np.abs(l - prev_close)))
    if len(tr) < period:
        return None
    return float(tr[-period:].mean())

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
