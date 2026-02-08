from __future__ import annotations

import datetime as dt
import hmac
import hashlib
import json
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import db
from .config import (
    COUPANG_ACCESS_KEY,
    COUPANG_SECRET_KEY,
    COUPANG_SUB_ID,
    COUPANG_BANNER_DEFAULT_CATEGORY,
    COUPANG_API_INFO_FILE,
)

VALID_INTEREST_CATEGORIES = {
    "daily",
    "card",
    "insurance",
    "health",
    "education",
    "housing",
    "pension",
    "donation",
    "finance",
}

DAILY_KEYWORDS: Tuple[str, ...] = (
    "휴지",
    "물티슈",
    "세탁세제",
    "주방세제",
    "샴푸",
    "린스",
    "치약",
    "칫솔",
    "생수",
    "라면",
    "쌀",
    "커피",
    "핸드워시",
    "주방랩",
    "키친타월",
)

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "daily": list(DAILY_KEYWORDS),
    "card": list(DAILY_KEYWORDS),
    "insurance": list(DAILY_KEYWORDS),
    "health": list(DAILY_KEYWORDS),
    "education": list(DAILY_KEYWORDS),
    "housing": list(DAILY_KEYWORDS),
    "pension": list(DAILY_KEYWORDS),
    "donation": list(DAILY_KEYWORDS),
    "finance": list(DAILY_KEYWORDS),
}

@dataclass(frozen=True)
class EventTheme:
    id: str
    name: str
    months: Tuple[int, ...]
    tagline: str
    keywords: Tuple[str, ...]
    cta: str

EVENT_CURATION: Tuple[EventTheme, ...] = ()

DEFAULT_THEME = EventTheme(
    id="always-on",
    name="생필품 추천",
    months=(),
    tagline="매일 쓰는 필수템만 모았어요",
    keywords=DAILY_KEYWORDS,
    cta="생필품 보러가기",
)

_BANNER_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHED_CREDS: Optional[Tuple[str, str]] = None


