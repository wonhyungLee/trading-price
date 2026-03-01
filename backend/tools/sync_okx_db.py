#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OKX_HOST = "https://www.okx.com"
TIMEFRAME_SECONDS = {"30m": 1800, "60m": 3600, "180m": 10800}
CORE_TIMEFRAMES = ("1m", "30m", "60m", "180m", "1D")


def now_ts() -> int:
    return int(time.time())


def align_ts(ts: int, sec: int) -> int:
    if sec <= 0:
        return ts
    return int(ts - (ts % sec))


def iso_utc(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def normalize_okx_inst_id(value: str) -> str:
    raw = str(value or "").strip().upper()
    compact = raw.replace(" ", "").replace("_", "-")
    # TradingView perpetual aliases (e.g. BTCUSDT.P) -> OKX swap instrument
    if compact in (
        "BTCUSDT.P",
        "BTC-USDT.P",
        "BTCUSDT-P",
        "BTCUSDT.PERP",
        "BTC-USDT-PERP",
        "BTC/USDT.P",
    ):
        return "BTC-USDT-SWAP"
    return compact or "BTC-USDT-SWAP"


def fetch_json(path: str, params: dict[str, str], *, timeout: int, retries: int) -> Any:
    query = urlencode(params)
    url = f"{OKX_HOST}{path}?{query}" if query else f"{OKX_HOST}{path}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = Request(
            url=url,
            headers={"Accept": "application/json", "User-Agent": "wonyodd-db-sync/okx-1.0"},
            method="GET",
        )
        try:
            with urlopen(req, timeout=max(1, timeout)) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            retriable = err.code in (429, 500, 502, 503, 504)
            if retriable and attempt < retries:
                time.sleep(0.6 * (2**attempt))
                continue
            last_error = RuntimeError(f"HTTP {err.code} {path}: {body[:300]}")
            break
        except URLError as err:
            if attempt < retries:
                time.sleep(0.6 * (2**attempt))
                continue
            last_error = RuntimeError(f"Network error {path}: {err}")
            break
        except json.JSONDecodeError as err:
            last_error = RuntimeError(f"Invalid JSON {path}: {err}")
            break
    raise last_error or RuntimeError(f"Request failed: {path}")


def post_json(url: str, payload: dict[str, Any], *, timeout: int, secret: str = "") -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "wonyodd-db-sync/okx-1.0",
    }
    if secret:
        headers["X-Webhook-Secret"] = secret
    req = Request(url=url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=max(1, timeout)) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status < 200 or resp.status >= 300:
                return False, f"http_{resp.status}:{body[:200]}"
            return True, body[:200] if body else "ok"
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return False, f"http_{err.code}:{body[:200]}"
    except URLError as err:
        return False, f"network:{err}"
    except Exception as err:
        return False, f"error:{type(err).__name__}:{err}"


def okx_history_candles(
    *,
    inst_id: str,
    bar: str,
    limit: int,
    after_ms: int | None,
    timeout: int,
    retries: int,
) -> list[Any]:
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": str(max(1, min(100, int(limit)))),
    }
    if after_ms is not None and after_ms > 0:
        params["after"] = str(int(after_ms))
    payload = fetch_json("/api/v5/market/history-candles", params, timeout=timeout, retries=retries)
    if not isinstance(payload, dict):
        raise RuntimeError("okx_invalid_payload")
    code = str(payload.get("code", ""))
    if code != "0":
        msg = str(payload.get("msg", ""))
        raise RuntimeError(f"okx_error_code_{code}:{msg}")
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return data


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
    )
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, timeframe: str, rows: list[tuple[int, float, float, float, float, float | None]]) -> int:
    if not rows:
        return 0
    payload = [(timeframe, ts, o, h, l, c, v, None) for ts, o, h, l, c, v in rows]
    conn.executemany(
        """
        INSERT INTO candles(timeframe, ts, open, high, low, close, volume, features)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(timeframe, ts) DO UPDATE SET
          open=excluded.open,
          high=excluded.high,
          low=excluded.low,
          close=excluded.close,
          volume=excluded.volume,
          features=excluded.features
        """,
        payload,
    )
    conn.commit()
    return len(payload)


