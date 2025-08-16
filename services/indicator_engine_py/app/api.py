"""
FastAPI application exposing endpoints for OHLC data, indicator
computation, and backtesting.  The API is stateless and can be
deployed independently of other services.
"""
from __future__ import annotations
import logging

import asyncio
import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, validator

from core import (
    fetch_ohlc,
    compute_sma,
    compute_ema,
    compute_rsi,
    compute_macd,
    compute_bollinger,
    macd_cross_signal,
    rsi_signal,
    bollinger_signal,
    sma_crossover_signal,
    combine_signals,
    backtest_strategy,
    find_examples,
)

app = FastAPI(title="Indicator & Backtesting API")

# Serve example charts from the /app/examples directory
import os
from fastapi.staticfiles import StaticFiles
examples_dir = "/app/examples"
os.makedirs(examples_dir, exist_ok=True)
app.mount("/examples", StaticFiles(directory=examples_dir), name="examples")


class OHLCResponse(BaseModel):
    date: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorRequest(BaseModel):
    symbol: str = Field(..., description="Trading pair symbol, e.g. BTCUSDT")
    interval: str = Field(..., description="Binance interval, e.g. 4h")
    start: dt.datetime
    end: dt.datetime
    indicators: List[str] = Field(..., description="List of indicators to compute: sma20, ema50, rsi14, macd, bollinger")

    @validator("end")
    def validate_dates(cls, v, values):
        start = values.get("start")
        if start and v <= start:
            raise ValueError("end must be after start")
        return v


class BacktestRule(BaseModel):
    logic: str = Field("and", description="Combination logic: and/or")
    signals: List[str] = Field(..., description="Signals to use: macd_cross, rsi, bollinger, sma_crossover")



class BacktestResponse(BaseModel):
    pnl: float
    win_rate: float
    max_drawdown: float
    sharpe: float
    trades: List[Dict[str, Any]]
    equity_curve: List[float]
    dates: List[str]

from core.ohlc_fetcher import fetch_ohlc  # the module we fixed earlier

logger = logging.getLogger("indicator_api")
app = FastAPI()


class BacktestRequest(BaseModel):
    symbol: str = Field(..., description="Binance pair (e.g. BTCUSDT) or CoinGecko id (e.g. bitcoin)")
    interval: str = Field(..., description="Binance-style interval: 1m, 5m, 1h, 4h, 1d, ...")
    start: dt.datetime
    end: dt.datetime
    vs_currency: str = Field("USDT", description="Quote currency for CG fallback (e.g. USD/USDT)")

def _as_utc(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc)

class ExamplesRequest(BaseModel):
    symbol: str
    interval: str
    start: dt.datetime
    end: dt.datetime
    rule: BacktestRule
    num_examples: int = 3


@app.get("/data/ohlc", response_model=List[OHLCResponse])
async def get_ohlc(
    symbol: str = Query(..., description="Trading pair, e.g. BTCUSDT"),
    interval: str = Query("4h", description="Binance interval, e.g. 1h, 4h, 1d"),
    start: dt.datetime = Query(...),
    end: dt.datetime = Query(...),
) -> List[OHLCResponse]:
    """Return OHLCV data for the given range."""
    df = await fetch_ohlc(symbol, interval, start, end)
    if df.empty:
        raise HTTPException(404, detail="No data found")
    return [
        OHLCResponse(date=idx.to_pydatetime(), open=row.open, high=row.high, low=row.low, close=row.close, volume=row.volume)
        for idx, row in df.iterrows()
    ]


