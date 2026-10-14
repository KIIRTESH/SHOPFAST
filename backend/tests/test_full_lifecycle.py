import pytest
import httpx
from app.main import app
from app.db.init_db import init_db


@pytest.mark.asyncio
async def test_full_customer_to_counter_lifecycle(admin_auth_headers):
    """
    Complete End-to-End Self-Checkout to Express Counter Verification Lifecycle:
    1. Register customer
    2. Add product to cart, update quantity
    3. Customer creates order (demo payment)
    4. Verify stock decrement
    5. Admin looks up order by order number
    6. Admin clears/verifies order
    7. Verify order shows CLEARED
    8. Admin refunds order
    9. Verify stock is restored
    """
    await init_db()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Register unique customer
        cust_username = "lifecycle_user_101"
        cust_display = "Lifecycle Shopper"
        cust_pin = "445566"
        reg_res = await client.post("/api/v1/auth/register", json={
            "username": cust_username,
            "display_name": cust_display,
            "pin": cust_pin
        })
        assert reg_res.status_code in [201, 409]
        if reg_res.status_code == 201:
            cust_token = reg_res.json()["token"]
        else:
            login_res = await client.post("/api/v1/auth/login", json={
                "username": cust_username,
                "pin": cust_pin
            })
            assert login_res.status_code == 200
            cust_token = login_res.json()["token"]

        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        # Step 2: Get initial stock of a test product
        prod_res = await client.get("/api/v1/products/barcode/8902519009807")
        assert prod_res.status_code == 200
        initial_stock = prod_res.json()["stock_qty"]
        assert initial_stock >= 5

        # Step 3: Add to cart
        cart_id = f"cart_lifecycle_{cust_username}"
        await client.delete(f"/api/v1/carts/{cart_id}", headers=cust_headers)

        add_res = await client.post(f"/api/v1/carts/{cart_id}/items", json={
            "barcode": "8902519009807",
            "quantity": 2
        }, headers=cust_headers)
        assert add_res.status_code == 200
        cart_data = add_res.json()
        assert cart_data["item_count"] == 2

        # Step 4: Customer checks out order
        order_res = await client.post("/api/v1/orders", json={
            "payment_method": "UPI",
            "payment_status": "PAID",
            "preferred_counter": "03",
            "items": [
                {
                    "product_barcode": "8902519009807",
                    "product_name": "Classmate Notebook",
                    "unit_price": 35.0,
                    "quantity": 2
                }
            ]
        }, headers=cust_headers)
        assert order_res.status_code == 201
        order = order_res.json()
        order_num = order["order_number"]
        assert order["payment_status"] == "PAID"
        assert order["verification_status"] == "PENDING"
        assert order["is_verified_by_cashier"] is False
        assert order["customer_identifier"] == cust_display
        assert "assigned_counter_number" in order

        # Step 5: Check stock decremented by 2
        prod_after_order = await client.get("/api/v1/products/barcode/8902519009807")
        assert prod_after_order.json()["stock_qty"] == initial_stock - 2

        # Step 6: Admin looks up order at Counter 03
        admin_lookup = await client.post("/api/v1/admin/verify/lookup", json={
            "token_or_order_number": order_num,
            "counter_number": "03"
        }, headers=admin_auth_headers)
        assert admin_lookup.status_code == 200
        admin_order_data = admin_lookup.json()
        assert admin_order_data["order_number"] == order_num
        assert admin_order_data["verification_status"] in ["PENDING", "IN_PROGRESS"]

        # Step 7: Cashier scans the customer's items physically at counter
        scan_res = await client.post("/api/v1/admin/verify/scan", json={
            "order_number": order_num,
            "scanned_barcode": "8902519009807",
            "counter_number": "03"
        }, headers=admin_auth_headers)
        assert scan_res.status_code == 200
        scan_data = scan_res.json()
        assert scan_data["status"] in ["MATCHED", "ALL_CLEARED"]
        assert scan_data["scanned_qty"] >= 1

        # Step 8: Admin marks verification as complete / cleared
        verify_res = await client.post("/api/v1/admin/verify/complete", json={
            "order_number": order_num,
            "counter_number": "03",
            "duration_seconds": 14
        }, headers=admin_auth_headers)
        assert verify_res.status_code == 200
        verified_order = verify_res.json()
        assert verified_order["is_verified_by_cashier"] is True
        assert verified_order["verification_status"] == "CLEARED"

        # Step 9: Customer views order status
        cust_order_check = await client.get(f"/api/v1/orders/{order_num}", headers=cust_headers)
        assert cust_order_check.status_code == 200
        assert cust_order_check.json()["is_verified_by_cashier"] is True
        assert cust_order_check.json()["verification_status"] == "CLEARED"

        # Step 10: Admin refunds order
        refund_res = await client.post(f"/api/v1/admin/transactions/{order_num}/refund", json={}, headers=admin_auth_headers)
        assert refund_res.status_code == 200
        assert refund_res.json()["payment_status"] == "REFUNDED"

        # Step 11: Verify stock is restored
        prod_after_refund = await client.get("/api/v1/products/barcode/8902519009807")
        assert prod_after_refund.json()["stock_qty"] == initial_stock


