import pytest
import httpx
from app.main import app
from app.db.init_db import init_db

@pytest.mark.asyncio
async def test_admin_single_login_and_dashboard_access():
    """Scenario 1: Home/Admin login -> one credential submission -> direct Admin Dashboard access."""
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Single login submission
        res = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert "access_token" in data
        assert data["token"] == data["access_token"]
        assert data["role"] == "store_admin"
        assert data["username"] == "admin"
        token = data["token"]

        # 2. Direct Admin Dashboard analytics access with the established token (no second login)
        headers = {"Authorization": f"Bearer {token}"}
        analytics = await client.get("/api/v1/admin/analytics", headers=headers)
        assert analytics.status_code == 200
        assert "total_revenue" in analytics.json() or "today_sales_total" in analytics.json()


@pytest.mark.asyncio
async def test_staff_single_login_and_dashboard_access():
    """Scenario 2: Home/Staff login -> one credential submission -> direct assigned Staff Dashboard access."""
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Single login submission
        res = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["role"] in ("admin", "staff")
        assert data["counter_number"] == "01"
        token = data["token"]

        # 2. Direct Staff Dashboard access with the established token (no second login)
        headers = {"Authorization": f"Bearer {token}"}
        dash = await client.get("/api/v1/staff/dashboard", headers=headers)
        assert dash.status_code == 200
        dash_data = dash.json()
        assert dash_data["counter_number"] == "01"


@pytest.mark.asyncio
async def test_invalid_credentials_prevent_session():
    """Scenarios 3 & 4: Invalid Admin and Staff credentials never create an authenticated session."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Invalid Admin PIN
        res_admin = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "0000"})
        assert res_admin.status_code == 401
        assert "Invalid" in res_admin.json()["detail"]

        # Invalid Staff PIN
        res_staff = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "9999"})
        assert res_staff.status_code == 401

        # Non-existent user
        res_fake = await client.post("/api/v1/auth/login", json={"username": "nonexistent_user", "pin": "1234"})
        assert res_fake.status_code == 401


@pytest.mark.asyncio
async def test_refresh_and_session_persistence():
    """Scenario 5: Refreshing an authenticated session preserves identity without re-prompting."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Multiple simulated page reloads/profile checks
        for _ in range(3):
            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["username"] == "admin"


@pytest.mark.asyncio
async def test_logout_and_relogin_cycle():
    """Scenario 8: Logging out invalidates the session and allows fresh login."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={"username": "staff02", "pin": "1234"})
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Logout
        logout_res = await client.post("/api/v1/auth/logout", headers=headers)
        assert logout_res.status_code == 204

        # Old token is now invalid
        me_fail = await client.get("/api/v1/auth/me", headers=headers)
        assert me_fail.status_code == 401

        # Relogin succeeds and creates a new valid token
        relogin_res = await client.post("/api/v1/auth/login", json={"username": "staff02", "pin": "1234"})
        assert relogin_res.status_code == 200
        new_token = relogin_res.json()["token"]
        new_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert new_me.status_code == 200


@pytest.mark.asyncio
async def test_staff_cannot_access_admin_dashboard():
    """Scenario 9: Staff account attempting to access Store Admin Dashboard is forbidden."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Store admin-only analytics endpoint
        res = await client.get("/api/v1/admin/analytics", headers=headers)
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_staff_login_routes():
    """Scenario 11: Route aliases /admin/login and /staff/login serve HTML pages with 200."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r_admin = await client.get("/admin/login")
        assert r_admin.status_code == 200
        assert "html" in r_admin.headers.get("content-type", "")

        r_staff = await client.get("/staff/login")
        assert r_staff.status_code == 200
        assert "html" in r_staff.headers.get("content-type", "")
