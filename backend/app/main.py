from __future__ import annotations
import time
from pathlib import Path
import threading
import urllib.error
import urllib.request
from urllib.parse import urlencode
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dateutil import parser as dtparser

from .config import (
    WEBHOOK_SECRET,
    REQUIRE_BAR_CLOSE,
    VALIDATE_TS_ALIGNMENT,
    RESAMPLE_FROM_LOWER_TF,
    INCLUDE_PARTIAL_BARS,
    SPIKE_NOTIFY_ENABLED,
    SPIKE_NOTIFY_TFS,
    SPIKE_NOTIFY_SIDE,
    SPIKE_NOTIFY_ONLY_BAR_CLOSE,
    SPIKE_NOTIFY_ONLY_READY,
    SPIKE_NOTIFY_COOLDOWN_SEC,
    READY_NOTIFY_ENABLED,
    READY_NOTIFY_TFS,
    READY_NOTIFY_SIDE,
    READY_NOTIFY_ONLY_BAR_CLOSE,
    READY_NOTIFY_COOLDOWN_SEC,
    FORWARD_WEBHOOK_TIMEOUT_SEC,
    AUTO_TRADE_WEBHOOK_URL,
    WONYODD_FX_RATE_AUTO_FETCH_ENABLED,
    WONYODD_FX_RATE_BASE,
    WONYODD_FX_RATE_FETCH_HOST,
    WONYODD_FX_RATE_FETCH_INTERVAL_SEC,
    WONYODD_FX_RATE_FETCH_TIMEOUT_SEC,
    WONYODD_FX_RATE_QUOTE,
)
from . import db
from .models import WebhookPayload
from .recommend import recommend, tf_key, resolve_ready_rule
from .notify import build_discord_message, send_discord_webhook, send_forward_webhooks
from .alerts import detect_volume_volatility_spike
from .coupang_banner import build_banner_payload, normalize_interest_category, record_interest_category

import json

# Resolve project root (/opt/wonyodd-reco)
PROJECT_ROOT = Path("/opt/wonyodd-reco")
FRONTEND_DIR = PROJECT_ROOT / "frontend"
AUTO_TRADE_READY_TP = {
    "A": "tp2_price",
    "B": "tp2_price",
    "C": "tp1_price",
}

app = FastAPI(title="Wonyodd Reco Engine", version="1.0.0")
db.init_db()

def _to_trade_price(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)

def _get_usdkrw_fx_rate() -> Optional[float]:
    row = db.fetch_latest_fx_rate(WONYODD_FX_RATE_BASE, WONYODD_FX_RATE_QUOTE)
    if row is None:
        return None
    try:
        return float(row["rate"])
    except Exception:
        return None

