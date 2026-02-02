from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class WebhookPayload(BaseModel):
    # TradingView alert payloads are flexible; keep minimal
    password: Optional[str] = Field(default=None, description="Optional shared secret in payload")
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    timeframe: str
    ts: Optional[int] = Field(default=None, description="Unix timestamp seconds or milliseconds")
    time: Optional[str] = Field(default=None, description="ISO time string")
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    features: Optional[Dict[str, Any]] = None

class RecommendQuery(BaseModel):
    side: str = Field(description="long or short")
    risk_pct: Optional[float] = Field(default=None, description="Risk % of equity per trade, e.g. 0.5")