@pytest.mark.asyncio
async def test_empty_cart_checkout_rejection(customer_auth_headers):
    """Empty cart checkout must be rejected with 422 or 400 validation error."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Empty items list
        res = await client.post("/api/v1/orders", json={
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": []
        }, headers=customer_auth_headers)
        assert res.status_code in [400, 422]


@pytest.mark.asyncio
async def test_unknown_barcode_scan():
    """Non-existent product barcode returns 404."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/products/barcode/0000000000000")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_out_of_stock_order_rejection(customer_auth_headers):
    """Attempting to purchase more than available stock must be rejected with 400."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/orders", json={
            "payment_method": "CASH",
            "payment_status": "PAID",
            "items": [
                {
                    "product_barcode": "8902519009807",
                    "product_name": "Classmate Notebook",
                    "unit_price": 35.0,
                    "quantity": 99999
                }
            ]
        }, headers=customer_auth_headers)
        assert res.status_code == 400
        assert "in stock" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rbac_boundary_admin_endpoints(admin_auth_headers):
    """
    Verify RBAC security matrix:
    - Anonymous: 401 Unauthorized
    - Customer role: 403 Forbidden
    - Admin role: 200 OK
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Anonymous request
        res_anon = await client.get("/api/v1/admin/analytics")
        assert res_anon.status_code == 401

        # 2. Customer login
        login_res = await client.post("/api/v1/auth/login", json={
            "username": "customer01",
            "pin": "1234"
        })
        assert login_res.status_code == 200
        cust_token = login_res.json()["token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        res_cust = await client.get("/api/v1/admin/analytics", headers=cust_headers)
        assert res_cust.status_code == 403

        # 3. Admin request
        res_admin = await client.get("/api/v1/admin/analytics", headers=admin_auth_headers)
        assert res_admin.status_code == 200
        assert "today_sales_total" in res_admin.json()


@pytest.mark.asyncio
async def test_order_idor_masking(admin_auth_headers):
    """
    Verify IDOR mitigation (Error #4 fix):
    Unauthenticated queries are strictly rejected with 401 Unauthorized.
    Owner customer and admin queries succeed and view customer display name.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create an order with customer01
        login_res = await client.post("/api/v1/auth/login", json={
            "username": "customer01",
            "pin": "1234"
        })
        cust_token = login_res.json()["token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        order_res = await client.post("/api/v1/orders", json={
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [
                {
                    "product_barcode": "8902519009807",
                    "product_name": "Classmate Notebook",
                    "unit_price": 35.0,
                    "quantity": 1
                }
            ]
        }, headers=cust_headers)
        assert order_res.status_code == 201
        order_number = order_res.json()["order_number"]

        # Anonymous caller query -> strictly 401 Unauthorized (Error #4 fix eliminates IDOR)
        res_anon = await client.get(f"/api/v1/orders/{order_number}")
        assert res_anon.status_code == 401

        # Customer owner query -> unmasked (shows 'Test Customer')
        res_owner = await client.get(f"/api/v1/orders/{order_number}", headers=cust_headers)
        assert res_owner.status_code == 200
        assert res_owner.json()["customer_identifier"] == "Test Customer"

        # Admin query -> unmasked (shows 'Test Customer')
        res_admin = await client.get(f"/api/v1/orders/{order_number}", headers=admin_auth_headers)
        assert res_admin.status_code == 200
        assert res_admin.json()["customer_identifier"] == "Test Customer"
