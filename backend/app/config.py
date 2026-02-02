from __future__ import annotations
import os


def env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    v = str(v).strip().lower()
    return v in ("1","true","yes","y","on")

def env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default

def env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v not in (None, "") else default

DB_PATH = env_str("WONYODD_DB_PATH", "./data/wonyodd.sqlite3")
WEBHOOK_SECRET = env_str("WONYODD_WEBHOOK_SECRET", "")
MAX_LEVERAGE = env_float("WONYODD_MAX_LEVERAGE", 10.0)
RISK_PCT_DEFAULT = env_float("WONYODD_RISK_PCT_DEFAULT", 0.5)  # % of equity per trade
STOP_ATR_MULT = env_float("WONYODD_STOP_ATR_MULT", 1.5)

# ATR entry multipliers per timeframe (minutes)
# long: entry = price - k*ATR ; short: entry = price + k*ATR
ENTRY_ATR_K_30 = env_float("WONYODD_ENTRY_ATR_K_30", 1.0)
ENTRY_ATR_K_60 = env_float("WONYODD_ENTRY_ATR_K_60", 0.25)
ENTRY_ATR_K_180 = env_float("WONYODD_ENTRY_ATR_K_180", 0.6)

# how many candles to keep in memory calculations
LOOKBACK_1D = int(env_float("WONYODD_LOOKBACK_1D", 260))
LOOKBACK_INTRA = int(env_float("WONYODD_LOOKBACK_INTRA", 260))


# Webhook ingestion guards
REQUIRE_BAR_CLOSE = env_bool("WONYODD_REQUIRE_BAR_CLOSE", False)
VALIDATE_TS_ALIGNMENT = env_bool("WONYODD_VALIDATE_TS_ALIGNMENT", False)

# Evaluator / scoring (recent backtest window)
EVAL_LOOKBACK_BARS = int(env_float("WONYODD_EVAL_LOOKBACK_BARS", 2000))

# Parameter grid (comma-separated)
ENTRY_K_GRID = env_str("WONYODD_ENTRY_K_GRID", "0.0,0.25,0.5,0.75,1.0")
STOP_MULT_GRID = env_str("WONYODD_STOP_MULT_GRID", "1.0,1.25,1.5,1.75,2.0")
