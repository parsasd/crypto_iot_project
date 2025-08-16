"""Core utilities for the indicator engine.

This package provides helpers for fetching OHLC data from public APIs,
computing technical indicators, defining trading signal rules, and
running simple backtests.  All functions are designed to be side‑effect
free and deterministic when given the same inputs.
"""

from .ohlc_fetcher import fetch_ohlc
from .indicators import (
    compute_sma,
    compute_ema,
    compute_rsi,
    compute_macd,
    compute_bollinger,
)
from .rules import (
    macd_cross_signal,
    rsi_signal,
    bollinger_signal,
    sma_crossover_signal,
    combine_signals,
)
from .backtester import BacktestResult, backtest_strategy, find_examples

__all__ = [
    "fetch_ohlc",
    "compute_sma",
    "compute_ema",
    "compute_rsi",
    "compute_macd",
    "compute_bollinger",
    "macd_cross_signal",
    "rsi_signal",
    "bollinger_signal",
    "sma_crossover_signal",
    "combine_signals",
    "BacktestResult",
    "backtest_strategy",
    "find_examples",
]