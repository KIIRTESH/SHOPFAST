import pytest
import httpx
from app.main import app
from app.db.init_db import init_db


@pytest.mark.asyncio
async def test_product_classmate_book_in_db():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/products/barcode/8902519009807")
        assert response.status_code == 200
        data = response.json()
        assert data["barcode"] == "8902519009807"
        assert data["name"] in ["Classmate Notebook", "Classmate book"]
        assert data["price"] == 35.0
        assert data["stock"] == 50
        assert data["stock_qty"] == 50


@pytest.mark.asyncio
async def test_cart_add_and_duplicate_scan_increment(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        cart_id = "test_cart_session_1"
        
        # Clear cart first
        await client.delete(f"/api/v1/carts/{cart_id}", headers=customer_auth_headers)

        # 1. First Scan
        res1 = await client.post(f"/api/v1/carts/{cart_id}/items", json={
            "barcode": "8902519009807",
            "quantity": 1
        }, headers=customer_auth_headers)
        assert res1.status_code == 200
        cart1 = res1.json()
        assert len(cart1["items"]) == 1
        assert cart1["items"][0]["product_barcode"] == "8902519009807"
        assert cart1["items"][0]["product_name"] in ["Classmate Notebook", "Classmate book"]
        assert cart1["items"][0]["unit_price"] == 35.0
        assert cart1["items"][0]["quantity"] == 1
        assert cart1["item_count"] == 1
        assert cart1["subtotal"] == 35.0

        # 2. Second Scan of same barcode -> Must INCREMENT quantity without duplicating row
        res2 = await client.post(f"/api/v1/carts/{cart_id}/items", json={
            "barcode": "8902519009807",
            "quantity": 1
        }, headers=customer_auth_headers)
        assert res2.status_code == 200
        cart2 = res2.json()
        assert len(cart2["items"]) == 1  # No duplicate rows
        assert cart2["items"][0]["quantity"] == 2
        assert cart2["item_count"] == 2
        assert cart2["subtotal"] == 70.0


@pytest.mark.asyncio
async def test_cart_quantity_updates_and_deletion(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        cart_id = "test_cart_session_2"
        await client.delete(f"/api/v1/carts/{cart_id}", headers=customer_auth_headers)

        # Add Milk
        await client.post(f"/api/v1/carts/{cart_id}/items", json={
            "barcode": "890103038384",
            "quantity": 1
        }, headers=customer_auth_headers)

        # Update Quantity to 3
        patch_res = await client.patch(f"/api/v1/carts/{cart_id}/items/890103038384", json={
            "quantity": 3
        }, headers=customer_auth_headers)
        assert patch_res.status_code == 200
        cart = patch_res.json()
        assert cart["items"][0]["quantity"] == 3
        assert cart["subtotal"] == 68.0 * 3

        # Delete item
        del_res = await client.delete(f"/api/v1/carts/{cart_id}/items/890103038384", headers=customer_auth_headers)
        assert del_res.status_code == 200
        cart_after_del = del_res.json()
        assert len(cart_after_del["items"]) == 0
        assert cart_after_del["item_count"] == 0


@pytest.mark.asyncio
async def test_unknown_barcode_returns_404(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        cart_id = "test_cart_session_3"
        res = await client.post(f"/api/v1/carts/{cart_id}/items", json={
            "barcode": "9999999999999",
            "quantity": 1
        }, headers=customer_auth_headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_prefix_compatibility(customer_auth_headers):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Check canonical /api/v1/products/barcode/...
        res = await client.get("/api/v1/products/barcode/8902519009807")
        assert res.status_code == 200
        assert res.json()["name"] in ["Classmate Notebook", "Classmate book"]

        # Check canonical /api/v1/carts/...
        res_cart = await client.get("/api/v1/carts/test_compat_cart", headers=customer_auth_headers)
        assert res_cart.status_code == 200
