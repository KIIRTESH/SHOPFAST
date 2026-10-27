import pytest
import httpx
from app.main import app
from app.db.init_db import init_db


@pytest.mark.asyncio
async def test_admin_can_access_dashboard_analytics_and_counters(admin_auth_headers):
    """Admin tests: Admin can access dashboard APIs, view all 5 counters and manage counter status."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Admin analytics endpoint returns comprehensive store-wide KPIs
        resp = await client.get("/api/v1/admin/analytics", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_revenue" in data
        assert "today_sales_total" in data
        assert "open_counters_count" in data
        assert "active_staff_count" in data
        assert "counters_overview" in data
        assert len(data["counters_overview"]) >= 5

        # 2. Admin counters monitor view returns all 5 counters
        counters_resp = await client.get("/api/v1/admin/counters", headers=admin_auth_headers)
        assert counters_resp.status_code == 200
        counters = counters_resp.json()
        c_nums = {c["counter_number"] for c in counters}
        assert {"01", "02", "03", "04", "07"}.issubset(c_nums)

        # 3. Admin can safely toggle counter open/closed status
        toggle_close = await client.patch(
            "/api/v1/admin/counters/04/status",
            json={"is_active": False},
            headers=admin_auth_headers
        )
        assert toggle_close.status_code == 200
        assert toggle_close.json()["is_active"] is False

        # Restore counter 04
        toggle_open = await client.patch(
            "/api/v1/admin/counters/04/status",
            json={"is_active": True},
            headers=admin_auth_headers
        )
        assert toggle_open.status_code == 200
        assert toggle_open.json()["is_active"] is True


@pytest.mark.asyncio
async def test_admin_can_manage_inventory_and_duplicate_barcode(admin_auth_headers):
    """Admin tests: Admin can manage catalog, add items, and duplicate/invalid barcodes are rejected."""
    import uuid
    uid = uuid.uuid4().hex[:8]
    test_barcode = f"999888{uid}"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Query products with search and low-stock filters
        prod_resp = await client.get("/api/v1/admin/products?limit=5", headers=admin_auth_headers)
        assert prod_resp.status_code == 200
        assert len(prod_resp.json()) > 0

        # 2. Add new product
        new_prod = {
            "barcode": test_barcode,
            "name": f"Supermarket Organic Honey {uid}",
            "price": 320.0,
            "stock_qty": 50,
            "category": "Organic",
            "icon": "🍯"
        }
        add_resp = await client.post("/api/v1/admin/products", json=new_prod, headers=admin_auth_headers)
        assert add_resp.status_code == 201
        created = add_resp.json()
        assert created["barcode"] == test_barcode
        assert created["price"] == 320.0

        # 3. Duplicate barcode is rejected with 400 Bad Request
        dup_resp = await client.post("/api/v1/admin/products", json=new_prod, headers=admin_auth_headers)
        assert dup_resp.status_code == 400
        assert "duplicate" in dup_resp.json()["detail"].lower()

        # 4. Invalid empty barcode rejected
        bad_barcode_resp = await client.post(
            "/api/v1/admin/products",
            json={**new_prod, "barcode": "   "},
            headers=admin_auth_headers
        )
        assert bad_barcode_resp.status_code == 400

        # 5. Update product price and stock
        upd_resp = await client.put(
            f"/api/v1/admin/products/{test_barcode}",
            json={"price": 340.0, "stock_qty": 45},
            headers=admin_auth_headers
        )
        assert upd_resp.status_code == 200
        assert upd_resp.json()["price"] == 340.0
        assert upd_resp.json()["stock_qty"] == 45


@pytest.mark.asyncio
async def test_admin_can_manage_staff_accounts(admin_auth_headers):
    """Admin tests: Admin can view staff accounts, create staff, reassign counters, and reset PIN."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_username = f"cashier_{uid}"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. View staff accounts
        staff_resp = await client.get("/api/v1/admin/staff", headers=admin_auth_headers)
        assert staff_resp.status_code == 200
        staff_list = staff_resp.json()
        usernames = {s["username"] for s in staff_list}
        assert {"staff01", "staff02", "staff03", "staff04", "staff07"}.issubset(usernames)
        # Ensure PIN hash is never exposed
        for s in staff_list:
            assert "pin_hash" not in s
            assert "pin_salt" not in s

        # 2. Provision new staff account
        new_staff_payload = {
            "username": test_username,
            "display_name": f"Temporary Cashier {uid}",
            "pin": "5555",
            "counter_number": "01"
        }
        create_resp = await client.post("/api/v1/admin/staff", json=new_staff_payload, headers=admin_auth_headers)
        assert create_resp.status_code == 201
        created_staff = create_resp.json()
        assert created_staff["username"] == test_username
        assert created_staff["counter_number"] == "01"
        staff_id = created_staff["id"]

        # 3. Reassign counter to Counter 02
        upd_resp = await client.put(
            f"/api/v1/admin/staff/{staff_id}",
            json={"counter_number": "02", "display_name": f"Reassigned Cashier {uid}"},
            headers=admin_auth_headers
        )
        assert upd_resp.status_code == 200
        assert upd_resp.json()["counter_number"] == "02"

        # 4. Reset staff PIN
        reset_resp = await client.post(
            f"/api/v1/admin/staff/{staff_id}/reset-pin",
            json={"new_pin": "9876"},
            headers=admin_auth_headers
        )
        assert reset_resp.status_code == 200

        # 5. New PIN works for login
        login_new = await client.post(
            "/api/v1/auth/login",
            json={"username": test_username, "pin": "9876"}
        )
        assert login_new.status_code == 200
        assert login_new.json()["counter_number"] == "02"



