import asyncio
from app.db.init_db import init_db


import pytest_asyncio
import httpx
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    await init_db(reset_stock=True)


@pytest_asyncio.fixture
async def admin_auth_headers():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        assert resp.status_code == 200, f"Admin login failed: {resp.text}"
        token = resp.json()["token"]
        return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def customer_auth_headers():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/login", json={"username": "customer01", "pin": "1234"})
        assert resp.status_code == 200, f"Customer login failed: {resp.text}"
        token = resp.json()["token"]
        return {"Authorization": f"Bearer {token}"}



