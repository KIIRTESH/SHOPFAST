import pytest
import httpx
from app.main import app
from app.models.order import Order
from app.db.session import async_session_maker
from sqlalchemy import select


@pytest.mark.asyncio
async def test_counter_isolation_operational_views(admin_auth_headers, customer_auth_headers):
    """
    Phase 16 Test Scenarios:
    Counter 1: Customer A (Order 101), Customer B (Order 102)
    Counter 2: Customer C (Order 201), Customer D (Order 202)
    Counter 3: Customer E (Order 301)
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create test orders across Counter 01, 02, 03
        orders_spec = [
            {"cust": "Customer A", "counter": "01", "name": "Maggi 2-Minute Noodles", "barcode": "8901058003765", "qty": 1, "price": 56.0},
            {"cust": "Customer B", "counter": "01", "name": "Amul Taaza Milk 1L", "barcode": "890103038384", "qty": 1, "price": 68.0},
            {"cust": "Customer C", "counter": "02", "name": "Britannia JimJam 150g", "barcode": "8901063029255", "qty": 2, "price": 45.0},
            {"cust": "Customer D", "counter": "02", "name": "Parle-G Royale", "barcode": "8901719128608", "qty": 1, "price": 25.0},
            {"cust": "Customer E", "counter": "03", "name": "Sensodyne Rapid Relief 80g", "barcode": "8901571005666", "qty": 1, "price": 180.0},
        ]

        created = {}
        for spec in orders_spec:
            payload = {
                "customer_identifier": spec["cust"],
                "payment_method": "UPI",
                "payment_status": "PAID",
                "preferred_counter": spec["counter"],
                "items": [{
                    "product_barcode": spec["barcode"],
                    "product_name": spec["name"],
                    "unit_price": spec["price"],
                    "quantity": spec["qty"]
                }]
            }
            resp = await client.post("/api/v1/orders", json=payload, headers=customer_auth_headers)
            assert resp.status_code == 201, f"Failed to create order: {resp.text}"
            data = resp.json()
            assert data["assigned_counter_number"] == spec["counter"]
            created[spec["cust"]] = data

        # Test 1: Select Counter 01
        resp_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=admin_auth_headers)
        assert resp_c1.status_code == 200
        c1_orders = resp_c1.json()
        c1_order_nums = {o["order_number"] for o in c1_orders}
        c1_customers = {o["customer_identifier"] for o in c1_orders}

        # Customer A and Customer B MUST appear in Counter 01
        assert created["Customer A"]["order_number"] in c1_order_nums
        assert created["Customer B"]["order_number"] in c1_order_nums
        # Counter 02 and 03 data must NOT leak into Counter 01
        assert created["Customer C"]["order_number"] not in c1_order_nums
        assert created["Customer D"]["order_number"] not in c1_order_nums
        assert created["Customer E"]["order_number"] not in c1_order_nums
        assert "Customer C" not in c1_customers
        assert "Customer D" not in c1_customers
        assert "Customer E" not in c1_customers

        # Test 2: Switch to Counter 02
        resp_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=admin_auth_headers)
        assert resp_c2.status_code == 200
        c2_orders = resp_c2.json()
        c2_order_nums = {o["order_number"] for o in c2_orders}
        c2_customers = {o["customer_identifier"] for o in c2_orders}

        # Counter 01 data must disappear from active Counter 02 view
        assert created["Customer A"]["order_number"] not in c2_order_nums
        assert created["Customer B"]["order_number"] not in c2_order_nums
        # Only Counter 02 data should appear
        assert created["Customer C"]["order_number"] in c2_order_nums
        assert created["Customer D"]["order_number"] in c2_order_nums
        assert created["Customer E"]["order_number"] not in c2_order_nums

        # Test 3: Switch to Counter 03
        resp_c3 = await client.get("/api/v1/admin/orders/active?counter_number=03", headers=admin_auth_headers)
        assert resp_c3.status_code == 200
        c3_orders = resp_c3.json()
        c3_order_nums = {o["order_number"] for o in c3_orders}
        assert created["Customer E"]["order_number"] in c3_order_nums
        assert created["Customer A"]["order_number"] not in c3_order_nums
        assert created["Customer B"]["order_number"] not in c3_order_nums
        assert created["Customer C"]["order_number"] not in c3_order_nums
        assert created["Customer D"]["order_number"] not in c3_order_nums

        # Test 4: Switch back to Counter 01
        resp_c1_revisit = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=admin_auth_headers)
        assert resp_c1_revisit.status_code == 200
        c1_revisit_nums = {o["order_number"] for o in resp_c1_revisit.json()}
        assert created["Customer A"]["order_number"] in c1_revisit_nums
        assert created["Customer B"]["order_number"] in c1_revisit_nums

        # Test 5: Verify invalid counter returns 404
        resp_invalid = await client.get("/api/v1/admin/orders/active?counter_number=99", headers=admin_auth_headers)
        assert resp_invalid.status_code == 404


@pytest.mark.asyncio
async def test_counter_boundary_security(admin_auth_headers, customer_auth_headers):
    """
    Ensure an order assigned to Counter 01 CANNOT be processed or verified
    at Counter 02 terminal.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create an order strictly assigned to Counter 01
        payload = {
            "customer_identifier": "Security Test Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{
                "product_barcode": "8901058003765",
                "product_name": "Maggi 2-Minute Noodles",
                "unit_price": 56.0,
                "quantity": 1
            }]
        }
        res = await client.post("/api/v1/orders", json=payload, headers=customer_auth_headers)
        assert res.status_code == 201
        order = res.json()
        order_num = order["order_number"]

        # 1. Lookup at wrong counter (Counter 02) -> 400 Bad Request
        lookup_wrong = await client.post(
            "/api/v1/admin/verify/lookup",
            headers=admin_auth_headers,
            json={
                "token_or_order_number": order_num,
                "counter_number": "02"
            }
        )
        assert lookup_wrong.status_code == 400
        assert "assigned to Counter 01, not Counter 02" in lookup_wrong.json()["detail"]

        # 2. Scanning item at wrong counter (Counter 02) -> 400 Bad Request
        scan_wrong = await client.post(
            "/api/v1/admin/verify/scan",
            headers=admin_auth_headers,
            json={
                "order_number": order_num,
                "scanned_barcode": "8901058003765",
                "counter_number": "02"
            }
        )
        assert scan_wrong.status_code == 400
        assert "assigned to Counter 01, not Counter 02" in scan_wrong.json()["detail"]

        # 3. Completing verification at wrong counter (Counter 02) -> 400 Bad Request
        complete_wrong = await client.post(
            "/api/v1/admin/verify/complete",
            headers=admin_auth_headers,
            json={
                "order_number": order_num,
                "counter_number": "02"
            }
        )
        assert complete_wrong.status_code == 400
        assert "assigned to Counter 01, not Counter 02" in complete_wrong.json()["detail"]

        # 4. Lookup at correct counter (Counter 01) -> 200 OK
        lookup_correct = await client.post(
            "/api/v1/admin/verify/lookup",
            headers=admin_auth_headers,
            json={
                "token_or_order_number": order_num,
                "counter_number": "01"
            }
        )
        assert lookup_correct.status_code == 200
        assert lookup_correct.json()["order_number"] == order_num


