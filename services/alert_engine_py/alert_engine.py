"""
Alert engine for threshold crossings.

This service listens to MQTT ticker topics and compares incoming
prices against user-defined thresholds stored in the database. When a
price crosses above or below a threshold, an email notification is
sent via SMTP and an entry is recorded in the audit log. A cooldown
mechanism prevents alert storms by ignoring repeated triggers for the
same user and symbol within a short window.
"""
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import Session, declarative_base

import paho.mqtt.client as mqtt


# --- Configuration ------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
SMTP_HOST = os.environ.get("SMTP_HOST", "mailhog")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
MQTT_BROKER = os.environ.get("MQTT_BROKER", "mosquitto")  # works inside Compose network
COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN", "300"))  # default 5 minutes


# --- ORM models ---------------------------------------------------------------

Base = declarative_base()


def seconds_since(dt):
    """Seconds since dt, tolerating tz-naive DB values by assuming UTC."""
    if dt is None:
        return float("inf")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


class Threshold(Base):
    __tablename__ = "thresholds"
    __table_args__ = ({"sqlite_autoincrement": True},)
    id = Column(Integer, primary_key=True)
    user_email = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    above_price = Column(Float, nullable=True)
    below_price = Column(Float, nullable=True)
    # tz-aware; seconds_since() still handles old naive rows
    last_trigger_time = Column(DateTime(timezone=True), nullable=True)


class AlertLog(Base):
    __tablename__ = "alert_logs"
    id = Column(Integer, primary_key=True)
    user_email = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    message = Column(String, nullable=False)


# Other tables so schema is centralized
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OTP(Base):
    __tablename__ = "otps"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    code = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    failed_attempts = Column(Integer, default=0)


class Watchlist(Base):
    __tablename__ = "watchlists"
    id = Column(Integer, primary_key=True)
    user_email = Column(String, nullable=False)
    symbol = Column(String, nullable=False)


engine = create_engine(DATABASE_URL, future=True)
Base.metadata.create_all(engine)  # create if missing; no destructive changes


# --- Email --------------------------------------------------------------------

def send_email(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = "noreply@crypto.iot"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host=SMTP_HOST, port=SMTP_PORT) as smtp:
        smtp.send_message(msg)
    print(f"[alert] Sent email to {to_email}: {subject}")


# --- Core logic ----------------------------------------------------------------

def handle_price(payload: dict) -> None:
    symbol = payload.get("symbol")
    price = payload.get("last_price")
    if symbol is None or price is None:
        return

    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        thresholds = session.execute(
            select(Threshold).where(Threshold.symbol == symbol)
        ).scalars().all()

        for th in thresholds:
            crossed = False
            direction = ""

            if th.above_price is not None and price >= th.above_price:
                crossed = True
                direction = "above"
            if th.below_price is not None and price <= th.below_price:
                crossed = True
                direction = "below"

            if not crossed:
                continue

            # Cooldown check — **this is the crash fix**
            if seconds_since(th.last_trigger_time) < COOLDOWN_SECONDS:
                continue

            # Send email
            subject = f"{symbol.upper()} price {direction} threshold"
            body = f"The price of {symbol.upper()} is now {price:.2f}, {direction} your threshold."
            send_email(th.user_email, subject, body)

            # Update last_trigger_time and log
            th.last_trigger_time = now
            session.add(
                AlertLog(
                    user_email=th.user_email,
                    symbol=symbol,
                    price=price,
                    timestamp=now,
                    message=subject,
                )
            )

        session.commit()


# --- MQTT callbacks -----------------------------------------------------------

def on_connect(client, userdata, flags, rc):
    print(f"[alert] Connected to MQTT broker with result {rc}")
    client.subscribe("crypto/+/ticker")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return
    handle_price(payload)


# --- Entrypoint ---------------------------------------------------------------

def main():
    # Wait for DB to be ready
    connected = False
    for _ in range(10):
        try:
            with engine.connect():
                connected = True
                break
        except Exception as e:
            print("[alert] Waiting for DB...", e)
            time.sleep(2)

    if not connected:
        print("[alert] Could not connect to DB")
        sys.exit(1)

    print(f"[alert] Connecting to MQTT broker at {MQTT_BROKER}:1883")
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, 1883)
    client.loop_forever()


if __name__ == "__main__":
    main()