@pytest.mark.asyncio
async def test_staff_cannot_access_admin_only_endpoints():
    """Security tests: Staff account cannot access admin-only analytics, inventory, staff, or counter endpoints."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Login as staff01
        staff_login = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert staff_login.status_code == 200
        staff_token = staff_login.json()["token"]
        staff_headers = {"Authorization": f"Bearer {staff_token}"}

        # 1. Staff calling /admin/analytics -> 403 Forbidden
        analytics_resp = await client.get("/api/v1/admin/analytics", headers=staff_headers)
        assert analytics_resp.status_code == 403

        # 2. Staff calling /admin/products (GET, POST, PUT) -> 403 Forbidden
        prod_get = await client.get("/api/v1/admin/products", headers=staff_headers)
        assert prod_get.status_code == 403

        prod_post = await client.post("/api/v1/admin/products", json={
            "barcode": "1111222233334",
            "name": "Unauthorized Product",
            "price": 10.0,
            "stock_qty": 10
        }, headers=staff_headers)
        assert prod_post.status_code == 403

        prod_put = await client.put(
            "/api/v1/admin/products/8901719128608",
            json={"price": 1.0},
            headers=staff_headers
        )
        assert prod_put.status_code == 403

        # 3. Staff calling /admin/staff -> 403 Forbidden
        staff_get = await client.get("/api/v1/admin/staff", headers=staff_headers)
        assert staff_get.status_code == 403

        staff_post = await client.post("/api/v1/admin/staff", json={
            "username": "hacker_staff",
            "display_name": "Hacker",
            "pin": "1234",
            "counter_number": "01"
        }, headers=staff_headers)
        assert staff_post.status_code == 403

        staff_reset = await client.post(
            "/api/v1/admin/staff/1/reset-pin",
            json={"new_pin": "1234"},
            headers=staff_headers
        )
        assert staff_reset.status_code == 403

        # 4. Staff calling /admin/counters -> 403 Forbidden
        counters_get = await client.get("/api/v1/admin/counters", headers=staff_headers)
        assert counters_get.status_code == 403

        counters_patch = await client.patch(
            "/api/v1/admin/counters/01/status",
            json={"is_active": False},
            headers=staff_headers
        )
        assert counters_patch.status_code == 403


@pytest.mark.asyncio
async def test_staff_counter_isolation_and_verification_workflow(customer_auth_headers):
    """
    Staff tests:
    - Staff 1 can access Counter 01 dashboard and active orders.
    - Staff 1 CANNOT view or verify Counter 02 orders.
    - Staff 1 CANNOT query Counter 02 transactions.
    - Staff 1 CAN reverify permitted carts at Counter 01.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create Order 1 at Counter 01
        order1_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer Counter 01",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "01",
            "items": [{"product_barcode": "8901058003765", "product_name": "Maggi 2-Minute Noodles", "unit_price": 56.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert order1_resp.status_code == 201
        order1_num = order1_resp.json()["order_number"]

        # Create Order 2 at Counter 02
        order2_resp = await client.post("/api/v1/orders", json={
            "customer_identifier": "Customer Counter 02",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "02",
            "items": [{"product_barcode": "890103038384", "product_name": "Amul Taaza Milk 1L", "unit_price": 68.0, "quantity": 1}]
        }, headers=customer_auth_headers)
        assert order2_resp.status_code == 201
        order2_num = order2_resp.json()["order_number"]

        # Login as staff01 (assigned to Counter 01)
        s1_login = await client.post("/api/v1/auth/login", json={"username": "staff01", "pin": "1234"})
        assert s1_login.status_code == 200
        s1_headers = {"Authorization": f"Bearer {s1_login.json()['token']}"}

        # 1. Staff 1 dashboard is scoped strictly to Counter 01
        dash_resp = await client.get("/api/v1/staff/dashboard", headers=s1_headers)
        assert dash_resp.status_code == 200
        dash = dash_resp.json()
        assert dash["counter_number"] == "01"
        assert dash["staff_username"] == "staff01"

        # 2. Staff 1 active orders only includes Order 1
        active_resp = await client.get("/api/v1/staff/orders/active", headers=s1_headers)
        assert active_resp.status_code == 200
        active_order_nums = [o["order_number"] for o in active_resp.json()]
        assert order1_num in active_order_nums
        assert order2_num not in active_order_nums

        # 3. Staff 1 attempts to query Counter 02 active orders -> 403 Forbidden
        tamper_active = await client.get("/api/v1/admin/orders/active?counter_number=02", headers=s1_headers)
        assert tamper_active.status_code == 403

        # 4. Staff 1 attempts to lookup Order 2 (Counter 02) -> 403 Forbidden or 400 Bad Request
        tamper_lookup = await client.post(
            "/api/v1/staff/verify/lookup",
            json={"token_or_order_number": order2_num, "counter_number": "02"},
            headers=s1_headers
        )
        assert tamper_lookup.status_code in (400, 403)

        # 5. Staff 1 attempts to verify Order 2 directly -> 400 or 403
        tamper_scan = await client.post(
            "/api/v1/staff/verify/scan",
            json={"order_number": order2_num, "scanned_barcode": "890103038384", "counter_number": "02"},
            headers=s1_headers
        )
        assert tamper_scan.status_code in (400, 403)

        # 6. Staff 1 attempts to view Counter 02 transactions -> 403 Forbidden
        tamper_tx = await client.get("/api/v1/admin/transactions?counter=02", headers=s1_headers)
        assert tamper_tx.status_code == 403

        # 7. Staff 1 legitimately verifies Order 1 at Counter 01
        lookup_ok = await client.post(
            "/api/v1/staff/verify/lookup",
            json={"token_or_order_number": order1_num, "counter_number": "01"},
            headers=s1_headers
        )
        assert lookup_ok.status_code == 200
        assert lookup_ok.json()["order_number"] == order1_num

        scan_ok = await client.post(
            "/api/v1/staff/verify/scan",
            json={"order_number": order1_num, "scanned_barcode": "8901058003765", "counter_number": "01"},
            headers=s1_headers
        )
        assert scan_ok.status_code == 200
        assert scan_ok.json()["is_all_matched"] is True

        complete_ok = await client.post(
            "/api/v1/staff/verify/complete",
            json={"order_number": order1_num, "counter_number": "01", "duration_seconds": 12},
            headers=s1_headers
        )
        assert complete_ok.status_code == 200
        assert complete_ok.json()["is_verified_by_cashier"] is True
        assert complete_ok.json()["verification_status"] == "CLEARED"

        # 8. Staff 1 transactions ledger shows completed order
        staff_tx_resp = await client.get("/api/v1/staff/transactions", headers=s1_headers)
        assert staff_tx_resp.status_code == 200
        staff_tx_nums = [t["order_number"] for t in staff_tx_resp.json()]
        assert order1_num in staff_tx_nums
        assert order2_num not in staff_tx_nums


@pytest.mark.asyncio
async def test_auth_logout_and_pin_change():
    """Auth tests: Secure PIN change and logout token invalidation."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Login
        login_res = await client.post("/api/v1/auth/login", json={"username": "staff03", "pin": "1234"})
        assert login_res.status_code == 200
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Change PIN
        change_res = await client.post(
            "/api/v1/auth/change-pin",
            json={"current_pin": "1234", "new_pin": "7777"},
            headers=headers
        )
        assert change_res.status_code == 200

        # Old PIN fails
        login_old = await client.post("/api/v1/auth/login", json={"username": "staff03", "pin": "1234"})
        assert login_old.status_code == 401

        # New PIN succeeds
        login_new = await client.post("/api/v1/auth/login", json={"username": "staff03", "pin": "7777"})
        assert login_new.status_code == 200
        new_token = login_new.json()["token"]

        # Logout invalidates token
        logout_res = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {new_token}"})
        assert logout_res.status_code == 204

        # Using logged-out token returns 401
        me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me_res.status_code == 401

        # Reset PIN back to 1234 for test idempotency
        # Login with new PIN
        relogin = await client.post("/api/v1/auth/login", json={"username": "staff03", "pin": "7777"})
        assert relogin.status_code == 200
        reset_headers = {"Authorization": f"Bearer {relogin.json()['token']}"}
        await client.post(
            "/api/v1/auth/change-pin",
            json={"current_pin": "7777", "new_pin": "1234"},
            headers=reset_headers
        )
