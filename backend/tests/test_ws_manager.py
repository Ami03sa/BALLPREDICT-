import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.ws_manager import WebSocketManager


@pytest.fixture
def manager():
    return WebSocketManager()


def _mock_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


async def test_connect_accepts_and_stores(manager):
    ws = _mock_ws()
    await manager.connect("game1", ws)
    ws.accept.assert_awaited_once()
    assert ws in manager.active_connections["game1"]


def test_disconnect_removes_connection(manager):
    ws = _mock_ws()
    manager.active_connections["game1"].append(ws)
    manager.disconnect("game1", ws)
    assert ws not in manager.active_connections["game1"]


def test_disconnect_missing_ws_is_safe(manager):
    ws = _mock_ws()
    manager.disconnect("game1", ws)  # should not raise


async def test_broadcast_sends_to_all(manager):
    ws1, ws2 = _mock_ws(), _mock_ws()
    manager.active_connections["game1"].extend([ws1, ws2])
    payload = {"score": "50-48"}
    await manager.broadcast("game1", payload)
    ws1.send_json.assert_awaited_once_with(payload)
    ws2.send_json.assert_awaited_once_with(payload)


async def test_broadcast_empty_room_is_safe(manager):
    await manager.broadcast("no-game", {"data": 1})  # should not raise
