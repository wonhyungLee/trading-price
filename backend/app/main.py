from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dateutil import parser as dtparser

from .config import WEBHOOK_SECRET
from . import db
from .models import WebhookPayload
from .recommend import recommend, tf_key

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
    print(f"[DEBUG] Upserting: tf={tf}, ts={ts}, price={payload.close}")
    db.upsert_candle(
        tf, ts,
        float(payload.open), float(payload.high), float(payload.low), float(payload.close),
        float(payload.volume) if payload.volume is not None else None,
        features=payload.features,
    )

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
    return {"ok": True, "timeframe": tf_norm, "data": data}

@app.get("/api/recommend")
def api_recommend(side: str, risk_pct: Optional[float] = None):
    try:
        out = recommend(side=side, risk_pct=risk_pct)
        return JSONResponse(out)
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
