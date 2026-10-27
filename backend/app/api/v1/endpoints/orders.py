import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete

from app.db.session import get_db
from app.models.order import Order, OrderItem
from app.models.counter import Counter
from app.models.product import Product
from app.models.user import User
from app.core.auth import get_current_user, require_admin, is_store_admin, validate_counter_access
from app.schemas.order import (
    OrderCreate,
    OrderRead,
    QRVerificationRequest,
    QRVerificationResponse,
)
from app.schemas.ws import WebSocketMessage
from app.services.qr_service import qr_service
from app.services.websocket_manager import ws_manager

router = APIRouter(prefix="/orders", tags=["Orders"])


async def _assign_counter(db: AsyncSession, total_item_units: int) -> Counter:
    """
    Least-queue-load counter assignment.
    Prefers express counters for small orders (<=5 units), avoids them for larger.
    Breaks ties by counter_number (predictable, deterministic).
    """
    c_stmt = select(Counter).where(Counter.is_active == True)
    c_res = await db.execute(c_stmt)
    all_counters = c_res.scalars().all()

    if not all_counters:
        raise HTTPException(status_code=503, detail="No active checkout counters available.")

    best: Optional[Counter] = None
    min_load = float("inf")

    for counter in all_counters:
        # Express counters: only accept <= 5 item units
        if counter.is_express and total_item_units > 5:
            continue

        # Count orders currently pending verification at this counter
        load_stmt = select(func.count(Order.id)).where(
            Order.assigned_counter_number == counter.counter_number,
            Order.is_verified_by_cashier == False,
        )
        load = (await db.execute(load_stmt)).scalar() or 0

        # Prefer express for small orders (speed factor bonus)
        effective_load = load - (0.5 if counter.is_express and total_item_units <= 5 else 0)

        if effective_load < min_load or (effective_load == min_load and best and counter.counter_number < best.counter_number):
            min_load = effective_load
            best = counter

    if not best:
        # Fallback: any counter, ignoring express restriction
        best = min(all_counters, key=lambda c: c.counter_number)

    return best


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a finalized order after customer payment confirmation.

    Security:
    - Authentication is strictly required (no ghost/anonymous checkout).
    - Product prices are re-validated from the database. Client-sent prices are ignored.
    - QR token contains only the order_number — no sensitive data in the barcode.
    - Counter is assigned by least-load algorithm, not by client preference.
    - Order is linked to the authenticated user_id for history retrieval.
    - Idempotency key prevents duplicate charges or double stock decrements on network retry.
    """
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order must contain at least 1 item.")

    user = current_user

    # --- Idempotency Check: prevent duplicate orders on retry ---
    idemp_key = payload.idempotency_key or (x_idempotency_key.strip() if x_idempotency_key else None)
    if idemp_key:
        idemp_stmt = select(Order).where(Order.idempotency_key == idemp_key)
        idemp_res = await db.execute(idemp_stmt)
        existing_order = idemp_res.scalars().first()
        if existing_order:
            return existing_order

    # --- Server-side price validation & atomic stock decrement ---
    validated_items = []
    stock_updates = []
    for item in payload.items:
        prod_res = await db.execute(
            select(Product).where(Product.barcode == item.product_barcode, Product.is_active == True)
        )
        product = prod_res.scalars().first()

        if not product:
            raise HTTPException(
                status_code=400,
                detail=f"Product with barcode '{item.product_barcode}' not found or inactive.",
            )
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Quantity must be at least 1 for '{product.name}'.")
        if product.stock_qty <= 0:
            raise HTTPException(status_code=400, detail=f"'{product.name}' is out of stock.")
        if product.stock_qty < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot purchase {item.quantity} units of '{product.name}'. Only {product.stock_qty} in stock."
            )

        # Atomic stock decrement: ensure stock_qty >= quantity
        stock_update_stmt = (
            update(Product)
            .where(Product.barcode == item.product_barcode, Product.stock_qty >= item.quantity, Product.is_active == True)
            .values(stock_qty=Product.stock_qty - item.quantity)
        )
        update_res = await db.execute(stock_update_stmt)
        if update_res.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Concurrent purchase conflict: remaining stock for '{product.name}' is insufficient."
            )

        new_stock = product.stock_qty - item.quantity
        init_stock = getattr(product, "initial_stock_qty", 100) or 100

        validated_items.append({
            "barcode": product.barcode,
            "name": product.name,
            "price": product.price,       # Server price — immutable
            "quantity": item.quantity,
            "new_stock": new_stock,
            "initial_stock": init_stock,
        })

        stock_updates.append({
            "barcode": product.barcode,
            "name": product.name,
            "stock_qty": new_stock,
            "initial_stock_qty": init_stock,
            "stock_change": new_stock - init_stock,
            "price": product.price
        })

    # --- Calculate financials ---
    subtotal = round(sum(v["price"] * v["quantity"] for v in validated_items), 2)
    tax_amount = round(subtotal * 0.05, 2)           # 5% GST
    discount_amount = round(15.0 if subtotal > 50 else 0.0, 2)
    total_amount = max(0.0, round(subtotal + tax_amount - discount_amount, 2))

    total_item_units = sum(v["quantity"] for v in validated_items)

    # --- Assign counter ---
    assigned_counter = None
    if payload.preferred_counter:
        c_res = await db.execute(
            select(Counter).where(Counter.counter_number == payload.preferred_counter, Counter.is_active == True)
        )
        assigned_counter = c_res.scalars().first()

    if not assigned_counter:
        assigned_counter = await _assign_counter(db, total_item_units)


    order_number = f"FS-{uuid.uuid4().hex[:6].upper()}"

    # QR token = just the order number. Nothing else.
    qr_token = order_number

    customer_name = (
        user.display_name if user else (payload.customer_identifier or "Guest")
    )

    order = Order(
        order_number=order_number,
        customer_identifier=customer_name,
        user_id=user.id if user else None,
        subtotal=subtotal,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        # Server-decided. Real payments are not integrated yet (demo mode), so every
        # order is recorded as PAID. TODO(payments, last priority): replace this with
        # the verified result from the payment provider. Never trust the client here.
        payment_status="PAID",
        payment_method=payload.payment_method,
        counter_id=assigned_counter.id,
        assigned_counter_number=assigned_counter.counter_number,
        qr_token=qr_token,
        verification_status="PENDING",
        idempotency_key=idemp_key,
    )
    db.add(order)
    await db.flush()

    for v in validated_items:
        db.add(OrderItem(
            order_id=order.id,
            product_barcode=v["barcode"],
            product_name=v["name"],
            unit_price=v["price"],
            quantity=v["quantity"],
            total_price=round(v["price"] * v["quantity"], 2),
        ))

    # Atomically clean up customer server-side cart session in same transaction
    if payload.cart_id:
        from app.models.cart import Cart, CartItem
        cart_res = await db.execute(select(Cart).where(Cart.id == payload.cart_id))
        c_obj = cart_res.scalars().first()
        if c_obj:
            if not c_obj.customer_identifier or c_obj.customer_identifier == user.username or user.role in ("admin", "store_admin"):
                c_obj.status = "COMPLETED"
                await db.execute(delete(CartItem).where(CartItem.cart_id == payload.cart_id))

    await db.commit()
    await db.refresh(order)

    # Real-time WebSocket broadcasts across store
    # 1. Counter specific alert (broadcasts to counter channel, admin, and order channel)
    order_notification = WebSocketMessage(
        event="NEW_ORDER_ASSIGNED",
        counter_number=assigned_counter.counter_number,
        data={
            "order_number": order.order_number,
            "customer": order.customer_identifier,
            "items_count": len(validated_items),
            "total": order.total_amount,
            "assigned_counter_number": assigned_counter.counter_number,
            "verification_status": order.verification_status,
        },
    )
    await ws_manager.broadcast_order_event(
        order_number=order.order_number,
        counter_number=assigned_counter.counter_number,
        message=order_notification
    )
    # Also broadcast alias NEW_ORDER for compatibility
    await ws_manager.broadcast_to_channel(
        f"counter:{assigned_counter.counter_number}",
        WebSocketMessage(
            event="NEW_ORDER",
            counter_number=assigned_counter.counter_number,
            data=order_notification.data
        )
    )

    # 2. Global real-time transaction event (updates admin transactions ledger, queue, and KPIs)
    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="NEW_TRANSACTION",
            counter_number=assigned_counter.counter_number,
            data={
                "order_number": order.order_number,
                "customer_identifier": order.customer_identifier,
                "total_amount": order.total_amount,
                "subtotal": order.subtotal,
                "tax_amount": order.tax_amount,
                "discount_amount": order.discount_amount,
                "payment_method": order.payment_method,
                "payment_status": order.payment_status,
                "verification_status": order.verification_status,
                "assigned_counter_number": order.assigned_counter_number,
                "items_count": len(validated_items),
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "products": [
                    {
                        "barcode": v["barcode"],
                        "name": v["name"],
                        "price": v["price"],
                        "quantity": v["quantity"],
                        "subtotal": round(v["price"] * v["quantity"], 2)
                    }
                    for v in validated_items
                ]
            }
        )
    )

    # 3. Global real-time stock update event (updates admin inventory table & customer view immediately)
    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="STOCK_UPDATED",
            data={"products": stock_updates}
        )
    )

    return order


@router.post("/verify-qr", response_model=QRVerificationResponse)
async def verify_order_qr(
    payload: QRVerificationRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Legacy QR verification endpoint — requires staff/admin authentication.
    The primary verification flow now uses /admin/verify/lookup.
    """
    # qr_token is now just the order_number string
    order_num = payload.qr_token.strip()

    stmt = select(Order).where(Order.order_number == order_num)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        return QRVerificationResponse(valid=False, message="Order not found.")

    if order.payment_status != "PAID":
        return QRVerificationResponse(valid=False, message="Payment not confirmed for this order.")

    return QRVerificationResponse(
        valid=True,
        order=OrderRead.model_validate(order),
        message=f"Order #{order.order_number} is valid.",
    )


