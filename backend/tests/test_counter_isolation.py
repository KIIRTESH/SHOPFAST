import uuid
import pytest
import httpx
from app.main import app
from app.models.order import Order
from app.db.session import async_session_maker
from sqlalchemy import select
from app.models.user import User
from app.core.auth import create_pin_hash


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
        # (The API no longer lets clients choose payment_status, so insert it directly.)
        import uuid as _uuid
        unpaid_num = f"FS-UNPAID-{_uuid.uuid4().hex[:6].upper()}"
        async with async_session_maker() as db:
            db.add(Order(
                order_number=unpaid_num,
                customer_identifier="Unpaid Customer",
                subtotal=56.0,
                tax_amount=2.8,
                discount_amount=0.0,
                total_amount=58.8,
                payment_status="PENDING",
                payment_method="UPI",
                assigned_counter_number="01",
                qr_token=unpaid_num,
                verification_status="PENDING",
            ))
            await db.commit()

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

        # 1. Store Administrator (username="admin", role="store_admin") has global access
        login_sa = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        assert login_sa.status_code == 200
        sa_headers = {"Authorization": f"Bearer {login_sa.json()['token']}"}

        # Store Admin can view Counter 01
        resp_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=sa_headers)
        assert resp_c1.status_code == 200
        assert o1_num in {o["order_number"] for o in resp_c1.json()}

        # Store Admin can view Counter 02
        resp_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=sa_headers)
        assert resp_c2.status_code == 200
        assert o2_num in {o["order_number"] for o in resp_c2.json()}

        # Store Admin can view order details directly
        det1 = await client.get(f"/api/v1/admin/orders/{o1_num}", headers=sa_headers)
        assert det1.status_code == 200
        det2 = await client.get(f"/api/v1/admin/orders/{o2_num}", headers=sa_headers)
        assert det2.status_code == 200

        # Store Admin can view store-wide transactions across all counters
        tx_all = await client.get("/api/v1/admin/transactions", headers=sa_headers)
        assert tx_all.status_code == 200
        tx_nums = {t["order_number"] for t in tx_all.json()}
        assert o1_num in tx_nums
        assert o2_num in tx_nums

        # 2. Counter 03 Staff (admin3) is restricted to Counter 03, NOT granted store-wide access
        login_a3 = await client.post("/api/v1/auth/login", json={"username": "admin3", "pin": "333333"})
        assert login_a3.status_code == 200
        assert login_a3.json()["role"] == "admin"
        assert login_a3.json()["counter_number"] == "03"
        a3_headers = {"Authorization": f"Bearer {login_a3.json()['token']}"}

        # admin3 is DENIED access to Counter 01 active orders
        denied_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=a3_headers)
        assert denied_c1.status_code == 403

        # admin3 is DENIED access to Counter 02 active orders
        denied_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=a3_headers)
        assert denied_c2.status_code == 403

        # admin3 is DENIED access to Counter 01 order details
        denied_det1 = await client.get(f"/api/v1/admin/orders/{o1_num}", headers=a3_headers)
        assert denied_det1.status_code == 403

        # admin3 transactions are scoped to Counter 03 and do not expose Counter 01 or 02 orders
        a3_tx = await client.get("/api/v1/admin/transactions", headers=a3_headers)
        assert a3_tx.status_code == 200
        a3_tx_nums = {t["order_number"] for t in a3_tx.json()}
        assert o1_num not in a3_tx_nums
        assert o2_num not in a3_tx_nums


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
        admin_login = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
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


