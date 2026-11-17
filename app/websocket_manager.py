"""WebSocket connection manager for live score broadcasting."""

import json
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect


class ConnectionManager:
    """Manages WebSocket connections for live score broadcasting."""

    def __init__(self):
        # Map match_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, match_id: int):
        """Accept a new WebSocket connection for a match."""
        await websocket.accept()
        self.active_connections[match_id].add(websocket)

    def disconnect(self, websocket: WebSocket, match_id: int):
        """Remove a WebSocket connection."""
        if match_id in self.active_connections:
            self.active_connections[match_id].discard(websocket)
            if not self.active_connections[match_id]:
                del self.active_connections[match_id]

    async def broadcast(self, match_id: int, message: dict):
        """Broadcast a message to all clients connected to a match."""
        if match_id not in self.active_connections:
            return
        dead_connections = []
        for connection in self.active_connections[match_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn, match_id)

    def get_connection_count(self, match_id: int) -> int:
        """Get the number of connected clients for a match."""
        return len(self.active_connections.get(match_id, set()))


# Global connection manager instance
manager = ConnectionManager()