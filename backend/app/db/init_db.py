import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.base import Base
from app.models.product import Product
from app.models.counter import Counter
from app.models.user import User
from app.core.auth import create_pin_hash
from app.core.config import settings
from app.db.session import engine

logger = logging.getLogger("fastshop.init_db")

SEED_PRODUCTS = [
    # Primary catalog products (Requirements 1 & 6) - 100 units initial stock
    {"barcode": "8901719128608", "name": "Parle-G Royale", "price": 25.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Biscuits", "icon": "🍪"},
    {"barcode": "8901063029255", "name": "JimJam", "price": 20.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Biscuits", "icon": "🍪"},
    {"barcode": "8901571005666", "name": "Sensodyne", "price": 245.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Personal Care", "icon": "🪥"},
    {"barcode": "8907611023454", "name": "Paan Churi", "price": 150.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Snacks", "icon": "🍃"},
    {"barcode": "8909106022645", "name": "Lux Soap", "price": 70.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Personal Care", "icon": "🧼"},
    {"barcode": "8906006787377", "name": "Vinegar", "price": 30.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Household", "icon": "🍾"},

    # Extended store items
    {"barcode": "8901058003765", "name": "Maggi 2-Minute Noodles", "price": 56.0, "stock_qty": 150, "initial_stock_qty": 150, "category": "Instant Food", "icon": "🍜"},
    {"barcode": "8901063065406", "name": "Britannia Good Day Biscuits", "price": 40.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Biscuits", "icon": "🍪"},
    {"barcode": "8901030810536", "name": "Surf Excel Matic", "price": 210.0, "stock_qty": 80, "initial_stock_qty": 80, "category": "Household", "icon": "🧺"},
    {"barcode": "8902519009807", "name": "Classmate Notebook", "price": 35.0, "stock_qty": 50, "initial_stock_qty": 50, "category": "Stationery", "icon": "📓"},
    {"barcode": "890103038384", "name": "Amul Taaza Milk 1L", "price": 68.0, "stock_qty": 100, "initial_stock_qty": 100, "category": "Dairy", "icon": "🥛"},
    {"barcode": "890171912401", "name": "Britannia Whole Wheat Bread", "price": 45.0, "stock_qty": 80, "initial_stock_qty": 80, "category": "Bakery", "icon": "🍞"},
    {"barcode": "544900000099", "name": "Coca-Cola Zero 750ml", "price": 40.0, "stock_qty": 60, "initial_stock_qty": 60, "category": "Beverage", "icon": "🥤"},
    {"barcode": "890149110183", "name": "Lay's India's Magic Masala", "price": 30.0, "stock_qty": 120, "initial_stock_qty": 120, "category": "Snacks", "icon": "🥔"},
    {"barcode": "890106301201", "name": "Tropicana Orange Juice 1L", "price": 95.0, "stock_qty": 40, "initial_stock_qty": 40, "category": "Beverage", "icon": "🍊"},
    {"barcode": "762220172584", "name": "Cadbury Oreo Vanilla 120g", "price": 50.0, "stock_qty": 90, "initial_stock_qty": 90, "category": "Biscuits", "icon": "🍪"},
    {"barcode": "890105885264", "name": "Maggi 2-Minute Noodles (4-Pack)", "price": 56.0, "stock_qty": 150, "initial_stock_qty": 150, "category": "Instant Food", "icon": "🍜"},
    {"barcode": "890103035821", "name": "Nescafe Classic Coffee 50g", "price": 180.0, "stock_qty": 35, "initial_stock_qty": 35, "category": "Beverage", "icon": "☕"},
    {"barcode": "7622201412389", "name": "Cadbury Dairy Milk Silk 150g", "price": 175.0, "stock_qty": 65, "initial_stock_qty": 65, "category": "Chocolates", "icon": "🍫"},
    {"barcode": "9002490100070", "name": "Red Bull Energy Drink 250ml", "price": 125.0, "stock_qty": 75, "initial_stock_qty": 75, "category": "Beverage", "icon": "⚡"},
    {"barcode": "8901396388431", "name": "Dettol Original Bathing Soap", "price": 45.0, "stock_qty": 110, "initial_stock_qty": 110, "category": "Personal Care", "icon": "🧼"},
    {"barcode": "8901314010529", "name": "Colgate MaxFresh Toothpaste", "price": 98.0, "stock_qty": 85, "initial_stock_qty": 85, "category": "Personal Care", "icon": "🪥"},
    {"barcode": "8901499008502", "name": "Doritos Cheese Supreme Nachos", "price": 50.0, "stock_qty": 90, "initial_stock_qty": 90, "category": "Snacks", "icon": "🧀"},
]

SEED_COUNTERS = [
    {"counter_number": "01", "name": "Checkout Register 01", "is_express": False, "avg_scan_speed_factor": 1.0},
    {"counter_number": "02", "name": "Checkout Register 02", "is_express": False, "avg_scan_speed_factor": 1.1},
    {"counter_number": "03", "name": "Express Lane 03 (<= 5 Items)", "is_express": True, "avg_scan_speed_factor": 1.4},
    {"counter_number": "04", "name": "Checkout Register 04", "is_express": False, "avg_scan_speed_factor": 0.95},
    {"counter_number": "07", "name": "Fast-Track Counter 07", "is_express": True, "avg_scan_speed_factor": 1.3},
]

# Admin staff accounts — one per counter. Store Administrator operates store-wide.
SEED_ADMIN_USERS = [
    {"username": "admin3", "display_name": "Admin Station", "pin": "333333", "role": "admin", "counter_number": "03"},
    {"username": "admin", "display_name": "Store Administrator", "pin": "1234", "role": "store_admin", "counter_number": None},
    {"username": "staff01", "display_name": "Counter 01 Staff", "pin": "1234", "role": "admin", "counter_number": "01"},
    {"username": "staff02", "display_name": "Counter 02 Staff", "pin": "1234", "role": "admin", "counter_number": "02"},
    {"username": "staff03", "display_name": "Counter 03 Staff", "pin": "1234", "role": "admin", "counter_number": "03"},
    {"username": "staff04", "display_name": "Counter 04 Staff", "pin": "1234", "role": "admin", "counter_number": "04"},
    {"username": "staff07", "display_name": "Counter 07 Staff", "pin": "1234", "role": "admin", "counter_number": "07"},
]

# Demo customer accounts — PIN: 1234
SEED_CUSTOMER_USERS = [
    {"username": "customer", "display_name": "Demo Shopper", "pin": "1234"},
    {"username": "customer01", "display_name": "Test Customer", "pin": "1234"},
    {"username": "guest", "display_name": "Guest Shopper", "pin": "1234"},
]


async def init_db(reset_stock: bool = False):
    """Initializes database schema, applies safe migrations, and seeds reference data."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        is_sqlite = "sqlite" in engine.dialect.name.lower()
        if is_sqlite:
            try:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.execute(text("PRAGMA synchronous=NORMAL;"))
                await conn.execute(text("PRAGMA busy_timeout=30000;"))
            except Exception as pe:
                logger.debug(f"SQLite PRAGMA note: {pe}")

        await conn.run_sync(Base.metadata.create_all)

        # Safe column additions (idempotent — ignored if column already exists)
        # Note: SQLite ALTER TABLE ADD COLUMN does not support FOREIGN KEY clauses
        fk_clause = "" if is_sqlite else " REFERENCES users(id) ON DELETE SET NULL"
        migration_statements = [
            "ALTER TABLE products ADD COLUMN initial_stock_qty INTEGER DEFAULT 100",
            "ALTER TABLE orders ADD COLUMN verification_status VARCHAR(32) DEFAULT 'PENDING'",
            "ALTER TABLE orders ADD COLUMN verification_duration_seconds INTEGER DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN verified_at DATETIME DEFAULT NULL",
            "ALTER TABLE order_items ADD COLUMN verified_quantity INTEGER DEFAULT 0",
            f"ALTER TABLE orders ADD COLUMN user_id INTEGER{fk_clause}",
            "ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(64) DEFAULT NULL",
        ]
        for stmt in migration_statements:
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                logger.debug(f"Migration note (column likely already exists): {e}")

    async with AsyncSession(engine) as session:
        # Upsert products
        for p in SEED_PRODUCTS:
            res = await session.execute(select(Product).where(Product.barcode == p["barcode"]))
            existing = res.scalars().first()
            if not existing:
                session.add(Product(**p))
            else:
                existing.price = p["price"]
                # Do NOT reset stock_qty on restart — preserve live inventory levels.
                # Only update initial_stock_qty for reference tracking (or when reset_stock=True for test fixtures).
                existing.initial_stock_qty = p.get("initial_stock_qty", existing.initial_stock_qty or 100)
                if reset_stock:
                    existing.stock_qty = p.get("stock_qty", 100)
                existing.name = p["name"]
                existing.category = p["category"]
                existing.icon = p["icon"]
                existing.is_active = True

        # Upsert counters
        for c in SEED_COUNTERS:
            res = await session.execute(select(Counter).where(Counter.counter_number == c["counter_number"]))
            if not res.scalars().first():
                session.add(Counter(**c))

        # Seed/update admin staff accounts
        if settings.should_seed_demo_accounts:
            for staff in SEED_ADMIN_USERS:
                res = await session.execute(select(User).where(User.username == staff["username"]))
                existing_user = res.scalars().first()
                staff_role = staff.get("role", "admin")
                if not existing_user:
                    pin_hash, pin_salt = create_pin_hash(staff["pin"])
                    session.add(User(
                        username=staff["username"],
                        display_name=staff["display_name"],
                        pin_hash=pin_hash,
                        pin_salt=pin_salt,
                        role=staff_role,
                        counter_number=staff["counter_number"],
                        is_active=True,
                    ))
                    logger.info(f"Seeded admin user: {staff['username']} → Counter {staff['counter_number']} (role: {staff_role})")
                else:
                    # Do NOT overwrite existing user PINs on restart — preserves user credentials
                    existing_user.role = staff_role
                    existing_user.display_name = staff["display_name"]
                    existing_user.counter_number = staff["counter_number"]
                    existing_user.is_active = True
                    logger.info(f"Verified admin user account exists: {staff['username']} (role: {staff_role})")
        elif settings.INITIAL_ADMIN_USERNAME and settings.INITIAL_ADMIN_PIN:
            # Secure initial store admin provisioning for production environments
            res = await session.execute(select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME))
            if not res.scalars().first():
                pin_hash, pin_salt = create_pin_hash(settings.INITIAL_ADMIN_PIN)
                session.add(User(
                    username=settings.INITIAL_ADMIN_USERNAME,
                    display_name="Store Administrator",
                    pin_hash=pin_hash,
                    pin_salt=pin_salt,
                    role="store_admin",
                    counter_number=None,
                    is_active=True,
                ))
                logger.info(f"Provisioned initial production store admin: {settings.INITIAL_ADMIN_USERNAME}")
        else:
            # Production environment: Verify whether an admin exists, warn if unconfigured
            res = await session.execute(select(User).where(User.role.in_(["store_admin", "admin"])))
            if not res.scalars().first():
                logger.warning(
                    "PRODUCTION SECURITY NOTE: No admin accounts seeded with default credentials. "
                    "Configure INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PIN in your environment."
                )

        # Seed demo customer accounts
        if settings.should_seed_demo_accounts:
            for cust in SEED_CUSTOMER_USERS:
                res = await session.execute(select(User).where(User.username == cust["username"]))
                existing_cust = res.scalars().first()
                if not existing_cust:
                    pin_hash, pin_salt = create_pin_hash(cust["pin"])
                    session.add(User(
                        username=cust["username"],
                        display_name=cust["display_name"],
                        pin_hash=pin_hash,
                        pin_salt=pin_salt,
                        role="customer",
                        is_active=True,
                    ))
                    logger.info(f"Seeded customer user: {cust['username']}")
                elif reset_stock:
                    pin_hash, pin_salt = create_pin_hash(cust["pin"])
                    existing_cust.pin_hash = pin_hash
                    existing_cust.pin_salt = pin_salt
                    existing_cust.role = "customer"
                    existing_cust.is_active = True

        await session.commit()
        logger.info("Database seeding complete.")