def reset_core_timeframes(conn: sqlite3.Connection) -> int:
    placeholders = ",".join("?" for _ in CORE_TIMEFRAMES)
    before = conn.execute(
        f"SELECT COUNT(*) AS c FROM candles WHERE timeframe IN ({placeholders})",
        tuple(CORE_TIMEFRAMES),
    ).fetchone()
    rows_before = int(before["c"]) if before else 0
    conn.execute(
        f"DELETE FROM candles WHERE timeframe IN ({placeholders})",
        tuple(CORE_TIMEFRAMES),
    )
    conn.commit()
    return rows_before


def parse_okx_candle_row(raw: Any, *, align_sec: int) -> tuple[int, float, float, float, float, float | None] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 6:
        return None
    try:
        ts_ms = int(float(raw[0]))
    except Exception:
        return None
    ts = ts_ms // 1000
    if align_sec > 0:
        ts = align_ts(ts, align_sec)

    o = safe_float(raw[1])
    h = safe_float(raw[2])
    l = safe_float(raw[3])
    c = safe_float(raw[4])
    v = safe_float(raw[5])
    if o is None or h is None or l is None or c is None:
        return None
    return (ts, o, h, l, c, v)


def sync_minutes(
    conn: sqlite3.Connection,
    inst_id: str,
    *,
    lookback_minutes: int,
    backfill_days: int,
    timeout: int,
    retries: int,
    request_pause: float,
    max_pages: int,
) -> tuple[int, int | None, int | None]:
    end_ts = align_ts(now_ts() - 5, 60)
    if backfill_days > 0:
        since_ts = end_ts - backfill_days * 86400
    else:
        since_ts = end_ts - max(1, lookback_minutes) * 60

    total_rows = 0
    min_ts: int | None = None
    max_ts: int | None = None
    pages = 0
    after_ms: int | None = None

    while True:
        pages += 1
        rows = okx_history_candles(
            inst_id=inst_id,
            bar="1m",
            limit=100,
            after_ms=after_ms,
            timeout=timeout,
            retries=retries,
        )
        if not rows:
            break

        parsed: list[tuple[int, float, float, float, float, float | None]] = []
        oldest_in_page: int | None = None
        for raw in rows:
            row = parse_okx_candle_row(raw, align_sec=60)
            if row is None:
                continue
            ts = row[0]
            oldest_in_page = ts if oldest_in_page is None else min(oldest_in_page, ts)
            if ts < since_ts:
                continue
            parsed.append(row)

        if parsed:
            parsed.sort(key=lambda x: x[0])
            upsert_rows(conn, "1m", parsed)
            total_rows += len(parsed)
            bmin = parsed[0][0]
            bmax = parsed[-1][0]
            min_ts = bmin if min_ts is None else min(min_ts, bmin)
            max_ts = bmax if max_ts is None else max(max_ts, bmax)

        if oldest_in_page is None:
            break
        if oldest_in_page <= since_ts:
            break
        if max_pages > 0 and pages >= max_pages:
            break

        after_ms = oldest_in_page * 1000
        if request_pause > 0:
            time.sleep(request_pause)

    return total_rows, min_ts, max_ts


def sync_days(
    conn: sqlite3.Connection,
    inst_id: str,
    *,
    day_count: int,
    day_bar: str,
    timeout: int,
    retries: int,
    request_pause: float,
) -> int:
    if day_count <= 0:
        return 0

    remaining = int(day_count)
    after_ms: int | None = None
    total = 0

    while remaining > 0:
        count = min(100, remaining)
        rows = okx_history_candles(
            inst_id=inst_id,
            bar=day_bar,
            limit=count,
            after_ms=after_ms,
            timeout=timeout,
            retries=retries,
        )
        if not rows:
            break

        parsed: list[tuple[int, float, float, float, float, float | None]] = []
        oldest_ts: int | None = None
        for raw in rows:
            row = parse_okx_candle_row(raw, align_sec=86400)
            if row is None:
                continue
            parsed.append(row)
            oldest_ts = row[0] if oldest_ts is None else min(oldest_ts, row[0])

        if not parsed:
            break

        parsed.sort(key=lambda x: x[0])
        upsert_rows(conn, "1D", parsed)
        total += len(parsed)
        remaining -= len(parsed)

        if oldest_ts is None:
            break
        after_ms = oldest_ts * 1000
        if request_pause > 0:
            time.sleep(request_pause)

    return total


