from __future__ import annotations
import argparse
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
BACKEND_DIR = THIS.parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa
from app.indicators import sma_last, rsi_sma_last  # noqa

def backtest(tf: str):
    rows = db.fetch_recent(tf, 1_000_000)
    if len(rows) < 250:
        raise SystemExit("not enough data")

    closes = [r["close"] for r in rows]
    position = 0
    entry_px = None
    eq = 1.0
    trades = 0
    wins = 0

    for i in range(len(rows)-1):
        window = closes[:i+1]
        sma200 = sma_last(window, 200)
        sma5 = sma_last(window, 5)
        rsi2 = rsi_sma_last(window, 2)

        if sma200 is None or sma5 is None or rsi2 is None:
            continue

        close = float(rows[i]["close"])
        next_open = float(rows[i+1]["open"])

        if position == 0:
            if close > sma200 and close < sma5 and rsi2 <= 5.0:
                position = 1
                entry_px = next_open
        else:
            if close > sma5:
                exit_px = next_open
                ret = exit_px / entry_px - 1.0
                eq *= (1.0 + ret)
                trades += 1
                if ret > 0:
                    wins += 1
                position = 0
                entry_px = None

    win_rate = wins / trades if trades else 0
    print(f"TF={tf} trades={trades} total_return={(eq-1)*100:.2f}% win_rate={win_rate*100:.2f}%")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", required=True, help="30m,60m,180m,1D")
    args = ap.parse_args()
    db.init_db()
    backtest(args.tf)

if __name__ == "__main__":
    main()
