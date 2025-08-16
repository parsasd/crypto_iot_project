"""
FastAPI application exposing endpoints for OHLC data, indicator
computation, and backtesting.  The API is stateless and can be
deployed independently of other services.
"""
from __future__ import annotations
import logging
import datetime as dt
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, validator

import pandas as pd
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

logger = logging.getLogger("indicator_api")
app = FastAPI(title="Indicator & Backtesting API")


# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------
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
    indicators: List[str] = Field(
        ..., description="Indicators: sma20, ema50, rsi14, macd, bollinger"
    )

    @validator("end")
    def validate_dates(cls, v, values):
        start = values.get("start")
        if start and v <= start:
            raise ValueError("end must be after start")
        return v


class BacktestRule(BaseModel):
    logic: str = Field("and", description="Combination logic: and/or")
    signals: List[str] = Field(
        ..., description="Signals: macd_cross, rsi, bollinger, sma_crossover"
    )


class BacktestRequest(BaseModel):
    """
    Request payload for running a backtest.  In addition to the symbol,
    interval and time range, accepts the signal rules, initial capital
    and per-trade fee.
    """
    symbol: str = Field(..., description="Binance pair (e.g. BTCUSDT) or CoinGecko id")
    interval: str = Field(..., description="Binance-style interval: 1m, 5m, 1h, 4h, 1d…")
    start: dt.datetime
    end: dt.datetime
    rule: BacktestRule = Field(..., description="Signal combination logic and signals")
    initial_capital: float = Field(10000.0, description="Starting capital")
    fee_pct: float = Field(0.0, description="Per trade fee (e.g. 0.0005 = 0.05%)")
    vs_currency: str = Field("USDT", description="Quote currency for CG fallback")

    @validator("end")
    def _validate_dates(cls, v, values):
        start = values.get("start")
        if start and v <= start:
            raise ValueError("end must be after start")
        return v


class ExamplesRequest(BaseModel):
    symbol: str
    interval: str
    start: dt.datetime
    end: dt.datetime
    rule: BacktestRule
    num_examples: int = 3