def resample_tf_from_1m(conn: sqlite3.Connection, tf: str, start_ts: int, end_ts: int) -> int:
    tf_sec = TIMEFRAME_SECONDS[tf]
    rows = conn.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM candles
        WHERE timeframe='1m' AND ts BETWEEN ? AND ?
        ORDER BY ts ASC
        """,
        (int(start_ts), int(end_ts)),
    ).fetchall()
    if not rows:
        return 0

    expected = tf_sec // 60
    buckets: dict[int, dict[str, float]] = {}
    for row in rows:
        ts = int(row["ts"])
        b = align_ts(ts, tf_sec)
        item = buckets.get(b)
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        v = float(row["volume"]) if row["volume"] is not None else 0.0

        if item is None:
            buckets[b] = {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "count": 1.0,
            }
            continue
        item["high"] = max(item["high"], h)
        item["low"] = min(item["low"], l)
        item["close"] = c
        item["volume"] += v
        item["count"] += 1.0

    full_rows: list[tuple[int, float, float, float, float, float]] = []
    for bucket_ts in sorted(buckets.keys()):
        item = buckets[bucket_ts]
        if int(item["count"]) != expected:
            continue
        full_rows.append(
            (
                int(bucket_ts),
                float(item["open"]),
                float(item["high"]),
                float(item["low"]),
                float(item["close"]),
                float(item["volume"]),
            )
        )

    return upsert_rows(conn, tf, full_rows)


def collect_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT timeframe, COUNT(*) AS cnt, MIN(ts) AS min_ts, MAX(ts) AS max_ts
        FROM candles
        GROUP BY timeframe
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        min_ts = int(r["min_ts"]) if r["min_ts"] is not None else None
        max_ts = int(r["max_ts"]) if r["max_ts"] is not None else None
        out.append(
            {
                "timeframe": str(r["timeframe"]),
                "rows": int(r["cnt"]),
                "min_ts": min_ts,
                "max_ts": max_ts,
                "min_utc": iso_utc(min_ts) if min_ts else None,
                "max_utc": iso_utc(max_ts) if max_ts else None,
                "age_sec": (now_ts() - max_ts) if max_ts else None,
            }
        )
    order = {"1m": 1, "5m": 2, "15m": 3, "30m": 4, "60m": 5, "180m": 6, "1D": 7}
    out.sort(key=lambda x: (order.get(x["timeframe"], 999), x["timeframe"]))
    return out


def latest_1m_row(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM candles
        WHERE timeframe='1m'
        ORDER BY ts DESC
        LIMIT 1
        """
    ).fetchone()


