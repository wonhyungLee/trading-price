from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from .indicators import clamp

@dataclass
class Metrics:
    n_trades: int
    win_rate: float
    total_return: float
    mdd: float
    profit_factor: Optional[float]
    avg_ret: Optional[float]
    fill_rate: Optional[float]
    mae_p95: Optional[float]

def _parse_grid(s: str) -> List[float]:
    out: List[float] = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out

def _rolling_sma(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None]*n
    if n < period:
        return out
    s = sum(values[:period])
    out[period-1] = s/period
    for i in range(period, n):
        s += values[i] - values[i-period]
        out[i] = s/period
    return out

def _rsi2(closes: List[float]) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None]*n
    if n < 3:
        return out
    # RSI(2) using simple average of last 2 gains/losses
    for i in range(2, n):
        d1 = closes[i-1] - closes[i-2]
        d2 = closes[i] - closes[i-1]
        g = (max(d1,0.0) + max(d2,0.0)) / 2.0
        l = (max(-d1,0.0) + max(-d2,0.0)) / 2.0
        if l == 0 and g == 0:
            out[i] = 50.0
        elif l == 0:
            out[i] = 100.0
        else:
            rs = g/l
            out[i] = 100.0 - (100.0/(1.0+rs))
    return out

def _atr14(highs: List[float], lows: List[float], closes: List[float]) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None]*n
    if n < 15:
        return out
    trs: List[float] = [0.0]*n
    for i in range(1,n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs[i] = tr
    # rolling mean 14
    s = sum(trs[1:15])  # i=1..14 (14 values)
    out[14] = s/14.0
    for i in range(15,n):
        s += trs[i] - trs[i-14]
        out[i] = s/14.0
    return out

def backtest_price_plan(
    rows: List[Dict[str, Any]],
    side: str,
    entry_mode: str,
    entry_k: float,
    stop_mult: float,
    fee_bps: float = 0.0,
) -> Tuple[Metrics, Dict[str, Any]]:
    """Backtest the Connors/Wonyodd-style rule on a single timeframe.

    Rules (no lookahead):
    - Signal uses bar i close.
    - If entry condition true, trade executes on bar i+1 (next bar).
      * market: entry = next_open
      * limit_atr: entry = next_open +/- entry_k * ATR14(i); must be filled within bar i+1 range
    - Exit rule: after entry, if bar j close crosses SMA5 in favor, exit at bar j+1 open.
    - Stop: hard stop based on ATR14(i) and stop_mult; triggered intrabar at stop price.
    - Fees: applied on entry and exit (bps each side).
    """
    side = side.lower().strip()
    if side not in ("long","short"):
        raise ValueError("side must be long or short")
    entry_mode = entry_mode.lower().strip()
    if entry_mode not in ("market","limit_atr"):
        raise ValueError("entry_mode must be market or limit_atr")

    n = len(rows)
    if n < 260:
        m = Metrics(0, 0.0, 0.0, 0.0, None, None, None, None)
        return m, {"note": "not_enough_rows"}

    o = [float(r["open"]) for r in rows]
    h = [float(r["high"]) for r in rows]
    l = [float(r["low"]) for r in rows]
    c = [float(r["close"]) for r in rows]
    ts = [int(r["ts"]) for r in rows]

    sma5 = _rolling_sma(c, 5)
    sma200 = _rolling_sma(c, 200)
    rsi2 = _rsi2(c)
    atr14 = _atr14(h, l, c)

    # equity curve (mark-to-market)
    equity = 1.0
    peak = 1.0
    mdd = 0.0

    in_pos = False
    entry_px = 0.0
    stop_px = 0.0
    entry_i = -1
    exit_pending = False

    trade_rets: List[float] = []
    mae_list: List[float] = []
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0

    signals = 0
    fills = 0

    def apply_fee(x: float) -> float:
        # fee_bps applied multiplicatively
        if fee_bps <= 0:
            return x
        return x * (1.0 - fee_bps/10000.0)

    def apply_fee_exit(x: float) -> float:
        if fee_bps <= 0:
            return x
        return x * (1.0 - fee_bps/10000.0)

    # iterate bars; use i as signal bar, i+1 as execution bar
    i = 0
    # mark-to-market uses close; compute dd each bar
    while i < n-2:  # ensure i+1 and i+2 exist for next open
        # update m2m equity at bar close
        if in_pos:
            if side == "long":
                m2m = equity * (c[i] / entry_px)
            else:
                m2m = equity * (entry_px / c[i])
            peak = max(peak, m2m)
            dd = (peak - m2m) / peak
            mdd = max(mdd, dd)
        else:
            peak = max(peak, equity)
            dd = (peak - equity) / peak
            mdd = max(mdd, dd)

        if not in_pos:
            # need indicators available
            if sma5[i] is None or sma200[i] is None or rsi2[i] is None or atr14[i] is None:
                i += 1
                continue

            # entry rule
            if side == "long":
                cond = (c[i] > sma200[i]) and (c[i] < sma5[i]) and (rsi2[i] <= 5.0)
            else:
                cond = (c[i] < sma200[i]) and (c[i] > sma5[i]) and (rsi2[i] >= 95.0)

            if not cond:
                i += 1
                continue

            signals += 1

            # execution on next bar (i+1)
            next_open = o[i+1]
            atr = atr14[i] or 0.0

            if entry_mode == "market":
                entry = next_open
                filled = True
            else:
                if side == "long":
                    entry = next_open - entry_k * atr
                    filled = (l[i+1] <= entry)  # touched
                else:
                    entry = next_open + entry_k * atr
                    filled = (h[i+1] >= entry)

            if not filled:
                i += 1
                continue

            fills += 1
            in_pos = True
            exit_pending = False
            entry_px = apply_fee(entry)  # fee on entry
            stop_px = entry_px - stop_mult * atr if side == "long" else entry_px + stop_mult * atr
            entry_i = i+1
            # record initial MAE baseline
            i += 1
            continue

        # in position: stop check on current bar i
        if in_pos:
            # stop intrabar at stop price (worst-case)
            stopped = False
            if side == "long":
                if l[i] <= stop_px:
                    exit_px = apply_fee_exit(stop_px)
                    stopped = True
            else:
                if h[i] >= stop_px:
                    exit_px = apply_fee_exit(stop_px)
                    stopped = True

            if stopped:
                # finalize trade at this bar
                if side == "long":
                    ret = (exit_px / entry_px) - 1.0
                else:
                    ret = (entry_px / exit_px) - 1.0
                equity *= (1.0 + ret)
                trade_rets.append(ret)
                # MAE: worst excursion from entry during holding (approx using lows/highs)
                if side == "long":
                    mae = max(0.0, (entry_px - min(l[entry_i:i+1])) / entry_px)
                else:
                    mae = max(0.0, (max(h[entry_i:i+1]) - entry_px) / entry_px)
                mae_list.append(mae)
                if ret > 0:
                    wins += 1
                    gross_profit += ret
                else:
                    gross_loss += abs(ret)
                in_pos = False
                exit_pending = False
                i += 1
                continue

            # exit rule: if exit_pending, exit at next open
            if exit_pending:
                exit_px = apply_fee_exit(o[i])  # execute on this bar open (it is next open after signal)
                if side == "long":
                    ret = (exit_px / entry_px) - 1.0
                else:
                    ret = (entry_px / exit_px) - 1.0
                equity *= (1.0 + ret)
                trade_rets.append(ret)
                if side == "long":
                    mae = max(0.0, (entry_px - min(l[entry_i:i])) / entry_px)
                else:
                    mae = max(0.0, (max(h[entry_i:i]) - entry_px) / entry_px)
                mae_list.append(mae)
                if ret > 0:
                    wins += 1
                    gross_profit += ret
                else:
                    gross_loss += abs(ret)
                in_pos = False
                exit_pending = False
                i += 1
                continue

            # set exit_pending when close crosses SMA5 (at bar close i)
            if sma5[i] is not None:
                if side == "long" and (c[i] > sma5[i]):
                    exit_pending = True
                elif side == "short" and (c[i] < sma5[i]):
                    exit_pending = True

            i += 1
            continue

        i += 1

    # finalize mtm for last close
    if in_pos:
        # exit at last close (conservative)
        exit_px = apply_fee_exit(c[-1])
        if side == "long":
            ret = (exit_px / entry_px) - 1.0
        else:
            ret = (entry_px / exit_px) - 1.0
        equity *= (1.0 + ret)
        trade_rets.append(ret)
        if side == "long":
            mae = max(0.0, (entry_px - min(l[entry_i:])) / entry_px)
        else:
            mae = max(0.0, (max(h[entry_i:]) - entry_px) / entry_px)
        mae_list.append(mae)
        if ret > 0:
            wins += 1
            gross_profit += ret
        else:
            gross_loss += abs(ret)

    n_trades = len(trade_rets)
    win_rate = (wins / n_trades) if n_trades else 0.0
    total_return = equity - 1.0
    avg_ret = (sum(trade_rets)/n_trades) if n_trades else None
    pf = (gross_profit / gross_loss) if (gross_loss > 0 and n_trades) else None
    fill_rate = (fills / signals) if signals else None

    mae_p95 = None
    if mae_list:
        srt = sorted(mae_list)
        idx = int(0.95*(len(srt)-1))
        mae_p95 = srt[idx]

    m = Metrics(
        n_trades=n_trades,
        win_rate=float(win_rate),
        total_return=float(total_return),
        mdd=float(mdd),
        profit_factor=float(pf) if pf is not None else None,
        avg_ret=float(avg_ret) if avg_ret is not None else None,
        fill_rate=float(fill_rate) if fill_rate is not None else None,
        mae_p95=float(mae_p95) if mae_p95 is not None else None,
    )
    detail = {
        "signals": signals,
        "fills": fills,
    }
    return m, detail

def score_metrics(m: Metrics) -> float:
    # A pragmatic score emphasizing MDD reduction + stable edge:
    # - Reward return
    # - Reward win_rate moderately
    # - Penalize MDD heavily
    # - Reward profit factor
    # - Penalize tail MAE
    ret = m.total_return
    mdd = max(1e-9, m.mdd)
    calmar_like = ret / mdd

    wr = m.win_rate
    pf = m.profit_factor if m.profit_factor is not None else 1.0
    fill = m.fill_rate if m.fill_rate is not None else 1.0
    tail = m.mae_p95 if m.mae_p95 is not None else 0.0

    score = 0.0
    score += calmar_like
    score += (wr - 0.5) * 0.5
    score += (pf - 1.0) * 0.2
    score += (fill - 0.8) * 0.1
    score -= tail * 1.5

    # very low trade count shouldn't dominate
    if m.n_trades < 20:
        score *= 0.5
    return float(score)
