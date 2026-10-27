from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_, func, delete
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
    AdminProductUpdateRequest,
    AdminProductCreateRequest,
    StaffAccountRead,
    StaffCreateRequest,
    StaffUpdateRequest,
    StaffResetPinRequest,
    CounterStatusUpdateRequest,
    CounterMonitorDetail,
)
from app.schemas.product import ProductRead
from app.schemas.ws import WebSocketMessage
from app.models.user import User
from app.services.websocket_manager import ws_manager
from app.services.admin_service import admin_service
from app.core.auth import (
    require_admin,
    is_store_admin,
    validate_counter_access,
    require_store_admin,
    create_pin_hash,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin & POS Terminal"],
    dependencies=[Depends(require_admin)]
)


@router.get("/analytics", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve live store operations KPI metrics for the Store Admin dashboard."""
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
    counter_number: Optional[str] = Query(None, description="Filter by counter number alias"),
    status: Optional[str] = Query(None, description="Filter by verification status (VERIFIED, PENDING, FLAGGED)"),
    search: Optional[str] = Query(None, description="Search by Order # or Customer"),
    date: Optional[str] = Query(None, description="Filter by date ('today' or 'YYYY-MM-DD')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Returns store-wide transaction audit ledger with real-time filters."""
    target_counter = counter or counter_number
    if not is_store_admin(current_admin):
        eff_counter = await validate_counter_access(current_admin, target_counter, db=db)
        target_counter = eff_counter

    return await admin_service.get_transactions(
        db=db,
        counter_number=target_counter,
        status_filter=status,
        search=search,
        date_filter=date,
        limit=limit,
        skip=skip
    )


@router.get("/products", response_model=List[ProductRead])
async def list_admin_products(
    search: Optional[str] = Query(None, description="Search name, barcode, or category"),
    low_stock: Optional[bool] = Query(None, description="Filter products with stock <= 10"),
    is_active: Optional[bool] = Query(None, description="Filter active/inactive products"),
    skip: int = 0,
    limit: int = 100,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: retrieve catalog with live stock tracking and filters."""
    stmt = select(Product)
    if search and search.strip():
        q = f"%{search.strip().lower()}%"
        stmt = stmt.where(or_(Product.name.ilike(q), Product.barcode.ilike(q), Product.category.ilike(q)))
    if low_stock is True:
        stmt = stmt.where(Product.stock_qty <= 10)
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
    stmt = stmt.order_by(Product.id).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_admin_product(
    payload: AdminProductCreateRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: add a new retail item with duplicate barcode detection."""
    clean_barcode = payload.barcode.strip()
    if not clean_barcode:
        raise HTTPException(status_code=400, detail="Barcode cannot be empty.")
    if not clean_barcode.isalnum():
        raise HTTPException(status_code=400, detail="Barcode must be alphanumeric.")

    stmt = select(Product).where(Product.barcode == clean_barcode)
    res = await db.execute(stmt)
    if res.scalars().first():
        raise HTTPException(
            status_code=400,
            detail=f"Product with barcode '{clean_barcode}' already exists. Duplicate barcode detected."
        )

    product = Product(
        barcode=clean_barcode,
        name=payload.name.strip(),
        description=payload.description or "",
        price=payload.price,
        stock_qty=payload.stock_qty,
        initial_stock_qty=payload.stock_qty,
        category=payload.category or "General",
        icon=payload.icon or "📦",
        is_active=payload.is_active
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="STOCK_UPDATED",
            data={
                "products": [{
                    "barcode": product.barcode,
                    "name": product.name,
                    "stock_qty": product.stock_qty,
                    "initial_stock_qty": product.initial_stock_qty,
                    "stock_change": 0,
                    "price": product.price
                }]
            }
        )
    )
    return product


@router.put("/products/{barcode}", response_model=ProductRead)
async def update_admin_product(
    barcode: str,
    payload: AdminProductUpdateRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: update product price, stock quantity, active status, or title."""
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


# =====================================================================
# STAFF MANAGEMENT ENDPOINTS (Store Admin Only)
# =====================================================================

@router.get("/staff", response_model=List[StaffAccountRead])
async def list_staff_accounts(
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: view all assigned counter staff accounts."""
    from app.models.session import UserSession
    from datetime import datetime, timezone

    stmt = select(User).where(User.role.in_(["admin", "staff"])).order_by(User.counter_number.asc().nulls_last(), User.id)
    res = await db.execute(stmt)
    staff_users = res.scalars().all()

    now = datetime.now(timezone.utc)
    sess_stmt = select(UserSession.user_id, func.max(UserSession.created_at)).where(
        UserSession.expires_at > now
    ).group_by(UserSession.user_id)
    sess_res = await db.execute(sess_stmt)
    active_users = dict(sess_res.all())

    results = []
    for u in staff_users:
        results.append(
            StaffAccountRead(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                role=u.role,
                counter_number=u.counter_number,
                is_active=u.is_active,
                is_online=u.id in active_users,
                last_active=active_users.get(u.id),
                created_at=getattr(u, "created_at", None)
            )
        )
    return results


@router.post("/staff", response_model=StaffAccountRead, status_code=status.HTTP_201_CREATED)
async def create_staff_account(
    payload: StaffCreateRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: provision a new staff account mapped to a counter."""
    uname = payload.username.strip().lower()
    if not uname or len(uname) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")

    u_chk = await db.execute(select(User).where(User.username == uname))
    if u_chk.scalars().first():
        raise HTTPException(status_code=400, detail=f"Username '{uname}' is already in use.")

    from app.models.counter import Counter
    c_chk = await db.execute(select(Counter).where(Counter.counter_number == payload.counter_number))
    if not c_chk.scalars().first():
        raise HTTPException(status_code=400, detail=f"Counter '{payload.counter_number}' does not exist.")

    pin_hash, pin_salt = create_pin_hash(payload.pin)
    new_staff = User(
        username=uname,
        display_name=payload.display_name.strip(),
        pin_hash=pin_hash,
        pin_salt=pin_salt,
        role=payload.role or "staff",
        counter_number=payload.counter_number,
        is_active=True
    )
    db.add(new_staff)
    await db.commit()
    await db.refresh(new_staff)

    return StaffAccountRead(
        id=new_staff.id,
        username=new_staff.username,
        display_name=new_staff.display_name,
        role=new_staff.role,
        counter_number=new_staff.counter_number,
        is_active=new_staff.is_active,
        is_online=False,
        last_active=None,
        created_at=getattr(new_staff, "created_at", None)
    )


@router.put("/staff/{user_id}", response_model=StaffAccountRead)
async def update_staff_account(
    user_id: int,
    payload: StaffUpdateRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: update staff member name, reassign counter, or activate/deactivate."""
    from app.models.session import UserSession
    from app.models.counter import Counter

    stmt = select(User).where(User.id == user_id, User.role.in_(["admin", "staff"]))
    res = await db.execute(stmt)
    staff = res.scalars().first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff account not found.")

    if payload.display_name is not None:
        staff.display_name = payload.display_name.strip()
    if payload.counter_number is not None:
        c_chk = await db.execute(select(Counter).where(Counter.counter_number == payload.counter_number))
        if not c_chk.scalars().first():
            raise HTTPException(status_code=400, detail=f"Counter '{payload.counter_number}' does not exist.")
        staff.counter_number = payload.counter_number
    if payload.is_active is not None:
        staff.is_active = payload.is_active
        if not payload.is_active:
            await db.execute(delete(UserSession).where(UserSession.user_id == staff.id))

    await db.commit()
    await db.refresh(staff)

    return StaffAccountRead(
        id=staff.id,
        username=staff.username,
        display_name=staff.display_name,
        role=staff.role,
        counter_number=staff.counter_number,
        is_active=staff.is_active,
        is_online=False,
        last_active=None,
        created_at=getattr(staff, "created_at", None)
    )


@router.post("/staff/{user_id}/reset-pin")
async def reset_staff_pin(
    user_id: int,
    payload: StaffResetPinRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: reset staff member PIN and immediately invalidate active sessions."""
    from app.models.session import UserSession

    stmt = select(User).where(User.id == user_id, User.role.in_(["admin", "staff"]))
    res = await db.execute(stmt)
    staff = res.scalars().first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff account not found.")

    pin_hash, pin_salt = create_pin_hash(payload.new_pin)
    staff.pin_hash = pin_hash
    staff.pin_salt = pin_salt
    await db.execute(delete(UserSession).where(UserSession.user_id == staff.id))
    await db.commit()

    return {"message": f"PIN for staff '{staff.username}' has been securely reset."}


# =====================================================================
# COUNTERS MONITORING & CONTROL ENDPOINTS (Store Admin Only)
# =====================================================================

@router.get("/counters", response_model=List[CounterMonitorDetail])
async def list_admin_counters(
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: centralized real-time view of all five assigned counters."""
    from app.models.counter import Counter
    from app.services.queue_service import queue_service
    from app.models.session import UserSession
    from datetime import datetime, timezone

    stmt = select(Counter).order_by(Counter.counter_number)
    res = await db.execute(stmt)
    counters = res.scalars().all()

    staff_stmt = select(User).where(User.role.in_(["admin", "staff"]))
    staff_res = await db.execute(staff_stmt)
    staff_by_counter = {s.counter_number: s for s in staff_res.scalars().all() if s.counter_number}

    now = datetime.now(timezone.utc)
    sess_stmt = select(UserSession.user_id).where(UserSession.expires_at > now)
    sess_res = await db.execute(sess_stmt)
    online_user_ids = set(sess_res.scalars().all())

    results = []
    for c in counters:
        cust_count, _, _ = await queue_service.get_counter_load(db, c)

        waiting_stmt = select(func.count(Order.id)).where(
            Order.assigned_counter_number == c.counter_number,
            Order.is_verified_by_cashier == False,
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        waiting_count = (await db.execute(waiting_stmt)).scalar() or 0

        verif_stmt = select(func.count(Order.id)).where(
            Order.assigned_counter_number == c.counter_number,
            Order.is_verified_by_cashier == True
        )
        verified_count = (await db.execute(verif_stmt)).scalar() or 0

        rev_stmt = select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(
            Order.assigned_counter_number == c.counter_number,
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        rev = float((await db.execute(rev_stmt)).scalar() or 0.0)

        assigned_u = staff_by_counter.get(c.counter_number)
        staff_read = None
        if assigned_u:
            staff_read = StaffAccountRead(
                id=assigned_u.id,
                username=assigned_u.username,
                display_name=assigned_u.display_name,
                role=assigned_u.role,
                counter_number=assigned_u.counter_number,
                is_active=assigned_u.is_active,
                is_online=assigned_u.id in online_user_ids,
                last_active=None,
                created_at=getattr(assigned_u, "created_at", None)
            )

        results.append(
            CounterMonitorDetail(
                id=c.id,
                counter_number=c.counter_number,
                name=c.name,
                is_active=c.is_active,
                is_express=c.is_express,
                avg_scan_speed_factor=c.avg_scan_speed_factor,
                assigned_staff=staff_read,
                active_queue_length=cust_count,
                waiting_orders_count=waiting_count,
                verified_today_count=verified_count,
                counter_revenue=round(rev, 2)
            )
        )
    return results


@router.patch("/counters/{counter_number}/status")
async def update_counter_status(
    counter_number: str,
    payload: CounterStatusUpdateRequest,
    current_admin: User = Depends(require_store_admin),
    db: AsyncSession = Depends(get_db)
):
    """Store Admin: open or close a checkout counter."""
    from app.models.counter import Counter
    stmt = select(Counter).where(Counter.counter_number == counter_number)
    res = await db.execute(stmt)
    counter = res.scalars().first()
    if not counter:
        raise HTTPException(status_code=404, detail=f"Counter '{counter_number}' not found.")

    counter.is_active = payload.is_active
    await db.commit()
    await db.refresh(counter)

    await ws_manager.broadcast_global(
        WebSocketMessage(
            event="COUNTER_STATUS_CHANGED",
            counter_number=counter.counter_number,
            data={"counter_number": counter.counter_number, "is_active": counter.is_active}
        )
    )

    return {
        "counter_number": counter.counter_number,
        "is_active": counter.is_active,
        "message": f"Counter {counter.counter_number} is now {'OPEN' if counter.is_active else 'CLOSED'}."
    }



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
