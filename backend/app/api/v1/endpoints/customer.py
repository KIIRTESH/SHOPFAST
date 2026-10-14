from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db.session import get_db
from app.models.order import Order
from app.schemas.order import OrderRead
from app.services.qr_service import qr_service

router = APIRouter(prefix="/customer", tags=["Customer"])


async def _resolve_user(authorization: Optional[str], db: AsyncSession):
    """Shared auth helper — avoids circular imports with auth.py dependency."""
    from datetime import datetime, timezone
    from app.models.session import UserSession

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    token = authorization.removeprefix("Bearer ").strip()
    res = await db.execute(select(UserSession).where(UserSession.token == token))
    session = res.scalars().first()

    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")

    if not session.user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive.")

    return session.user


@router.get("/orders", response_model=List[OrderRead])
async def get_customer_order_history(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
):
    """
    Returns the authenticated customer's order history, newest first.
    A customer can only access their own orders.
    """
    user = await _resolve_user(authorization, db)

    stmt = (
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(desc(Order.created_at))
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    orders = res.scalars().all()
    return orders


@router.get("/orders/{order_number}", response_model=OrderRead)
async def get_customer_order_detail(
    order_number: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a specific order's details including all items.
    Enforces ownership — customers can only view their own orders.
    """
    user = await _resolve_user(authorization, db)

    stmt = select(Order).where(Order.order_number == order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # Ownership check — critical security boundary
    if order.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. This order does not belong to your account.",
        )

    return order


@router.get("/orders/{order_number}/qr-image")
async def get_customer_order_qr(
    order_number: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the QR image PNG for a specific order.
    Enforces ownership — only the order's customer can retrieve it.
    """
    user = await _resolve_user(authorization, db)

    stmt = select(Order).where(Order.order_number == order_number)
    res = await db.execute(stmt)
    order = res.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    png_bytes = await qr_service.generate_qr_bytes(order.qr_token)
    return Response(content=png_bytes, media_type="image/png")