@app.post("/indicators/compute")
async def compute_indicators(req: IndicatorRequest):
    df = await fetch_ohlc(req.symbol, req.interval, req.start, req.end)
    if df.empty:
        raise HTTPException(404, detail="No data")
    result: Dict[str, Any] = {}
    if not req.indicators:
        raise HTTPException(400, detail="No indicators requested")
    for ind in req.indicators:
        key = ind.lower()
        if key.startswith("sma"):
            window = int(key.replace("sma", ""))
            result[key] = compute_sma(df["close"], window).dropna().to_dict()
        elif key.startswith("ema"):
            window = int(key.replace("ema", ""))
            result[key] = compute_ema(df["close"], window).dropna().to_dict()
        elif key.startswith("rsi"):
            window = int(key.replace("rsi", "")) if len(key) > 3 else 14
            result[key] = compute_rsi(df["close"], window).dropna().to_dict()
        elif key == "macd":
            macd_df = compute_macd(df["close"])
            result[key] = macd_df.dropna().to_dict("list")
        elif key == "bollinger":
            bb_df = compute_bollinger(df["close"])
            result[key] = bb_df.dropna().to_dict("list")
        else:
            raise HTTPException(400, detail=f"Unknown indicator {ind}")
    return result


@app.post("/backtest/run")
async def run_backtest(req: BacktestRequest):
    start = _as_utc(req.start)
    end = _as_utc(req.end)

    if start >= end:
        raise HTTPException(status_code=400, detail="`start` must be before `end`.")
    if (end - start).total_seconds() <= 0:
        raise HTTPException(status_code=400, detail="Invalid time range.")

    try:
        df = await fetch_ohlc(
            symbol=req.symbol,
            interval=req.interval,
            start=start,
            end=end,
            vs_currency=req.vs_currency,
        )
    except RuntimeError as e:
        # Our fetcher raises RuntimeError with informative messages for CG errors.
        msg = str(e)
        # Map likely upstream problems to useful HTTP status codes:
        if "401" in msg or "Unauthorized" in msg:
            raise HTTPException(status_code=401, detail=msg)
        if "429" in msg or "rate limit" in msg.lower():
            raise HTTPException(status_code=429, detail=msg)
        if "allowed time range" in msg or "365" in msg:
            # Free/demo CoinGecko range exceeded
            raise HTTPException(status_code=400, detail=msg)
        # Anything else from the upstream gets treated as a bad gateway
        raise HTTPException(status_code=502, detail=msg)
    except Exception as e:
        logger.exception("Unhandled error in /backtest/run")
        raise HTTPException(status_code=500, detail="Internal server error.")

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail="No candles returned for the given symbol/interval/time range."
        )

    # If your backtest needs raw candles, return them; otherwise feed `df` into your strategy.
    # Here’s a simple JSON shape with candles you can adapt:
    out = df.reset_index().rename(columns={"date": "ts"})
    out["ts"] = out["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    records = out.to_dict(orient="records")

    return {
        "symbol": req.symbol,
        "interval": req.interval,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(records),
        "candles": records,
    }

@app.post("/backtest/examples")
async def backtest_examples(req: ExamplesRequest):
    df = await fetch_ohlc(req.symbol, req.interval, req.start, req.end)
    if df.empty:
        raise HTTPException(404, detail="No data")
    # compute indicators for signals
    signals_series = []
    indicators_map: Dict[str, Any] = {}
    if any(s in req.rule.signals for s in ["macd_cross"]):
        macd_df = compute_macd(df["close"])
        indicators_map["macd"] = macd_df
    if "bollinger" in req.rule.signals:
        indicators_map["bollinger"] = compute_bollinger(df["close"])
    # build signal
    for sig in req.rule.signals:
        if sig == "macd_cross":
            if "macd" not in indicators_map:
                macd_df = compute_macd(df["close"])
                indicators_map["macd"] = macd_df
            s = macd_cross_signal(indicators_map["macd"]["macd"], indicators_map["macd"]["macd_signal"])
        elif sig == "bollinger":
            if "bollinger" not in indicators_map:
                indicators_map["bollinger"] = compute_bollinger(df["close"])
            s = bollinger_signal(df["close"], indicators_map["bollinger"]["bb_lower"], indicators_map["bollinger"]["bb_upper"])
        else:
            raise HTTPException(400, detail=f"Unsupported signal {sig}")
        signals_series.append(s)
    combined = combine_signals(signals_series, logic=req.rule.logic)
    examples = find_examples(
        df,
        combined,
        indicators=indicators_map,
        num_examples=req.num_examples,
        symbol=req.symbol,
        output_dir="/app/examples",
    )
    return {"examples": examples}