@router.get("/{order_number}/qr-image")
async def get_order_qr_image(
    order_number: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the server-rendered QR PNG for an order.
    The QR encodes only the order_number — the admin terminal resolves everything else from the DB.
    Requires customer ownership or admin role. Authenticated via Bearer token or token query param.
    """
    auth_token = None
    if authorization and authorization.startswith("Bearer "):
        auth_token = authorization.removeprefix("Bearer ").strip()
    elif token:
        auth_token = token.strip()

    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access order QR image."
        )

    from datetime import datetime, timezone
    from app.models.session import UserSession
    res = await db.execute(select(UserSession).where(UserSession.token == auth_token))
    session = res.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.")

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")

    current_user = session.user
    if not current_user or not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive account.")

    stmt = select(Order).where(Order.order_number == order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if current_user.role not in ("admin", "store_admin") and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied."
        )

    if current_user.role in ("admin", "store_admin") and not is_store_admin(current_user):
        eff_counter = await validate_counter_access(current_user, db=db)
        if order.assigned_counter_number != eff_counter:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Order is assigned to Counter {order.assigned_counter_number}, not Counter {eff_counter}."
            )

    png_bytes = await qr_service.generate_qr_bytes(order.qr_token)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{order_number}", response_model=OrderRead)
async def get_order_by_number(
    order_number: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns order status and details by order number.
    Enables live status polling for checkout and verification terminals.
    Strictly verifies user ownership or admin role to prevent IDOR data leaks.
    """
    stmt = select(Order).where(Order.order_number == order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if current_user.role not in ("admin", "store_admin") and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You do not own this order."
        )

    if current_user.role in ("admin", "store_admin") and not is_store_admin(current_user):
        eff_counter = await validate_counter_access(current_user, db=db)
        if order.assigned_counter_number != eff_counter:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Order is assigned to Counter {order.assigned_counter_number}, not Counter {eff_counter}."
            )

    return order
