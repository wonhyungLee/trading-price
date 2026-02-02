from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dateutil import parser as dtparser

from .config import WEBHOOK_SECRET, REQUIRE_BAR_CLOSE, VALIDATE_TS_ALIGNMENT, RESAMPLE_FROM_LOWER_TF, INCLUDE_PARTIAL_BARS
from . import db
from .models import WebhookPayload
from .recommend import recommend, tf_key
from .notify import build_discord_message, send_discord_webhook

# Resolve project root (/opt/wonyodd-reco)
PROJECT_ROOT = Path("/opt/wonyodd-reco")
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(title="Wonyodd Reco Engine", version="1.0.0")
db.init_db()

def _parse_ts(payload: WebhookPayload) -> int:
    # 1. ts field
    if payload.ts is not None:
        val = int(payload.ts)
    # 2. time field
    elif payload.time is not None:
        if isinstance(payload.time, (int, float)):
            val = int(payload.time)
        else:
            try:
                val = int(payload.time)
            except ValueError:
                dt = dtparser.parse(str(payload.time))
                return int(dt.timestamp())
    else:
        return int(time.time())

    # Milliseconds check (13 digits) -> Seconds (10 digits)
    if val > 10_000_000_000:
        val //= 1000
    return val

def _auth_ok(payload: WebhookPayload, header_secret: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    if header_secret and header_secret == WEBHOOK_SECRET:
        return True
    if payload.password and payload.password == WEBHOOK_SECRET:
        return True
    return False

def _is_bar_close(payload: WebhookPayload) -> bool:
    if payload.bar_close_confirmed is True:
        return True
    if payload.bar_close is True:
        return True
    if payload.is_bar_close is True:
        return True
    if payload.barstate:
        s = str(payload.barstate).strip().lower()
        if s in ("closed", "close", "bar_close", "confirmed", "final"):
            return True
    return False

def _is_ts_aligned(ts: int, tf: str) -> bool:
    # Accept alignment to bar open OR bar close.
    # e.g. 30m bar: ts % 1800 == 0 (open) or (ts + 1800) % 1800 == 0 (close).
    tf_sec = {
        "30m": 30 * 60,
        "60m": 60 * 60,
        "180m": 180 * 60,
        "1D": 24 * 60 * 60,
    }.get(tf)
    if not tf_sec:
        return True
    return (ts % tf_sec == 0) or ((ts + tf_sec) % tf_sec == 0)

def _resample_from_lower_tf(tf: str, ts: int) -> None:
    if not RESAMPLE_FROM_LOWER_TF:
        return
    if tf not in ("1m", "5m", "15m"):
        return

    tf_sec_map = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "180m": 10800}
    src_sec = tf_sec_map[tf]
    targets = ("30m", "60m", "180m")

    for tgt in targets:
        tgt_sec = tf_sec_map[tgt]
        if tgt_sec % src_sec != 0:
            continue
        # Use bar-open timestamps. A lower-tf bar at ts is the last bar of target
        # if its close time aligns with target close.
        if (ts + src_sec) % tgt_sec != 0:
            continue
        start_ts = ts + src_sec - tgt_sec
        rows = db.fetch_range(tf, start_ts, ts)
        expected = tgt_sec // src_sec
        if len(rows) < expected:
            print(f"[WARN] Not enough {tf} bars to resample {tgt}: {len(rows)}/{expected}")
            continue

        o = float(rows[0]["open"])
        h = max(float(r["high"]) for r in rows)
        l = min(float(r["low"]) for r in rows)
        c = float(rows[-1]["close"])
        v = sum(float(r["volume"] or 0.0) for r in rows)

        db.upsert_candle(tgt, start_ts, o, h, l, c, v, features=None)
        print(f"[DEBUG] Resampled {tgt} @ {start_ts} from {tf} ({len(rows)} bars)")

