"""Implement common technical indicators using pure pandas.

This module provides stand‑alone implementations of SMA, EMA, RSI,
MACD and Bollinger Bands without relying on external TA libraries.
These functions return pandas Series/DataFrames consistent with the
original project’s expectations.
"""

from __future__ import annotations
import pandas as pd
import numpy as np


def compute_sma(close: pd.Series, window: int) -> pd.Series:
    """
    Compute the simple moving average (SMA) over the given window.
    Missing values in the initial window remain NaN to avoid look‑ahead.
    """
    return close.rolling(window=window, min_periods=window).mean()


def compute_ema(close: pd.Series, window: int) -> pd.Series:
    """
    Compute the exponential moving average (EMA) using pandas’ ewm.
    The `adjust=False` parameter replicates typical trading‑platform
    EMA behaviour.
    """
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """
    Compute the Relative Strength Index (RSI) using Wilder’s method.
    RSI oscillates between 0 and 100. Oversold <30, overbought >70.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """
    Compute the Moving Average Convergence Divergence (MACD).
    Returns a DataFrame with columns macd, macd_signal and macd_diff.
    """
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    macd_diff = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "macd_diff": macd_diff}
    )


def compute_bollinger(
    close: pd.Series, window: int = 20, n_std: float = 2.0
) -> pd.DataFrame:
    """
    Compute Bollinger Bands (lower, mid, upper) using a rolling mean
    (mid band) and rolling standard deviation.  Missing values in the
    initial window remain NaN.
    """
    mid = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + n_std * std
    lower = mid - n_std * std
    return pd.DataFrame({"bb_lower": lower, "bb_mid": mid, "bb_upper": upper})


def bollinger_signal(
    close: pd.Series, bb_lower: pd.Series, bb_upper: pd.Series
) -> pd.Series:
    """
    Contrarian Bollinger-band signal: +1 when price is below the lower band
    (buy), -1 when price is above the upper band (sell); 0 otherwise.
    """
    sig = pd.Series(0, index=close.index, dtype=np.int8)
    sig[close < bb_lower] = 1
    sig[close > bb_upper] = -1
    return sig
