"""
Simulated Raspberry Pi price feeder.

This service periodically fetches cryptocurrency prices from
CoinGecko and publishes them to the MQTT broker.  It publishes to
topics of the form ``crypto/<symbol>/ticker`` where ``symbol``
corresponds to the symbol names configured via the environment.

Environment variables:

* MQTT_BROKER: hostname or IP of the MQTT broker (default: localhost)
* SYMBOLS: comma‑separated list of CoinGecko ids (default: bitcoin)
* FETCH_INTERVAL: seconds between fetches (default: 10)

If Binance returns an error for a symbol it falls back to CoinGecko.
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx
import paho.mqtt.client as mqtt


MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
SYMBOLS = [s.strip() for s in os.environ.get("SYMBOLS", "bitcoin").split(",") if s.strip()]
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "10"))


def fetch_prices_coingecko(ids: List[str]) -> Dict[str, float]:
    """Fetch current prices for the given CoinGecko ids in USD."""
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd"}
    try:
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {k: v.get("usd") for k, v in data.items() if v.get("usd") is not None}
    except Exception:
        return {}


def main():
    client = mqtt.Client(client_id=f"feeder-{int(time.time())}",
                     callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    client.connect(MQTT_BROKER, 1883)
    print(f"[feeder] Connected to MQTT broker at {MQTT_BROKER}:1883")
    last_prices: Dict[str, float] = {}
    while True:
        prices = fetch_prices_coingecko(SYMBOLS)
        ts_iso = datetime.now(timezone.utc).isoformat()
        for sym, price in prices.items():
            if price is None:
                continue
            last_price = last_prices.get(sym)
            delta = None if last_price is None else (price - last_price) / last_price
            last_prices[sym] = price
            payload = {
                "symbol": sym,
                "last_price": price,
                "delta": delta,
                "exchange": "coingecko",
                "ts": ts_iso,
            }
            topic = f"crypto/{sym}/ticker"
            client.publish(topic, json.dumps(payload))
            print(f"[feeder] Published {payload} to {topic}")
        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()