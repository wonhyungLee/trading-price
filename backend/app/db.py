from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS candles (
  timeframe TEXT NOT NULL,
  ts INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL,
  features TEXT,
  PRIMARY KEY (timeframe, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_tf_ts ON candles(timeframe, ts);
"""

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

def upsert_candle(timeframe: str, ts: int, o: float, h: float, l: float, c: float, v: Optional[float], features: Optional[Dict[str, Any]]=None) -> None:
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO candles(timeframe, ts, open, high, low, close, volume, features)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(timeframe, ts) DO UPDATE SET
                   open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                   volume=excluded.volume, features=excluded.features
            """,
            (timeframe, ts, o, h, l, c, v, json.dumps(features) if features is not None else None),
        )
        conn.commit()
    finally:
        conn.close()

def fetch_recent(timeframe: str, limit: int) -> List[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM candles WHERE timeframe=? ORDER BY ts DESC LIMIT ?""",
            (timeframe, limit),
        )
        rows = cur.fetchall()
        return list(reversed(rows))  # ascending
    finally:
        conn.close()

def fetch_latest(timeframe: str) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM candles WHERE timeframe=? ORDER BY ts DESC LIMIT 1""",
            (timeframe,),
        )
        row = cur.fetchone()
        return row
    finally:
        conn.close()

def timeframes_available() -> List[str]:
    conn = connect()
    try:
        cur = conn.execute("""SELECT DISTINCT timeframe FROM candles""")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
