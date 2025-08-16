# core/ohlc_fetcher.py
"""Fetch historical OHLCV data from public cryptocurrency APIs.

Tries Binance first (unauthenticated). If Binance is unavailable for the
requested asset/interval, falls back to CoinGecko with rate-limit handling
and correct API key header/param.

All timestamps are UTC (datetime64[ns, UTC]). Prices/volumes are floats.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd
from datetime import timedelta

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger("ohlc_fetcher")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_h)
logger.setLevel(os.getenv("OHLC_LOG_LEVEL", "INFO").upper())

# ──────────────────────────────────────────────────────────────────────────────
# Env helpers (strip quotes/whitespace so .env "KEY=value " doesn’t break things)
# ──────────────────────────────────────────────────────────────────────────────

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v or default

# ──────────────────────────────────────────────────────────────────────────────
# CoinGecko config (via env)
# ──────────────────────────────────────────────────────────────────────────────

COINGECKO_BASE_URL = (_env("COINGECKO_BASE_URL", "https://api.coingecko.com") or "").rstrip("/")
COINGECKO_API_KEY = _env("COINGECKO_API_KEY")  # <-- must be injected into container
_COINGECKO_API_KEY_HEADER = _env("COINGECKO_API_KEY_HEADER")  # usually x-cg-demo-api-key or x-cg-pro-api-key
COINGECKO_API_KEY_PARAM = _env("COINGECKO_API_KEY_PARAM")     # optional: x_cg_demo_api_key or x_cg_pro_api_key

MAX_LOOKBACK_DAYS = int(_env("COINGECKO_MAX_LOOKBACK_DAYS", "365") or "365")
CG_MAX_RETRIES = int(_env("COINGECKO_MAX_RETRIES", "3") or "3")
CG_BACKOFF_BASE_SECS = float(_env("COINGECKO_BACKOFF_BASE_SECS", "1.5") or "1.5")

# Print a clear, masked startup line
masked = f"...{COINGECKO_API_KEY[-4:]}" if COINGECKO_API_KEY and len(COINGECKO_API_KEY) >= 4 else None
logger.info(
    "CoinGecko base=%s header='%s' param='%s' key=%s",
    COINGECKO_BASE_URL,
    ( _COINGECKO_API_KEY_HEADER or ("x-cg-pro-api-key" if "pro-api" in COINGECKO_BASE_URL else "x-cg-demo-api-key") ),
    COINGECKO_API_KEY_PARAM,
    (masked or None),
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_STABLE_TO_FIAT = {"usdt": "usd", "usdc": "usd", "dai": "usd", "busd": "usd", "tusd": "usd"}

_CG_ID_TO_BINANCE_BASE: Dict[str, str] = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "litecoin": "LTC",
    "dogecoin": "DOGE",
    "cardano": "ADA",
    "solana": "SOL",
    "ripple": "XRP",
    "polkadot": "DOT",
    "tron": "TRX",
}

def _to_utc_ts(ts: dt.datetime | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")

def _normalize_vs_currency(vs: str) -> str:
    if not vs:
        return "usd"
    vs = vs.lower()
    return _STABLE_TO_FIAT.get(vs, vs)

def _to_ms(ts: dt.datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return int(ts.timestamp() * 1000)

def _infer_cg_header_name() -> str:
    if _COINGECKO_API_KEY_HEADER:
        return _COINGECKO_API_KEY_HEADER
    return "x-cg-pro-api-key" if "pro-api" in COINGECKO_BASE_URL else "x-cg-demo-api-key"

def _cg_headers() -> dict:
    if not COINGECKO_API_KEY:
        return {}
    return {_infer_cg_header_name(): COINGECKO_API_KEY}

def clamp_range(start: dt.datetime, end: dt.datetime) -> Tuple[dt.datetime, dt.datetime]:
    if start > end:
        start, end = end, start
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.timezone.utc)
    span_days = (end.date() - start.date()).days
    if span_days > MAX_LOOKBACK_DAYS:
        end = end.replace(hour=23, minute=59, second=59, microsecond=0)
        start = end - timedelta(days=MAX_LOOKBACK_DAYS)
    return start, end

def _interval_to_ms(interval: str) -> Optional[int]:
    interval = interval.lower()
    unit = interval[-1]
    try:
        n = int(interval[:-1])
    except Exception:
        return None
    mult = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 7 * 86_400_000}.get(unit)
    return None if mult is None else n * mult

def _to_binance_symbol(symbol: str, vs_currency: str) -> Optional[str]:
    s = symbol.upper()
    if len(s) >= 6 and s.isalnum() and s == symbol:
        return s  # already a pair like BTCUSDT
    base = _CG_ID_TO_BINANCE_BASE.get(symbol.lower())
    if not base:
        return None
    vs = _normalize_vs_currency(vs_currency)
    quote = "USDT" if vs in {"usd", "usdt", "usdc", "dai", "busd", "tusd"} else vs.upper()
    return f"{base}{quote}"

# ──────────────────────────────────────────────────────────────────────────────
# Binance
# ──────────────────────────────────────────────────────────────────────────────

async def _fetch_binance_klines(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    start_ts: int,
    end_ts: int,
    limit: int = 1000,
) -> List[List]:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "startTime": start_ts, "endTime": end_ts, "limit": limit}
    resp = await client.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()

async def fetch_ohlc_binance(
    symbol: str,
    interval: str,
    start: dt.datetime,
    end: dt.datetime,
    vs_currency: str = "USDT",
) -> pd.DataFrame:
    binance_symbol = _to_binance_symbol(symbol, vs_currency)
    if not binance_symbol:
        return pd.DataFrame()

    interval_ms = _interval_to_ms(interval)
    if not interval_ms:
        return pd.DataFrame()

    start_ts = _to_ms(start)
    end_ts = _to_ms(end)

    all_rows: List[List] = []
    limit = 1000
    step = interval_ms * limit

    async with httpx.AsyncClient() as client:
        cur_start = start_ts
        while cur_start < end_ts:
            cur_end = min(cur_start + step - 1, end_ts)
            try:
                rows = await _fetch_binance_klines(client, binance_symbol, interval, cur_start, cur_end, limit)
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code in (400, 404, 429):
                    logger.debug(f"Binance fetch aborted ({e.response.status_code}) for {binance_symbol}@{interval}")
                    return pd.DataFrame()
                raise
            if not rows:
                break
            all_rows.extend(rows)

            last_open_time = rows[-1][0]
            next_start = last_open_time + interval_ms
            if next_start <= cur_start:
                break
            cur_start = next_start
            await asyncio.sleep(0.12)

    if not all_rows:
        return pd.DataFrame()

    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","number_of_trades",
        "taker_buy_base_asset_volume","taker_buy_quote_asset_volume","ignore",
    ]
    df = pd.DataFrame(all_rows, columns=cols)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("date")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df.loc[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index <= pd.Timestamp(end, tz="UTC"))]

# ──────────────────────────────────────────────────────────────────────────────
# CoinGecko (fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _apply_cg_auth(params: dict) -> Tuple[dict, dict]:
    """Return (headers, params) with API key applied via header and (optionally) query param."""
    headers = _cg_headers()
    if COINGECKO_API_KEY and COINGECKO_API_KEY_PARAM:
        params = dict(params)
        params[COINGECKO_API_KEY_PARAM] = COINGECKO_API_KEY
    return headers, params

async def _cg_get_json(path: str, params: dict) -> dict:
    url = f"{COINGECKO_BASE_URL}/api/v3{path}"
    headers, params = _apply_cg_auth(params)
    masked_key = f"...{COINGECKO_API_KEY[-4:]}" if COINGECKO_API_KEY and len(COINGECKO_API_KEY) >= 4 else "(none)"

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, CG_MAX_RETRIES + 1):
            resp = await client.get(url, params=params, headers=headers)
            status = resp.status_code

            if "x-ratelimit-remaining" in resp.headers:
                logger.debug(
                    "CG rate: remaining=%s reset=%s status=%s key=%s",
                    resp.headers.get("x-ratelimit-remaining"),
                    resp.headers.get("x-ratelimit-reset"),
                    status,
                    masked_key,
                )

            if status == 401:
                raise RuntimeError(
                    "CoinGecko 401 Unauthorized. Ensure COINGECKO_API_KEY is set in the container and "
                    f"the header name is correct (using '{_infer_cg_header_name()}')."
                )
            if status == 429 or 500 <= status < 600:
                try:
                    err_json = resp.json()
                    msg = (
                        err_json.get("error", {}).get("status", {}).get("error_message")
                        or err_json.get("status", {}).get("error_message")
                    )
                except Exception:
                    msg = resp.text
                if attempt == CG_MAX_RETRIES:
                    raise RuntimeError(f"CoinGecko error {status}: {msg or 'rate limited/temporary error'}")
                delay = CG_BACKOFF_BASE_SECS * (2 ** (attempt - 1))
                logger.warning("CG %s on attempt %s: %s (backoff %.2fs)", status, attempt, msg or "retrying", delay)
                await asyncio.sleep(delay)
                continue

            if status >= 400:
                try:
                    err_json = resp.json()
                    msg = (
                        err_json.get("error", {}).get("status", {}).get("error_message")
                        or err_json.get("status", {}).get("error_message")
                    )
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"CoinGecko error {status}: {msg}")

            return resp.json()

    raise RuntimeError("CoinGecko request failed after retries.")

async def fetch_ohlc_coingecko(symbol: str, vs_currency: str, days: int, interval: str) -> pd.DataFrame:
    """
    Fetch OHLCV from CoinGecko `market_chart` by reconstructing OHLC from close prices
    and summing 'total_volumes' per bucket.
    """
    vs_currency = _normalize_vs_currency(vs_currency)
    days = max(1, min(int(days), MAX_LOOKBACK_DAYS))

    path = f"/coins/{symbol}/market_chart"
    params = {"vs_currency": vs_currency, "days": days, "interval": interval}

    data = await _cg_get_json(path, params)

    prices = pd.DataFrame(data.get("prices", []), columns=["ts", "price"])
    vols = pd.DataFrame(data.get("total_volumes", []), columns=["ts", "volume"])

    if prices.empty:
        return pd.DataFrame()

    prices["date"] = pd.to_datetime(prices["ts"], unit="ms", utc=True)
    prices = prices.set_index("date").drop(columns=["ts"])
    rule = "1H" if interval == "hourly" else "1D"

    ohlc = prices["price"].resample(rule).ohlc()

    if not vols.empty:
        vols["date"] = pd.to_datetime(vols["ts"], unit="ms", utc=True)
        vols = vols.set_index("date").drop(columns=["ts"])
        ohlc["volume"] = vols["volume"].resample(rule).sum()
    else:
        ohlc["volume"] = float("nan")

    ohlc = ohlc[["open", "high", "low", "close", "volume"]].astype(float)
    ohlc = ohlc.dropna(subset=["close"])
    return ohlc

# ──────────────────────────────────────────────────────────────────────────────
# Public entry
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_ohlc(
    symbol: str,
    interval: str,
    start: dt.datetime,
    end: dt.datetime,
    vs_currency: str = "USDT",
) -> pd.DataFrame:
    start_utc = _to_utc_ts(start)
    end_utc = _to_utc_ts(end)
    if start_utc >= end_utc:
        return pd.DataFrame()

    # 1) Try Binance
    try:
        df_binance = await fetch_ohlc_binance(symbol, interval, start_utc.to_pydatetime(), end_utc.to_pydatetime(), vs_currency)
        if not df_binance.empty:
            return df_binance
    except Exception:
        pass

    # 2) CoinGecko fallback
    cg_start, cg_end = clamp_range(start_utc.to_pydatetime(), end_utc.to_pydatetime())
    delta_days = (cg_end - cg_start).days
    interval_cg = "hourly" if delta_days <= 90 else "daily"

    df_cg = await fetch_ohlc_coingecko(
        symbol=symbol.lower(),
        vs_currency=vs_currency.lower(),
        days=min(delta_days + 1, 730),
        interval=interval_cg,
    )
    if df_cg.empty:
        return df_cg

    if df_cg.index.tz is None:
        df_cg.index = df_cg.index.tz_localize("UTC")
    else:
        df_cg.index = df_cg.index.tz_convert("UTC")

    mask = (df_cg.index >= start_utc) & (df_cg.index <= end_utc)
    return df_cg.loc[mask]
