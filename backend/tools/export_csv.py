from __future__ import annotations
import argparse
import csv
import sys
import os
import datetime
from pathlib import Path

# ensure backend/ is on sys.path
THIS = Path(__file__).resolve()
BACKEND_DIR = THIS.parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="./data/backup", help="directory to save csv files")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    db.init_db() # ensure connection logic works

    # Get available timeframes
    timeframes = db.timeframes_available()
    print(f"Found timeframes: {timeframes}")

    conn = db.connect()
    try:
        for tf in timeframes:
            # Select all rows for this timeframe
            cur = conn.execute("SELECT ts, open, high, low, close, volume FROM candles WHERE timeframe=? ORDER BY ts ASC", (tf,))
            rows = cur.fetchall()
            
            if not rows:
                continue

            filename = f"candles_{tf}.csv"
            filepath = out_dir / filename
            
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["time", "open", "high", "low", "close", "volume"])
                
                for row in rows:
                    # Convert ts to ISO string
                    dt = datetime.datetime.fromtimestamp(row["ts"], tz=datetime.timezone.utc)
                    iso_time = dt.isoformat()
                    
                    writer.writerow([
                        iso_time,
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["volume"]
                    ])
            
            print(f"Exported {len(rows)} rows to {filepath}")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
