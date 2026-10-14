import pytest
import httpx
import asyncio
from app.main import app

EXPECTED_PRODUCTS = [
    ("8901719128608", "Parle-G Royale", 25.0, 100),
    ("8901063029255", "JimJam", 20.0, 100),
    ("8901571005666", "Sensodyne", 245.0, 100),
    ("8907611023454", "Paan Churi", 150.0, 100),
    ("8909106022645", "Lux Soap", 70.0, 100),
    ("8906006787377", "Vinegar", 30.0, 100),
]


@pytest.mark.asyncio
async def test_six_products_present_in_catalog():
    """Requirement 1 & 6: Verify all 6 products exist in catalog with 100 stock & 100 initial stock."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/products?limit=100")
        assert res.status_code == 200
        products = res.json()
        prod_map = {p["barcode"]: p for p in products}

        for barcode, name, price, stock in EXPECTED_PRODUCTS:
            assert barcode in prod_map, f"Missing product with barcode {barcode}"
            p = prod_map[barcode]
            assert p["name"] == name
            assert p["price"] == price
            assert p["initial_stock_qty"] == 100
            assert p["stock_qty"] >= 0


@pytest.mark.asyncio
async def test_barcode_lookup_success_and_not_found():
    """Requirement 2: Verify instant barcode lookup and clear 404 for non-existent barcodes."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for barcode, name, price, _ in EXPECTED_PRODUCTS:
            res = await client.get(f"/api/v1/products/barcode/{barcode}")
            assert res.status_code == 200
            data = res.json()
            assert data["name"] == name
            assert data["price"] == price
            assert data["barcode"] == barcode

        # Non-existent barcode
        bad_res = await client.get("/api/v1/products/barcode/9999999999999")
        assert bad_res.status_code == 404
        assert "not found" in bad_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_atomic_stock_decrement_on_order(admin_auth_headers, customer_auth_headers):
    """Requirement 3 & 5: Check stock decreases atomically on purchase (e.g. 100 - 3 = 97)."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Reset Parle-G Royale stock to 100 first via admin endpoint
        await client.put(
            "/api/v1/admin/products/8901719128608",
            json={"stock_qty": 100, "initial_stock_qty": 100},
            headers=admin_auth_headers
        )

        # Check initial stock
        res = await client.get("/api/v1/products/barcode/8901719128608")
        assert res.json()["stock_qty"] == 100
        assert res.json()["initial_stock_qty"] == 100

        # Purchase 3 units of Parle-G Royale
        order_payload = {
            "customer_identifier": "Atomic Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [
                {
                    "product_barcode": "8901719128608",
                    "product_name": "Parle-G Royale",
                    "unit_price": 25.0,
                    "quantity": 3
                }
            ]
        }
        order_res = await client.post("/api/v1/orders", json=order_payload, headers=customer_auth_headers)
        assert order_res.status_code == 201
        order = order_res.json()
        assert order["total_amount"] == round(75.0 + 3.75 - 15.0, 2)  # subtotal + 5% GST - 15 discount

        # Verify stock immediately became 97
        res2 = await client.get("/api/v1/products/barcode/8901719128608")
        assert res2.json()["stock_qty"] == 97
        assert res2.json()["stock_change"] == -3


@pytest.mark.asyncio
async def test_prevent_purchasing_more_than_available_stock(admin_auth_headers, customer_auth_headers):
    """Requirement 2 & 5: Prevent customer from adding or checking out more units than available stock."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Set JimJam stock to 5
        await client.put(
            "/api/v1/admin/products/8901063029255",
            json={"stock_qty": 5},
            headers=admin_auth_headers
        )

        # Attempt to purchase 6 units
        order_payload = {
            "customer_identifier": "Greedy Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [
                {
                    "product_barcode": "8901063029255",
                    "product_name": "JimJam",
                    "unit_price": 20.0,
                    "quantity": 6
                }
            ]
        }
        fail_res = await client.post("/api/v1/orders", json=order_payload, headers=customer_auth_headers)
        assert fail_res.status_code == 400
        assert "Cannot purchase" in fail_res.json()["detail"] or "stock" in fail_res.json()["detail"].lower()

        # Stock should still be 5
        res = await client.get("/api/v1/products/barcode/8901063029255")
        assert res.json()["stock_qty"] == 5

        # Reset back to 100
        await client.put(
            "/api/v1/admin/products/8901063029255",
            json={"stock_qty": 100, "initial_stock_qty": 100},
            headers=admin_auth_headers
        )


