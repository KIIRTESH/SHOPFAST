import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.websocket_manager import ws_manager

logger = logging.getLogger("fastshop.ws_router")
router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws/counter/{counter_number}")
async def counter_websocket_endpoint(websocket: WebSocket, counter_number: str):
    """
    Real-time WebSocket connection for Counter POS screens and queue monitors.
    Subscribes the client to events for a specific counter (e.g. '03').
    """
    channel = f"counter:{counter_number}"
    await ws_manager.connect(websocket, channel)
    
    try:
        while True:
            # Handle incoming ping/heartbeat or messages from the terminal
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
    except Exception as e:
        logger.warning(f"WebSocket connection error on {channel}: {e}")
        ws_manager.disconnect(websocket, channel)


@router.websocket("/ws/store-overview")
async def store_overview_websocket(websocket: WebSocket):
    """Global WebSocket feed for main store digital signage display board."""
    channel = "global"
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
