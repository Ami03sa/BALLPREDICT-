from fastapi import APIRouter

from app.schemas.game import SeriesSimulationRequest, SimulationRequest
from app.services.live_game_service import live_game_service


router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("/game")
async def simulate_game(payload: SimulationRequest):
    return await live_game_service.simulate_matchup(payload.home_team, payload.away_team, payload.strategy_tags)


@router.post("/series")
async def simulate_series(payload: SeriesSimulationRequest) -> dict:
    home_wins = round(payload.games * 0.57)
    away_wins = payload.games - home_wins
    return {
        "summary": (
            f"{payload.home_team} projects to win the series {home_wins}-{away_wins} "
            "behind stronger half-court defense and late-clock shot creation."
        ),
        "series_win_probability": {
            payload.home_team: 0.61,
            payload.away_team: 0.39,
        },
        "swing_factors": [
            "lineup spacing against switch-heavy coverages",
            "paint touch sustainability in non-star minutes",
            "rebounding resilience when shrinking the floor",
        ],
    }