@pytest.mark.asyncio
async def test_global_revenue_system_wide_and_counter_isolation(admin_auth_headers, customer_auth_headers):
    """
    Phase 17 Revenue Requirements:
    - Authoritative system-wide total revenue across all counters
    - Failed/unpaid orders excluded
    - Cancelled orders excluded
    - Switching counters does NOT change global revenue
    - Counter revenue is tracked independently per checkout counter
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Get baseline analytics
        base_resp = await client.get("/api/v1/admin/analytics", headers=admin_auth_headers)
        assert base_resp.status_code == 200
        base_rev = base_resp.json()["total_revenue"]

        # Create paid order at Counter 01
        o1_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Rev Customer 1",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 2}]
        }, headers=customer_auth_headers)
        assert o1_resp.status_code == 201
        o1 = o1_resp.json()

        # Create paid order at Counter 02
        o2_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Rev Customer 2",
            "payment_method": "CARD",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 3}]
        }, headers=customer_auth_headers)
        assert o2_resp.status_code == 201
        o2 = o2_resp.json()

        # Create paid order at Counter 03
        o3_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Rev Customer 3",
            "payment_method": "CASH",
            "payment_status": "PAID",
            "preferred_counter": "03",
            "items": [{"product_barcode": "8901571005666", "product_name": "Sensodyne", "unit_price": 245.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert o3_resp.status_code == 201
        o3 = o3_resp.json()

        # Create UNPAID order -> MUST NOT COUNT IN REVENUE
        await client.post("/api/v1/orders", json={
            "customer_identifier": "Unpaid Customer",
            "payment_method": "UPI",
            "payment_status": "PENDING",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)

        # Create CANCELLED order -> MUST NOT COUNT IN REVENUE
        cancelled_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Cancelled Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        can_order = cancelled_resp.json()
        async with async_session_maker() as db:
            o_res = await db.execute(select(Order).where(Order.order_number == can_order["order_number"]))
            o = o_res.scalar_one()
            o.verification_status = "CANCELLED"
            await db.commit()

        # Check Global Total Revenue
        analytics_resp = await client.get("/api/v1/admin/analytics", headers=admin_auth_headers)
        assert analytics_resp.status_code == 200
        new_rev = analytics_resp.json()["total_revenue"]
        
        expected_added = round(o1["total_amount"] + o2["total_amount"] + o3["total_amount"], 2)
        added_revenue = round(new_rev - base_rev, 2)
        assert added_revenue == expected_added, f"Expected added revenue ₹{expected_added}, got ₹{added_revenue}"

        # Counters list should display counter-specific revenue
        counters_resp = await client.get("/api/v1/counters")
        assert counters_resp.status_code == 200
        counters = {c["counter_number"]: c for c in counters_resp.json()}

        assert counters["01"]["counter_revenue"] >= o1["total_amount"]
        assert counters["02"]["counter_revenue"] >= o2["total_amount"]
        assert counters["03"]["counter_revenue"] >= o3["total_amount"]


@pytest.mark.asyncio
async def test_staff_cross_counter_api_denial_and_isolation(customer_auth_headers):
    """
    Validates strict backend counter isolation:
    1. Order A assigned to Counter 01, Order B assigned to Counter 02.
    2. Counter 01 portal only receives Counter 01 orders.
    3. Counter 02 portal only receives Counter 02 orders.
    4. Direct API attempts by staff01 to access Counter 02's orders/verification/active view are REJECTED with 403.
    5. Direct API attempts by staff02 to access Counter 01's orders are REJECTED with 403.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create Order A for Counter 01
        res_a = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer A (C01)",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi 2-Minute Noodles", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert res_a.status_code == 201
        order_a = res_a.json()
        order_a_num = order_a["order_number"]

        # Create Order B for Counter 02
        res_b = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer B (C02)",
            "payment_method": "CARD",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901063029255", "product_name": "Britannia JimJam 150g", "unit_price": 20.0, "quantity": 2}]
        }, headers=customer_auth_headers)
        assert res_b.status_code == 201
        order_b = res_b.json()
        order_b_num = order_b["order_number"]

        # Login as staff01 (Counter 01 cashier)
        login_s1 = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert login_s1.status_code == 200
        headers_s1 = {"Authorization": f"Bearer {login_s1.json()['token']}"}

        # Login as staff02 (Counter 02 cashier)
        login_s2 = await client.post("/api/v1/auth/login", json={"username": "staff02", "pin": "1234"})
        assert login_s2.status_code == 200
        headers_s2 = {"Authorization": f"Bearer {login_s2.json()['token']}"}

        # 1. Counter 01 portal sees Order A, does NOT see Order B
        c1_active = await client.get("/api/v1/admin/orders/active", headers=headers_s1)
        assert c1_active.status_code == 200
        c1_nums = {o["order_number"] for o in c1_active.json()}
        assert order_a_num in c1_nums
        assert order_b_num not in c1_nums

        # 2. Counter 02 portal sees Order B, does NOT see Order A
        c2_active = await client.get("/api/v1/admin/orders/active", headers=headers_s2)
        assert c2_active.status_code == 200
        c2_nums = {o["order_number"] for o in c2_active.json()}
        assert order_b_num in c2_nums
        assert order_a_num not in c2_nums

        # 3. staff01 attempts to query Counter 02 active orders -> 403 Forbidden
        tamper_active = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_s1)
        assert tamper_active.status_code == 403
        assert "restricted to Counter 01" in tamper_active.json()["detail"]

        # 4. staff01 attempts direct GET /admin/orders/{order_b} -> 403 Forbidden
        direct_admin_get = await client.get(f"/api/v1/admin/orders/{order_b_num}", headers=headers_s1)
        assert direct_admin_get.status_code == 403
        assert "assigned to Counter 02, not Counter 01" in direct_admin_get.json()["detail"]

        # 5. staff01 attempts direct GET /orders/{order_b} -> 403 Forbidden
        direct_order_get = await client.get(f"/api/v1/orders/{order_b_num}", headers=headers_s1)
        assert direct_order_get.status_code == 403

        # 6. staff01 attempts lookup on Counter 02 -> 403 Forbidden
        lookup_tamper = await client.post("/api/v1/admin/verify/lookup", headers=headers_s1, json={
            "token_or_order_number": order_b_num,
            "counter_number": "02"
        })
        assert lookup_tamper.status_code == 403

        # 7. staff01 attempts scan on Counter 02 -> 403 Forbidden
        scan_tamper = await client.post("/api/v1/admin/verify/scan", headers=headers_s1, json={
            "order_number": order_b_num,
            "scanned_barcode": "8901063029255",
            "counter_number": "02"
        })
        assert scan_tamper.status_code == 403

        # 8. staff01 attempts complete verification on Counter 02 -> 403 Forbidden
        comp_tamper = await client.post("/api/v1/admin/verify/complete", headers=headers_s1, json={
            "order_number": order_b_num,
            "counter_number": "02"
        })
        assert comp_tamper.status_code == 403

        # 9. staff01 attempts to view Counter 02 transactions -> 403 Forbidden
        tx_tamper = await client.get("/api/v1/admin/transactions?counter=02", headers=headers_s1)
        assert tx_tamper.status_code == 403

        # 10. staff01 attempts to refund Counter 02 order -> 403 Forbidden
        refund_tamper = await client.post(f"/api/v1/admin/transactions/{order_b_num}/refund", headers=headers_s1)
        assert refund_tamper.status_code == 403

        # 11. staff02 attempts direct access to Counter 01 order -> 403 Forbidden
        s2_to_a = await client.get(f"/api/v1/admin/orders/{order_a_num}", headers=headers_s2)
        assert s2_to_a.status_code == 403
        assert "assigned to Counter 01, not Counter 02" in s2_to_a.json()["detail"]


