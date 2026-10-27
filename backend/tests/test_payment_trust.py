"""Checkout must not trust client-supplied payment fields."""
import pytest
import httpx
from app.main import app

ITEM = {
    "product_barcode": "8901058003765",
    "product_name": "Maggi",
    "unit_price": 56.0,
    "quantity": 1,
}


@pytest.mark.asyncio
async def test_client_cannot_choose_payment_status(customer_auth_headers):
    """A client-sent payment_status is ignored; the server decides it."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/orders", json={
            "payment_method": "UPI",
            "payment_status": "SOMETHING_THE_CLIENT_MADE_UP",
            "items": [ITEM],
        }, headers=customer_auth_headers)
        assert res.status_code == 201, res.text
        # Server-decided value (demo mode) — never the client's string.
        assert res.json()["payment_status"] == "PAID"


@pytest.mark.asyncio
async def test_invalid_payment_method_rejected(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/orders", json={
            "payment_method": "BITCOIN",
            "items": [ITEM],
        }, headers=customer_auth_headers)
        assert res.status_code == 422, res.text
