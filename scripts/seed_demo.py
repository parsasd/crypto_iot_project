"""
Seed the development database with a demo user, watchlist entries,
and price thresholds.  This script is intended to be run via ``make seed``
inside the Docker Compose environment.  It connects to the database
using the DATABASE_URL environment variable.
"""
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # ensure local modules can be imported
from services.alert_engine_py.alert_engine import Base, User, Watchlist, Threshold, engine  # type: ignore


def main():
    email = os.environ.get("DEMO_EMAIL", "demo@example.com")
    # Ensure tables exist
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # Insert user if not exists
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(email=email, created_at=datetime.now(timezone.utc))
            session.add(user)
            print(f"Created user {email}")
        # Insert watchlist symbols
        watch_symbols = ["bitcoin", "ethereum"]
        for sym in watch_symbols:
            exists = session.execute(
                select(Watchlist).where(Watchlist.user_email == email, Watchlist.symbol == sym)
            ).scalar_one_or_none()
            if exists is None:
                session.add(Watchlist(user_email=email, symbol=sym))
                print(f"Added {sym} to watchlist")
        # Insert thresholds
        thresholds = [
            {"symbol": "bitcoin", "above_price": 60000.0, "below_price": 58000.0},
            {"symbol": "ethereum", "above_price": 4000.0, "below_price": 3500.0},
        ]
        for t in thresholds:
            exists = session.execute(
                select(Threshold).where(
                    Threshold.user_email == email,
                    Threshold.symbol == t["symbol"],
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(Threshold(
                    user_email=email,
                    symbol=t["symbol"],
                    above_price=t["above_price"],
                    below_price=t["below_price"],
                ))
                print(f"Added threshold for {t['symbol']}")
        session.commit()
        print("Seeding complete")


if __name__ == "__main__":
    main()