@pytest.mark.asyncio
async def test_concurrency_race_condition_on_last_unit(admin_auth_headers, customer_auth_headers):
    """Requirement 5: Test multiple simultaneous transactions to ensure inventory remains accurate."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Set Vinegar stock to exactly 1 unit
        await client.put(
            "/api/v1/admin/products/8906006787377",
            json={"stock_qty": 1, "initial_stock_qty": 100},
            headers=admin_auth_headers
        )

        order_payload_1 = {
            "customer_identifier": "Customer A",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [{"product_barcode": "8906006787377", "product_name": "Vinegar", "unit_price": 30.0, "quantity": 1}]
        }
        order_payload_2 = {
            "customer_identifier": "Customer B",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [{"product_barcode": "8906006787377", "product_name": "Vinegar", "unit_price": 30.0, "quantity": 1}]
        }

        # Launch two orders simultaneously
        responses = await asyncio.gather(
            client.post("/api/v1/orders", json=order_payload_1, headers=customer_auth_headers),
            client.post("/api/v1/orders", json=order_payload_2, headers=customer_auth_headers)
        )

        status_codes = [r.status_code for r in responses]
        # Exactly one order must succeed (201) and the other must fail (400)
        assert 201 in status_codes, "At least one order should have succeeded"
        assert 400 in status_codes, "The second concurrent order must have been rejected due to zero stock"

        # Final stock must be exactly 0, not negative
        res = await client.get("/api/v1/products/barcode/8906006787377")
        assert res.json()["stock_qty"] == 0

        # Reset Vinegar back to 100
        await client.put(
            "/api/v1/admin/products/8906006787377",
            json={"stock_qty": 100, "initial_stock_qty": 100},
            headers=admin_auth_headers
        )


@pytest.mark.asyncio
async def test_transaction_refund_restores_stock(admin_auth_headers, customer_auth_headers):
    """Requirement 3 & 4: Refunded transaction updates status and restores physical inventory."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Set Lux Soap stock to 100
        await client.put(
            "/api/v1/admin/products/8909106022645",
            json={"stock_qty": 100, "initial_stock_qty": 100},
            headers=admin_auth_headers
        )

        # Customer purchases 4 units
        order_res = await client.post("/api/v1/orders", json={
            "customer_identifier": "Refund Test Customer",
            "payment_method": "UPI",
            "payment_status": "PAID",
            "items": [{"product_barcode": "8909106022645", "product_name": "Lux Soap", "unit_price": 70.0, "quantity": 4}]
        }, headers=customer_auth_headers)
        assert order_res.status_code == 201
        order = order_res.json()
        order_num = order["order_number"]

        # Stock is now 96
        p_res = await client.get("/api/v1/products/barcode/8909106022645")
        assert p_res.json()["stock_qty"] == 96

        # Admin refunds transaction
        refund_res = await client.post(
            f"/api/v1/admin/transactions/{order_num}/refund",
            headers=admin_auth_headers
        )
        assert refund_res.status_code == 200
        refund_data = refund_res.json()
        assert refund_data["payment_status"] == "REFUNDED"
        assert refund_data["verification_status"] == "CANCELLED"

        # Stock should be restored back to 100!
        p_res2 = await client.get("/api/v1/products/barcode/8909106022645")
        assert p_res2.json()["stock_qty"] == 100
        assert p_res2.json()["stock_change"] == 0