@pytest.mark.asyncio
async def test_admin_portal_global_access_preserved(customer_auth_headers):
    """
    Confirms Store Admin (admin3 & admin) maintains authorized visibility across all counters.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create orders for Counter 01 and 02
        r1 = await client.post("/api/v1/orders", json={
            "customer_identifier": "Admin View Cust 1",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        o1_num = r1.json()["order_number"]

        r2 = await client.post("/api/v1/orders", json={
            "customer_identifier": "Admin View Cust 2",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        o2_num = r2.json()["order_number"]

        for admin_user, admin_pin in [("admin3", "333333"), ("admin", "1234")]:
            login = await client.post("/api/v1/auth/login", json={"username": admin_user, "pin": admin_pin})
            assert login.status_code == 200, f"Failed login for {admin_user}"
            headers = {"Authorization": f"Bearer {login.json()['token']}"}

            # Admin can view Counter 01
            resp_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=headers)
            assert resp_c1.status_code == 200
            assert o1_num in {o["order_number"] for o in resp_c1.json()}

            # Admin can view Counter 02
            resp_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers)
            assert resp_c2.status_code == 200
            assert o2_num in {o["order_number"] for o in resp_c2.json()}

            # Admin can view order details directly
            det1 = await client.get(f"/api/v1/admin/orders/{o1_num}", headers=headers)
            assert det1.status_code == 200
            det2 = await client.get(f"/api/v1/admin/orders/{o2_num}", headers=headers)
            assert det2.status_code == 200

            # Admin can view store-wide transactions across all counters
            tx_all = await client.get("/api/v1/admin/transactions", headers=headers)
            assert tx_all.status_code == 200
            tx_nums = {t["order_number"] for t in tx_all.json()}
            assert o1_num in tx_nums
            assert o2_num in tx_nums


@pytest.mark.asyncio
async def test_logout_and_login_isolation_persistence(customer_auth_headers):
    """
    Verify counter access isolation persists across logout and login.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create order at Counter 01
        r = await client.post("/api/v1/orders", json={
            "customer_identifier": "Login-Logout Cust",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        o_num = r.json()["order_number"]

        # Staff01 logs in, confirms order visible
        s1 = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        t1 = s1.json()["token"]
        h1 = {"Authorization": f"Bearer {t1}"}
        active1 = await client.get("/api/v1/admin/orders/active", headers=h1)
        assert o_num in {o["order_number"] for o in active1.json()}

        # Staff01 logs out
        logout_resp = await client.post("/api/v1/auth/logout", headers=h1)
        assert logout_resp.status_code == 204

        # Former token is invalidated
        old_token_resp = await client.get("/api/v1/admin/orders/active", headers=h1)
        assert old_token_resp.status_code == 401

        # Staff01 logs in again with new session
        s1_again = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        h1_new = {"Authorization": f"Bearer {s1_again.json()['token']}"}
        active_again = await client.get("/api/v1/admin/orders/active", headers=h1_new)
        assert o_num in {o["order_number"] for o in active_again.json()}

        # Attempt to access Counter 02 is still blocked
        block_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=h1_new)
        assert block_c2.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_order_safety(admin_auth_headers):
    """
    Verify orders without counter assignment are not falsely attributed to Counter 01.
    """
    import uuid
    uniq_num = f"FS-UNASSIGNED-{uuid.uuid4().hex[:6].upper()}"
    async with async_session_maker() as db:
        unassigned_order = Order(
            order_number=uniq_num,
            customer_identifier="Unassigned Customer",
            subtotal=100.0,
            tax_amount=5.0,
            discount_amount=0.0,
            total_amount=105.0,
            payment_status="PAID",
            payment_method="UPI",
            counter_id=None,
            assigned_counter_number=None,
            qr_token=uniq_num,
            verification_status="PENDING"
        )
        db.add(unassigned_order)
        await db.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Counter 01 active orders MUST NOT contain unassigned order
        c1_resp = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=admin_auth_headers)
        assert c1_resp.status_code == 200
        assert uniq_num not in {o["order_number"] for o in c1_resp.json()}

        # Attempting lookup at Counter 01 safely reports not assigned to Counter 01
        lookup_resp = await client.post("/api/v1/admin/verify/lookup", headers=admin_auth_headers, json={
            "token_or_order_number": uniq_num,
            "counter_number": "01"
        })
        assert lookup_resp.status_code == 400
        assert "has not been assigned to a counter" in lookup_resp.json()["detail"]


