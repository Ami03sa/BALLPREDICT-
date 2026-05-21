import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app  # Import your FastAPI app instance

client = TestClient(app)

# We patch the service layer where it is imported in the router module
@pytest.fixture
def mock_service():
    with patch("app.api.routes.game_router.live_game_service", new_callable=AsyncMock) as mock:
        yield mock

def test_list_slate_games(mock_service):
    mock_service.list_slate_games.return_value = [{"id": "1", "name": "Game 1"}]
    
    response = client.get("/games/slate")
    
    assert response.status_code == 200
    assert response.json() == [{"id": "1", "name": "Game 1"}]
    mock_service.list_slate_games.assert_awaited_once()

def test_list_live_games(mock_service):
    mock_service.list_live_games.return_value = [{"id": "2", "status": "live"}]
    
    response = client.get("/games/live")
    
    assert response.status_code == 200
    assert response.json() == [{"id": "2", "status": "live"}]
    mock_service.list_live_games.assert_awaited_once()

def test_get_game_preview(mock_service):
    mock_service.get_game_preview.return_value = {"preview": "data"}
    
    response = client.get("/games/123/preview")
    
    assert response.status_code == 200
    assert response.json() == {"preview": "data"}
    mock_service.get_game_preview.assert_awaited_once_with("123")

def test_get_player_detail(mock_service):
    mock_service.get_player_detail.return_value = {"player": "stats"}
    
    response = client.get("/games/123/players/456")
    
    assert response.status_code == 200
    assert response.json() == {"player": "stats"}
    mock_service.get_player_detail.assert_awaited_once_with("123", "456")

def test_get_game_snapshot(mock_service):
    mock_service.get_game_snapshot.return_value = {"score": "1-0"}
    
    response = client.get("/games/123")
    
    assert response.status_code == 200
    assert response.json() == {"score": "1-0"}
    mock_service.get_game_snapshot.assert_awaited_once_with("123")