def _fetch_fx_rate_from_frankfurter(base: str, quote: str) -> tuple[float, str, str]:
    base_u = str(base).upper()
    quote_u = str(quote).upper()
    params = urlencode({"base": base_u, "symbols": quote_u})
    host = WONYODD_FX_RATE_FETCH_HOST.rstrip("/")
    url = f"{host}/v1/latest?{params}"
    req = urllib.request.Request(
        url=url,
        headers={"User-Agent": "Mozilla/5.0 WonyoddRecoFX"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=max(1, WONYODD_FX_RATE_FETCH_TIMEOUT_SEC)) as resp:
        if resp.status != 200:
            body = resp.read(300).decode("utf-8", errors="replace")
            body = body.replace("\\n", " ")
            raise RuntimeError(f"frankfurter_status_{resp.status}:{body}")
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    rate = float(payload["rates"][quote_u])
    as_of_date = str(payload.get("date"))
    if not as_of_date:
        as_of_date = time.strftime("%Y-%m-%d", time.gmtime())
    return rate, as_of_date, url

def _refresh_fx_rate(base: str, quote: str) -> Optional[float]:
    try:
        rate, as_of_date, source = _fetch_fx_rate_from_frankfurter(base, quote)
        db.insert_fx_rate(base, quote, rate, as_of_date, source=source)
        print(f"[INFO] FX rate updated {base.upper()}->{quote.upper()} date={as_of_date} rate={rate}")
        return rate
    except Exception as e:
        print(f"[WARN] FX rate refresh failed: {type(e).__name__}: {e}")
        return None

def _resolve_usdkrw_fx_rate() -> Optional[float]:
    rate = _get_usdkrw_fx_rate()
    if rate is not None:
        return rate
    if not WONYODD_FX_RATE_AUTO_FETCH_ENABLED:
        return None
    return _refresh_fx_rate(WONYODD_FX_RATE_BASE, WONYODD_FX_RATE_QUOTE)

def _start_fx_rate_worker() -> None:
    if not WONYODD_FX_RATE_AUTO_FETCH_ENABLED:
        return
    interval = max(60, int(WONYODD_FX_RATE_FETCH_INTERVAL_SEC))
    while True:
        rate = _refresh_fx_rate(WONYODD_FX_RATE_BASE, WONYODD_FX_RATE_QUOTE)
        if rate is not None:
            sent = _flush_pending_upbit_webhooks(rate)
            if sent:
                print(f"[INFO] Pending upbit auto-trade webhook flushed: count={sent}")
        time.sleep(interval)

threading.Thread(target=_start_fx_rate_worker, daemon=True).start()

def _auto_trade_order_sides(side: str) -> tuple[str, str, str, str]:
    s = str(side or "").strip().lower()
    if s == "long":
        return "entry/buy", "close/sell", "롱OKX", "롱마감OKX"
    if s == "short":
        return "entry/sell", "close/buy", "숏OKX", "숏마감OKX"
    raise ValueError("side must be long or short")

def _build_auto_trade_payloads(rec: Dict[str, Any], fx_rate: Optional[float] = None) -> list[Dict[str, Any]]:
    plan = rec.get("plan") or {}
    selected = rec.get("selected") or {}
    try:
        side = str(plan.get("side") or rec.get("side") or "").strip().lower()
    except Exception:
        side = ""
    if side not in ("long", "short"):
        return []

    rule = str(selected.get("ready_rule", plan.get("ready_rule", ""))).strip().upper()
    tp_key = AUTO_TRADE_READY_TP.get(rule)
    if tp_key is None:
        return []

    entry_price = plan.get("entry_price")
    tp_price = plan.get(tp_key)
    if entry_price is None or tp_price is None:
        return []

    entry_side, close_side, entry_name, close_name = _auto_trade_order_sides(side)
    common = {
        "password": "dldnjsgud",
        "exchange": "OKX",
        "base": "BTC",
        "quote": "USDT.P",
        "type": "limit",
        "amount": "0.01",
        "percent": "NaN",
        "leverage": "50",
        "margin_mode": "cross",
    }
    payloads = [
        {
            **common,
            "side": entry_side,
            "price": _to_trade_price(entry_price),
            "order_name": entry_name,
        },
        {
            **common,
            "side": close_side,
            "price": _to_trade_price(tp_price),
            "order_name": close_name,
        },
    ]

    if fx_rate is not None:
        payloads.extend(_build_upbit_auto_trade_payloads(side, entry_price, tp_price, fx_rate))
    return payloads

def _build_upbit_auto_trade_payloads(
    side: str,
    entry_price: Any,
    tp_price: Any,
    fx_rate: float,
) -> list[Dict[str, Any]]:
    try:
        entry_krw = _to_trade_price(float(entry_price) * float(fx_rate))
        tp_krw = _to_trade_price(float(tp_price) * float(fx_rate))
    except Exception:
        return []

    return [
        {
            "password": "dldnjsgud",
            "exchange": "UPBIT",
            "base": "BTC",
            "quote": "KRW",
            "side": "buy",
            "type": "limit",
            "amount": "NaN",
            "price": entry_krw,
            "percent": "95",
            "order_name": "업비트 풀매수",
        },
        {
            "password": "dldnjsgud",
            "exchange": "UPBIT",
            "base": "BTC",
            "quote": "KRW",
            "side": "sell",
            "type": "limit",
            "amount": "NaN",
            "price": tp_krw,
            "percent": "100",
            "order_name": "업비트 풀매도",
        },
    ]

def _send_auto_trade_webhook(payload: Dict[str, Any]) -> tuple[bool, str]:
    if not AUTO_TRADE_WEBHOOK_URL:
        return False, "auto_trade_webhook_missing"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=AUTO_TRADE_WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 WonyoddRecoAutoTrade",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_WEBHOOK_TIMEOUT_SEC) as resp:
            if 200 <= resp.status < 300:
                return True, "sent"
            body = resp.read(300).decode("utf-8", errors="replace")
            if body:
                body = body.replace("\n", "\\n")
                return False, f"http_{resp.status}:{body}"
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(300).decode("utf-8", errors="replace")
        except Exception:
            pass
        if body:
            return False, "http_{}:{}".format(e.code, body.replace("\n", "\\n"))
        return False, f"http_{e.code}"
    except Exception as e:
        return False, f"request_error:{type(e).__name__}:{e}"

def _enqueue_pending_upbit_trade(rec: Dict[str, Any]) -> bool:
    plan = rec.get("plan") or {}
    selected = rec.get("selected") or {}
    try:
        side = str(plan.get("side") or rec.get("side") or "").strip().lower()
    except Exception:
        side = ""
    if side not in ("long", "short"):
        return False

    rule = str(selected.get("ready_rule", plan.get("ready_rule", ""))).strip().upper()
    tp_key = AUTO_TRADE_READY_TP.get(rule)
    if tp_key is None:
        return False

    entry_price = plan.get("entry_price")
    tp_price = plan.get(tp_key)
    if entry_price is None or tp_price is None:
        return False

    try:
        db.insert_pending_upbit_auto_trade(side=side, entry_price=float(entry_price), tp_price=float(tp_price))
        print(f"[INFO] Upbit retry queued: side={side}, entry={entry_price}, tp={tp_price}")
        return True
    except Exception as e:
        print(f"[WARN] Upbit queue insert failed: {type(e).__name__}:{e}")
        return False

def _flush_pending_upbit_webhooks(fx_rate: Optional[float] = None) -> int:
    if fx_rate is None:
        fx_rate = _resolve_usdkrw_fx_rate()
    if fx_rate is None:
        return 0

    sent_count = 0
    pending_rows = db.fetch_pending_upbit_auto_trades(limit=100)
    if not pending_rows:
        return 0

    for row in pending_rows:
        pid = int(row["id"])
        side = str(row["side"])
        entry = row["entry_price"]
        tp = row["tp_price"]
        upbit_payloads = _build_upbit_auto_trade_payloads(side, entry, tp, fx_rate)
        if not upbit_payloads:
            db.bump_pending_upbit_auto_trade(pid, "invalid_price")
            continue

        results = []
        all_ok = True
        for payload in upbit_payloads:
            ok, detail = _send_auto_trade_webhook(payload)
            results.append((payload.get("order_name"), ok, detail))
            all_ok = all_ok and ok
            print(
                "[DEBUG] Pending upbit auto-trade webhook: "
                + json.dumps({"id": pid, "order_name": payload.get("order_name"), "ok": ok, "detail": detail}, ensure_ascii=False)
            )
        if all_ok:
            db.delete_pending_upbit_auto_trade(pid)
            sent_count += 1
            print(f"[INFO] Pending upbit auto-trade webhook sent and removed: id={pid}, side={side}")
        else:
            last = ",".join([str(x[2]) for x in results if x[1] is False][-1:] or ["unknown"])
            db.bump_pending_upbit_auto_trade(pid, last)
    return sent_count

def _parse_tf_list(s: str) -> set[str]:
    out: set[str] = set()
    for part in str(s or "").split(","):
        part = part.strip()
        if not part:
            continue
        k = tf_key(part)
        out.add(k or part)
    return out

def _choose_auto_side(rec_long: dict, rec_short: dict) -> str:
    ok_l = bool(rec_long.get("ok"))
    ok_s = bool(rec_short.get("ok"))
    if ok_l and not ok_s:
        return "long"
    if ok_s and not ok_l:
        return "short"
    if not ok_l and not ok_s:
        return "long"

    sel_l = rec_long.get("selected") or {}
    sel_s = rec_short.get("selected") or {}
    status_l = sel_l.get("status")
    status_s = sel_s.get("status")
    if status_l == "ready" and status_s != "ready":
        return "long"
    if status_s == "ready" and status_l != "ready":
        return "short"

    try:
        score_l = float(sel_l.get("composite_score") or 0.0)
    except Exception:
        score_l = 0.0
    try:
        score_s = float(sel_s.get("composite_score") or 0.0)
    except Exception:
        score_s = 0.0
    if score_l > score_s:
        return "long"
    if score_s > score_l:
        return "short"

    bias = (rec_long.get("regime") or {}).get("bias") or (rec_short.get("regime") or {}).get("bias")
    if bias == "short_favored":
        return "short"
    return "long"

def _maybe_notify_spike(
    tf: str,
    ts: int,
    payload: WebhookPayload,
    *,
    force_bar_close: bool = False,
    ignore_tf_filter: bool = False,
) -> None:
    if not SPIKE_NOTIFY_ENABLED:
        return

    enabled_tfs = _parse_tf_list(SPIKE_NOTIFY_TFS)
    if enabled_tfs and tf not in enabled_tfs and not ignore_tf_filter:
        return

    if SPIKE_NOTIFY_ONLY_BAR_CLOSE and not (force_bar_close or _is_bar_close(payload)):
        return

    ctx = detect_volume_volatility_spike(tf, ts)
    if not ctx:
        return

    # Add symbol context if present
    if payload.symbol:
        ctx["symbol"] = payload.symbol
    if payload.exchange:
        ctx["exchange"] = payload.exchange

    side_mode = str(SPIKE_NOTIFY_SIDE or "auto").strip().lower()
    recs = []
    if side_mode in ("long", "short"):
        recs.append(recommend(side=side_mode))
    elif side_mode == "both":
        recs.append(recommend(side="long"))
        recs.append(recommend(side="short"))
    else:
        rec_long = recommend(side="long")
        rec_short = recommend(side="short")
        side = _choose_auto_side(rec_long, rec_short)
        recs.append(rec_long if side == "long" else rec_short)

    now = int(time.time())
    for rec in recs:
        if not rec or not rec.get("ok"):
            print("[WARN] Spike notify: recommend failed")
            continue

        plan = rec.get("plan") or {}
        side = str(plan.get("side") or "").lower() or str(rec.get("side") or "").lower() or "auto"
        kind = f"{ctx.get('kind', 'spike')}:{side}"

        if db.notification_exists(kind, tf, ts):
            continue

        last = db.fetch_latest_notification(kind)
        if last:
            try:
                last_created = int(last["created_ts"])
                if int(SPIKE_NOTIFY_COOLDOWN_SEC) > 0 and (now - last_created) < int(SPIKE_NOTIFY_COOLDOWN_SEC):
                    print("[DEBUG] Spike notify skipped (cooldown)")
                    continue
            except Exception:
                pass

        if SPIKE_NOTIFY_ONLY_READY and (rec.get("selected") or {}).get("status") != "ready":
            print("[DEBUG] Spike notify skipped (status!=ready)")
            continue

        # Spike-only policy: keep server-side logging, but do not send Discord messages.
        inserted = db.insert_notification(
            kind,
            tf,
            ts,
            created_ts=now,
            detail=json.dumps(
                {"ctx": ctx, "detail": "logged_only_no_discord"},
                ensure_ascii=False,
            ),
        )
        forward_results = send_forward_webhooks({
            "event": "spike",
            "kind": kind,
            "timeframe": tf,
            "ts": ts,
            "created_ts": now,
            "recommend": rec,
            "context": ctx,
            "db_logged": inserted,
        })
        if forward_results:
            print(
                "[DEBUG] Spike forward webhooks: "
                + json.dumps([(u, ok, d) for u, ok, d in forward_results], ensure_ascii=False)
            )
        print(f"[DEBUG] Spike notify logged only: inserted={inserted}")

def _maybe_notify_ready(tf: str, ts: int, payload: WebhookPayload, *, force_bar_close: bool = False) -> None:
    if not READY_NOTIFY_ENABLED:
        return

    enabled_tfs = _parse_tf_list(READY_NOTIFY_TFS)
    if enabled_tfs and tf not in enabled_tfs:
        return

    if READY_NOTIFY_ONLY_BAR_CLOSE and not (force_bar_close or _is_bar_close(payload)):
        return

    side_mode = str(READY_NOTIFY_SIDE or "both").strip().lower()
    recs: list[tuple[str, dict]] = []
    if side_mode in ("long", "short"):
        recs.append((side_mode, recommend(side=side_mode, focus_tf=tf)))
    elif side_mode == "both":
        recs.append(("long", recommend(side="long", focus_tf=tf)))
        recs.append(("short", recommend(side="short", focus_tf=tf)))
    else:
        rec_long = recommend(side="long", focus_tf=tf)
        rec_short = recommend(side="short", focus_tf=tf)
        side = _choose_auto_side(rec_long, rec_short)
        recs.append((side, rec_long if side == "long" else rec_short))

    now = int(time.time())
    ctx = {"kind": "ready", "timeframe": tf, "ts": int(ts)}
    for side, rec in recs:
        if not rec or not rec.get("ok"):
            continue
        if (rec.get("selected") or {}).get("status") != "ready":
            continue

        kind = f"ready:{tf}:{side}"
        if db.notification_exists(kind, tf, ts):
            continue

        last = db.fetch_latest_notification(kind)
        if last:
            try:
                last_created = int(last["created_ts"])
                if int(READY_NOTIFY_COOLDOWN_SEC) > 0 and (now - last_created) < int(READY_NOTIFY_COOLDOWN_SEC):
                    print("[DEBUG] Ready notify skipped (cooldown)")
                    continue
            except Exception:
                pass

        msg = build_discord_message(rec, context=ctx, content=_ready_notify_content(rec))
        ok, detail = send_discord_webhook(msg)
        print(f"[DEBUG] Ready notify: ok={ok} detail={detail}")
        auto_trade_results = []
        if ok:
            fx_rate = _resolve_usdkrw_fx_rate()
            if fx_rate is None:
                queued = _enqueue_pending_upbit_trade(rec)
                print(f"[WARN] USD/KRW 환율이 없어 업비트 풀매수/풀매도 전송을 생략합니다. queued={queued}")
                if queued:
                    auto_trade_results.append(("upbit", "queued", True, "queued"))
            for payload in _build_auto_trade_payloads(rec, fx_rate=fx_rate):
                ok2, detail2 = _send_auto_trade_webhook(payload)
                auto_trade_results.append((payload.get("side"), payload.get("order_name"), ok2, detail2))
                print(
                    "[DEBUG] Ready auto-trade webhook: "
                    + json.dumps({"side": payload.get("side"), "order_name": payload.get("order_name"), "ok": ok2, "detail": detail2},
                                 ensure_ascii=False)
                )
        forward_results = send_forward_webhooks({
            "event": "ready",
            "kind": kind,
            "timeframe": tf,
            "ts": ts,
            "created_ts": now,
            "recommend": rec,
            "context": ctx,
            "discord": {"ok": ok, "detail": detail},
            "auto_trade": {"ok": bool(auto_trade_results), "details": auto_trade_results},
        })
        if forward_results:
            print(
                "[DEBUG] Ready forward webhooks: "
                + json.dumps([(u, ok2, d) for u, ok2, d in forward_results], ensure_ascii=False)
            )
        if ok:
            db.insert_notification(
                kind,
                tf,
                ts,
                created_ts=now,
                detail=json.dumps(
                    {
                        "ctx": ctx,
                        "detail": detail,
                        "auto_trade": auto_trade_results,
                    },
                    ensure_ascii=False,
                ),
            )

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

def _ready_notify_content(rec: dict) -> str:
    selected = (rec or {}).get("selected") or {}
    plan = (rec or {}).get("plan") or {}
    rule = selected.get("ready_rule", plan.get("ready_rule"))
    rule_norm = str(rule).strip().upper() if rule else ""
    if rule_norm not in ("A", "B", "C", "D"):
        rule_norm = "-"

    sma_distance_pct = selected.get("sma_distance_pct")
    atr_pct = selected.get("atr_pct")
    if sma_distance_pct is not None and atr_pct is not None:
        resolved_rule, resolved_mdd = resolve_ready_rule(sma_distance_pct, atr_pct)
        if resolved_rule in ("A", "B", "C", "D"):
            rule_norm = resolved_rule
            plan["ready_rule"] = resolved_rule
            selected["ready_rule"] = resolved_rule
            if resolved_mdd is not None:
                plan["ready_rule_mdd_pct"] = resolved_mdd
                selected["ready_rule_mdd_pct"] = resolved_mdd

    if rule_norm in ("A", "B", "C", "D"):
        return f"READY신호->추천({rule_norm})"
    return "READY신호->추천"

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

def _resample_from_lower_tf(tf: str, ts: int) -> list[tuple[str, int]]:
    if not RESAMPLE_FROM_LOWER_TF:
        return []
    if tf not in ("1m", "5m", "15m"):
        return []

    tf_sec_map = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "180m": 10800}
    src_sec = tf_sec_map[tf]
    targets = ("30m", "60m", "180m")

    resampled: list[tuple[str, int]] = []
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
        resampled.append((tgt, start_ts))
    return resampled

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
    resampled = _resample_from_lower_tf(tf, ts)
    try:
        is_1m = (tf == "1m")
        _maybe_notify_spike(
            tf,
            ts,
            payload,
            force_bar_close=is_1m,
            ignore_tf_filter=is_1m,
        )
    except Exception as e:
        print(f"[WARN] Spike notify error: {type(e).__name__}: {e}")
    try:
        _maybe_notify_ready(tf, ts, payload)
    except Exception as e:
        print(f"[WARN] Ready notify error: {type(e).__name__}: {e}")
    if resampled:
        for res_tf, res_ts in resampled:
            try:
                _maybe_notify_ready(res_tf, res_ts, payload, force_bar_close=True)
            except Exception as e:
                print(f"[WARN] Ready notify error (resampled {res_tf}): {type(e).__name__}: {e}")

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
def api_recommend(side: str, risk_pct: Optional[float] = None, tf: Optional[str] = None):
    try:
        out = recommend(side=side, risk_pct=risk_pct, focus_tf=tf)
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/notify/recommend")
def api_notify_recommend(side: str, risk_pct: Optional[float] = None, tf: Optional[str] = None):
    try:
        out = recommend(side=side, risk_pct=risk_pct, focus_tf=tf)
        content = "추천"
        if (out.get("selected") or {}).get("status") == "ready":
            content = _ready_notify_content(out)
        msg = build_discord_message(out, content=content)
        ok, detail = send_discord_webhook(msg)
        send_forward_webhooks({
            "event": "manual_recommend",
            "kind": "manual",
            "timeframe": out.get("plan", {}).get("tf", tf),
            "recommend": out,
            "discord": {"ok": ok, "detail": detail},
            "risk_pct": risk_pct,
        })
        return {"ok": ok, "detail": detail, "recommend": out}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/api/latest")
