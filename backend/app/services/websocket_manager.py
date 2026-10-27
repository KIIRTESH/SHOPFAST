import logging
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from app.schemas.ws import WebSocketMessage

logger = logging.getLogger("fastshop.ws")


class ConnectionManager:
    """
    Thread-safe async WebSocket connection and channel distribution manager.
    Supports counter-specific rooms and global broadcasts.
    """
    def __init__(self):
        # Maps channel (e.g. "global", "counter:03") to list of active WebSockets
        self.active_channels: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str = "global"):
        await websocket.accept()
        if channel not in self.active_channels:
            self.active_channels[channel] = set()
        self.active_channels[channel].add(websocket)
        logger.info(f"WebSocket client joined channel: {channel}. Total clients: {len(self.active_channels[channel])}")

    def disconnect(self, websocket: WebSocket, channel: str = "global"):
        if channel in self.active_channels and websocket in self.active_channels[channel]:
            self.active_channels[channel].remove(websocket)
            if not self.active_channels[channel]:
                del self.active_channels[channel]
        logger.info(f"WebSocket client disconnected from {channel}")

    async def broadcast_to_channel(self, channel: str, message: WebSocketMessage):
        """Broadcast structured JSON message to all clients in a specific room."""
        if channel in self.active_channels:
            payload = message.model_dump_json()
            dead_sockets = []
            for ws in list(self.active_channels[channel]):
                try:
                    await ws.send_text(payload)
                except Exception as e:
                    logger.warning(f"Error sending WS message to client on {channel}: {e}")
                    dead_sockets.append(ws)
            
            # Clean up dead sockets
            for ws in dead_sockets:
                self.disconnect(ws, channel)

    async def broadcast_order_event(self, order_number: str, counter_number: Optional[str], message: WebSocketMessage):
        """
        Broadcast order event to all relevant authorized channels:
        the order's direct channel, the assigned counter's channel, the admin channel, and global store channel.
        """
        channels = set(["global", "admin"])
        if order_number:
            channels.add(f"order:{order_number}")
        if counter_number:
            channels.add(f"counter:{counter_number}")
        
        for ch in channels:
            await self.broadcast_to_channel(ch, message)

    async def broadcast_global(self, message: WebSocketMessage):
        """Broadcast to all connected channels across the store."""
        for channel in list(self.active_channels.keys()):
            await self.broadcast_to_channel(channel, message)

    def get_channel_count(self, channel: str) -> int:
        return len(self.active_channels.get(channel, set()))

    def active_clients_count(self) -> int:
        return sum(len(sockets) for sockets in self.active_channels.values())


ws_manager = ConnectionManager()
