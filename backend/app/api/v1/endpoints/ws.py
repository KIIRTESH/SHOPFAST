import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import engine
from app.models.session import UserSession
from app.models.user import User
from app.services.websocket_manager import ws_manager

logger = logging.getLogger("fastshop.ws_router")
router = APIRouter(tags=["WebSockets"])


async def _get_user_from_token(token: Optional[str]) -> Tuple[bool, Optional[User]]:
    """
    Validates a session token asynchronously without keeping an open DB session.
    Returns (is_token_present, user_or_none).
    """
    if not token or not token.strip():
        return False, None

    clean_token = token.removeprefix("Bearer ").strip()
    async with AsyncSession(engine) as db:
        stmt = select(UserSession).where(UserSession.token == clean_token)
        res = await db.execute(stmt)
        session = res.scalars().first()
        if not session:
            return True, None

        now = datetime.now(timezone.utc)
        exp = session.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            return True, None

        user = session.user
        if not user or not user.is_active:
            return True, None

        return True, user


@router.websocket("/ws/counter/{counter_number}")
async def counter_websocket_endpoint(
    websocket: WebSocket,
    counter_number: str,
    token: Optional[str] = Query(None)
):
    """
    Real-time WebSocket connection for Counter POS screens and queue monitors.
    Subscribes the client to events for a specific counter (e.g. '03').
    Enforces that staff cannot subscribe to another counter's stream.
    """
    # Authorization check if staff token provided
    has_token, user = await _get_user_from_token(token)
    if has_token:
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        if user.role in ("admin", "staff") and user.role != "store_admin":
            if user.counter_number and user.counter_number != counter_number:
                logger.warning(
                    f"Staff {user.username} (Counter {user.counter_number}) denied WS subscription to Counter {counter_number}"
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    channel = f"counter:{counter_number}"
    await ws_manager.connect(websocket, channel)
    
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
    except Exception as e:
        logger.warning(f"WebSocket connection error on {channel}: {e}")
        ws_manager.disconnect(websocket, channel)


@router.websocket("/ws/store-overview")
async def store_overview_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """Global WebSocket feed for store digital signage and dashboards."""
    channel = "global"
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)


@router.websocket("/ws/admin")
async def admin_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    Real-time WebSocket connection for Store Administrator.
    Strictly requires authenticated store_admin session.
    """
    has_token, user = await _get_user_from_token(token)
    if not has_token or not user or user.role != "store_admin":
        logger.warning("Unauthorized attempt to connect to /ws/admin")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    channel = "admin"
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)


@router.websocket("/ws/order/{order_number}")
async def order_websocket_endpoint(
    websocket: WebSocket,
    order_number: str
):
    """Real-time customer tracking feed for a specific order."""
    channel = f"order:{order_number}"
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)


@router.websocket("/ws")
async def generic_ws_router(
    websocket: WebSocket,
    counter_number: Optional[str] = Query(None),
    order_number: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    Unified WebSocket endpoint supporting query parameters:
    ?counter_number=01&token=...
    ?order_number=FS-XXXX
    ?channel=admin&token=...
    """
    target_channel = "global"

    if channel == "admin":
        has_token, user = await _get_user_from_token(token)
        if not has_token or not user or user.role != "store_admin":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        target_channel = "admin"
    elif counter_number:
        has_token, user = await _get_user_from_token(token)
        if has_token:
            if not user:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if user.role in ("admin", "staff") and user.role != "store_admin":
                if user.counter_number and user.counter_number != counter_number:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
        target_channel = f"counter:{counter_number}"
    elif order_number:
        target_channel = f"order:{order_number}"

    await ws_manager.connect(websocket, target_channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, target_channel)
    except Exception as e:
        logger.warning(f"WebSocket error on {target_channel}: {e}")
        ws_manager.disconnect(websocket, target_channel)
