"""Each login page (portal) only accepts its own kind of account."""
import pytest
import httpx
from app.main import app

# Demo accounts seeded in dev/test: customer01 (customer), staff01 (counter staff,
# role "admin"), admin (store administrator, role "store_admin"). All use PIN 1234.
CUSTOMER = "customer01"
STAFF = "staff01"
ADMIN = "admin"


async def _login(client, username, portal, pin="1234"):
    body = {"username": username, "pin": pin}
    if portal is not None:
        body["portal"] = portal
    return await client.post("/api/v1/auth/login", json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("username,portal,expected", [
    (CUSTOMER, "customer", 200),
    (CUSTOMER, "staff", 403),
    (CUSTOMER, "admin", 403),
    (STAFF, "staff", 200),
    (STAFF, "customer", 403),
    (STAFF, "admin", 403),
    (ADMIN, "admin", 200),
    (ADMIN, "customer", 403),
    (ADMIN, "staff", 403),
])
async def test_portal_matrix(username, portal, expected):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await _login(client, username, portal)
        assert res.status_code == expected, res.text
        if expected == 403:
            # A rejected portal login must not hand out a session token.
            assert "token" not in res.json()
            assert "access_token" not in res.json()


@pytest.mark.asyncio
async def test_login_without_portal_still_works():
    """Backward compatibility: older clients that send no portal keep working."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for username in (CUSTOMER, STAFF, ADMIN):
            res = await _login(client, username, None)
            assert res.status_code == 200, f"{username}: {res.text}"


@pytest.mark.asyncio
async def test_unknown_portal_value_rejected():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await _login(client, CUSTOMER, "superuser")
        assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_wrong_pin_never_reveals_account_type():
    """Bad credentials give the same generic 401 whatever the portal, so the
    portal check cannot be used to discover which usernames are staff/admin."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for portal in ("customer", "staff", "admin"):
            res = await _login(client, ADMIN, portal, pin="9999")
            assert res.status_code == 401, res.text
            assert res.json()["detail"] == "Invalid username or PIN."