def normalize_interest_category(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    trimmed = value.strip()
    return trimmed if trimmed in VALID_INTEREST_CATEGORIES else ""


def _get_event_theme(now: Optional[dt.datetime] = None) -> EventTheme:
    return DEFAULT_THEME


def _build_keyword_pool(theme: EventTheme, category: str) -> List[str]:
    pool = list(theme.keywords)
    if CATEGORY_KEYWORDS.get(category):
        pool.extend(CATEGORY_KEYWORDS[category])
    else:
        pool.extend(CATEGORY_KEYWORDS["finance"])
    unique = []
    seen = set()
    for item in pool:
        if not item or item in seen:
            continue
        unique.append(item)
        seen.add(item)
    return unique or ["가계부"]


def _pick_keyword(pool: Iterable[str]) -> str:
    pool_list = list(pool)
    if not pool_list:
        return "가계부"
    return random.choice(pool_list)


def _get_coupang_date(now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.utcnow()
    year = str(now.year)[-2:]
    return f"{year}{now.month:02d}{now.day:02d}T{now.hour:02d}{now.minute:02d}{now.second:02d}Z"


def _sign(secret_key: str, message: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _load_credentials_from_file(path: str) -> Optional[Tuple[str, str]]:
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    access_match = re.search(r"Access\s*key\s*\n\s*([0-9a-f\-]+)", text, re.IGNORECASE)
    secret_match = re.search(r"Secret\s*key\s*\n\s*([0-9a-f]+)", text, re.IGNORECASE)
    access_key = access_match.group(1).strip() if access_match else ""
    secret_key = secret_match.group(1).strip() if secret_match else ""
    if access_key and secret_key:
        return access_key, secret_key
    return None


def _get_credentials() -> Tuple[str, str]:
    global _CACHED_CREDS
    if COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY:
        return COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY
    if _CACHED_CREDS:
        return _CACHED_CREDS
    creds = _load_credentials_from_file(COUPANG_API_INFO_FILE)
    if creds:
        _CACHED_CREDS = creds
        return creds
    raise RuntimeError("COUPANG_ACCESS_KEY/COUPANG_SECRET_KEY not configured")


def _clamp_int(value: Any, min_value: int, max_value: int, fallback: int) -> int:
    try:
        parsed = int(str(value))
    except Exception:
        return fallback
    return max(min_value, min(max_value, parsed))


def fetch_coupang_search_products(keyword: str, limit: int = 3, sub_id: Optional[str] = None) -> List[Dict[str, Any]]:
    access_key, secret_key = _get_credentials()
    resolved_sub_id = sub_id or COUPANG_SUB_ID or "cp-banner"

    path = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"
    query = urllib.parse.urlencode(
        {
            "keyword": keyword,
            "limit": str(limit),
            "subId": resolved_sub_id,
        }
    )
    datetime_str = _get_coupang_date()
    message = f"{datetime_str}GET{path}{query}"
    signature = _sign(secret_key, message)
    authorization = (
        "CEA algorithm=HmacSHA256, "
        f"access-key={access_key}, signed-date={datetime_str}, signature={signature}"
    )

    req = urllib.request.Request(
        f"https://api-gateway.coupang.com{path}?{query}",
        headers={"Authorization": authorization},
    )
    with urllib.request.urlopen(req, timeout=6) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("rCode") and payload.get("rCode") != "0":
        raise RuntimeError(payload.get("rMessage") or "Coupang API error")
    return payload.get("data", {}).get("productData", []) or []


def build_banner_payload(
    *,
    keyword_override: Optional[str] = None,
    category_override: Optional[str] = None,
    limit: int = 3,
) -> Dict[str, Any]:
    keyword_override = (keyword_override or "").strip()
    category_override = normalize_interest_category(category_override)
    limit = _clamp_int(limit, 1, 10, 3)

    theme = _get_event_theme()
    category = category_override

    if not category:
        try:
            category = normalize_interest_category(db.fetch_top_interest_category() or "")
        except Exception:
            category = ""

    if not category:
        category = normalize_interest_category(COUPANG_BANNER_DEFAULT_CATEGORY) or "finance"

    keyword_pool = _build_keyword_pool(theme, category)
    keyword = keyword_override or _pick_keyword(keyword_pool)
    keyword_key = f"kw:{keyword_override}" if keyword_override else "kw:auto"
    cache_key = f"cp-banner:{theme.id}:{category or 'any'}:{limit}:{keyword_key}"

    cached = _BANNER_CACHE.get(cache_key)
    now = dt.datetime.utcnow().timestamp()
    if cached and cached[0] > now:
        return cached[1]

    items: List[Dict[str, Any]] = []
    try:
        products = fetch_coupang_search_products(keyword, limit=limit)
        for idx, product in enumerate(products or []):
            discount = _safe_number(product.get("productDiscountRate"))
            rocket = bool(
                product.get("rocketWow")
                or product.get("rocket")
                or product.get("rocketDeliveryType") == "ROCKET"
                or product.get("isRocket")
                or product.get("isRocketWow")
            )
            free_shipping = bool(product.get("isFreeShipping") or product.get("freeShipping"))
            shipping_tag = "로켓배송" if rocket else "무료배송" if free_shipping else ""

            rating_count = _safe_number(product.get("ratingCount") or product.get("reviewCount"))
            rating = _safe_number(product.get("rating") or product.get("ratingAverage") or product.get("ratingScore"))
            meta_parts: List[str] = []
            if rating is not None and rating > 0:
                meta_parts.append(f"★{rating:.1f}")
            if rating_count is not None and rating_count > 0:
                meta_parts.append(f"리뷰 {int(rating_count):,}개")
            if shipping_tag:
                meta_parts.append(shipping_tag)
            if product.get("categoryName") or product.get("sellerName") or theme.name:
                meta_parts.append(product.get("categoryName") or product.get("sellerName") or theme.name)

            items.append(
                {
                    "title": product.get("productName"),
                    "image": product.get("productImage"),
                    "link": product.get("productUrl"),
                    "price": _format_price(_safe_number(product.get("productPrice"))),
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                    "badge": theme.name,
                    "discountRate": int(round(discount)) if discount is not None and discount > 0 else None,
                    "cta": theme.cta or _cta_variant(idx),
                    "shippingTag": shipping_tag,
                    "ratingCount": int(rating_count) if rating_count is not None and rating_count > 0 else None,
                    "rating": rating if rating is not None and rating > 0 else None,
                }
            )
    except Exception:
        items = []

    payload = {
        "category": category,
        "keyword": keyword,
        "theme": {
            "id": theme.id,
            "title": theme.name,
            "tagline": theme.tagline,
            "cta": theme.cta,
        },
        "items": items,
    }

    ttl = 1800 if items else 120
    _BANNER_CACHE[cache_key] = (now + ttl, payload)
    return payload


def record_interest_category(category: str) -> None:
    normalized = normalize_interest_category(category)
    if not normalized:
        return
    db.record_ad_interest(normalized)


def _safe_number(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except Exception:
        return None
    return num if num == num else None


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{int(round(value)):,}원"


def _cta_variant(idx: int) -> str:
    variants = ("최저가 보기", "배송 일정 확인", "리뷰 보고 선택")
    return variants[idx % len(variants)]
