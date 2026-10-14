from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.models.counter import Counter
from app.models.order import Order
from app.schemas.counter import CounterRead, CounterMetrics
from app.services.queue_service import queue_service

router = APIRouter(prefix="/counters", tags=["Counters"])


@router.get("", response_model=List[CounterRead])
async def list_counters(db: AsyncSession = Depends(get_db)):
    """List all checkout registers and compute their live queue lengths & wait times."""
    stmt = select(Counter).where(Counter.is_active == True)
    result = await db.execute(stmt)
    counters = result.scalars().all()

    response = []
    for c in counters:
        cust_count, _, wait_sec = await queue_service.get_counter_load(db, c)
        c_read = CounterRead.model_validate(c)
        c_read.current_queue_length = cust_count
        c_read.estimated_wait_seconds = wait_sec

        rev_stmt = select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(
            Order.assigned_counter_number == c.counter_number,
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        rev_res = await db.execute(rev_stmt)
        c_read.counter_revenue = round(float(rev_res.scalar() or 0.0), 2)
        response.append(c_read)

    return response


@router.get("/{counter_number}/metrics", response_model=CounterMetrics)
async def get_counter_metrics(
    counter_number: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve POS operations dashboard metrics for a specific counter."""
    stmt = select(Counter).where(Counter.counter_number == counter_number)
    result = await db.execute(stmt)
    counter = result.scalars().first()

    if not counter:
        raise HTTPException(status_code=404, detail="Counter not found.")

    cust_count, items_count, _ = await queue_service.get_counter_load(db, counter)

    # Count verified orders today
    order_stmt = select(func.count(Order.id)).where(
        Order.assigned_counter_number == counter_number,
        Order.is_verified_by_cashier == True
    )
    order_res = await db.execute(order_stmt)
    verified_count = order_res.scalar() or 0

    return CounterMetrics(
        counter_number=counter_number,
        active_customers_in_line=cust_count,
        items_in_queue=items_count,
        avg_throughput_items_per_min=42.0 * counter.avg_scan_speed_factor,
        verified_today_count=verified_count
    )
