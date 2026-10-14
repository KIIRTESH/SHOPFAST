import uuid
import pytest
import httpx
from app.main import app

@pytest.mark.asyncio
async def test_customer_registration_and_login_flow():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        test_username = f"user_{uuid.uuid4().hex[:8]}"
        # 1. Register customer
        reg_payload = {
            "username": test_username,
            "display_name": "Test Shopper",
            "pin": "4321"
        }
        reg_resp = await client.post("/api/v1/auth/register", json=reg_payload)
        assert reg_resp.status_code == 201
        reg_data = reg_resp.json()
        assert "token" in reg_data
        assert reg_data["username"] == test_username
        assert reg_data["role"] == "customer"
        token = reg_data["token"]

        # 2. Get current user profile with token
        me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["username"] == test_username
        assert me_data["display_name"] == "Test Shopper"

        # 3. Login with credentials
        login_payload = {
            "username": test_username,
            "pin": "4321"
        }
        login_resp = await client.post("/api/v1/auth/login", json=login_payload)
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        assert "token" in login_data
        assert login_data["username"] == test_username
        new_token = login_data["token"]

        # 4. Check customer orders history (empty initially)
        orders_resp = await client.get("/api/v1/customer/orders", headers={"Authorization": f"Bearer {new_token}"})
        assert orders_resp.status_code == 200
        orders = orders_resp.json()
        assert isinstance(orders, list)

        # 5. Logout
        logout_resp = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {new_token}"})
        assert logout_resp.status_code == 204

        # After logout, token should be invalid
        me_after_logout = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_staff_admin_login():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Pre-seeded staff account
        payload = {
            "username": "staff03",
            "pin": "1234"
        }
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"
        assert data["counter_number"] == "03"


@pytest.mark.asyncio
async def test_product_search():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Search by keyword
        resp = await client.get("/api/v1/products?search=milk")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) > 0
        assert any("milk" in item["name"].lower() for item in items)

        # Search by barcode
        resp2 = await client.get("/api/v1/products?search=890103038384")
        assert resp2.status_code == 200
        items2 = resp2.json()
        assert len(items2) == 1
        assert items2[0]["barcode"] == "890103038384"


@pytest.mark.asyncio
async def test_order_qr_image_and_customer_flow():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Login customer01
        login_res = await client.post("/api/v1/auth/login", json={"username": "customer01", "pin": "1234"})
        assert login_res.status_code == 200
        token = login_res.json()["token"]

        # Create an order
        order_payload = {
            "customer_identifier": "Customer One",
            "items": [
                {
                    "product_barcode": "890103038384",
                    "product_name": "Amul Taaza Milk 500ml",
                    "unit_price": 27.0,
                    "quantity": 2
                }
            ],
            "payment_method": "UPI",
            "payment_status": "PAID"
        }
        order_res = await client.post(
            "/api/v1/orders",
            json=order_payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert order_res.status_code == 201
        order_data = order_res.json()
        order_number = order_data["order_number"]

        # Test QR image generation
        qr_res = await client.get(
            f"/api/v1/orders/{order_number}/qr-image",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert qr_res.status_code == 200
        assert qr_res.headers["content-type"] == "image/png"
        assert len(qr_res.content) > 100

        # Test customer order detail
        detail_res = await client.get(
            f"/api/v1/customer/orders/{order_number}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert detail_res.status_code == 200
        assert detail_res.json()["order_number"] == order_number
