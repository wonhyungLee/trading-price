from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import DISCORD_WEBHOOK_URL, DISCORD_WEBHOOK_FILE

TRADING_SITE_URL = "http://trading.p-e.kr"

def _read_webhook_from_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("https://discord.com/api/webhooks/"):
            return s.split()[0]
    # fallback: regex search in entire file
    m = re.search(r"https://discord\\.com/api/webhooks/\\S+", text)
    if m:
        return m.group(0).split()[0]
    return None

def get_discord_webhook_url() -> Optional[str]:
    if DISCORD_WEBHOOK_URL:
        return DISCORD_WEBHOOK_URL.strip()
    if DISCORD_WEBHOOK_FILE:
        p = Path(DISCORD_WEBHOOK_FILE)
        candidates = []
        if p.is_absolute():
            candidates.append(p)
        else:
            # 1) CWD
            candidates.append(Path.cwd() / p)
            # 2) Project root (backend/..)
            project_root = Path(__file__).resolve().parents[2]
            candidates.append(project_root / p)
            # 3) One level above project root (often where secrets live)
            candidates.append(project_root.parent / p)
        for cand in candidates:
            url = _read_webhook_from_file(cand)
            if url:
                return url
    return None

def _fmt_num(x: Any, digits: int = 2) -> str:
    try:
        n = float(x)
        if digits <= 0:
            return f"{n:,.0f}"
        return f"{n:,.{digits}f}"
    except Exception:
        return str(x)

def _append_site_link(content: Optional[str]) -> str:
    base = (content or "").strip()
    if TRADING_SITE_URL in base:
        return base
    if not base:
        return TRADING_SITE_URL
    return f"{base}\n{TRADING_SITE_URL}"

def build_discord_message(
    rec: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    plan = rec.get("plan") or {}
    regime = rec.get("regime") or {}
    selected = rec.get("selected") or {}
    notes = rec.get("notes") or []

    title = f"[{plan.get('side', '').upper()}] {plan.get('tf', '-')}"
    status = selected.get("status", "wait").upper()
    conf = selected.get("confidence")
    atr_pct = selected.get("atr_pct")

    fields = [
        {"name": "Status", "value": f"{status} / conf {conf if conf is not None else '-'}", "inline": True},
        {"name": "ATR%", "value": f"{atr_pct if atr_pct is not None else '-'}", "inline": True},
        {"name": "Entry", "value": f"{plan.get('entry_price', '-')}", "inline": True},
        {"name": "Stop", "value": f"{plan.get('stop_price', '-')}", "inline": True},
        {"name": "TP1", "value": f"{plan.get('tp1_price', '-')}", "inline": True},
        {"name": "TP2/TP3", "value": f"{plan.get('tp2_price', '-')}/{plan.get('tp3_price', '-')}", "inline": True},
        {"name": "Max Lev", "value": f"{plan.get('max_leverage_by_risk', '-') }x", "inline": True},
        {"name": "R:R", "value": f"{plan.get('reward_risk_to_tp1', '-')}", "inline": True},
    ]

    if context:
        lines = []
        try:
            ts = int(context.get("ts") or 0)
            if ts > 0:
                tf = context.get("timeframe") or "-"
                t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"Bar: {tf} @ {t}")
        except Exception:
            pass

        if context.get("volume") is not None and context.get("volume_base") is not None:
            lines.append(
                f"Volume: {_fmt_num(context.get('volume'), 0)} (base {_fmt_num(context.get('volume_base'), 0)}, x{context.get('volume_ratio', '-')})"
            )
        if context.get("range_pct") is not None and context.get("range_base") is not None:
            lines.append(
                f"Range: {_fmt_num(context.get('range_pct'), 3)}% (base {_fmt_num(context.get('range_base'), 3)}%, x{context.get('range_ratio', '-')})"
            )

        if lines:
            fields.insert(0, {"name": "Trigger", "value": "\n".join(lines), "inline": False})
        if content is None:
            content = "스파이크 감지 → 추천 업데이트"

    if regime.get("bias"):
        fields.append({"name": "Regime", "value": f"{regime.get('bias')} (conf {regime.get('confidence')})", "inline": False})

    if notes:
        fields.append({"name": "Notes", "value": "\n".join([f"- {n}" for n in notes]), "inline": False})

    embed = {
        "title": title,
        "color": 0x4B6BB5,
        "fields": fields,
    }
    if content is None:
        content = "추천 업데이트"
    content = _append_site_link(content)
    return {"content": content, "embeds": [embed]}

def send_discord_webhook(message: Dict[str, Any]) -> Tuple[bool, str]:
    url = get_discord_webhook_url()
    if not url:
        return False, "discord_webhook_missing"

    data = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 WonyoddReco",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if 200 <= resp.status < 300:
                return True, "sent"
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"http_{e.code}"
    except Exception as e:
        return False, f"error: {type(e).__name__}"
