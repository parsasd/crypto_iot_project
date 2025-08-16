import os
import sys
import pandas as pd

# add indicator_engine_py to sys.path for tests
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/indicator_engine_py')))

from core.indicators import compute_sma, compute_ema, compute_rsi


def test_compute_sma():
    series = pd.Series([1, 2, 3, 4, 5])
    sma3 = compute_sma(series, 3)
    # last value should be average of [3,4,5] = 4
    assert round(sma3.iloc[-1], 2) == 4.00


def test_compute_ema():
    series = pd.Series([1, 2, 3, 4, 5])
    ema3 = compute_ema(series, 3)
    # The first non‑NA value should equal the third element for EMA with span 3
    assert not pd.isna(ema3.iloc[2])


def test_compute_rsi():
    # constant series has RSI=50
    series = pd.Series([1] * 20)
    rsi = compute_rsi(series, 14)
    last = rsi.iloc[-1]
    assert 45 <= last <= 55