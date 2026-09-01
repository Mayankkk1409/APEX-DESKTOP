"""Seed a paper demo user. Passwords hashed with argon2 — no secrets in source."""
import asyncio

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models.trading import WatchlistItem
from app.models.user import User
from app.security import hash_password


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.username == "trader"))
        if existing:
            print("seed: trader already exists")
            return
        user = User(
            full_name="APEX Demo Trader",
            username="trader",
            email="trader@example.com",
            password_hash=hash_password("ApexDemo!23"),
            account_mode="paper_funded",
            starting_balance=25000,
            cash_balance=25000,
            buying_power=25000,
            portfolio_value=25000,
        )
        db.add(user)
        await db.flush()
        for sym in ("SPX", "AAPL", "NVDA", "MSFT"):
            db.add(WatchlistItem(user_id=user.id, symbol=sym))
        await db.commit()
        print("seed: trader / ApexDemo!23 (paper_funded $25,000)")


if __name__ == "__main__":
    asyncio.run(main())
