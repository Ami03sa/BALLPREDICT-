from unittest.mock import AsyncMock, patch

from app.schemas.game import CoachingAdjustment, InsightCard, SimulationResponse


def test_simulate_series(client):
    response = client.post(
        "/api/v1/simulations/series",
        json={"home_team": "LAL", "away_team": "BOS", "games": 7},
    )

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "LAL" in data["series_win_probability"]
    assert "BOS" in data["series_win_probability"]
    assert len(data["swing_factors"]) > 0


def test_simulate_series_default_games(client):
    response = client.post(
        "/api/v1/simulations/series",
        json={"home_team": "GSW", "away_team": "DAL"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "GSW" in data["series_win_probability"]


def test_simulate_game(client):
    fake_response = SimulationResponse(
        summary="Home wins.",
        home_win_probability=0.6,
        away_win_probability=0.4,
        projected_score={"LAL": 112, "BOS": 106},
        key_adjustments=[
            CoachingAdjustment(
                title="Blitz",
                side="defense",
                trigger="Hot player",
                explanation="Double team.",
                counters=["trap"],
                impact={"field_goal_pct": -0.05},
            )
        ],
        player_edges=[
            InsightCard(title="Edge", body="Info", severity="info")
        ],
    )

    with patch(
        "app.api.routes.simulations.live_game_service.simulate_matchup",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        response = client.post(
            "/api/v1/simulations/game",
            json={"home_team": "LAL", "away_team": "BOS", "strategy_tags": ["switch-everything"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["home_win_probability"] == 0.6
    assert data["summary"] == "Home wins."