def _as_utc(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@app.get("/data/ohlc", response_model=List[OHLCResponse])
async def get_ohlc(
    symbol: str = Query(..., description="Trading pair, e.g. BTCUSDT"),
    interval: str = Query("4h", description="Interval: 1m, 5m, 1h, 4h, 1d…"),
    start: dt.datetime = Query(...),
    end: dt.datetime = Query(...),
) -> List[OHLCResponse]:
    """Return OHLCV data for the given range."""
    df = await fetch_ohlc(symbol, interval, start, end)
    if df.empty:
        raise HTTPException(404, detail="No data found")
    return [
        OHLCResponse(
            date=idx.to_pydatetime(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for idx, row in df.iterrows()
    ]


@app.post("/indicators/compute")
async def compute_indicators(req: IndicatorRequest):
    df = await fetch_ohlc(req.symbol, req.interval, req.start, req.end)
    if df.empty:
        raise HTTPException(404, detail="No data")
    if not req.indicators:
        raise HTTPException(400, detail="No indicators requested")
    result: Dict[str, Any] = {}
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
    """
    Run a signal-driven backtest.  Fetches OHLC data, computes the
    requested indicator signals, applies smoothing for AND logic, and
    returns performance metrics and an equity curve.
    """
    start = _as_utc(req.start)
    end = _as_utc(req.end)
    if start >= end:
        raise HTTPException(status_code=400, detail="`start` must be before `end`")

    # fetch candles
    try:
        df = await fetch_ohlc(
            symbol=req.symbol,
            interval=req.interval,
            start=start,
            end=end,
            vs_currency=req.vs_currency,
        )
    except RuntimeError as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            raise HTTPException(status_code=401, detail=msg)
        if "429" in msg or "rate limit" in msg.lower():
            raise HTTPException(status_code=429, detail=msg)
        if "allowed time range" in msg or "365" in msg:
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=502, detail=msg)
    except Exception:
        logger.exception("Unhandled error in /backtest/run")
        raise HTTPException(status_code=500, detail="Internal server error")

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail="No candles returned for the given symbol/interval/time range",
        )

    # build signals
    indicators_map: Dict[str, Any] = {}
    signals_series: List[pd.Series] = []

    def _smooth_signal(sig: pd.Series, lookback: int = 3) -> pd.Series:
        """
        Smooth a signal for AND logic by propagating +1/-1 if a non-zero
        signal occurred within the previous lookback bars.  This helps
        ensure overlapping signals.
        """
        pos = sig.rolling(window=lookback + 1).max().fillna(0)
        neg = sig.rolling(window=lookback + 1).min().fillna(0)
        sm = pd.Series(0, index=sig.index)
        sm[pos > 0] = 1
        sm[neg < 0] = -1
        return sm

    for sig in req.rule.signals:
        if sig == "macd_cross":
            if "macd" not in indicators_map:
                indicators_map["macd"] = compute_macd(df["close"])
            s = macd_cross_signal(
                indicators_map["macd"]["macd"], indicators_map["macd"]["macd_signal"]
            )
        elif sig == "bollinger":
            if "bollinger" not in indicators_map:
                indicators_map["bollinger"] = compute_bollinger(df["close"])
            s = bollinger_signal(
                df["close"],
                indicators_map["bollinger"]["bb_lower"],
                indicators_map["bollinger"]["bb_upper"],
            )
        elif sig == "rsi":
            s = rsi_signal(compute_rsi(df["close"]))
        elif sig == "sma_crossover":
            s = sma_crossover_signal(
                compute_sma(df["close"], 20), compute_sma(df["close"], 50)
            )
        elif sig == "ema_crossover":
            # reuse SMA crossover logic for EMA crossovers
            s = sma_crossover_signal(
                compute_ema(df["close"], 20), compute_ema(df["close"], 50)
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported signal {sig}")

        s = s.reindex(df.index, fill_value=0)
        if req.rule.logic.lower() == "and":
            s = _smooth_signal(s, lookback=3)
        signals_series.append(s)

    # final combination; apply another round of smoothing for AND logic
    lookback = 3 if req.rule.logic.lower() == "and" else 1
    smoothed_signals: List[pd.Series] = []
    for s in signals_series:
        if lookback > 1:
            pos_mask = s.rolling(window=lookback, min_periods=1).max() > 0
            neg_mask = s.rolling(window=lookback, min_periods=1).min() < 0
            s_smoothed = pd.Series(0, index=s.index)
            s_smoothed.loc[pos_mask] = 1
            s_smoothed.loc[neg_mask] = -1
            smoothed_signals.append(s_smoothed)
        else:
            smoothed_signals.append(s)
    combined_signal = combine_signals(smoothed_signals, logic=req.rule.logic)

    # run backtest
    result = backtest_strategy(
        df,
        combined_signal,
        initial_capital=req.initial_capital,
        fee_pct=req.fee_pct,
    )

    # serialize trades
    trades_serialised = [
        {
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "entry_price": float(t.entry_price),
            "exit_price": float(t.exit_price),
            "profit_pct": float(t.profit_pct),
        }
        for t in result.trades
    ]
    return {
        "pnl": result.pnl,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
        "sharpe": result.sharpe,
        "trades": trades_serialised,
        "equity_curve": [float(x) for x in result.equity_curve.tolist()],
        "dates": [ts.isoformat() for ts in result.equity_curve.index],
    }


@app.post("/backtest/examples")
async def backtest_examples(req: ExamplesRequest):
    """
    Return example charts and metadata for recent signal occurrences.
    Applies the same smoothing logic for AND-combined signals as in
    /backtest/run.
    """
    df = await fetch_ohlc(req.symbol, req.interval, req.start, req.end)
    if df.empty:
        raise HTTPException(404, detail="No data")

    signals_series: List[pd.Series] = []
    indicators_map: Dict[str, Any] = {}
    if any(s in req.rule.signals for s in ["macd_cross"]):
        indicators_map["macd"] = compute_macd(df["close"])
    if "bollinger" in req.rule.signals:
        indicators_map["bollinger"] = compute_bollinger(df["close"])

    for sig in req.rule.signals:
        if sig == "macd_cross":
            if "macd" not in indicators_map:
                indicators_map["macd"] = compute_macd(df["close"])
            s = macd_cross_signal(
                indicators_map["macd"]["macd"], indicators_map["macd"]["macd_signal"]
            )
        elif sig == "bollinger":
            if "bollinger" not in indicators_map:
                indicators_map["bollinger"] = compute_bollinger(df["close"])
            s = bollinger_signal(
                df["close"],
                indicators_map["bollinger"]["bb_lower"],
                indicators_map["bollinger"]["bb_upper"],
            )
        elif sig == "rsi":
            s = rsi_signal(compute_rsi(df["close"]))
        elif sig == "sma_crossover":
            s = sma_crossover_signal(
                compute_sma(df["close"], 20), compute_sma(df["close"], 50)
            )
        elif sig == "ema_crossover":
            s = sma_crossover_signal(
                compute_ema(df["close"], 20), compute_ema(df["close"], 50)
            )
        else:
            raise HTTPException(400, detail=f"Unsupported signal {sig}")
        s = s.reindex(df.index, fill_value=0)
        signals_series.append(s)

    lookback = 3 if req.rule.logic.lower() == "and" else 1
    smoothed_signals: List[pd.Series] = []
    for s in signals_series:
        if lookback > 1:
            pos_mask = s.rolling(window=lookback, min_periods=1).max() > 0
            neg_mask = s.rolling(window=lookback, min_periods=1).min() < 0
            s_smoothed = pd.Series(0, index=s.index)
            s_smoothed.loc[pos_mask] = 1
            s_smoothed.loc[neg_mask] = -1
            smoothed_signals.append(s_smoothed)
        else:
            smoothed_signals.append(s)
    combined = combine_signals(smoothed_signals, logic=req.rule.logic)

    examples = find_examples(
        df,
        combined,
        indicators=indicators_map,
        num_examples=req.num_examples,
        symbol=req.symbol,
        output_dir="/app/examples",
    )
    return {"examples": examples}
