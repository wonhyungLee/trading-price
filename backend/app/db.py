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
  entry_price REAL,
  recommended_price REAL,
  tp1_price REAL,
  tp2_price REAL,
  tp3_price REAL,
  ready_rule TEXT,
  ready_rule_mdd_pct REAL,
  status TEXT,
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

CREATE TABLE IF NOT EXISTS pending_auto_trade_webhooks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  tp_price REAL NOT NULL,
  created_ts INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
  ,order_name TEXT
  ,exchange TEXT
  ,order_side TEXT
  ,trigger_type TEXT
  ,trigger_price REAL
  ,payload_json TEXT
  ,requires_fx INTEGER NOT NULL DEFAULT 0
  ,batch_id INTEGER
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
        _migrate_notifications_columns(conn)
        _migrate_fx_rates_columns(conn)
        _migrate_pending_auto_trade_webhooks(conn)
        _ensure_fx_rate_indexes(conn)
        conn.commit()
    finally:
        conn.close()

def _migrate_notifications_columns(conn: sqlite3.Connection) -> None:
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'"
    ).fetchone()
    if table_row is None:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
    required_columns = {
        "entry_price": "REAL",
        "recommended_price": "REAL",
        "tp1_price": "REAL",
        "tp2_price": "REAL",
        "tp3_price": "REAL",
        "ready_rule": "TEXT",
        "ready_rule_mdd_pct": "REAL",
        "status": "TEXT",
    }
    for col, col_type in required_columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE notifications ADD COLUMN {col} {col_type}")


def _migrate_fx_rates_columns(conn: sqlite3.Connection) -> None:
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fx_rates'"
    ).fetchone()
    if table_row is None:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(fx_rates)").fetchall()}
    if "as_of_date" not in existing:
        conn.execute("ALTER TABLE fx_rates ADD COLUMN as_of_date TEXT")
        if "date" in existing:
            conn.execute(
                """
                UPDATE fx_rates
                   SET as_of_date = COALESCE(date, strftime('%Y-%m-%d', 'now'))
                """
            )
        elif "rate_date" in existing:
            conn.execute(
                """
                UPDATE fx_rates
                   SET as_of_date = COALESCE(rate_date, strftime('%Y-%m-%d', 'now'))
                """
            )
        else:
            conn.execute(
                """
                UPDATE fx_rates
                   SET as_of_date = strftime('%Y-%m-%d', 'now')
                """
            )
    if "rate_date" in existing:
        conn.execute(
            """
            UPDATE fx_rates
               SET as_of_date = COALESCE(NULLIF(TRIM(as_of_date), ''), rate_date, strftime('%Y-%m-%d', 'now'))
            """
        )
    else:
        conn.execute(
            "UPDATE fx_rates SET as_of_date = strftime('%Y-%m-%d', 'now') WHERE as_of_date IS NULL OR TRIM(as_of_date) = ''"
        )


def _migrate_pending_auto_trade_webhooks(conn: sqlite3.Connection) -> None:
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_auto_trade_webhooks'"
    ).fetchone()
    if table_row is None:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(pending_auto_trade_webhooks)").fetchall()}
    required_columns = {
        "order_name": "TEXT",
        "exchange": "TEXT",
        "order_side": "TEXT",
        "trigger_type": "TEXT",
        "trigger_price": "REAL",
        "payload_json": "TEXT",
        "requires_fx": "INTEGER NOT NULL DEFAULT 0",
        "batch_id": "INTEGER",
    }
    for col, col_type in required_columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE pending_auto_trade_webhooks ADD COLUMN {col} {col_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_auto_trade_webhooks_batch ON pending_auto_trade_webhooks(batch_id, trigger_type, exchange, side)")


def _ensure_fx_rate_indexes(conn: sqlite3.Connection) -> None:
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fx_rates'"
    ).fetchone()
    if table_row is None:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(fx_rates)").fetchall()}
    if "as_of_date" in existing:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fx_rates_pair_date ON fx_rates(base, quote, as_of_date)")
    elif "date" in existing:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fx_rates_pair_date ON fx_rates(base, quote, date)")

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

def fetch_one(timeframe: str, ts: int) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """SELECT * FROM candles WHERE timeframe=? AND ts=? LIMIT 1""",
            (timeframe, int(ts)),
        )
        return cur.fetchone()
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

