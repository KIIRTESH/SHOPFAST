"""
ShopFast — Safe SQLite to PostgreSQL Backup & Migration Utility

This script safely migrates existing SQLite records to a target PostgreSQL database
without deleting or modifying the source SQLite database.

Usage:
    python backend/scripts/migrate_sqlite_to_postgres.py --sqlite-path ./fastshop.db --postgres-url "postgresql+asyncpg://user:pass@host:5432/fastshop"
"""
import argparse
import asyncio
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add backend to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.base import Base
from app.models.user import User
from app.models.counter import Counter
from app.models.product import Product
from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem
from app.models.queue import QueueTicket
from app.models.session import UserSession


async def migrate(sqlite_path: str, postgres_url: str):
    print(f"[{datetime.now()}] Starting ShopFast Database Migration...")

    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite source database not found at {sqlite_path}")
        sys.exit(1)

    # Step 1: Create a safe physical backup of the SQLite database
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{sqlite_path}.backup_{timestamp}"
    shutil.copy2(sqlite_path, backup_path)
    print(f"✓ Step 1: Created safe source backup at {backup_path}")

    # Step 2: Normalize PostgreSQL URL
    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif postgres_url.startswith("postgresql://") and not postgres_url.startswith("postgresql+asyncpg://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    sqlite_url = f"sqlite+aiosqlite:///{os.path.abspath(sqlite_path)}"

    src_engine = create_async_engine(sqlite_url)
    dst_engine = create_async_engine(postgres_url)

    # Step 3: Ensure destination schema exists
    print(f"✓ Step 2: Connecting to target PostgreSQL and initializing schema...")
    async with dst_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"✓ Step 3: Schema verified in target database.")

    src_session_maker = async_sessionmaker(bind=src_engine, class_=AsyncSession)
    dst_session_maker = async_sessionmaker(bind=dst_engine, class_=AsyncSession)

    tables_in_order = [
        ("users", User),
        ("counters", Counter),
        ("products", Product),
        ("carts", Cart),
        ("cart_items", CartItem),
        ("orders", Order),
        ("order_items", OrderItem),
        ("queue_tickets", QueueTicket),
        ("user_sessions", UserSession),
    ]

    migration_stats = {}

    async with src_session_maker() as src_sess, dst_session_maker() as dst_sess:
        for tbl_name, model_cls in tables_in_order:
            print(f"Migrating table '{tbl_name}'...")
            res = await src_sess.execute(select(model_cls))
            src_records = res.scalars().all()

            migrated_count = 0
            for record in src_records:
                # Merge into destination session to preserve primary keys & relationships
                await dst_sess.merge(record)
                migrated_count += 1

            await dst_sess.commit()
            migration_stats[tbl_name] = migrated_count
            print(f"  ✓ {tbl_name}: {migrated_count} records migrated.")

        # Step 4: Reset PostgreSQL auto-increment sequences for integer PKs
        if "postgres" in dst_engine.dialect.name.lower():
            print("✓ Step 4: Resetting PostgreSQL ID sequences to match migrated data...")
            async with dst_engine.begin() as conn:
                sequence_tables = [
                    ("users", "id"),
                    ("counters", "id"),
                    ("products", "id"),
                    ("cart_items", "id"),
                    ("orders", "id"),
                    ("order_items", "id"),
                    ("queue_tickets", "id"),
                ]
                for tbl, pk_col in sequence_tables:
                    try:
                        await conn.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{tbl}', '{pk_col}'), "
                            f"COALESCE((SELECT MAX({pk_col}) FROM {tbl}), 1), true);"
                        ))
                    except Exception as seq_err:
                        print(f"  Note: Sequence reset for {tbl}.{pk_col}: {seq_err}")

    await src_engine.dispose()
    await dst_engine.dispose()

    print("\n==========================================")
    print("MIGRATION COMPLETED SUCCESSFULLY")
    print("==========================================")
    for tbl, count in migration_stats.items():
        print(f"  • {tbl}: {count} records transferred")
    print(f"\nSafe backup preserved at: {backup_path}")
    print("==========================================")


def main():
    parser = argparse.ArgumentParser(description="Migrate ShopFast data from SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", default="./fastshop.db", help="Path to SQLite database file")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL connection URL")
    args = parser.parse_args()

    asyncio.run(migrate(args.sqlite_path, args.postgres_url))


if __name__ == "__main__":
    main()
