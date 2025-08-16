"""Implement common technical indicators using pandas and ta library."""
from __future__ import annotations

import pandas as pd
import numpy as np
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator
from typing import Union
from ta.volatility import BollingerBands



def compute_sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return SMAIndicator(close=close, window=window, fillna=False).sma_indicator()


def compute_ema(close: pd.Series, window: int) -> pd.Series:
    """Exponential moving average."""
    return EMAIndicator(close=close, window=window, fillna=False).ema_indicator()


def compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return RSIIndicator(close=close, window=window, fillna=False).rsi()


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    Compute MACD, MACD signal and histogram.  Returns a DataFrame
    with columns ``macd``, ``macd_signal`` and ``macd_diff``.
    """
    macd_ind = MACD(close=close, window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
    df = pd.DataFrame({
        "macd": macd_ind.macd(),
        "macd_signal": macd_ind.macd_signal(),
        "macd_diff": macd_ind.macd_diff(),
    })
    return df

def compute_bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    """
    Return a DataFrame with columns exactly:
      - 'bb_lower'
      - 'bb_mid'
      - 'bb_upper'
    so that code like indicators_map["bollinger"]["bb_lower"] works.
    """
    mid = close.rolling(window=window, min_periods=window).mean()
    # Use population std (ddof=0) to match many finance libraries. Change to ddof=1 if you prefer sample std.
    std = close.rolling(window=window, min_periods=window).std(ddof=0)

    upper = mid + n_std * std
    lower = mid - n_std * std

    out = pd.DataFrame(
        {
            "bb_lower": lower.astype(float),
            "bb_mid": mid.astype(float),
            "bb_upper": upper.astype(float),
        }
    )
    return out

# ─────────────────────────────────────────────
# Bollinger Signal (optional helper)
# ─────────────────────────────────────────────
def bollinger_signal(close: pd.Series, bb_lower: pd.Series, bb_upper: pd.Series) -> pd.Series:
    """
    Simple contrarian signal:
      +1 when close < lower band
      -1 when close > upper band
       0 otherwise
    """
    df = pd.concat(
        [close.rename("close"), bb_lower.rename("bb_lower"), bb_upper.rename("bb_upper")],
        axis=1,
    )
    sig = pd.Series(0, index=df.index, dtype="int8", name="bollinger_signal")
    sig[df["close"] < df["bb_lower"]] = 1
    sig[df["close"] > df["bb_upper"]] = -1
    return sig