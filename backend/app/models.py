from __future__ import annotations
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra='ignore')

    password: Optional[str] = Field(default=None, description="Optional shared secret in payload")
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    timeframe: str
    ts: Optional[int] = Field(default=None, description="Unix timestamp seconds or milliseconds")
    bar_close_confirmed: Optional[bool] = Field(
        default=None,
        description="Whether this candle is fully closed (recommended to send from TradingView)",
    )
    bar_close: Optional[bool] = Field(
        default=None,
        description="Alias for bar_close_confirmed (legacy clients)",
    )
    barstate: Optional[str] = Field(default=None, description="Optional bar state hint e.g. 'closed'")
    is_bar_close: Optional[bool] = Field(default=None, description="Alias for bar_close_confirmed")
    
    # Support both string (ISO) and int/float (Timestamp) for time
    time: Optional[Union[int, float, str]] = Field(default=None)
    
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    features: Optional[Dict[str, Any]] = None

class RecommendQuery(BaseModel):
    side: str = Field(description="long or short")
    risk_pct: Optional[float] = Field(default=None, description="Risk % of equity per trade, e.g. 0.5")
