"""
Define trading signal rules based on indicator series.

Each function returns a pandas Series with values +1 (bullish), -1 (bearish)
or 0 (neutral).  The combine_signals function composes multiple signal
series using logical AND/OR semantics.
"""

from __future__ import annotations
import pandas as pd


def _cross_up(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """Return True when series1 crosses above series2."""
    return (series1.shift(1) < series2.shift(1)) & (series1 >= series2)


def _cross_down(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """Return True when series1 crosses below series2."""
    return (series1.shift(1) > series2.shift(1)) & (series1 <= series2)


def macd_cross_signal(macd: pd.Series, signal: pd.Series) -> pd.Series:
    """
    +1 when MACD crosses above its signal line, -1 when it crosses below.
    """
    up = _cross_up(macd, signal)
    down = _cross_down(macd, signal)
    s = pd.Series(0, index=macd.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def rsi_signal(rsi: pd.Series, low: float = 30.0, high: float = 70.0) -> pd.Series:
    """
    +1 when RSI crosses below the low threshold (oversold), -1 when RSI
    crosses above the high threshold (overbought).
    """
    up = (rsi.shift(1) > low) & (rsi <= low)
    down = (rsi.shift(1) < high) & (rsi >= high)
    s = pd.Series(0, index=rsi.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def bollinger_signal(
    close: pd.Series, lower: pd.Series, upper: pd.Series
) -> pd.Series:
    """
    +1 when price crosses below the lower band (contrarian buy), -1 when
    price crosses above the upper band (sell).  Crossing requires a
    change from inside to outside the band.
    """
    up = _cross_down(close, lower)  # crosses below lower
    down = _cross_up(close, upper)  # crosses above upper
    s = pd.Series(0, index=close.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def sma_crossover_signal(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    +1 when a fast SMA/EMA crosses above the slow SMA/EMA (golden cross),
    -1 when it crosses below (death cross).
    """
    up = _cross_up(fast, slow)
    down = _cross_down(fast, slow)
    s = pd.Series(0, index=fast.index)
    s.loc[up] = 1
    s.loc[down] = -1
    return s


def combine_signals(signals: list[pd.Series], logic: str = "and") -> pd.Series:
    """
    Combine multiple signal series.  If logic is 'and' then +1 only if
    all signals are +1, and -1 only if all signals are -1; else 0.
    If logic is 'or' then +1 if any signal is +1, -1 if any is -1
    (with +1 dominating if both +1 and -1 occur).
    """
    if not signals:
        raise ValueError("no signals to combine")
    df = pd.concat(signals, axis=1, keys=range(len(signals)))
    if logic.lower() == "and":
        pos = (df > 0).all(axis=1)
        neg = (df < 0).all(axis=1)
        combined = pd.Series(0, index=df.index)
        combined.loc[pos] = 1
        combined.loc[neg] = -1
        return combined
    elif logic.lower() == "or":
        combined = pd.Series(0, index=df.index)
        pos = (df > 0).any(axis=1)
        neg = (df < 0).any(axis=1)
        combined.loc[pos & ~neg] = 1
        combined.loc[neg & ~pos] = -1
        return combined
    else:
        raise ValueError("logic must be 'and' or 'or'")