def latest():
    out = {}
    for tf in ("1m","5m","15m","1D","30m","60m","180m"):
        row = db.fetch_latest(tf)
        out[tf] = {"ts": int(row["ts"]), "close": float(row["close"])} if row else None
    return {"ok": True, "latest": out}

@app.get("/api/fx-rate")
def fx_rate():
    base = str(WONYODD_FX_RATE_BASE).upper()
    quote = str(WONYODD_FX_RATE_QUOTE).upper()
    row = db.fetch_latest_fx_rate(base, quote)
    if row is None:
        return {"ok": False, "base": base, "quote": quote, "rate": None}
    return {
        "ok": True,
        "base": base,
        "quote": quote,
        "rate": float(row["rate"]),
        "as_of_date": row["as_of_date"],
        "fetched_ts": int(row["fetched_ts"]),
        "source": row["source"],
    }

@app.get("/api/coupang-banner")
def coupang_banner(keyword: Optional[str] = None, category: Optional[str] = None, limit: int = 3):
    try:
        payload = build_banner_payload(
            keyword_override=keyword,
            category_override=category,
            limit=limit,
        )
        return JSONResponse(payload)
    except Exception:
        return JSONResponse({"message": "배너를 불러오지 못했습니다."}, status_code=500)

@app.post("/api/ad-interest")
async def ad_interest(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"message": "잘못된 요청입니다."}, status_code=400)

    category = normalize_interest_category((body or {}).get("category"))
    if not category:
        return JSONResponse({"message": "잘못된 카테고리입니다."}, status_code=400)

    try:
        record_interest_category(category)
        return {"success": True}
    except Exception:
        return {"success": False}

# Serve frontend (static) AFTER API routes so /api/* wins.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