def print_summary(title: str, rows: list[dict[str, Any]]) -> None:
    print(title)
    if not rows:
        print("  (no rows)")
        return
    for item in rows:
        age = item["age_sec"]
        age_text = "-" if age is None else str(int(age))
        print(
            f"  {item['timeframe']:>4} rows={item['rows']:>8} "
            f"min={item['min_utc'] or '-'} max={item['max_utc'] or '-'} age_sec={age_text}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync OKX candles into wonyodd sqlite DB.")
    parser.add_argument("--db-path", type=str, default=os.getenv("WONYODD_DB_PATH", "/opt/wonyodd-reco/data/wonyodd.sqlite3"))
    parser.add_argument("--inst-id", type=str, default="BTC-USDT.P")
    parser.add_argument("--sync-minutes", type=int, default=240, help="Sync latest N minutes into 1m")
    parser.add_argument("--backfill-days", type=int, default=0, help="Backfill 1m for N days (0 disables)")
    parser.add_argument("--day-sync-count", type=int, default=365, help="Sync latest N daily candles into 1D")
    parser.add_argument("--day-bar", type=str, default="1Dutc", help="OKX daily bar type, e.g. 1Dutc or 1D")
    parser.add_argument("--max-pages", type=int, default=0, help="Cap minute-sync pages (0 = unlimited)")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--pause-sec", type=float, default=0.05)
    parser.add_argument("--no-resample", action="store_true", help="Do not rebuild 30m/60m/180m from 1m")
    parser.add_argument("--reset-core-timeframes", action="store_true", help="Delete 1m/30m/60m/180m/1D before sync")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--summary-json", type=str, default="")
    parser.add_argument("--emit-webhook-url", type=str, default="http://127.0.0.1:8010/api/webhook/tradingview")
    parser.add_argument("--emit-webhook-timeout", type=int, default=8)
    parser.add_argument("--emit-webhook-secret", type=str, default=os.getenv("WONYODD_WEBHOOK_SECRET", ""))
    parser.add_argument("--no-emit-webhook", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if db_path.parent and not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        before = collect_summary(conn)
        print_summary("[before]", before)

        if args.report_only:
            return 0

        if args.reset_core_timeframes:
            deleted = reset_core_timeframes(conn)
            print(f"[reset] deleted_rows={deleted} timeframes={','.join(CORE_TIMEFRAMES)}")

        inst_id = normalize_okx_inst_id(args.inst_id)

        minute_rows, min_ts, max_ts = sync_minutes(
            conn,
            inst_id,
            lookback_minutes=max(1, args.sync_minutes),
            backfill_days=max(0, args.backfill_days),
            timeout=max(1, args.timeout),
            retries=max(0, args.retries),
            request_pause=max(0.0, args.pause_sec),
            max_pages=max(0, args.max_pages),
        )
        print(f"[sync] 1m rows_upserted={minute_rows} inst_id={inst_id}")

        day_rows = sync_days(
            conn,
            inst_id,
            day_count=max(0, args.day_sync_count),
            day_bar=str(args.day_bar or "1Dutc"),
            timeout=max(1, args.timeout),
            retries=max(0, args.retries),
            request_pause=max(0.0, args.pause_sec),
        )
        print(f"[sync] 1D rows_upserted={day_rows} inst_id={inst_id} bar={args.day_bar}")

        rebuilt: dict[str, int] = {}
        if not args.no_resample and min_ts is not None and max_ts is not None:
            start = max(0, min_ts - 10800 * 2)
            end = max_ts
            for tf in ("30m", "60m", "180m"):
                cnt = resample_tf_from_1m(conn, tf, start, end)
                rebuilt[tf] = cnt
                print(f"[sync] {tf} rows_upserted={cnt} from_1m_range={iso_utc(start)}~{iso_utc(end)}")

        emit_result: dict[str, Any] | None = None
        if not args.no_emit_webhook:
            row_1m = latest_1m_row(conn)
            if row_1m is not None:
                payload = {
                    "timeframe": "1",
                    "ts": int(row_1m["ts"]),
                    "open": float(row_1m["open"]),
                    "high": float(row_1m["high"]),
                    "low": float(row_1m["low"]),
                    "close": float(row_1m["close"]),
                    "volume": float(row_1m["volume"]) if row_1m["volume"] is not None else 0.0,
                    "bar_close_confirmed": True,
                }
                ok_emit, detail_emit = post_json(
                    str(args.emit_webhook_url),
                    payload,
                    timeout=max(1, int(args.emit_webhook_timeout)),
                    secret=str(args.emit_webhook_secret or ""),
                )
                emit_result = {"ok": bool(ok_emit), "detail": str(detail_emit), "ts": int(row_1m["ts"])}
                print(f"[emit] webhook_ok={ok_emit} detail={detail_emit}")
            else:
                emit_result = {"ok": False, "detail": "no_1m_data"}
                print("[emit] webhook_ok=False detail=no_1m_data")

        after = collect_summary(conn)
        print_summary("[after]", after)

        if args.summary_json:
            payload = {
                "db_path": str(db_path),
                "inst_id": inst_id,
                "synced_at": iso_utc(now_ts()),
                "upserted": {
                    "1m": minute_rows,
                    "1D": day_rows,
                    "rebuilt": rebuilt,
                },
                "emit_webhook": emit_result,
                "before": before,
                "after": after,
            }
            out = Path(args.summary_json)
            if out.parent and not out.parent.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[saved] {out}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
