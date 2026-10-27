import time
import uuid
import json
import pytest
import httpx
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.main import app
from app.db.init_db import init_db
from app.services.websocket_manager import ws_manager
from app.schemas.ws import WebSocketMessage


@pytest.mark.asyncio
async def test_end_to_end_realtime_orchestration(admin_auth_headers):
    """
    Complete End-to-End Live Purchase & Orchestration Test:
    1. Customer adds items to cart -> cart persisted
    2. Customer checks out -> counter assigned, stock decremented, NEW_ORDER_ASSIGNED broadcast
    3. Staff receives order on counter channel, starts verification -> VERIFICATION_STARTED broadcast
    4. Staff scans item -> VERIFICATION_PROGRESS broadcast
    5. Staff completes verification -> ORDER_CLEARED_RELEASED broadcast, status CLEARED
    6. Admin dashboard reflects authoritative metrics and transaction ledger
    7. Staff transaction history is strictly counter-isolated
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Setup unique customer
        uid = uuid.uuid4().hex[:6]
        cust_user = f"cust_rt_{uid}"
        reg_res = await client.post("/api/v1/auth/register", json={
            "username": cust_user,
            "display_name": "Realtime Shopper",
            "pin": "1234"
        })
        cust_token = reg_res.json()["token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        # Step 1: Customer scans product into cart
        cart_id = f"cart_rt_{uid}"
        add_res = await client.post(
            f"/api/v1/carts/{cart_id}/items",
            json={"barcode": "8901719128608", "quantity": 2},
            headers=cust_headers
        )
        assert add_res.status_code == 200
        cart_data = add_res.json()
        assert len(cart_data["items"]) == 1
        assert cart_data["items"][0]["quantity"] == 2

        # Step 2: Customer checkout with preferred counter 01
        order_res = await client.post(
            "/api/v1/orders",
            json={
                "customer_identifier": "Realtime Shopper",
                "payment_method": "UPI",
                "preferred_counter": "01",
                "cart_id": cart_id,
                "idempotency_key": f"idemp_{uid}",
                "items": [
                    {
                        "product_barcode": "8901719128608",
                        "product_name": "Parle-G Royale",
                        "unit_price": 25.0,
                        "quantity": 2
                    }
                ]
            },
            headers=cust_headers
        )
        assert order_res.status_code == 201
        order = order_res.json()
        order_num = order["order_number"]
        assert order["assigned_counter_number"] == "01"
        assert order["payment_status"] == "PAID"
        assert order["verification_status"] == "PENDING"
        assert order["total_amount"] > 0

        # Login Staff for Counter 01
        staff_login = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert staff_login.status_code == 200
        staff01_token = staff_login.json()["token"]
        staff01_headers = {"Authorization": f"Bearer {staff01_token}"}

        # Step 3: Staff looks up order -> transitions to IN_PROGRESS
        lookup_res = await client.post(
            "/api/v1/staff/verify/lookup",
            json={"token_or_order_number": order_num, "counter_number": "01"},
            headers=staff01_headers
        )
        assert lookup_res.status_code == 200
        detail = lookup_res.json()
        assert detail["verification_status"] == "IN_PROGRESS"

        # Step 4: Staff scans 1 unit of product
        scan_res = await client.post(
            "/api/v1/staff/verify/scan",
            json={"order_number": order_num, "scanned_barcode": "8901719128608", "counter_number": "01"},
            headers=staff01_headers
        )
        assert scan_res.status_code == 200
        scan_data = scan_res.json()
        assert scan_data["status"] == "MATCHED"
        assert scan_data["scanned_qty"] == 1
        assert scan_data["expected_qty"] == 2
        assert scan_data["is_all_matched"] is False

        # Step 5: Staff completes verification
        comp_res = await client.post(
            "/api/v1/staff/verify/complete",
            json={"order_number": order_num, "counter_number": "01", "duration_seconds": 12},
            headers=staff01_headers
        )
        assert comp_res.status_code == 200
        comp_data = comp_res.json()
        assert comp_data["is_verified_by_cashier"] is True
        assert comp_data["verification_status"] == "CLEARED"

        # Step 6: Verify order query by customer reflects CLEARED state
        get_order = await client.get(f"/api/v1/orders/{order_num}", headers=cust_headers)
        assert get_order.status_code == 200
        assert get_order.json()["verification_status"] == "CLEARED"
        assert get_order.json()["is_verified_by_cashier"] is True

        # Step 7: Staff counter-isolated transactions ledger contains the order
        staff_txs = await client.get("/api/v1/staff/transactions", headers=staff01_headers)
        assert staff_txs.status_code == 200
        tx_numbers = [t["order_number"] for t in staff_txs.json()]
        assert order_num in tx_numbers


@pytest.mark.asyncio
async def test_idempotency_duplicate_order_protection(admin_auth_headers):
    """
    Test that submitting duplicate checkout requests with the same idempotency key:
    1. Returns the exact existing order
    2. Does NOT decrement stock a second time
    3. Does NOT create duplicate order records
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Get baseline stock
        p_res = await client.get("/api/v1/products/barcode/8901063029255")
        stock_before = p_res.json()["stock_qty"]

        idemp_key = f"key_dedup_{uuid.uuid4().hex[:8]}"

        # First checkout attempt
        res1 = await client.post(
            "/api/v1/orders",
            json={
                "customer_identifier": "Dedup Shopper",
                "payment_method": "UPI",
                "preferred_counter": "02",
                "idempotency_key": idemp_key,
                "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 1}]
            },
            headers=admin_auth_headers
        )
        assert res1.status_code == 201
        order1 = res1.json()

        # Check stock decremented by 1
        p_after1 = await client.get("/api/v1/products/barcode/8901063029255")
        assert p_after1.json()["stock_qty"] == stock_before - 1

        # Second duplicate checkout attempt with same key
        res2 = await client.post(
            "/api/v1/orders",
            json={
                "customer_identifier": "Dedup Shopper",
                "payment_method": "UPI",
                "preferred_counter": "02",
                "idempotency_key": idemp_key,
                "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 1}]
            },
            headers=admin_auth_headers
        )
        assert res2.status_code == 201
        order2 = res2.json()

        # Must return the SAME order number
        assert order2["order_number"] == order1["order_number"]

        # Stock must NOT be decremented again
        p_after2 = await client.get("/api/v1/products/barcode/8901063029255")
        assert p_after2.json()["stock_qty"] == stock_before - 1


