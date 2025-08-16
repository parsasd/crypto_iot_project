# Crypto IoT Price & Indicator System

This monorepo contains a complete, hardware‑free prototype of an IoT‑inspired cryptocurrency monitoring and trading recommendation system.  It emulates a Raspberry Pi price feeder, an ESP32/OLED display, an alert engine, a Python indicator and backtesting service, and a simple web application.  The project is designed for demonstration on a single machine using Docker Compose and can later be extended to real hardware.

## Quick start

Clone this repository and run the following command to spin up all services, seed a demo user, and open the web application:

```sh
# from the root of this repo
make up      # start Mosquitto, MailHog, Postgres, the services and the webapp
make seed    # create a demo user, watchlist entries and thresholds
make demo    # open the backtest showcase page
```

When `make up` finishes you will have the following stack running:

| Service                   | Description                                  | Port |
| ------------------------- | -------------------------------------------- | ---- |
| Mosquitto broker          | MQTT broker used by all services             | 1883 |
| MailHog                   | SMTP server and web UI for emails            | 1025 / 8025 |
| Postgres                  | Database for user accounts and thresholds    | 5432 |
| Indicator API (FastAPI)   | Computes indicators and runs backtests       | 8000 |
| Price feeder (Python)     | Fetches live prices and publishes to MQTT    | — |
| Alert engine (Python)     | Listens to prices, triggers threshold alerts | — |
| ESP32 simulator (Python)  | Subscribes to MQTT and prints “OLED” output  | — |
| Webapp (Next.js/React)    | User interface and API gateway               | 3000 |

Navigate to `http://localhost:3000` after the stack is up.  Login with the seeded email `demo@example.com`.  The OTP for the demo user will appear in the MailHog web UI (`http://localhost:8025`).  Once logged in you can manage your watchlist, set price thresholds, and run indicator backtests.

For a detailed explanation of the codebase and architecture, please refer to `analytics/reports/REPORT.md`.
