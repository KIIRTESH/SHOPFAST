from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.db.session import get_db
from app.models.order import Order
from app.models.counter import Counter
from app.models.user import User
from app.schemas.admin import (
    AdminOrderVerificationDetail,
    AdminLookupRequest,
    AdminScanItemRequest,
    AdminScanItemResponse,
    AdminCompleteVerificationRequest,
    AdminDiscrepancyActionRequest,
    AdminTransactionSummary,
)
from app.core.auth import require_staff, validate_counter_access, is_store_admin
from app.services.admin_service import admin_service
from app.services.queue_service import queue_service

router = APIRouter(
    prefix="/staff",
    tags=["Staff Counter Terminal"],
    dependencies=[Depends(require_staff)]
)


@router.get("/dashboard")
async def get_staff_dashboard(
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Staff dashboard: operational metrics and active queue strictly scoped
    to the authenticated staff member's assigned checkout register.
    """
    eff_counter = await validate_counter_access(current_user, db=db)

    # Counter details
    stmt = select(Counter).where(Counter.counter_number == eff_counter)
    res = await db.execute(stmt)
    counter = res.scalars().first()
    if not counter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assigned counter '{eff_counter}' not found in store database."
        )

    # Active queue & waiting customers
    cust_count, items_count, wait_sec = await queue_service.get_counter_load(db, counter)

    # Orders awaiting cashier reverification at this counter
    pending_stmt = select(func.count(Order.id)).where(
        Order.assigned_counter_number == eff_counter,
        Order.is_verified_by_cashier == False,
        Order.payment_status == "PAID",
        Order.verification_status != "CANCELLED"
    )
    pending_count = (await db.execute(pending_stmt)).scalar() or 0

    # Orders verified today at this counter
    verified_stmt = select(func.count(Order.id)).where(
        Order.assigned_counter_number == eff_counter,
        Order.is_verified_by_cashier == True
    )
    verified_count = (await db.execute(verified_stmt)).scalar() or 0

    # Today's revenue for this counter
    rev_stmt = select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(
        Order.assigned_counter_number == eff_counter,
        Order.payment_status == "PAID",
        Order.verification_status != "CANCELLED"
    )
    counter_revenue = float((await db.execute(rev_stmt)).scalar() or 0.0)

    # Recent transactions for this counter
    recent_transactions = await admin_service.get_transactions(
        db=db,
        counter_number=eff_counter,
        limit=10
    )

    return {
        "counter_number": counter.counter_number,
        "counter_name": counter.name,
        "is_active": counter.is_active,
        "is_express": counter.is_express,
        "staff_username": current_user.username,
        "staff_display_name": current_user.display_name,
        "pending_verifications_count": int(pending_count),
        "verified_today_count": int(verified_count),
        "active_queue_length": int(cust_count),
        "estimated_wait_seconds": int(wait_sec),
        "counter_revenue": round(counter_revenue, 2),
        "recent_transactions": recent_transactions
    }


@router.get("/orders/active", response_model=List[AdminOrderVerificationDetail])
async def get_staff_active_orders(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists incoming customer orders awaiting physical cart verification
    strictly at the authenticated staff member's assigned counter.
    """
    eff_counter = await validate_counter_access(current_user, db=db)

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


@router.get("/transactions", response_model=List[AdminTransactionSummary])
async def list_staff_transactions(
    status: Optional[str] = Query(None, description="Filter by status (VERIFIED, PENDING, FLAGGED)"),
    search: Optional[str] = Query(None, description="Search by Order # or Customer"),
    date: Optional[str] = Query(None, description="Filter by date ('today' or 'YYYY-MM-DD')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns transaction audit ledger strictly for the staff member's assigned counter.
    Server-side filtering guarantees staff cannot view other counters' records.
    """
    eff_counter = await validate_counter_access(current_user, db=db)

    return await admin_service.get_transactions(
        db=db,
        counter_number=eff_counter,
        status_filter=status,
        search=search,
        date_filter=date,
        limit=limit,
        skip=skip
    )


@router.post("/verify/lookup", response_model=AdminOrderVerificationDetail)
async def staff_lookup_order(
    payload: AdminLookupRequest,
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Look up customer order by QR payload or Order Number for cashier reverification.
    Enforces that order is assigned to the authenticated cashier's counter.
    """
    eff_counter = await validate_counter_access(current_user, payload.counter_number, db=db)
    try:
        detail = await admin_service.lookup_order(
            db=db,
            token_or_number=payload.token_or_order_number,
            counter_number=eff_counter
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{payload.token_or_order_number}' not found."
        )
    return detail


@router.post("/verify/scan", response_model=AdminScanItemResponse)
async def staff_scan_physical_item(
    payload: AdminScanItemRequest,
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Cashier physically scans an item barcode from customer basket.
    Validates against paid cart items and updates verification progress.
    """
    eff_counter = await validate_counter_access(current_user, payload.counter_number, db=db)
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
async def staff_complete_verification(
    payload: AdminCompleteVerificationRequest,
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """
    Cashier finalizes verification and clears customer for exit.
    Records authenticated staff identity and completion timestamp.
    """
    eff_counter = await validate_counter_access(current_user, payload.counter_number, db=db)
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
async def staff_reset_verification(
    order_number: str = Query(..., description="Order number to reset"),
    counter_number: Optional[str] = Query(None, description="Counter number"),
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Resets item verification progress for re-scan workflow."""
    eff_counter = await validate_counter_access(current_user, counter_number, db=db)
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
async def staff_discrepancy_action(
    payload: AdminDiscrepancyActionRequest,
    current_user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db)
):
    """Handles discrepancy actions on unexpected item in customer basket."""
    eff_counter = await validate_counter_access(current_user, payload.counter_number, db=db)
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
