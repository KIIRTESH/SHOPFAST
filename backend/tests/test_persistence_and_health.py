import pytest
import os
import tempfile
from unittest.mock import patch
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text

from app.main import app
from app.core.config import settings
from app.models.base import Base
from app.models.user import User
from app.models.product import Product
from app.models.order import Order, OrderItem
from app.db.init_db import init_db


@pytest.mark.asyncio
async def test_health_check_healthy():
    """Verify that when database is reachable, /health returns 200 OK and connected status."""
    app.state.db_ready = True
    app.state.db_error = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_health_check_unhealthy_when_init_failed():
    """Verify that when DB initialization failed, /health returns 503 Service Unavailable."""
    orig_ready = getattr(app.state, "db_ready", True)
    orig_error = getattr(app.state, "db_error", None)
    try:
        app.state.db_ready = False
        app.state.db_error = "Connection to PostgreSQL refused on port 5432"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["database"] == "uninitialized"
            assert "PostgreSQL" in data["detail"]
    finally:
        app.state.db_ready = orig_ready
        app.state.db_error = orig_error


@pytest.mark.asyncio
async def test_liveness_check():
    """Verify that liveness probe /health/live succeeds regardless of DB state."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_readiness_check_alias():
    """Verify that /health/ready functions as an explicit readiness endpoint."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_health_error_sanitization():
    """Verify that connection string passwords are masked in error details."""
    orig_ready = getattr(app.state, "db_ready", True)
    orig_error = getattr(app.state, "db_error", None)
    try:
        app.state.db_ready = False
        app.state.db_error = "Connection failed to postgresql://admin_user:supersecretpass@db.host.internal:5432/fastshop"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert "supersecretpass" not in data["detail"], "Password leaked in health response!"
            assert "***" in data["detail"], "Password should be masked with ***!"
    finally:
        app.state.db_ready = orig_ready
        app.state.db_error = orig_error


@pytest.mark.asyncio
async def test_health_check_unhealthy_when_db_probe_fails():
    """Verify that when database connection drops, /health active probe returns 503."""
    app.state.db_ready = True
    app.state.db_error = None

    with patch("sqlalchemy.ext.asyncio.AsyncEngine.connect", side_effect=RuntimeError("Database network timeout")):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["database"] == "unavailable"


@pytest.mark.asyncio
async def test_production_seeding_credential_protection():
    """
    Verify that in production (ENVIRONMENT='production'), default demo credentials
    with weak PINs (1234, 333333) are NOT seeded automatically.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        test_url = f"sqlite+aiosqlite:///{tmp_path}"
        test_engine = create_async_engine(test_url)

        with patch("app.db.init_db.engine", test_engine):
            with patch.object(settings, "ENVIRONMENT", "production"):
                with patch.object(settings, "ALLOW_DEFAULT_CREDENTIALS", None):
                    assert settings.should_seed_demo_accounts is False
                    await init_db()

                    async with AsyncSession(test_engine) as session:
                        # Demo accounts must NOT exist
                        res_admin = await session.execute(select(User).where(User.username == "admin"))
                        assert res_admin.scalars().first() is None, "Default admin user should not be seeded in production!"

                        res_admin3 = await session.execute(select(User).where(User.username == "admin3"))
                        assert res_admin3.scalars().first() is None, "Default admin3 user should not be seeded in production!"

                        res_cust = await session.execute(select(User).where(User.username == "customer"))
                        assert res_cust.scalars().first() is None, "Default customer user should not be seeded in production!"

                        # Catalog products and counters should still be seeded
                        res_prod = await session.execute(select(Product))
                        assert len(res_prod.scalars().all()) > 0, "Products should still be seeded in production!"

        await test_engine.dispose()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_actual_database_restart_persistence():
    """
    Actual restart persistence test:
    1. Writes customer, order, and stock decrement records to a database file.
    2. Completely tears down and disposes the SQLAlchemy engine (simulating service shutdown).
    3. Starts a brand-new engine on the same database file (simulating service restart).
    4. Verifies all records, stock levels, and transaction histories persist.
    5. Demonstrates that if the underlying storage is ephemeral (removed on redeploy), records are lost.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_file = tmp.name

    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Phase 1: First startup & write records
    engine1 = create_async_engine(db_url)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker1 = async_sessionmaker(bind=engine1, class_=AsyncSession)
    async with session_maker1() as session:
        # Create a test customer
        cust = User(
            username="persistent_customer",
            display_name="Persistent Shopper",
            pin_hash="hash123",
            pin_salt="salt123",
            role="customer",
            is_active=True,
        )
        session.add(cust)

        # Create a product with live stock
        prod = Product(
            barcode="999000111222",
            name="Persistent Test Product",
            price=99.0,
            stock_qty=45,
            initial_stock_qty=50,
            category="Test",
            is_active=True,
        )
        session.add(prod)
        await session.flush()

        # Create an order
        order = Order(
            order_number="ORD-PERSIST-001",
            customer_identifier="persistent_customer",
            user_id=cust.id,
            subtotal=99.0,
            total_amount=99.0,
            payment_status="PAID",
            payment_method="UPI",
            qr_token="QR-TEST-TOKEN",
            is_verified_by_cashier=True,
            verification_status="CLEARED",
        )
        session.add(order)
        await session.flush()

        order_item = OrderItem(
            order_id=order.id,
            product_barcode="999000111222",
            product_name="Persistent Test Product",
            unit_price=99.0,
            quantity=1,
            total_price=99.0,
        )
        session.add(order_item)
        await session.commit()

    # Completely shutdown engine 1 (simulating process restart)
    await engine1.dispose()

    # Phase 2: Brand new engine reconnecting to the persistent database file
    engine2 = create_async_engine(db_url)
    session_maker2 = async_sessionmaker(bind=engine2, class_=AsyncSession)
    async with session_maker2() as session:
        # Verify customer persists
        res_cust = await session.execute(select(User).where(User.username == "persistent_customer"))
        persisted_cust = res_cust.scalars().first()
        assert persisted_cust is not None, "Customer record lost across restart!"
        assert persisted_cust.display_name == "Persistent Shopper"

        # Verify product and modified stock persist
        res_prod = await session.execute(select(Product).where(Product.barcode == "999000111222"))
        persisted_prod = res_prod.scalars().first()
        assert persisted_prod is not None, "Product record lost across restart!"
        assert persisted_prod.stock_qty == 45, "Inventory stock level was reset on restart!"

        # Verify order and items persist
        res_order = await session.execute(select(Order).where(Order.order_number == "ORD-PERSIST-001"))
        persisted_order = res_order.scalars().first()
        assert persisted_order is not None, "Order record lost across restart!"
        assert persisted_order.payment_status == "PAID"
        assert persisted_order.verification_status == "CLEARED"

    await engine2.dispose()

    # Phase 3: Ephemeral filesystem simulation (Render Free container reset)
    # When Render restarts or redeploys without persistent storage, db_file is deleted
    os.remove(db_file)
    assert not os.path.exists(db_file), "Database file should be absent in fresh container"

    # A new container starting without the file creates an empty database
    engine3 = create_async_engine(db_url)
    async with engine3.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker3 = async_sessionmaker(bind=engine3, class_=AsyncSession)
    async with session_maker3() as session:
        res_lost = await session.execute(select(User).where(User.username == "persistent_customer"))
        assert res_lost.scalars().first() is None, "Demonstrates that ephemeral disk wipes all customer data!"

    await engine3.dispose()
    if os.path.exists(db_file):
        os.remove(db_file)
