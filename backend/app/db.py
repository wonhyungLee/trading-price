from __future__ import annotations
import json
import sqlite3
import time
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

CREATE TABLE IF NOT EXISTS notifications (
  kind TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  ts INTEGER NOT NULL,
  created_ts INTEGER NOT NULL,
  detail TEXT,
  PRIMARY KEY (kind, timeframe, ts)
);
CREATE INDEX IF NOT EXISTS idx_notifications_kind_created ON notifications(kind, created_ts);

CREATE TABLE IF NOT EXISTS ad_interest (
  category TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ad_interest_count_updated ON ad_interest(count DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS fx_rates (
  base TEXT NOT NULL,
  quote TEXT NOT NULL,
  rate REAL NOT NULL,
  as_of_date TEXT NOT NULL,
  fetched_ts INTEGER NOT NULL,
  source TEXT,
  PRIMARY KEY (base, quote, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_fx_rates_pair_date ON fx_rates(base, quote, as_of_date);

CREATE TABLE IF NOT EXISTS pending_auto_trade_webhooks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  tp_price REAL NOT NULL,
  created_ts INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);
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

def fetch_range(timeframe: str, start_ts: int, end_ts: int) -> List[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM candles WHERE timeframe=? AND ts BETWEEN ? AND ? ORDER BY ts ASC""",
            (timeframe, start_ts, end_ts),
        )
        return cur.fetchall()
    finally:
        conn.close()

def timeframes_available() -> List[str]:
    conn = connect()
    try:
        cur = conn.execute("""SELECT DISTINCT timeframe FROM candles""")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

def notification_exists(kind: str, timeframe: str, ts: int) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT 1 FROM notifications WHERE kind=? AND timeframe=? AND ts=? LIMIT 1""",
            (kind, timeframe, int(ts)),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()

def fetch_latest_notification(kind: str) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM notifications WHERE kind=? ORDER BY created_ts DESC LIMIT 1""",
            (kind,),
        )
        return cur.fetchone()
    finally:
        conn.close()

def insert_notification(kind: str, timeframe: str, ts: int, created_ts: int, detail: Optional[str] = None) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO notifications(kind, timeframe, ts, created_ts, detail)
               VALUES (?, ?, ?, ?, ?)""",
            (kind, timeframe, int(ts), int(created_ts), detail),
        )
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()

def ensure_ad_interest_schema() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ad_interest (
              category TEXT PRIMARY KEY,
              count INTEGER NOT NULL DEFAULT 0,
              updated_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ad_interest_count_updated ON ad_interest(count DESC, updated_at DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()

def record_ad_interest(category: str) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO ad_interest (category, count, updated_at)
            VALUES (?, 1, strftime('%s','now'))
            ON CONFLICT(category)
            DO UPDATE SET count = count + 1, updated_at = strftime('%s','now')
            """,
            (category,),
        )
        conn.commit()
    finally:
        conn.close()

def fetch_top_interest_category() -> Optional[str]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT category FROM ad_interest ORDER BY count DESC, updated_at DESC LIMIT 1"""
        )
        row = cur.fetchone()
        return row["category"] if row else None
    finally:
        conn.close()

def insert_fx_rate(
    base: str,
    quote: str,
    rate: float,
    as_of_date: str,
    fetched_ts: Optional[int] = None,
    source: Optional[str] = None,
) -> None:
    conn = connect()
    try:
        now = int(time.time()) if fetched_ts is None else int(fetched_ts)
        conn.execute(
            """
            INSERT INTO fx_rates (base, quote, rate, as_of_date, fetched_ts, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(base, quote, as_of_date)
            DO UPDATE SET
              rate = excluded.rate,
              fetched_ts = excluded.fetched_ts,
              source = excluded.source
            """,
            (str(base).upper(), str(quote).upper(), float(rate), str(as_of_date), now, source),
        )
        conn.commit()
    finally:
        conn.close()

def fetch_latest_fx_rate(base: str, quote: str) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM fx_rates
               WHERE base=? AND quote=?
               ORDER BY as_of_date DESC, fetched_ts DESC
               LIMIT 1""",
            (str(base).upper(), str(quote).upper()),
        )
        return cur.fetchone()
    finally:
        conn.close()

def insert_pending_upbit_auto_trade(side: str, entry_price: float, tp_price: float, created_ts: Optional[int] = None) -> int:
    conn = connect()
    try:
        ts = int(time.time()) if created_ts is None else int(created_ts)
        cur = conn.execute(
            """
            INSERT INTO pending_auto_trade_webhooks (side, entry_price, tp_price, created_ts, attempts, last_error)
            VALUES (?, ?, ?, ?, 0, NULL)
            """,
            (str(side).lower(), float(entry_price), float(tp_price), ts),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def fetch_pending_upbit_auto_trades(limit: int = 100) -> List[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """
            SELECT id, side, entry_price, tp_price, created_ts, attempts
              FROM pending_auto_trade_webhooks
             WHERE attempts < 10
             ORDER BY created_ts ASC, id ASC
             LIMIT ?
            """,
            (int(limit),),
        )
        return cur.fetchall()
    finally:
        conn.close()

def delete_pending_upbit_auto_trade(pending_id: int) -> None:
    conn = connect()
    try:
        conn.execute(
            "DELETE FROM pending_auto_trade_webhooks WHERE id = ?",
            (int(pending_id),),
        )
        conn.commit()
    finally:
        conn.close()

def bump_pending_upbit_auto_trade(pending_id: int, last_error: str) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE pending_auto_trade_webhooks
               SET attempts = attempts + 1,
                   last_error = ?
             WHERE id = ?
            """,
            (str(last_error), int(pending_id)),
        )
        conn.commit()
    finally:
        conn.close()
