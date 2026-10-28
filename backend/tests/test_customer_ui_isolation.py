"""Regression test: Customer app UI must not contain Staff POS Terminal or Admin options."""
import pytest
import httpx
from app.main import app


@pytest.mark.asyncio
async def test_customer_ui_has_no_staff_or_admin_terminal_entry_points():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/shop")
        assert res.status_code == 200
        html = res.text
        # Ensure customer navigation does not present staff or admin options
        assert "Staff POS Terminal" not in html
        assert "Admin Terminal" not in html
        assert "Admin Management" not in html
        assert "authCounterSelectCard" not in html
        assert "launchAdminTerminal" not in html


@pytest.mark.asyncio
async def test_staff_and_admin_routes_remain_fully_accessible():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        staff_res = await client.get("/staff")
        assert staff_res.status_code == 200
        assert "Staff POS Terminal" in staff_res.text or "Staff Terminal" in staff_res.text or "Staff" in staff_res.text

        admin_res = await client.get("/admin")
        assert admin_res.status_code == 200
        assert "Admin" in admin_res.text
