"""
PIN hashing using PBKDF2-HMAC-SHA256 (Python stdlib — no extra dependencies).
Session token generation using secrets.token_hex.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

SESSION_EXPIRE_HOURS = 24 * 7  # 7 days
TOKEN_BYTES = 32  # 64-char hex string


def _hash_pin(pin: str, salt: str) -> str:
    """PBKDF2-HMAC-SHA256 with 200_000 iterations."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    )
    return dk.hex()


def create_pin_hash(pin: str) -> tuple[str, str]:
    """Returns (pin_hash, salt) for a new user."""
    salt = secrets.token_hex(16)
    return _hash_pin(pin, salt), salt


def verify_pin(pin: str, stored_hash: str, salt: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    expected = _hash_pin(pin, salt)
    return hmac.compare_digest(expected, stored_hash)


def generate_session_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def session_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRE_HOURS)


from app.db.session import get_db


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency: validates Bearer token and returns the authenticated User.
    Raises 401 if token is missing, invalid, or expired.
    """
    from app.models.session import UserSession

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    stmt = select(UserSession).where(UserSession.token == token)
    result = await db.execute(stmt)
    session = result.scalars().first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        await db.delete(session)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not session.user or not session.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )

    return session.user


async def require_admin(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Dependency: ensures the authenticated user has an admin or store_admin role."""
    user = await get_current_user(authorization=authorization, db=db)
    if user.role not in ("admin", "store_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


def is_store_admin(user) -> bool:
    """
    Returns True if user has store-wide administrator privileges across all counters.
    Determined strictly by explicit role 'store_admin'.
    No hardcoded usernames or automatic fallbacks for missing counter assignments.
    """
    if not user or not getattr(user, "is_active", False):
        return False
    return getattr(user, "role", None) == "store_admin"


async def validate_counter_access(
    user,
    requested_counter: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """
    Validates and resolves the counter number for the authenticated user.
    - If user is a store admin (role == 'store_admin'): allows the requested_counter (or defaults to '03').
    - If user is counter staff:
        - Must have a valid assigned counter_number.
        - If counter_number is missing, empty, or whitespace: raises 403 Forbidden.
        - Verifies that the staff member's assigned counter exists and is active in the ShopFast database.
          If nonexistent, inactive, or malformed, raises 403 Forbidden.
        - If requested_counter is provided and differs from assigned counter: raises 403 Forbidden.
    Returns the authoritative counter number.
    """
    if is_store_admin(user):
        return requested_counter or "03"

    staff_counter = getattr(user, "counter_number", None)
    if staff_counter is None or not str(staff_counter).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: No counter assigned to this staff account."
        )

    staff_counter = str(staff_counter).strip()

    # Query database to verify assigned counter exists and is active
    from app.models.counter import Counter

    async def _verify_counter(session: AsyncSession) -> bool:
        stmt = select(Counter).where(Counter.counter_number == staff_counter, Counter.is_active == True)
        res = await session.execute(stmt)
        return res.scalars().first() is not None

    if db is not None:
        counter_valid = await _verify_counter(db)
    else:
        from app.db.session import async_session_maker
        async with async_session_maker() as session:
            counter_valid = await _verify_counter(session)

    if not counter_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Assigned counter '{staff_counter}' is invalid or does not exist."
        )

    if requested_counter and str(requested_counter).strip() != staff_counter:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Counter terminal restricted to Counter {staff_counter}. Cannot access Counter {requested_counter}."
        )

    return staff_counter