@pytest.mark.asyncio
async def test_counter_authorization_and_store_admin_role_consistency(customer_auth_headers):
    """
    Targeted regression tests for Issue 1: Counter Authorization and Store Admin Role Inconsistency.
    Verifies:
    1. Counter 01 staff can access Counter 01.
    2. Counter 01 staff are denied access to Counter 02.
    3. Counter 03 staff, including admin3, cannot access store-wide admin operations unless explicitly assigned store-admin role.
    4. The legitimate store administrator can access all counters.
    5. An account with a missing or invalid counter assignment cannot gain store-wide access automatically and is denied counter access by default.
    6. Changing the requested counter number (parameter tampering) does not bypass authorization.
    7. Changing a username or using a username resembling admin does not grant store-admin privileges.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create orders at Counter 01, 02, and 03
        r1 = await client.post("/api/v1/orders", json={
            "customer_identifier": "Issue1 Cust 01",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert r1.status_code == 201
        num_1 = r1.json()["order_number"]

        r2 = await client.post("/api/v1/orders", json={
            "customer_identifier": "Issue1 Cust 02",
            "payment_method": "CARD",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "8901063029255", "product_name": "JimJam", "unit_price": 20.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert r2.status_code == 201
        num_2 = r2.json()["order_number"]

        r3 = await client.post("/api/v1/orders", json={
            "customer_identifier": "Issue1 Cust 03",
            "payment_method": "CASH",
            "payment_status": "PAID",
            "preferred_counter": "03",
            "items": [{"product_barcode": "8901571005666", "product_name": "Sensodyne", "unit_price": 245.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert r3.status_code == 201
        num_3 = r3.json()["order_number"]

        # 1. Counter 01 staff can access Counter 01
        login_c1 = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert login_c1.status_code == 200
        headers_c1 = {"Authorization": f"Bearer {login_c1.json()['token']}"}

        c1_active = await client.get("/api/v1/admin/orders/active", headers=headers_c1)
        assert c1_active.status_code == 200
        assert num_1 in {o["order_number"] for o in c1_active.json()}

        c1_order = await client.get(f"/api/v1/admin/orders/{num_1}", headers=headers_c1)
        assert c1_order.status_code == 200
        assert c1_order.json()["order_number"] == num_1

        # 2. Counter 01 staff are denied access to Counter 02
        c1_try_c2_active = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_c1)
        assert c1_try_c2_active.status_code == 403

        c1_try_c2_order = await client.get(f"/api/v1/admin/orders/{num_2}", headers=headers_c1)
        assert c1_try_c2_order.status_code == 403

        c1_try_c2_tx = await client.get("/api/v1/admin/transactions?counter=02", headers=headers_c1)
        assert c1_try_c2_tx.status_code == 403

        c1_try_c2_refund = await client.post(f"/api/v1/admin/transactions/{num_2}/refund", headers=headers_c1)
        assert c1_try_c2_refund.status_code == 403

        # 3. Counter 03 staff, including admin3, cannot access store-wide admin operations
        login_a3 = await client.post("/api/v1/auth/login", json={"username": "admin3", "pin": "333333"})
        assert login_a3.status_code == 200
        data_a3 = login_a3.json()
        assert data_a3["role"] == "admin"
        assert data_a3["counter_number"] == "03"
        headers_a3 = {"Authorization": f"Bearer {data_a3['token']}"}

        # admin3 can access Counter 03
        a3_active = await client.get("/api/v1/admin/orders/active", headers=headers_a3)
        assert a3_active.status_code == 200
        assert num_3 in {o["order_number"] for o in a3_active.json()}
        assert num_1 not in {o["order_number"] for o in a3_active.json()}

        # admin3 is DENIED store-wide access to Counter 01 and Counter 02
        assert (await client.get("/api/v1/admin/orders/active?counter_number=01", headers=headers_a3)).status_code == 403
        assert (await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_a3)).status_code == 403
        assert (await client.get(f"/api/v1/admin/orders/{num_1}", headers=headers_a3)).status_code == 403
        assert (await client.get(f"/api/v1/admin/orders/{num_2}", headers=headers_a3)).status_code == 403
        assert (await client.get("/api/v1/admin/transactions?counter=01", headers=headers_a3)).status_code == 403
        assert (await client.post(f"/api/v1/admin/transactions/{num_1}/refund", headers=headers_a3)).status_code == 403

        # Transactions for admin3 are automatically scoped to Counter 03
        a3_tx = await client.get("/api/v1/admin/transactions", headers=headers_a3)
        assert a3_tx.status_code == 200
        a3_tx_nums = {t["order_number"] for t in a3_tx.json()}
        assert num_3 in a3_tx_nums
        assert num_1 not in a3_tx_nums
        assert num_2 not in a3_tx_nums

        # 4. Legitimate store administrator (role=store_admin) can access all counters
        login_admin = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        assert login_admin.status_code == 200
        data_admin = login_admin.json()
        assert data_admin["role"] == "store_admin"
        headers_admin = {"Authorization": f"Bearer {data_admin['token']}"}

        # Store admin can access Counter 01, 02, and 03
        sa_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=headers_admin)
        assert sa_c1.status_code == 200
        assert num_1 in {o["order_number"] for o in sa_c1.json()}

        sa_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_admin)
        assert sa_c2.status_code == 200
        assert num_2 in {o["order_number"] for o in sa_c2.json()}

        sa_c3 = await client.get("/api/v1/admin/orders/active?counter_number=03", headers=headers_admin)
        assert sa_c3.status_code == 200
        assert num_3 in {o["order_number"] for o in sa_c3.json()}

        # Store admin can access order details across all counters
        assert (await client.get(f"/api/v1/admin/orders/{num_1}", headers=headers_admin)).status_code == 200
        assert (await client.get(f"/api/v1/admin/orders/{num_2}", headers=headers_admin)).status_code == 200
        assert (await client.get(f"/api/v1/admin/orders/{num_3}", headers=headers_admin)).status_code == 200

        # Store admin can access store-wide transactions across all counters
        sa_tx = await client.get("/api/v1/admin/transactions", headers=headers_admin)
        assert sa_tx.status_code == 200
        sa_tx_nums = {t["order_number"] for t in sa_tx.json()}
        assert num_1 in sa_tx_nums
        assert num_2 in sa_tx_nums
        assert num_3 in sa_tx_nums

        # 5. Account with missing or invalid counter assignment cannot gain store-wide access
        uid = uuid.uuid4().hex[:8]
        user_nocounter = f"staff_nocounter_{uid}"
        user_emptycounter = f"staff_empty_{uid}"

        async with async_session_maker() as db:
            h, s = create_pin_hash("9999")
            db.add(User(
                username=user_nocounter,
                display_name="No Counter Staff",
                pin_hash=h,
                pin_salt=s,
                role="admin",
                counter_number=None
            ))
            db.add(User(
                username=user_emptycounter,
                display_name="Empty Counter Staff",
                pin_hash=h,
                pin_salt=s,
                role="admin",
                counter_number=""
            ))
            await db.commit()

        login_nocounter = await client.post("/api/v1/auth/login", json={"username": user_nocounter, "pin": "9999"})
        assert login_nocounter.status_code == 200
        headers_nocounter = {"Authorization": f"Bearer {login_nocounter.json()['token']}"}

        # Denied counter access by default
        nc_resp = await client.get("/api/v1/admin/orders/active", headers=headers_nocounter)
        assert nc_resp.status_code == 403
        assert "No counter assigned" in nc_resp.json()["detail"]

        nc_resp_c1 = await client.get("/api/v1/admin/orders/active?counter_number=01", headers=headers_nocounter)
        assert nc_resp_c1.status_code == 403

        nc_tx = await client.get("/api/v1/admin/transactions", headers=headers_nocounter)
        assert nc_tx.status_code == 403

        nc_det = await client.get(f"/api/v1/admin/orders/{num_1}", headers=headers_nocounter)
        assert nc_det.status_code == 403

        # Empty counter also denied
        login_empty = await client.post("/api/v1/auth/login", json={"username": user_emptycounter, "pin": "9999"})
        assert login_empty.status_code == 200
        headers_empty = {"Authorization": f"Bearer {login_empty.json()['token']}"}
        empty_resp = await client.get("/api/v1/admin/orders/active", headers=headers_empty)
        assert empty_resp.status_code == 403

        # 6. Parameter tampering does not bypass authorization
        tamper_c1_c2 = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_c1)
        assert tamper_c1_c2.status_code == 403

        tamper_c1_c3 = await client.get("/api/v1/admin/orders/active?counter_number=03", headers=headers_c1)
        assert tamper_c1_c3.status_code == 403

        tamper_c1_c99 = await client.get("/api/v1/admin/orders/active?counter_number=99", headers=headers_c1)
        assert tamper_c1_c99.status_code == 403

        tamper_lookup = await client.post("/api/v1/admin/verify/lookup", headers=headers_c1, json={
            "token_or_order_number": num_2,
            "counter_number": "02"
        })
        assert tamper_lookup.status_code == 403

        # 7. Resembling username does not grant store-admin privileges
        user_lookalike = f"admin_lookalike_{uid}"
        async with async_session_maker() as db:
            h2, s2 = create_pin_hash("8888")
            db.add(User(
                username=user_lookalike,
                display_name="Admin Lookalike Staff",
                pin_hash=h2,
                pin_salt=s2,
                role="admin",
                counter_number="01"
            ))
            await db.commit()

        login_lookalike = await client.post("/api/v1/auth/login", json={"username": user_lookalike, "pin": "8888"})
        assert login_lookalike.status_code == 200
        assert login_lookalike.json()["role"] == "admin"
        headers_lookalike = {"Authorization": f"Bearer {login_lookalike.json()['token']}"}

        # Lookalike staff can access its own counter
        lookalike_own = await client.get("/api/v1/admin/orders/active", headers=headers_lookalike)
        assert lookalike_own.status_code == 200
        assert num_1 in {o["order_number"] for o in lookalike_own.json()}

        # Lookalike staff CANNOT access other counters or store-wide data
        lookalike_other = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=headers_lookalike)
        assert lookalike_other.status_code == 403

        lookalike_other_order = await client.get(f"/api/v1/admin/orders/{num_2}", headers=headers_lookalike)
        assert lookalike_other_order.status_code == 403

        lookalike_other_tx = await client.get("/api/v1/admin/transactions?counter=02", headers=headers_lookalike)
        assert lookalike_other_tx.status_code == 403


@pytest.mark.asyncio
async def test_nonexistent_and_invalid_counter_assignment_denial(customer_auth_headers):
    """
    Focused regression test for targeted fix:
    Counter staff with missing, empty, malformed, or nonexistent counter assignments must receive 403 Forbidden.
    Valid counter staff can access only their assigned counter.
    Legitimate store_admin retains access to all configured counters.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create an order at Counter 01
        o1_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Nonexistent Counter Test Cust",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert o1_resp.status_code == 201
        num_1 = o1_resp.json()["order_number"]

        uid = uuid.uuid4().hex[:8]
        u_none = f"staff_none_{uid}"
        u_empty = f"staff_empty_{uid}"
        u_space = f"staff_space_{uid}"
        u_99 = f"staff_c99_{uid}"
        u_malformed = f"staff_malformed_{uid}"

        async with async_session_maker() as db:
            h, s = create_pin_hash("1234")
            db.add_all([
                User(username=u_none, display_name="No Counter", pin_hash=h, pin_salt=s, role="admin", counter_number=None),
                User(username=u_empty, display_name="Empty Counter", pin_hash=h, pin_salt=s, role="admin", counter_number=""),
                User(username=u_space, display_name="Whitespace Counter", pin_hash=h, pin_salt=s, role="admin", counter_number="   "),
                User(username=u_99, display_name="Counter 99 Staff", pin_hash=h, pin_salt=s, role="admin", counter_number="99"),
                User(username=u_malformed, display_name="Malformed Counter", pin_hash=h, pin_salt=s, role="admin", counter_number="INVALID_@#$%"),
            ])
            await db.commit()

        # Test each invalid/nonexistent account
        for invalid_user, desc in [
            (u_none, "no counter (None)"),
            (u_empty, "empty string counter"),
            (u_space, "whitespace-only counter"),
            (u_99, "nonexistent Counter 99"),
            (u_malformed, "malformed Counter string"),
        ]:
            login = await client.post("/api/v1/auth/login", json={"username": invalid_user, "pin": "1234"})
            assert login.status_code == 200, f"Login should succeed for {desc}"
            headers = {"Authorization": f"Bearer {login.json()['token']}"}

            # 1. /admin/orders/active must return 403 Forbidden
            r_active = await client.get("/api/v1/admin/orders/active", headers=headers)
            assert r_active.status_code == 403, f"Expected 403 on /orders/active for {desc}, got {r_active.status_code}"

            # 2. /admin/verify/lookup must return 403 Forbidden
            r_lookup = await client.post("/api/v1/admin/verify/lookup", headers=headers, json={
                "token_or_order_number": num_1,
                "counter_number": "01"
            })
            assert r_lookup.status_code == 403, f"Expected 403 on /verify/lookup for {desc}, got {r_lookup.status_code}"

            # 3. /admin/verify/scan must return 403 Forbidden
            r_scan = await client.post("/api/v1/admin/verify/scan", headers=headers, json={
                "order_number": num_1,
                "scanned_barcode": "8901058003765",
                "counter_number": "01"
            })
            assert r_scan.status_code == 403, f"Expected 403 on /verify/scan for {desc}, got {r_scan.status_code}"

            # 4. /admin/orders/{order_number} must return 403 Forbidden
            r_ord = await client.get(f"/api/v1/admin/orders/{num_1}", headers=headers)
            assert r_ord.status_code == 403, f"Expected 403 on /admin/orders/detail for {desc}, got {r_ord.status_code}"

            # 5. /admin/transactions must return 403 Forbidden
            r_tx = await client.get("/api/v1/admin/transactions", headers=headers)
            assert r_tx.status_code == 403, f"Expected 403 on /transactions for {desc}, got {r_tx.status_code}"

            # 6. /orders/{order_number} must return 403 Forbidden
            r_pub_ord = await client.get(f"/api/v1/orders/{num_1}", headers=headers)
            assert r_pub_ord.status_code == 403, f"Expected 403 on /orders/by_number for {desc}, got {r_pub_ord.status_code}"

            # 7. /orders/{order_number}/qr-image must return 403 Forbidden
            r_qr = await client.get(f"/api/v1/orders/{num_1}/qr-image", headers=headers)
            assert r_qr.status_code == 403, f"Expected 403 on /orders/qr-image for {desc}, got {r_qr.status_code}"

        # Confirm valid Counter 01 staff can access Counter 01
        s1_login = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert s1_login.status_code == 200
        s1_headers = {"Authorization": f"Bearer {s1_login.json()['token']}"}

        s1_active = await client.get("/api/v1/admin/orders/active", headers=s1_headers)
        assert s1_active.status_code == 200
        assert num_1 in {o["order_number"] for o in s1_active.json()}

        # Confirm Counter 01 staff cannot access Counter 02 or Counter 03
        assert (await client.get("/api/v1/admin/orders/active?counter_number=02", headers=s1_headers)).status_code == 403
        assert (await client.get("/api/v1/admin/orders/active?counter_number=03", headers=s1_headers)).status_code == 403

        # Confirm admin3 can access Counter 03 but cannot access other counters or store-wide operations
        a3_login = await client.post("/api/v1/auth/login", json={"username": "admin3", "pin": "333333"})
        assert a3_login.status_code == 200
        a3_headers = {"Authorization": f"Bearer {a3_login.json()['token']}"}

        assert (await client.get("/api/v1/admin/orders/active", headers=a3_headers)).status_code == 200
        assert (await client.get("/api/v1/admin/orders/active?counter_number=01", headers=a3_headers)).status_code == 403
        assert (await client.get("/api/v1/admin/orders/active?counter_number=02", headers=a3_headers)).status_code == 403

        # Confirm store_admin retains authorized access across all configured counters
        sa_login = await client.post("/api/v1/auth/login", json={"username": "admin", "pin": "1234"})
        assert sa_login.status_code == 200
        sa_headers = {"Authorization": f"Bearer {sa_login.json()['token']}"}

        for c_num in ["01", "02", "03", "04", "07"]:
            sa_res = await client.get(f"/api/v1/admin/orders/active?counter_number={c_num}", headers=sa_headers)
            assert sa_res.status_code == 200, f"Store admin should access Counter {c_num}"


