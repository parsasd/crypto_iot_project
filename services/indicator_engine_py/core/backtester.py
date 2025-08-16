"""
Simple backtesting engine for indicator‑based strategies.

The engine supports long‑only strategies and combines multiple
indicator signals with AND/OR logic.  It produces a list of trades,
key performance metrics, and an equity curve.  It also exposes a
function to find example trades for demonstration purposes.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # allow headless environments
import matplotlib.pyplot as plt

from .rules import combine_signals


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    profit_pct: float


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: pd.Series
    pnl: float
    win_rate: float
    max_drawdown: float
    sharpe: float


def _compute_equity_curve(returns: pd.Series) -> pd.Series:
    """Compute cumulative equity curve from periodic returns."""
    return (1 + returns.fillna(0)).cumprod()


def backtest_strategy(
    df: pd.DataFrame,
    signal: pd.Series,
    initial_capital: float = 10000.0,
    fee_pct: float = 0.0,
) -> BacktestResult:
    """
    Run a simple long‑only backtest on provided OHLC data and signal
    series.  A position is opened on +1 signals and closed on -1 signals.
    Only one trade can be open at a time.  Fees are deducted on both
    entry and exit.
    """
    position_open = False
    entry_price: Optional[float] = None
    entry_time: Optional[pd.Timestamp] = None
    trades: List[Trade] = []
    capital = initial_capital
    equity = []
    last_price = None
    returns = []
    for ts, row in df.iterrows():
        sig = signal.loc[ts]
        price = row["close"]
        last_price = price
        # open position
        if sig > 0 and not position_open:
            position_open = True
            entry_price = price * (1 + fee_pct)
            entry_time = ts
        # close position
        elif sig < 0 and position_open:
            exit_price = price * (1 - fee_pct)
            profit_pct = (exit_price - entry_price) / entry_price
            trades.append(Trade(entry_time, ts, entry_price, exit_price, profit_pct))
            capital *= (1 + profit_pct)
            position_open = False
            entry_price = None
            entry_time = None
        # compute equity
        if position_open and entry_price:
            # unrealised PnL
            returns.append((price - last_price) / last_price if last_price else 0)
        else:
            returns.append(0)
        equity.append(capital)
    equity_series = pd.Series(equity, index=df.index)
    returns_series = pd.Series(returns, index=df.index)
    # compute metrics
    pnl = capital / initial_capital - 1
    win_trades = [t for t in trades if t.profit_pct > 0]
    win_rate = len(win_trades) / len(trades) if trades else 0.0
    # max drawdown
    eq_curve = _compute_equity_curve(returns_series)
    running_max = eq_curve.cummax()
    drawdowns = (eq_curve - running_max) / running_max
    max_drawdown = drawdowns.min() if not drawdowns.empty else 0.0
    # sharpe ratio (annualised assuming returns per bar; use sqrt(len))
    if returns_series.std(ddof=0) > 0:
        sharpe = (returns_series.mean() / returns_series.std(ddof=0)) * np.sqrt(len(returns_series))
    else:
        sharpe = 0.0
    return BacktestResult(
        trades=trades,
        equity_curve=eq_curve * initial_capital,
        pnl=pnl,
        win_rate=win_rate,
        max_drawdown=abs(max_drawdown),
        sharpe=sharpe,
    )


def find_examples(
    df: pd.DataFrame,
    signal: pd.Series,
    indicators: dict[str, pd.DataFrame],
    num_examples: int = 3,
    lookback: int = 30,
    lookforward: int = 30,
    symbol: str = "",
    output_dir: str = "examples",
) -> List[dict]:
    """
    Find a number of example trades where the signal fired.  For each
    example, capture a window of data around the signal and save a
    chart PNG.  Returns a list of dicts with metadata and file paths.
    """
    examples = []
    # indices where signal is non‑zero
    idxs = signal[signal != 0].index
    # pick last num_examples occurrences to make examples more relevant
    selected_idxs = idxs[-num_examples:]
    for ts in selected_idxs:
        i = df.index.get_loc(ts)
        start_i = max(0, i - lookback)
        end_i = min(len(df) - 1, i + lookforward)
        window = df.iloc[start_i:end_i + 1]
        # Plot price and one or two indicators depending on availability
        fig, ax1 = plt.subplots(figsize=(6, 4))
        ax1.plot(window.index, window["close"], label="Close", color="black")
        # overlay Bollinger if available
        if "bollinger" in indicators:
            bb = indicators["bollinger"].loc[window.index]
            ax1.plot(window.index, bb["bb_upper"], linestyle="--", color="red", alpha=0.6, label="BB Upper")
            ax1.plot(window.index, bb["bb_lower"], linestyle="--", color="green", alpha=0.6, label="BB Lower")
        # overlay MACD on secondary axis if available
        ax2 = ax1.twinx()
        if "macd" in indicators:
            macd_df = indicators["macd"].loc[window.index]
            ax2.plot(window.index, macd_df["macd"], color="blue", alpha=0.5, label="MACD")
            ax2.plot(window.index, macd_df["macd_signal"], color="orange", alpha=0.5, label="MACD Signal")
            ax2.set_ylabel("MACD")
        ax1.axvline(ts, color="magenta", linestyle=":", label="Signal")
        ax1.set_title(f"{symbol} signal on {ts.strftime('%Y-%m-%d %H:%M')}")
        ax1.set_ylabel("Price")
        ax1.legend(loc="upper left", fontsize=7)
        # Save figure
        import os
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{symbol}_{ts.strftime('%Y%m%d%H%M')}.png"
        filepath = os.path.join(output_dir, filename)
        fig.tight_layout()
        fig.savefig(filepath)
        plt.close(fig)
        # compute outcome: price change over lookforward bars
        if i + lookforward < len(df):
            future_price = df.iloc[i + lookforward]["close"]
            curr_price = df.loc[ts]["close"]
            outcome_pct = (future_price - curr_price) / curr_price
        else:
            outcome_pct = None
        examples.append({
            "timestamp": ts.isoformat(),
            "signal": int(signal.loc[ts]),
            "chart_path": filepath,
            "outcome_pct": outcome_pct,
        })
    return examples