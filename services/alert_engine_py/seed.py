"""
Seed the database with a demo user, watchlist and thresholds.  This
script runs inside the alert_engine container which already has
SQLAlchemy models defined.  It can be invoked via docker compose exec:

    docker compose exec alert_engine python seed.py
"""
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from alert_engine import engine, Base, User, Watchlist, Threshold


def main():
    email = os.environ.get("DEMO_EMAIL", "demo@example.com")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(email=email, created_at=datetime.now(timezone.utc))
            session.add(user)
            print(f"Created user {email}")
        for sym in ["bitcoin", "ethereum"]:
            exists = session.execute(
                select(Watchlist).where(Watchlist.user_email == email, Watchlist.symbol == sym)
            ).scalar_one_or_none()
            if exists is None:
                session.add(Watchlist(user_email=email, symbol=sym))
                print(f"Added {sym} to watchlist")
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