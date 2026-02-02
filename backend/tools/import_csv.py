from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path
from dateutil import parser as dtparser

# ensure backend/ is on sys.path
THIS = Path(__file__).resolve()
BACKEND_DIR = THIS.parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa

def parse_ts(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    if s.isdigit():
        ts = int(s)
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    try:
        dt = dtparser.parse(s)
        return int(dt.timestamp())
    except Exception:
        return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="path to OHLCV csv (must include time/open/high/low/close)")
    ap.add_argument("--timeframe", required=True, help="1D,30m,60m,180m")
    args = ap.parse_args()

    path = args.csv
    tf = args.timeframe

    db.init_db()
    n = 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header")
        cols = {c.lower(): c for c in reader.fieldnames}

        required = ["time","open","high","low","close"]
        for r in required:
            if r not in cols:
                raise SystemExit(f"CSV missing column: {r}")

        for row in reader:
            ts = parse_ts(row[cols["time"]])
            if ts == 0:
                continue
            o = float(row[cols["open"]])
            h = float(row[cols["high"]])
            l = float(row[cols["low"]])
            c = float(row[cols["close"]])
            v = None
            if "volume" in cols and row.get(cols["volume"], "") not in ("", None):
                try:
                    v = float(row[cols["volume"]])
                except Exception:
                    v = None
            db.upsert_candle(tf, ts, o, h, l, c, v, features=None)
            n += 1

    print(f"Imported {n} rows into timeframe={tf}")

if __name__ == "__main__":
    main()
