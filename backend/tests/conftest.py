import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with patch(
        "app.services.live_game_service.live_game_service.bootstrap_demo_game",
        new_callable=AsyncMock,
    ):
        with TestClient(app) as c:
            yield c
