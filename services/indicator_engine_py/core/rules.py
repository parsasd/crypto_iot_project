"""
Define trading signal rules based on indicator series.

All functions return a pandas Series indexed like the underlying data
frame with values +1 for a bullish signal, -1 for a bearish signal,
and 0 for neutral/no signal.  The ``combine_signals`` function
composes multiple signal series using logical AND/OR semantics.
"""
from __future__ import annotations

import pandas as pd


def _cross_up(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """Return True when series1 crosses above series2."""
    cond = (series1.shift(1) < series2.shift(1)) & (series1 >= series2)
    return cond


def _cross_down(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """Return True when series1 crosses below series2."""
    cond = (series1.shift(1) > series2.shift(1)) & (series1 <= series2)
    return cond


def macd_cross_signal(macd: pd.Series, signal: pd.Series) -> pd.Series:
    """
    Generate +1 when MACD crosses above its signal line (bullish) and
    -1 when it crosses below (bearish).  Neutral otherwise.
    """
    up = _cross_up(macd, signal)
    down = _cross_down(macd, signal)
    s = pd.Series(0, index=macd.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def rsi_signal(rsi: pd.Series, low: float = 30.0, high: float = 70.0) -> pd.Series:
    """
    Generate +1 when RSI crosses below the ``low`` threshold (oversold
    -> buy) and -1 when RSI crosses above the ``high`` threshold (overbought
    -> sell).  Neutral otherwise.
    """
    up = (rsi.shift(1) > low) & (rsi <= low)
    down = (rsi.shift(1) < high) & (rsi >= high)
    s = pd.Series(0, index=rsi.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def bollinger_signal(close: pd.Series, lower: pd.Series, upper: pd.Series) -> pd.Series:
    """
    Generate +1 when price crosses below the lower band (contrarian buy)
    and -1 when price crosses above the upper band (sell/trim).
    """
    up = _cross_down(close, lower)  # crosses below lower
    down = _cross_up(close, upper)  # crosses above upper
    s = pd.Series(0, index=close.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def sma_crossover_signal(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    Generate +1 when the fast SMA/EMA crosses above the slow SMA/EMA
    (golden cross) and -1 when it crosses below (death cross).
    """
    up = _cross_up(fast, slow)
    down = _cross_down(fast, slow)
    s = pd.Series(0, index=fast.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def combine_signals(signals: list[pd.Series], logic: str = "and") -> pd.Series:
    """
    Combine multiple signal series.  If ``logic`` is "and" then a
    combined signal is +1 only when all signals are +1 and -1 only when
    all signals are -1; otherwise 0.  If ``logic`` is "or" then +1
    whenever any signal is +1, -1 whenever any is -1 (with +1
    dominating over -1 if both present).
    """
    if not signals:
        raise ValueError("no signals to combine")
    df = pd.concat(signals, axis=1, keys=range(len(signals)))
    if logic.lower() == "and":
        # bullish if all positive
        pos = (df > 0).all(axis=1)
        neg = (df < 0).all(axis=1)
        combined = pd.Series(0, index=df.index)
        combined.loc[pos] = 1
        combined.loc[neg] = -1
        return combined
    elif logic.lower() == "or":
        combined = pd.Series(0, index=df.index)
        # bullish if any positive and none negative
        pos = (df > 0).any(axis=1)
        neg = (df < 0).any(axis=1)
        combined.loc[pos & ~neg] = 1
        combined.loc[neg & ~pos] = -1
        return combined
    else:
        raise ValueError("logic must be 'and' or 'or'")