def _partial_candle_from_1m(tf_norm: str) -> Optional[dict]:
    if not INCLUDE_PARTIAL_BARS:
        return None
    if tf_norm not in ("30m", "60m", "180m"):
        return None
    latest_1m = db.fetch_latest("1m")
    if not latest_1m:
        return None

    tf_sec = {"30m": 1800, "60m": 3600, "180m": 10800}[tf_norm]
    latest_ts = int(latest_1m["ts"])
    bucket_start = latest_ts - (latest_ts % tf_sec)

    last_closed = db.fetch_latest(tf_norm)
    last_closed_ts = int(last_closed["ts"]) if last_closed else -1
    if bucket_start <= last_closed_ts:
        return None

    rows = db.fetch_range("1m", bucket_start, latest_ts)
    if not rows:
        return None

    o = float(rows[0]["open"])
    h = max(float(r["high"]) for r in rows)
    l = min(float(r["low"]) for r in rows)
    c = float(rows[-1]["close"])
    v = sum(float(r["volume"] or 0.0) for r in rows)
    return {
        "ts": int(bucket_start),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "is_partial": True,
    }

@app.post("/order")
@app.post("/api/webhook/tradingview")
async def tradingview_webhook(req: Request):
    try:
        data = await req.json()
        payload = WebhookPayload.model_validate(data)
    except Exception as e:
        print(f"[DEBUG] Payload Error: {e}")
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}")

    header_secret = req.headers.get("X-Webhook-Secret", "")
    if not _auth_ok(payload, header_secret):
        raise HTTPException(status_code=401, detail="unauthorized")

    tf = tf_key(payload.timeframe)
    if tf is None:
        raise HTTPException(status_code=400, detail="unsupported timeframe; use 30,60,180,1D")

    ts = _parse_ts(payload)
    if REQUIRE_BAR_CLOSE and not _is_bar_close(payload):
        raise HTTPException(status_code=400, detail="bar_close_confirmed required")
    if VALIDATE_TS_ALIGNMENT and not _is_ts_aligned(ts, tf):
        raise HTTPException(status_code=400, detail="timestamp not aligned to timeframe")
    print(f"[DEBUG] Upserting: tf={tf}, ts={ts}, price={payload.close}")
    db.upsert_candle(
        tf, ts,
        float(payload.open), float(payload.high), float(payload.low), float(payload.close),
        float(payload.volume) if payload.volume is not None else None,
        features=payload.features,
    )
    _resample_from_lower_tf(tf, ts)

    return {"ok": True, "timeframe": tf, "ts": ts}

@app.get("/api/candles")
def candles(tf: str, limit: int = 200):
    """Return recent candles for charting."""
    tf_norm = tf_key(tf) or str(tf).strip()
    if tf_norm not in ("1D", "30m", "60m", "180m"):
        raise HTTPException(status_code=400, detail="unsupported timeframe; use 30,60,180,1D")
    
    rows = db.fetch_recent(tf_norm, limit)
    data = []
    for r in rows:
        data.append({
            "ts": int(r["ts"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]) if r["volume"] else 0.0
        })
    partial = _partial_candle_from_1m(tf_norm)
    if partial:
        data.append(partial)
    return {"ok": True, "timeframe": tf_norm, "data": data}

@app.get("/api/recommend")
def api_recommend(side: str, risk_pct: Optional[float] = None):
    try:
        out = recommend(side=side, risk_pct=risk_pct)
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/notify/recommend")
def api_notify_recommend(side: str, risk_pct: Optional[float] = None):
    try:
        out = recommend(side=side, risk_pct=risk_pct)
        msg = build_discord_message(out)
        ok, detail = send_discord_webhook(msg)
        return {"ok": ok, "detail": detail, "recommend": out}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/api/latest")
def latest():
    out = {}
    for tf in ("1D","30m","60m","180m"):
        row = db.fetch_latest(tf)
        out[tf] = {"ts": int(row["ts"]), "close": float(row["close"])} if row else None
    return {"ok": True, "latest": out}

# Serve frontend (static) AFTER API routes so /api/* wins.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
