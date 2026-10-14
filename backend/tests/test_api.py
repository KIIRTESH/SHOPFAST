import pytest
import httpx
from app.main import app

@pytest.mark.asyncio
async def test_health_check():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "FASTSHOP" in data["service"]

@pytest.mark.asyncio
async def test_root_serves_frontend_html():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "SHOPFAST" in response.text.upper() or "FASTSHOP" in response.text.upper()
        # Verify v2.0 PRO badge was removed
        assert "v2.0 PRO" not in response.text
        assert "Enter as Counter Admin" not in response.text

@pytest.mark.asyncio
async def test_list_products():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/products")
        assert response.status_code == 200
        products = response.json()
        assert len(products) > 0
        assert "barcode" in products[0]

@pytest.mark.asyncio
async def test_barcode_lookup():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/products/barcode/890103038384")
        assert response.status_code == 200
        product = response.json()
        assert "Milk" in product["name"]
        assert product["price"] == 68.0

@pytest.mark.asyncio
async def test_create_order_and_lookup(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "customer_identifier": "Customer #T101",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [
                {
                    "product_barcode": "890103038384",
                    "product_name": "Amul Taaza Milk 1L",
                    "unit_price": 68.0,
                    "quantity": 2
                }
            ]
        }
        response = await client.post("/api/v1/orders", json=payload, headers=customer_auth_headers)
        assert response.status_code == 201
        order = response.json()
        assert order["order_number"].startswith("FS-")
        assert order["total_amount"] > 0
        assert order["qr_token"] is not None
        assert "verification_status" in order
        assert order["verification_status"] == "PENDING"
        assert order["is_verified_by_cashier"] is False

        # Test GET /orders/{order_number}
        get_order_resp = await client.get(f"/api/v1/orders/{order['order_number']}", headers=customer_auth_headers)
        assert get_order_resp.status_code == 200
        fetched_order = get_order_resp.json()
        assert fetched_order["order_number"] == order["order_number"]
        assert fetched_order["verification_status"] == "PENDING"

        # Test QR image endpoint
        qr_resp = await client.get(f"/api/v1/orders/{order['order_number']}/qr-image", headers=customer_auth_headers)
        assert qr_resp.status_code == 200
        assert qr_resp.headers["content-type"] == "image/png"
        assert len(qr_resp.content) > 100

@pytest.mark.asyncio
async def test_queue_allocation():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "customer_name": "Queue Test Customer",
            "items_count": 3
        }
        response = await client.post("/api/v1/queue/allocate", json=payload)
        assert response.status_code == 200
        alloc = response.json()
        assert alloc["assigned_counter_number"] is not None
        assert alloc["ticket_number"].startswith("Q-")
