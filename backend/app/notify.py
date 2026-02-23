from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import math

from .config import DISCORD_WEBHOOK_URL, DISCORD_WEBHOOK_FILE
from .config import FORWARD_WEBHOOK_TIMEOUT_SEC, FORWARD_WEBHOOK_URLS
from .recommend import resolve_ready_rule

TRADING_SITE_URL = "https://aicoincenter.store"
READY_TP_RECOMMENDATION = {
    "A": "TP2",
    "B": "TP2",
    "C": "TP1",
    "D": "TP1",
    "S": "TP1",
}
NO_STOP_RULES = {"A", "B", "C", "S"}


def _recommended_tp_by_rule(rule: str) -> str:
    return READY_TP_RECOMMENDATION.get(rule.upper(), "-")


def _is_no_stop_rule(rule: Any) -> bool:
    return str(rule).strip().upper() in NO_STOP_RULES


def _format_leverage(value: Any) -> str:
    try:
        n = float(value)
    except Exception:
        return str(value) if value is not None else "-"
    if math.isfinite(n):
        return f"{n:.2f}"
    return str(value)


def _format_tp_value(value: Any, is_recommended: bool) -> str:
    text = str(value)
    if value in (None, ""):
        return "-"
    return f"{text} (추천)" if is_recommended else text


def _format_tp_pair(tp2_value: Any, tp3_value: Any, target: str) -> str:
    tp2_txt = _format_tp_value(tp2_value, target == "TP2")
    tp3_txt = _format_tp_value(tp3_value, target == "TP3")
    return f"{tp2_txt}/{tp3_txt}"

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


def _normalized_ready_rule(selected: Dict[str, Any], plan: Dict[str, Any]) -> tuple[str, Optional[float]]:
    rule = selected.get("ready_rule", plan.get("ready_rule"))
    rule_norm = str(rule).strip().upper() if rule not in (None, "") else "-"
    if rule_norm == "S":
        return (
            rule_norm,
            selected.get("ready_rule_mdd_pct", plan.get("ready_rule_mdd_pct")),
        )
    if rule_norm not in ("A", "B", "C", "D"):
        rule_norm = "-"

    sma_distance_pct = selected.get("sma_distance_pct")
    atr_pct = selected.get("atr_pct")
    if sma_distance_pct is not None and atr_pct is not None:
        resolved_rule, resolved_mdd = resolve_ready_rule(sma_distance_pct, atr_pct)
        rule_norm = resolved_rule
        if resolved_mdd is not None:
            selected["ready_rule_mdd_pct"] = resolved_mdd
            plan["ready_rule_mdd_pct"] = resolved_mdd
            selected["ready_rule"] = resolved_rule
            plan["ready_rule"] = resolved_rule
    return (
        rule_norm,
        selected.get("ready_rule_mdd_pct", plan.get("ready_rule_mdd_pct")),
    )

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
    status = str(selected.get("status", "wait")).strip().upper()
    conf = selected.get("confidence")
    atr_pct = selected.get("atr_pct")
    rule_norm, rule_mdd = _normalized_ready_rule(selected, plan)
    rule_str = rule_norm if rule_norm != "-" else "-"
    rule_mdd_str = f"{rule_mdd}%" if rule_mdd is not None else "-"
    status_is_ready = str(status).upper() == "READY"
    plan_recommended_tp = str(plan.get("recommended_tp_key") or "").strip().upper()
    if status_is_ready:
        if plan_recommended_tp in ("TP1", "TP2", "TP3"):
            recommended_tp = plan_recommended_tp
        else:
            recommended_tp = _recommended_tp_by_rule(rule_norm)
    else:
        recommended_tp = "-"
    if recommended_tp == "-":
        recommended_tp = ""
    tp1_price = plan.get("tp1_price", "-")
    tp2_price = plan.get("tp2_price", "-")
    tp3_price = plan.get("tp3_price", "-")
    stop_text = plan.get("stop_price", "-")
    risk_lev = plan.get("max_leverage_by_risk", "-")
    mdd_lev = plan.get("max_leverage_by_mdd", risk_lev)
    is_no_stop_rule = _is_no_stop_rule(rule_norm)
    if status_is_ready and is_no_stop_rule:
        stop_text = f"No Stop ({rule_norm})"
    max_lev_for_field = (
        mdd_lev if is_no_stop_rule else plan.get("max_leverage_by_mdd", plan.get("max_leverage_by_risk", "-"))
    )

    fields = [
        {"name": "Status", "value": f"{status} / conf {conf if conf is not None else '-'}", "inline": True},
        {"name": "ATR%", "value": f"{atr_pct if atr_pct is not None else '-'}", "inline": True},
        {"name": "Rule", "value": rule_str, "inline": True},
        {"name": "Rule MDD", "value": rule_mdd_str, "inline": True},
        {"name": "Entry", "value": f"{plan.get('entry_price', '-')}", "inline": True},
        {"name": "Stop", "value": f"{stop_text}", "inline": True},
        {"name": "TP1", "value": _format_tp_value(tp1_price, recommended_tp == "TP1"), "inline": True},
        {"name": "TP2/TP3", "value": _format_tp_pair(tp2_price, tp3_price, recommended_tp), "inline": True},
        {"name": "Max Lev", "value": f"{_format_leverage(max_lev_for_field)}x", "inline": True},
        {"name": "Max Lev (Risk)", "value": f"{_format_leverage(risk_lev)}x", "inline": True},
        {"name": "R:R", "value": f"{plan.get('reward_risk_to_tp1', '-')}", "inline": True},
    ]

    if is_no_stop_rule and status_is_ready:
        fields.append(
            {
                "name": "Max Lev (No Stop)",
                "value": f"청산 방지 기준 {_format_leverage(mdd_lev)}x",
                "inline": True,
            }
        )

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

def _post_webhook(url: str, message: Dict[str, Any], *, timeout: int = 8) -> Tuple[bool, str]:
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            body = body.replace("\n", "\\n")
            return False, f"http_{e.code}:{body}"
        return False, f"http_{e.code}"
    except Exception as e:
        return False, f"error: {type(e).__name__}"

def _parse_forward_webhook_urls() -> list[str]:
    out: list[str] = []
    for raw in str(FORWARD_WEBHOOK_URLS or "").split(","):
        u = raw.strip()
        if u:
            out.append(u)
    return out

def send_forward_webhooks(message: Dict[str, Any]) -> list[tuple[str, bool, str]]:
    urls = _parse_forward_webhook_urls()
    if not urls:
        return []
    out: list[tuple[str, bool, str]] = []
    for url in urls:
        ok, detail = _post_webhook(url, message, timeout=FORWARD_WEBHOOK_TIMEOUT_SEC)
        out.append((url, ok, detail))
    return out

def send_discord_webhook(message: Dict[str, Any]) -> Tuple[bool, str]:
    url = get_discord_webhook_url()
    if not url:
        return False, "discord_webhook_missing"
    return _post_webhook(url, message, timeout=FORWARD_WEBHOOK_TIMEOUT_SEC)
