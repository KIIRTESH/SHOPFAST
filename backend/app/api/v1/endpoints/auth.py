from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.session import get_db
from app.models.user import User
from app.models.session import UserSession
from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse, UserProfile, ChangePinRequest
from app.core.auth import (
    create_pin_hash,
    verify_pin,
    generate_session_token,
    session_expires_at,
    get_current_user,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _build_auth_response(user: User, token: str, expires_at: datetime) -> AuthResponse:
    return AuthResponse(
        token=token,
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        counter_number=user.counter_number,
        expires_at=expires_at.isoformat(),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_customer(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Customer self-registration. Creates a new customer account and returns a session token.
    Admin accounts are pre-seeded; they cannot be registered via this endpoint.
    """
    # Check username uniqueness
    res = await db.execute(select(User).where(User.username == payload.username))
    if res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already taken.",
        )

    pin_hash, pin_salt = create_pin_hash(payload.pin)
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        pin_hash=pin_hash,
        pin_salt=pin_salt,
        role="customer",
        is_active=True,
    )
    db.add(user)
    await db.flush()  # get user.id before creating session

    token = generate_session_token()
    expires = session_expires_at()
    session = UserSession(
        token=token,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        expires_at=expires,
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

    return _build_auth_response(user, token, expires)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login for both customers and admin staff.
    Returns a session token valid for 7 days.
    """
    res = await db.execute(select(User).where(User.username == payload.username))
    user = res.scalars().first()

    if not user or not verify_pin(payload.pin, user.pin_hash, user.pin_salt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or PIN.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact store management.",
        )

    if payload.portal is not None:
        if payload.portal == "customer" and user.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Customer portal is for customer accounts only.",
            )
        elif payload.portal == "staff" and user.role not in ("admin", "staff"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Staff portal is for staff accounts only.",
            )
        elif payload.portal == "admin" and user.role != "store_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Admin portal is for store administrator accounts only.",
            )

    token = generate_session_token()
    expires = session_expires_at()
    session = UserSession(
        token=token,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        expires_at=expires,
    )
    db.add(session)
    await db.commit()

    return _build_auth_response(user, token, expires)


@router.post("/guest", response_model=AuthResponse)
async def guest_session(
    db: AsyncSession = Depends(get_db),
):
    """
    Creates or reuses an active guest session token so first-time walk-in shoppers
    can immediately scan, build a cart, and checkout without a forced signup screen.
    """
    res = await db.execute(select(User).where(User.username == "guest"))
    user = res.scalars().first()
    if not user:
        pin_hash, pin_salt = create_pin_hash("1234")
        user = User(
            username="guest",
            display_name="Guest Shopper",
            pin_hash=pin_hash,
            pin_salt=pin_salt,
            role="customer",
            is_active=True,
        )
        db.add(user)
        await db.flush()

    token = generate_session_token()
    expires = session_expires_at()
    session = UserSession(
        token=token,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        expires_at=expires,
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

    return _build_auth_response(user, token, expires)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Invalidates the current session token."""
    if not authorization or not authorization.startswith("Bearer "):
        return  # Already logged out

    token = authorization.removeprefix("Bearer ").strip()
    await db.execute(delete(UserSession).where(UserSession.token == token))
    await db.commit()


@router.get("/me", response_model=UserProfile)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the authenticated user's profile.
    Frontend calls this on load to restore session state.
    """
    return UserProfile(
        user_id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        counter_number=current_user.counter_number,
    )


@router.post("/change-pin")
async def change_pin(
    payload: ChangePinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Secure PIN change for authenticated user (store admin or staff)."""
    if not verify_pin(payload.current_pin, current_user.pin_hash, current_user.pin_salt):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current PIN is incorrect."
        )

    new_hash, new_salt = create_pin_hash(payload.new_pin)
    current_user.pin_hash = new_hash
    current_user.pin_salt = new_salt
    await db.commit()
    return {"message": "PIN updated successfully."}

