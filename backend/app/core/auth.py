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
    """Dependency: ensures the authenticated user has the admin role."""
    user = await get_current_user(authorization=authorization, db=db)
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


def is_store_admin(user) -> bool:
    """
    Returns True if user has store-wide administrator privileges across all counters.
    Store admins can access, view, and verify orders across any counter.
    Counter staff users (e.g. staff01) have a specific counter_number assigned and are restricted to their counter.
    """
    if not user or getattr(user, "role", None) != "admin":
        return False
    # If username is "admin3" (the Store Admin) or "admin", or no specific counter is bound:
    if getattr(user, "username", None) in ("admin3", "admin") or not getattr(user, "counter_number", None):
        return True
    return False


def validate_counter_access(user, requested_counter: Optional[str]) -> str:
    """
    Validates and resolves the counter number for the authenticated user.
    - If user is a store admin: allows the requested_counter (or defaults to requested_counter or '03').
    - If user is a counter-specific staff: enforces user.counter_number.
      If requested_counter is provided and differs, raises 403 Forbidden.
    Returns the authoritative counter number.
    """
    if is_store_admin(user):
        return requested_counter or "03"

    staff_counter = getattr(user, "counter_number", None)
    if requested_counter and staff_counter and requested_counter != staff_counter:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Counter terminal restricted to Counter {staff_counter}. Cannot access Counter {requested_counter}."
        )
    return staff_counter or requested_counter or "03"