@pytest.mark.asyncio
async def test_section_5_nine_verification_scenarios(customer_auth_headers):
    """
    Direct verification of all 9 criteria from Section 5 of requirements:
    1. Create an order and assign it to Counter A. Confirm it appears in Counter A.
    2. Open Counter B. Confirm Counter A's order is not visible.
    3. Create another order for Counter B. Confirm it appears only in Counter B.
    4. Switch repeatedly between counters and verify that no previous counter's data remains visible.
    5. Refresh both counter portals and verify correct data isolation.
    6. Log out and log back in to each counter and verify access remains correct.
    7. Attempt to access another counter's order through a direct API request. Confirm access is denied.
    8. Log in as admin and confirm that all counters and their customer/order details remain visible.
    9. Verify that existing barcode scanning, checkout, payments, and revenue reporting continue to work.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Authenticate staff for Counter A (01) and Counter B (02)
        login_a = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert login_a.status_code == 200
        token_a = login_a.json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        login_b = await client.post("/api/v1/auth/login", json={"username": "staff02", "pin": "1234"})
        assert login_b.status_code == 200
        token_b = login_b.json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Case 1: Create an order and assign it to Counter A. Confirm it appears in Counter A.
        order_a_res = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer Section5 A",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert order_a_res.status_code == 201
        order_a = order_a_res.json()
        num_a = order_a["order_number"]

        active_a = await client.get("/api/v1/admin/orders/active", headers=headers_a)
        assert active_a.status_code == 200
        assert num_a in {o["order_number"] for o in active_a.json()}

        # Case 2: Open Counter B. Confirm Counter A's order is not visible.
        active_b_before = await client.get("/api/v1/admin/orders/active", headers=headers_b)
        assert active_b_before.status_code == 200
        assert num_a not in {o["order_number"] for o in active_b_before.json()}

        # Case 3: Create another order for Counter B. Confirm it appears only in Counter B.
        order_b_res = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer Section5 B",
            "payment_method": "CARD",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 2}]
        }, headers=customer_auth_headers)
        assert order_b_res.status_code == 201
        order_b = order_b_res.json()
        num_b = order_b["order_number"]

        active_b_after = await client.get("/api/v1/admin/orders/active", headers=headers_b)
        assert active_b_after.status_code == 200
        b_nums = {o["order_number"] for o in active_b_after.json()}
        assert num_b in b_nums
        assert num_a not in b_nums

        active_a_after = await client.get("/api/v1/admin/orders/active", headers=headers_a)
        assert active_a_after.status_code == 200
        a_nums = {o["order_number"] for o in active_a_after.json()}
        assert num_a in a_nums
        assert num_b not in a_nums

        # Case 4: Switch repeatedly between counters and verify that no previous counter's data remains visible.
        admin_login = await client.post("/api/v1/auth/login", json={"username": "admin3", "pin": "333333"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

        for _ in range(3):
            sw_a = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=admin_headers)
            assert num_a in {o["order_number"] for o in sw_a.json()}
            assert num_b not in {o["order_number"] for o in sw_a.json()}

            sw_b = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=admin_headers)
            assert num_b in {o["order_number"] for o in sw_b.json()}
            assert num_a not in {o["order_number"] for o in sw_b.json()}

        # Case 5: Refresh both counter portals and verify correct data isolation.
        ref_a = await client.get("/api/v1/admin/orders/active", headers=headers_a)
        assert num_a in {o["order_number"] for o in ref_a.json()}
        assert num_b not in {o["order_number"] for o in ref_a.json()}

        ref_b = await client.get("/api/v1/admin/orders/active", headers=headers_b)
        assert num_b in {o["order_number"] for o in ref_b.json()}
        assert num_a not in {o["order_number"] for o in ref_b.json()}

        # Case 6: Log out and log back in to each counter and verify access remains correct.
        await client.post("/api/v1/auth/logout", headers=headers_a)
        await client.post("/api/v1/auth/logout", headers=headers_b)

        relogin_a = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        new_headers_a = {"Authorization": f"Bearer {relogin_a.json()['token']}"}
        relogin_b = await client.post("/api/v1/auth/login", json={"username": "staff02", "pin": "1234"})
        new_headers_b = {"Authorization": f"Bearer {relogin_b.json()['token']}"}

        post_login_a = await client.get("/api/v1/admin/orders/active", headers=new_headers_a)
        assert num_a in {o["order_number"] for o in post_login_a.json()}
        assert num_b not in {o["order_number"] for o in post_login_a.json()}

        post_login_b = await client.get("/api/v1/admin/orders/active", headers=new_headers_b)
        assert num_b in {o["order_number"] for o in post_login_b.json()}
        assert num_a not in {o["order_number"] for o in post_login_b.json()}

        # Case 7: Attempt to access another counter's order through direct API requests. Confirm access is denied.
        tamper_1 = await client.get(f"/api/v1/admin/orders/{num_b}", headers=new_headers_a)
        assert tamper_1.status_code == 403
        tamper_2 = await client.get(f"/api/v1/orders/{num_b}", headers=new_headers_a)
        assert tamper_2.status_code == 403
        tamper_3 = await client.post("/api/v1/admin/verify/lookup", headers=new_headers_a, json={
            "token_or_order_number": num_b,
            "counter_number": "02"
        })
        assert tamper_3.status_code == 403
        tamper_4 = await client.post("/api/v1/admin/verify/scan", headers=new_headers_a, json={
            "order_number": num_b,
            "scanned_barcode": "8901063029255",
            "counter_number": "02"
        })
        assert tamper_4.status_code == 403

        # Case 8: Log in as admin and confirm that all counters and their customer/order details remain visible.
        admin_resp = await client.get("/api/v1/admin/transactions", headers=admin_headers)
        assert admin_resp.status_code == 200
        all_tx_nums = {t["order_number"] for t in admin_resp.json()}
        assert num_a in all_tx_nums
        assert num_b in all_tx_nums

        # Case 9: Verify existing barcode scanning, checkout, payments, and revenue reporting continue to work.
        scan_res = await client.post("/api/v1/admin/verify/scan", headers=new_headers_a, json={
            "order_number": num_a,
            "scanned_barcode": "8901058003765",
            "counter_number": "01"
        })
        assert scan_res.status_code == 200
        assert scan_res.json()["status"] in ("MATCHED", "ALL_CLEARED")

        analytics_res = await client.get("/api/v1/admin/analytics", headers=admin_headers)
        assert analytics_res.status_code == 200
        analytics_data = analytics_res.json()
        assert analytics_data["total_revenue"] > 0
        assert len(analytics_data["counters_overview"]) >= 3