def insert_notification(
    kind: str,
    timeframe: str,
    ts: int,
    created_ts: int,
    detail: Optional[str] = None,
    entry_price: Optional[float] = None,
    recommended_price: Optional[float] = None,
    tp1_price: Optional[float] = None,
    tp2_price: Optional[float] = None,
    tp3_price: Optional[float] = None,
    ready_rule: Optional[str] = None,
    ready_rule_mdd_pct: Optional[float] = None,
    status: Optional[str] = None,
) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO notifications(
                   kind, timeframe, ts, created_ts, detail,
                   entry_price, recommended_price, tp1_price, tp2_price, tp3_price,
                   ready_rule, ready_rule_mdd_pct, status
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                kind,
                timeframe,
                int(ts),
                int(created_ts),
                detail,
                entry_price,
                recommended_price,
                tp1_price,
                tp2_price,
                tp3_price,
                ready_rule,
                ready_rule_mdd_pct,
                status,
            ),
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
        base_u = str(base).upper()
        quote_u = str(quote).upper()
        as_of = str(as_of_date)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(fx_rates)").fetchall()}
        has_rate_date = "rate_date" in cols
        has_as_of_date = "as_of_date" in cols

        if has_rate_date and has_as_of_date:
            params = (base_u, quote_u, float(rate), as_of, as_of, now, source)
            insert_sql = """
                INSERT INTO fx_rates (base, quote, rate, rate_date, as_of_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(base, quote, rate_date)
                DO UPDATE SET
                  rate = excluded.rate,
                  as_of_date = excluded.as_of_date,
                  fetched_ts = excluded.fetched_ts,
                  source = excluded.source
                """
            replace_sql = """
                INSERT OR REPLACE INTO fx_rates (base, quote, rate, rate_date, as_of_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
        elif has_rate_date:
            params = (base_u, quote_u, float(rate), as_of, now, source)
            insert_sql = """
                INSERT INTO fx_rates (base, quote, rate, rate_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(base, quote, rate_date)
                DO UPDATE SET
                  rate = excluded.rate,
                  fetched_ts = excluded.fetched_ts,
                  source = excluded.source
                """
            replace_sql = """
                INSERT OR REPLACE INTO fx_rates (base, quote, rate, rate_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """
        else:
            params = (base_u, quote_u, float(rate), as_of, now, source)
            insert_sql = """
                INSERT INTO fx_rates (base, quote, rate, as_of_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(base, quote, as_of_date)
                DO UPDATE SET
                  rate = excluded.rate,
                  fetched_ts = excluded.fetched_ts,
                  source = excluded.source
                """
            replace_sql = """
                INSERT OR REPLACE INTO fx_rates (base, quote, rate, as_of_date, fetched_ts, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """
        try:
            conn.execute(insert_sql, params)
        except sqlite3.OperationalError as e:
            if "ON CONFLICT clause does not match" in str(e):
                conn.execute(replace_sql, params)
            else:
                raise
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

def insert_pending_auto_trade(
    side: str,
    order_name: str,
    order_side: str,
    exchange: str,
    trigger_type: str,
    trigger_price: float,
    payload_json: str,
    requires_fx: bool = False,
    created_ts: Optional[int] = None,
    entry_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    batch_id: Optional[int] = None,
) -> int:
    conn = connect()
    try:
        ts = int(time.time()) if created_ts is None else int(created_ts)
        entry_value = float(entry_price if entry_price is not None else trigger_price)
        tp_value = float(tp_price if tp_price is not None else trigger_price)
        cur = conn.execute(
            """
            INSERT INTO pending_auto_trade_webhooks (
              side, entry_price, tp_price, created_ts, attempts, last_error,
              order_name, exchange, order_side, trigger_type, trigger_price, payload_json, requires_fx, batch_id
            )
            VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(side).lower(),
                float(entry_value),
                float(tp_value),
                ts,
                str(order_name),
                str(exchange),
                str(order_side),
                str(trigger_type),
                float(trigger_price),
                payload_json,
                1 if requires_fx else 0,
                None if batch_id is None else int(batch_id),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def fetch_pending_auto_trades(limit: int = 100) -> List[sqlite3.Row]:
    conn = connect()
    try:
        cur = conn.execute(
            """
            SELECT id, side, entry_price, tp_price, created_ts, attempts, last_error,
                   order_name, exchange, order_side, trigger_type, trigger_price, payload_json, requires_fx, batch_id
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

def prune_pending_auto_trades(older_than_seconds: int = 86400) -> int:
    conn = connect()
    try:
        cutoff = int(time.time()) - int(older_than_seconds)
        cur = conn.execute(
            """
            DELETE FROM pending_auto_trade_webhooks
             WHERE created_ts < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()

def delete_pending_auto_trade(pending_id: int) -> None:
    conn = connect()
    try:
        conn.execute(
            "DELETE FROM pending_auto_trade_webhooks WHERE id = ?",
            (int(pending_id),),
        )
        conn.commit()
    finally:
        conn.close()

def has_pending_entry_in_batch(batch_id: int, side: str, exchange: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            """
            SELECT 1
              FROM pending_auto_trade_webhooks
             WHERE batch_id = ?
               AND side = ?
               AND exchange = ?
               AND trigger_type = 'entry'
             LIMIT 1
            """,
            (int(batch_id), str(side).lower(), str(exchange)),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()

def bump_pending_auto_trade(pending_id: int, last_error: str) -> None:
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
