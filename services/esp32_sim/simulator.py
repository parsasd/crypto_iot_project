"""
ESP32 OLED simulator.

This service subscribes to one or more MQTT topics and prints a simple
ASCII representation of an OLED display whenever new price updates
arrive.  It calculates simple percentage changes over 1 minute and 1
hour windows and estimates RSI and MACD from recent prices.  It does
not require any hardware.
"""
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import pandas as pd


MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
SYMBOLS = [s.strip() for s in os.environ.get("SYMBOLS", "bitcoin").split(",") if s.strip()]

# maintain history of last 3600 seconds (1 hour) of closes per symbol
history: dict[str, deque] = {sym: deque(maxlen=3600) for sym in SYMBOLS}


def compute_rsi(prices: pd.Series, window: int = 14) -> float:
    if len(prices) < window + 1:
        return float("nan")
    delta = prices.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=window).mean().iloc[-1]
    avg_loss = loss.rolling(window=window).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_macd_arrow(prices: pd.Series) -> str:
    if len(prices) < 26:
        return "?"
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    if macd.iloc[-1] > signal.iloc[-1]:
        return "↑"
    elif macd.iloc[-1] < signal.iloc[-1]:
        return "↓"
    else:
        return "→"


def render_display(sym: str, price: float, delta1m: float | None, delta1h: float | None, rsi: float | float, macd_arrow: str, band_msg: str) -> None:
    """Render a 24x6 character OLED like display."""
    lines = []
    lines.append(f" {sym.upper():<6}  ${price:,.2f}")
    if delta1m is None:
        lines.append(" 1m Δ: N/A")
    else:
        lines.append(f" 1m Δ: {delta1m:+.2%}")
    if delta1h is None:
        lines.append(" 1h Δ: N/A")
    else:
        lines.append(f" 1h Δ: {delta1h:+.2%}")
    rsi_str = f"{rsi:.0f}" if not pd.isna(rsi) else "N/A"
    lines.append(f" RSI: {rsi_str:<3}  MACD: {macd_arrow}")
    lines.append(f" BB: {band_msg:<14}")
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines.append(f" Last: {now}  ")
    # Box drawing
    width = max(len(l) for l in lines) + 2
    print("+" + "-" * width + "+")
    for l in lines:
        print("|" + l.ljust(width) + "|")
    print("+" + "-" * width + "+")


def on_connect(client, userdata, flags, rc):
    print(f"[esp32] Connected with result code {rc}")
    # subscribe to topics
    for sym in SYMBOLS:
        topic = f"crypto/{sym}/ticker"
        client.subscribe(topic)
        print(f"[esp32] Subscribed to {topic}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return
    sym = payload.get("symbol") or msg.topic.split("/")[1]
    price = payload.get("last_price")
    ts = datetime.now(timezone.utc)
    # update history
    hist = history.get(sym)
    if hist is None:
        return
    hist.append((ts, price))
    # compute deltas
    delta1m = delta1h = None
    # convert deque to pandas
    df = pd.DataFrame(list(hist), columns=["ts", "price"])
    df.set_index("ts", inplace=True)
    now = df.index.max()
    one_min = now - pd.Timedelta(minutes=1)
    one_hr = now - pd.Timedelta(hours=1)
    if one_min in df.index or not df[df.index <= one_min].empty:
        past = df[df.index <= one_min]["price"]
        if not past.empty:
            delta1m = price / past.iloc[-1] - 1
    if one_hr in df.index or not df[df.index <= one_hr].empty:
        past = df[df.index <= one_hr]["price"]
        if not past.empty:
            delta1h = price / past.iloc[-1] - 1
    # compute RSI and MACD arrow
    prices_series = df["price"]
    rsi_value = compute_rsi(prices_series)
    macd_arrow = compute_macd_arrow(prices_series)
    # band message: not computed here; placeholder
    band_msg = "--"
    render_display(sym, price, delta1m, delta1h, rsi_value, macd_arrow, band_msg)


def main():
    client = mqtt.Client(client_id=f"esp32-sim-{int(time.time())}",
                     callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, 1883)
    print(f"[esp32] Connecting to MQTT broker at {MQTT_BROKER}:1883")
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)