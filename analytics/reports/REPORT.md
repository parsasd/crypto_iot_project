# Indicator and Backtesting Engine Report

This report explains the implementation of the Crypto IoT price and indicator system, focusing on the Python back‑end services.  The project is organised as a monorepo with clearly separated services for fetching prices, computing technical indicators and running backtests, sending alerts and a small web application.  Only the key components are described here; refer to the source code for further detail.

## Overview of the Pipeline

1. **Price feeder (`services/price_feeder_py`)** – Simulates a Raspberry Pi.  It periodically fetches live spot prices for configured crypto assets from CoinGecko (via the `/simple/price` endpoint) and publishes JSON messages to the MQTT broker under topics of the form `crypto/&lt;symbol&gt;/ticker`.  Each payload contains the current price, a delta from the previous value and a timestamp.  This module uses the [paho‑mqtt](https://pypi.org/project/paho-mqtt/) client library.

2. **ESP32 OLED simulator (`services/esp32_sim`)** – Acts like an ESP32 with an OLED attached.  It subscribes to the same MQTT topics and maintains a short history of recent prices for each asset.  On every new message it renders a 24×6 ASCII “screen” showing the latest price, 1 minute and 1 hour percentage changes, a simple RSI estimate, a MACD arrow and a timestamp.  RSI and MACD are computed on the fly from the recent price series using exponential moving averages; no external API calls are made.

3. **Alert engine (`services/alert_engine_py`)** – Listens for price updates and compares them against user‑defined thresholds stored in Postgres.  When a price crosses above or below a threshold and the per‑user cool‑down window has elapsed, it sends an email notification via SMTP (MailHog in development) and records the alert in an audit log.  Tables for users, OTPs, watchlists, thresholds and alerts are defined with SQLAlchemy.  The alert engine is responsible for creating these tables if they do not exist.

4. **Indicator & backtesting API (`services/indicator_engine_py`)** – Provides a FastAPI service exposing endpoints to fetch historical OHLCV data, compute indicators and run backtests.  Historical data is fetched asynchronously: first from Binance klines and, if that fails, from CoinGecko.  Indicators such as SMA, EMA, RSI, MACD and Bollinger Bands are computed using the [`ta`](https://github.com/bukosabino/ta) library.  Signal rules are defined in `core/rules.py` and include MACD crossovers, RSI thresholds, Bollinger band breaches and moving average crossovers.  Signals are combined with AND/OR logic by the `combine_signals` function.  The backtester (`core/backtester.py`) simulates a long‑only strategy: a long position is opened when a bullish signal fires and closed on a bearish signal.  It produces a list of trades, an equity curve and simple performance metrics such as PnL, win rate, maximum drawdown and a basic Sharpe ratio.  The `find_examples` function scans the signal series, selects concrete past occurrences and generates PNG charts (served under `/examples/` via FastAPI) highlighting the signal and the relevant indicators.

5. **Web application (`services/webapp`)** – A Next.js/React front‑end with simple API routes.  Users authenticate via email‑only one‑time passwords.  The `/api/request‑otp` route generates a six‑digit code, stores it in the `otps` table and sends it via SMTP.  `/api/verify‑otp` verifies the code, issues a signed JWT and sets an HTTP‑only cookie.  Authenticated users can manage their watchlist and price thresholds via `/api/watchlist` and `/api/thresholds`.  The `/backtest` page lets users pick a symbol, combine the `macd_cross` and `bollinger` signals with AND/OR logic and launch a backtest; results and three historical examples are fetched via the indicator API and displayed along with small charts.

## Key Implementation Details

* **Asynchronous data fetching** – The function `fetch_ohlc` in `core/ohlc_fetcher.py` first attempts to call the Binance klines endpoint, iterating through the requested date range with 1000‑candle windows.  If Binance fails (e.g. an unsupported symbol) it falls back to CoinGecko’s `market_chart` endpoint, adjusting the resolution (hourly vs. daily) based on the span of the request.  All timestamps are converted to UTC and returned as a Pandas `DataFrame` with `open`, `high`, `low`, `close` and `volume` columns.

* **Indicator computation** – Functions in `core/indicators.py` wrap the `ta` library and return Pandas series or data frames.  For example, `compute_macd` returns a frame with the MACD line, signal line and histogram.  `compute_bollinger` returns the moving average, upper/lower bands, bandwidth and %B in a single frame.

* **Signal rules** – `core/rules.py` defines helpers to detect crossovers (`_cross_up`/`_cross_down`) and uses them to implement MACD cross, RSI overbought/oversold, Bollinger band breaches and SMA/EMA crossovers.  Each rule produces a series of +1 (bullish), 0 (neutral) or –1 (bearish).  `combine_signals` takes a list of such series and performs a pointwise logical AND (all bullish or all bearish) or OR (any bullish and no bearish) to produce a combined trading signal.

* **Backtesting** – `core/backtester.py` simulates a long‑only strategy on the OHLC data.  When a +1 appears in the combined signal and no position is open, it “buys” at the next close price (including fees).  When a –1 appears and a position is open, it “sells” at the next close.  The equity curve is computed from the cumulative product of period returns.  Maximum drawdown is the largest peak‑to‑trough decline; the Sharpe ratio is the mean return divided by the standard deviation scaled by the square root of the number of observations.  The backtester is deliberately simple and does not account for limit orders, slippage or short positions.

* **Example extraction** – The `find_examples` function takes the OHLC data, the combined signal and a dictionary of indicator frames and selects the last *N* non‑zero signal events.  For each example it slices a window of data around the signal, plots the close price with Bollinger Bands, overlays the MACD and signal lines on a secondary axis and draws a vertical magenta line at the bar when the rule fired.  It saves the PNG to a configurable directory and returns metadata (timestamp, signal direction, relative performance over the look‑ahead window and the filename).  These images are served by FastAPI from the `/examples` path.

## Demonstration and Results

The notebook `analytics/notebooks/backtesting_demo.ipynb` walks through an example using the 4‑hour BTCUSDT data from the last 18 months.  It fetches OHLC data, computes Bollinger Bands and MACD, builds an AND rule where both a Bollinger band breach and a MACD cross must occur in the same bar, runs the backtest and extracts three recent examples.  You can reproduce the results by running:

```
make up
make seed
jupyter notebook analytics/notebooks/backtesting_demo.ipynb
```

Within the notebook you will see code that:

* Calls `fetch_ohlc` asynchronously to retrieve the candles;
* Computes indicators and the combined signal;
* Runs `backtest_strategy` and prints metrics such as final PnL, win rate, drawdown and Sharpe ratio;
* Calls `find_examples` to generate three example charts and displays their metadata.

Because external package installation is restricted in this environment the notebook does not include executed outputs here.  When run in the provided Docker Compose environment the backtest should produce a handful of trades over the 18‑month period.  You may observe that requiring both Bollinger and MACD confirmation reduces the number of signals but helps avoid false positives; however, performance metrics will vary depending on the chosen parameters.  The example charts clearly illustrate the entry bars and subsequent price movement, allowing you to judge the rule’s usefulness.

## Limitations and Future Work

1. **Data quality and latency** – The demo uses free public APIs without guaranteed uptime or accuracy.  Binance limits klines to 1 000 per request and CoinGecko only offers hourly or daily bars.  For serious trading a paid data provider with tick‑level accuracy would be preferable.
2. **Look‑ahead bias** – Although the backtester executes trades on the next close after a signal, there is still potential look‑ahead bias if indicators are computed on the same bar as the signal.  Care should be taken to offset indicators appropriately.
3. **Web application completeness** – The Next.js front‑end included here demonstrates authentication, watchlist management and backtesting.  It lacks advanced features such as real‑time charts via WebSockets, a rule builder UI or portfolio tracking.  Those could be added incrementally.
4. **Hardware integration** – The current stack runs entirely in containers.  To deploy on physical hardware you would install the `price_feeder_py` on a Raspberry Pi, deploy the MQTT broker on a network host and flash the ESP32 with a MicroPython or C++ sketch subscribing to the same topics and rendering to an actual OLED.  The Python ESP32 simulator shows how a 24×6 display could be populated.  Libraries such as [MicroPython urequests](https://docs.micropython.org/en/latest/library/urequests.html) and [uMQTT](https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple) would be used on the microcontroller.

## Conclusion

This project delivers a modular and extensible IoT‑style crypto monitoring platform.  The backtesting engine is sufficiently flexible to combine multiple indicators via logical rules and to surface concrete historical signals.  By running everything in Docker Compose you can demonstrate the full pipeline—from live price ingestion through indicator computation, signal generation, alerting and a simple user interface—without any physical hardware.  Once real devices are available you can reuse the same MQTT topics and business logic, replacing the simulators with firmware on the Raspberry Pi and ESP32.