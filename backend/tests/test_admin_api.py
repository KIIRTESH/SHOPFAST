import pytest
import httpx
from app.main import app


@pytest.mark.asyncio
async def test_admin_rbac_unauthorized_and_forbidden():
    """Verify that admin endpoints reject unauthenticated callers with 401 and customer accounts with 403."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unauthenticated request -> 401
        unauth_resp = await client.get("/api/v1/admin/analytics")
        assert unauth_resp.status_code == 401

        # 2. Customer login -> 403 when trying admin endpoint
        cust_login = await client.post("/api/v1/auth/login", json={"username": "customer01", "pin": "1234"})
        assert cust_login.status_code == 200
        cust_token = cust_login.json()["token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        forbidden_resp = await client.get("/api/v1/admin/analytics", headers=cust_headers)
        assert forbidden_resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_analytics(admin_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/analytics", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "today_sales_total" in data
        assert "today_orders_count" in data
        assert "today_verified_count" in data
        assert "counters_overview" in data
        assert len(data["counters_overview"]) > 0


@pytest.mark.asyncio
async def test_admin_verification_workflow(admin_auth_headers, customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create an order with 2 products (1 Maggi, 1 Milk)
        order_payload = {
            "customer_identifier": "Admin Test Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "03",
            "items": [
                {
                    "product_barcode": "8901058003765",
                    "product_name": "Maggi 2-Minute Noodles",
                    "unit_price": 56.0,
                    "quantity": 1
                },
                {
                    "product_barcode": "890103038384",
                    "product_name": "Amul Taaza Milk 1L",
                    "unit_price": 68.0,
                    "quantity": 1
                }
            ]
        }
        order_resp = await client.post("/api/v1/orders", json=order_payload, headers=customer_auth_headers)
        assert order_resp.status_code == 201
        order_data = order_resp.json()
        order_number = order_data["order_number"]

        # 2. Look up the order in the Admin POS Terminal
        lookup_resp = await client.post(
            "/api/v1/admin/verify/lookup",
            json={"token_or_order_number": order_number, "counter_number": "03"},
            headers=admin_auth_headers
        )
        assert lookup_resp.status_code == 200
        detail = lookup_resp.json()
        assert detail["order_number"] == order_number
        assert detail["items_expected_count"] == 2
        assert detail["items_verified_count"] == 0
        assert detail["is_all_matched"] is False

        # 3. Cashier scans an unexpected item NOT in the cart (e.g. Lay's Chips: 890149110183)
        discrepancy_resp = await client.post(
            "/api/v1/admin/verify/scan",
            json={
                "order_number": order_number,
                "scanned_barcode": "890149110183",
                "counter_number": "03"
            },
            headers=admin_auth_headers
        )
        assert discrepancy_resp.status_code == 200
        discrepancy_data = discrepancy_resp.json()
        assert discrepancy_data["status"] == "UNEXPECTED_ITEM"
        assert "NOT IN PAID CART" in discrepancy_data["message"]
        assert discrepancy_data["is_all_matched"] is False

        # 4. Cashier scans 1st expected item (Maggi)
        scan1_resp = await client.post(
            "/api/v1/admin/verify/scan",
            json={
                "order_number": order_number,
                "scanned_barcode": "8901058003765",
                "counter_number": "03"
            },
            headers=admin_auth_headers
        )
        assert scan1_resp.status_code == 200
        scan1_data = scan1_resp.json()
        assert scan1_data["status"] == "MATCHED"
        assert scan1_data["order"]["items_verified_count"] == 1
        assert scan1_data["is_all_matched"] is False

        # 5. Cashier scans 2nd expected item (Milk) -> Triggers ALL_CLEARED
        scan2_resp = await client.post(
            "/api/v1/admin/verify/scan",
            json={
                "order_number": order_number,
                "scanned_barcode": "890103038384",
                "counter_number": "03"
            },
            headers=admin_auth_headers
        )
        assert scan2_resp.status_code == 200
        scan2_data = scan2_resp.json()
        assert scan2_data["status"] == "ALL_CLEARED"
        assert scan2_data["order"]["items_verified_count"] == 2
        assert scan2_data["is_all_matched"] is True

        # 6. Cashier completes verification and clearance
        complete_resp = await client.post(
            "/api/v1/admin/verify/complete",
            json={
                "order_number": order_number,
                "counter_number": "03",
                "duration_seconds": 18
            },
            headers=admin_auth_headers
        )
        assert complete_resp.status_code == 200
        cleared_data = complete_resp.json()
        assert cleared_data["is_verified_by_cashier"] is True
        assert cleared_data["verification_status"] == "CLEARED"
        assert cleared_data["verification_duration_seconds"] == 18


@pytest.mark.asyncio
async def test_admin_transactions_ledger(admin_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/transactions?limit=10", headers=admin_auth_headers)
        assert resp.status_code == 200
        txs = resp.json()
        assert isinstance(txs, list)
        if txs:
            assert "order_number" in txs[0]
            assert "total_amount" in txs[0]
            assert "verification_status" in txs[0]


@pytest.mark.asyncio
async def test_admin_product_inventory_update(admin_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Check product listing
        p_list = await client.get("/api/v1/admin/products", headers=admin_auth_headers)
        assert p_list.status_code == 200
        products = p_list.json()
        assert len(products) > 0

        target_barcode = products[0]["barcode"]
        orig_price = products[0]["price"]

        # Update price and stock
        new_price = orig_price + 5.0
        up_resp = await client.put(
            f"/api/v1/admin/products/{target_barcode}",
            json={"price": new_price, "stock_qty": 999},
            headers=admin_auth_headers
        )
        assert up_resp.status_code == 200
        updated = up_resp.json()
        assert updated["price"] == new_price
        assert updated["stock_qty"] == 999

        # Restore original price
        await client.put(
            f"/api/v1/admin/products/{target_barcode}",
            json={"price": orig_price, "stock_qty": 100},
            headers=admin_auth_headers
        )
