from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.db.session import get_db
from app.models.order import Order
from app.models.product import Product
from app.schemas.admin import (
    AdminOrderVerificationDetail,
    AdminLookupRequest,
    AdminScanItemRequest,
    AdminScanItemResponse,
    AdminCompleteVerificationRequest,
    AdminDiscrepancyActionRequest,
    AdminAnalyticsResponse,
    AdminTransactionSummary,
    AdminProductUpdateRequest
)
from app.schemas.product import ProductRead
from app.schemas.ws import WebSocketMessage
from app.models.user import User
from app.services.websocket_manager import ws_manager
from app.services.admin_service import admin_service
from app.core.auth import require_admin, is_store_admin, validate_counter_access

router = APIRouter(
    prefix="/admin",
    tags=["Admin & POS Terminal"],
    dependencies=[Depends(require_admin)]
)


@router.get("/analytics", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(db: AsyncSession = Depends(get_db)):
    """Retrieve live store operations KPI metrics for the Admin dashboard."""
    return await admin_service.get_analytics(db)


@router.post("/verify/lookup", response_model=AdminOrderVerificationDetail)
async def lookup_order_for_verification(
    payload: AdminLookupRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Looks up a customer order by Fast-Pass QR token payload or Order Number.
    Initializes cashier verification session.
    """
    eff_counter = await validate_counter_access(current_admin, payload.counter_number, db=db)
    try:
        detail = await admin_service.lookup_order(
            db=db,
            token_or_number=payload.token_or_order_number,
            counter_number=eff_counter
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{payload.token_or_order_number}' not found in FASTSHOP system."
        )
    return detail



@router.post("/verify/scan", response_model=AdminScanItemResponse)
async def scan_physical_item(
    payload: AdminScanItemRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Cashier physically scans an item barcode from customer's shopping basket.
    Validates against paid cart, detects discrepancies, and updates verification progress.
    """
    eff_counter = await validate_counter_access(current_admin, payload.counter_number, db=db)
    try:
        (
            status_code,
            msg,
            prod_name,
            expected,
            scanned,
            is_all_matched,
            order_detail
        ) = await admin_service.scan_physical_item(
            db=db,
            order_number=payload.order_number,
            scanned_barcode=payload.scanned_barcode,
            counter_number=eff_counter
        )
        return AdminScanItemResponse(
            status=status_code,
            scanned_barcode=payload.scanned_barcode,
            product_name=prod_name,
            expected_qty=expected,
            scanned_qty=scanned,
            message=msg,
            is_all_matched=is_all_matched,
            order=order_detail
        )
    except ValueError as e:
        err = str(e)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)


@router.post("/verify/complete", response_model=AdminOrderVerificationDetail)
async def complete_customer_verification(
    payload: AdminCompleteVerificationRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Cashier finalizes clearance, prints/stamps receipt, and releases customer for exit.
    Records verification performance duration and clears transaction.
    """
    eff_counter = await validate_counter_access(current_admin, payload.counter_number, db=db)
    try:
        return await admin_service.complete_verification(
            db=db,
            order_number=payload.order_number,
            counter_number=eff_counter,
            duration_seconds=payload.duration_seconds
        )
    except ValueError as e:
        err = str(e)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)


@router.post("/verify/reset", response_model=AdminOrderVerificationDetail)
async def reset_verification_session(
    order_number: str = Query(..., description="Order number to reset"),
    counter_number: Optional[str] = Query(None, description="Cashier counter number"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Resets verification items for testing or re-scan workflows."""
    eff_counter = await validate_counter_access(current_admin, counter_number, db=db)
    try:
        return await admin_service.reset_verification(
            db=db,
            order_number=order_number,
            counter_number=eff_counter
        )
    except ValueError as e:
        err = str(e)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)


@router.post("/verify/discrepancy-action", response_model=AdminOrderVerificationDetail)
async def handle_discrepancy_action(
    payload: AdminDiscrepancyActionRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Handles cashier action on an unexpected item in basket:
    'REMOVE_AND_CONTINUE': customer removes unpurchased item from bag.
    'SEND_TO_REGULAR_CHECKOUT': transaction flagged and customer redirected to regular register.
    """
    eff_counter = await validate_counter_access(current_admin, payload.counter_number, db=db)
    stmt = select(Order).where(Order.order_number == payload.order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if eff_counter and order.assigned_counter_number != eff_counter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order #{order.order_number} is assigned to Counter {order.assigned_counter_number}, not Counter {eff_counter}."
        )

    if payload.action == "SEND_TO_REGULAR_CHECKOUT":
        order.verification_status = "FLAGGED"
        await db.commit()
        await db.refresh(order)

    return await admin_service._build_order_detail(db, order)


@router.get("/orders/active", response_model=List[AdminOrderVerificationDetail])
async def get_active_orders_for_counter(
    counter_number: Optional[str] = Query(None, description="Assigned counter number"),
    limit: int = Query(10, ge=1, le=50),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Lists current active incoming and processing orders at this counter register."""
    eff_counter = await validate_counter_access(current_admin, counter_number, db=db)
    from app.models.counter import Counter
    c_check = await db.execute(select(Counter).where(Counter.counter_number == eff_counter))
    if not c_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Counter '{eff_counter}' does not exist in store system."
        )

    stmt = (
        select(Order)
        .where(
            Order.assigned_counter_number == eff_counter,
            Order.is_verified_by_cashier == False,
            Order.verification_status != "CANCELLED",
            Order.payment_status != "REFUNDED"
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    orders = res.scalars().all()
    return await admin_service.build_order_details_batch(db, list(orders))



@router.get("/orders/{order_number}", response_model=AdminOrderVerificationDetail)
async def get_order_verification_detail(
    order_number: str,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve item-by-item verification breakdown for a specific order."""
    detail = await admin_service.lookup_order(db=db, token_or_number=order_number)
    if not detail:
        raise HTTPException(status_code=404, detail="Order not found.")

    if not is_store_admin(current_admin):
        eff_counter = await validate_counter_access(current_admin, db=db)
        if detail.assigned_counter_number != eff_counter:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Order #{order_number} is assigned to Counter {detail.assigned_counter_number}, not Counter {eff_counter}."
            )

    return detail


@router.get("/transactions", response_model=List[AdminTransactionSummary])
async def list_transactions_ledger(
    counter: Optional[str] = Query(None, description="Filter by counter number"),
    status: Optional[str] = Query(None, description="Filter by verification status (VERIFIED, PENDING, FLAGGED)"),
    search: Optional[str] = Query(None, description="Search by Order # or Customer"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Returns store-wide transaction audit ledger with real-time filters."""
    if not is_store_admin(current_admin):
        eff_counter = await validate_counter_access(current_admin, counter, db=db)
        counter = eff_counter

    return await admin_service.get_transactions(
        db=db,
        counter_number=counter,
        status_filter=status,
        search=search,
        limit=limit,
        skip=skip
    )


@router.get("/products", response_model=List[ProductRead])
async def list_admin_products(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """Retrieve store catalog with stock levels and status for inventory management."""
    stmt = select(Product).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.put("/products/{barcode}", response_model=ProductRead)
async def update_admin_product(
    barcode: str,
    payload: AdminProductUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update product price, stock quantity, active status, or title."""
    stmt = select(Product).where(Product.barcode == barcode)
    res = await db.execute(stmt)
    product = res.scalars().first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    if payload.name is not None:
        product.name = payload.name
    if payload.price is not None:
        product.price = payload.price
    if payload.stock_qty is not None:
        product.stock_qty = payload.stock_qty
    if payload.initial_stock_qty is not None:
        product.initial_stock_qty = payload.initial_stock_qty
    if payload.category is not None:
        product.category = payload.category
    if payload.icon is not None:
        product.icon = payload.icon
    if payload.is_active is not None:
        product.is_active = payload.is_active

    await db.commit()
    await db.refresh(product)

    # Real-time WebSocket broadcast to all admin and customer terminals
    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="STOCK_UPDATED",
            data={
                "products": [{
                    "barcode": product.barcode,
                    "name": product.name,
                    "stock_qty": product.stock_qty,
                    "initial_stock_qty": getattr(product, "initial_stock_qty", 100) or 100,
                    "stock_change": product.stock_qty - (getattr(product, "initial_stock_qty", 100) or 100),
                    "price": product.price
                }]
            }
        )
    )

    return product


@router.post("/transactions/{order_number}/refund", response_model=AdminTransactionSummary)
async def refund_transaction(
    order_number: str,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancels/refunds an order transaction and restores physical item stock in real time.
    Atomic inventory restore and WebSocket broadcast to Customer & Admin terminals.
    """
    stmt = select(Order).where(Order.order_number == order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail=f"Order #{order_number} not found.")

    if not is_store_admin(current_admin):
        eff_counter = await validate_counter_access(current_admin, db=db)
        if order.assigned_counter_number != eff_counter:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Counter terminal restricted to Counter {eff_counter}."
            )

    if order.payment_status == "REFUNDED":
        return AdminTransactionSummary(
            order_number=order.order_number,
            customer_identifier=order.customer_identifier,
            total_amount=order.total_amount,
            items_count=len(order.items),
            payment_method=order.payment_method,
            payment_status=order.payment_status,
            verification_status=order.verification_status,
            assigned_counter_number=order.assigned_counter_number,
            verification_duration_seconds=order.verification_duration_seconds,
            created_at=order.created_at
        )

    # Restore inventory stock atomically for each purchased item
    stock_updates = []
    for item in order.items:
        upd = (
            update(Product)
            .where(Product.barcode == item.product_barcode)
            .values(stock_qty=Product.stock_qty + item.quantity)
        )
        await db.execute(upd)

        p_res = await db.execute(select(Product).where(Product.barcode == item.product_barcode))
        prod = p_res.scalars().first()
        if prod:
            init_s = getattr(prod, "initial_stock_qty", 100) or 100
            stock_updates.append({
                "barcode": prod.barcode,
                "name": prod.name,
                "stock_qty": prod.stock_qty,
                "initial_stock_qty": init_s,
                "stock_change": prod.stock_qty - init_s,
                "price": prod.price
            })

    order.payment_status = "REFUNDED"
    order.verification_status = "CANCELLED"
    await db.commit()
    await db.refresh(order)

    # Real-time WebSocket broadcast for inventory restoration and transaction cancellation
    if stock_updates:
        await ws_manager.broadcast_global(
            WebSocketMessage(
                event="STOCK_UPDATED",
                data={"products": stock_updates}
            )
        )

    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="TRANSACTION_UPDATED",
            counter_number=order.assigned_counter_number,
            data={
                "order_number": order.order_number,
                "payment_status": "REFUNDED",
                "verification_status": "CANCELLED"
            }
        )
    )

    return AdminTransactionSummary(
        order_number=order.order_number,
        customer_identifier=order.customer_identifier,
        total_amount=order.total_amount,
        items_count=len(order.items),
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        verification_status=order.verification_status,
        assigned_counter_number=order.assigned_counter_number,
        verification_duration_seconds=order.verification_duration_seconds,
        created_at=order.created_at
    )