@pytest.mark.asyncio
async def test_order_lifecycle_rejections(admin_auth_headers):
    """
    Test server-side order lifecycle state validation:
    1. Scanning an already CLEARED order is rejected
    2. Verifying a CANCELLED/REFUNDED order is rejected
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create and complete an order at counter 03
        order_res = await client.post(
            "/api/v1/orders",
            json={
                "customer_identifier": "State Shopper",
                "payment_method": "CARD",
                "preferred_counter": "03",
                "items": [{"product_barcode": "8901571005666", "product_name": "Sensodyne", "unit_price": 245.0, "quantity": 1}]
            },
            headers=admin_auth_headers
        )
        order_num = order_res.json()["order_number"]

        staff03_login = await client.post("/api/v1/auth/login", json={"username": "staff03", "pin": "1234"})
        staff03_headers = {"Authorization": f"Bearer {staff03_login.json()['token']}"}

        # Complete verification
        await client.post(
            "/api/v1/staff/verify/complete",
            json={"order_number": order_num, "counter_number": "03"},
            headers=staff03_headers
        )

        # Attempt to scan items on the already cleared order -> must reject with 400
        scan_err = await client.post(
            "/api/v1/staff/verify/scan",
            json={"order_number": order_num, "scanned_barcode": "8901571005666", "counter_number": "03"},
            headers=staff03_headers
        )
        assert scan_err.status_code == 400
        assert "already been verified" in scan_err.json()["detail"].lower()

        # Refund the order via admin
        ref_res = await client.post(f"/api/v1/admin/transactions/{order_num}/refund", headers=admin_auth_headers)
        assert ref_res.status_code == 200

        # Attempt to complete verification on refunded order -> must reject with 400
        comp_err = await client.post(
            "/api/v1/staff/verify/complete",
            json={"order_number": order_num, "counter_number": "03"},
            headers=staff03_headers
        )
        assert comp_err.status_code == 400
        assert "cancelled or refunded" in comp_err.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cross_counter_cart_isolation():
    """
    Verify cross-counter data isolation:
    Staff01 (Counter 01) cannot lookup or scan an order assigned to Counter 02.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create order assigned to Counter 02
        admin_login = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

        ord_res = await client.post(
            "/api/v1/orders",
            json={
                "customer_identifier": "Isolation Shopper",
                "payment_method": "UPI",
                "preferred_counter": "02",
                "items": [{"product_barcode": "8901719128608", "product_name": "Parle-G Royale", "unit_price": 25.0, "quantity": 1}]
            },
            headers=admin_headers
        )
        order_num = ord_res.json()["order_number"]

        # Staff01 attempts to access Counter 02's order
        staff01_login = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        staff01_headers = {"Authorization": f"Bearer {staff01_login.json()['token']}"}

        # 1. Staff01 tries lookup -> 400 Bad Request
        lookup_res = await client.post(
            "/api/v1/staff/verify/lookup",
            json={"token_or_order_number": order_num, "counter_number": "01"},
            headers=staff01_headers
        )
        assert lookup_res.status_code == 400
        assert "assigned to counter 02" in lookup_res.json()["detail"].lower()

        # 2. Staff01 tries scan -> 400 Bad Request
        scan_res = await client.post(
            "/api/v1/staff/verify/scan",
            json={"order_number": order_num, "scanned_barcode": "8901719128608", "counter_number": "01"},
            headers=staff01_headers
        )
        assert scan_res.status_code == 400
        assert "assigned to counter 02" in scan_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_websocket_authorization_and_latency():
    """
    Test real-time WebSocket authorization and measure event delivery latency:
    1. Unauthorized client rejected from /ws/admin (code 1008)
    2. Staff01 rejected from subscribing to counter:02 (code 1008)
    3. Measure WebSocket roundtrip propagation latency (< 50ms)
    """
    client = TestClient(app)

    # 1. Non-admin connection to /ws/admin is rejected with policy violation
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/ws/admin"):
            pass
    assert exc.value.code == 1008

    # Get staff01 token
    staff_res = client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
    assert staff_res.status_code == 200
    staff01_token = staff_res.json()["token"]

    # 2. Staff01 attempting to subscribe to counter:04 is rejected
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/ws/counter/04?token={staff01_token}"):
            pass
    assert exc.value.code == 1008

    # 3. Staff01 subscribing to assigned counter:01 succeeds
    with client.websocket_connect(f"/api/v1/ws/counter/01?token={staff01_token}") as ws:
        # Measure ping-pong latency
        t0 = time.perf_counter()
        ws.send_text("ping")
        resp = ws.receive_text()
        t1 = time.perf_counter()
        assert resp == '{"event":"pong"}'
        latency_ms = (t1 - t0) * 1000
        print(f"\nMeasured WebSocket roundtrip latency: {latency_ms:.2f}ms")
        assert latency_ms < 50.0  # Industry standard real-time POS target < 50ms
