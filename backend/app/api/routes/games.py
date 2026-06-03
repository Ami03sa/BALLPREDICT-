from fastapi import APIRouter

from app.services.live_game_service import live_game_service
from app.services import projection_service as _ps
from app.services import nba_api_service as _nas
from app.services.injury_lineup_service import _game_cache as _injury_cache


router = APIRouter(prefix="/games", tags=["games"])


@router.get("/slate")
async def list_slate_games() -> list[dict]:
    return await live_game_service.list_slate_games()


@router.get("/live")
async def list_live_games() -> list[dict]:
    return await live_game_service.list_live_games()


@router.get("/{game_id}/preview")
async def get_game_preview(game_id: str) -> dict:
    return await live_game_service.get_game_preview(game_id)


@router.get("/{game_id}/players/{player_id}")
async def get_player_detail(game_id: str, player_id: str):
    return await live_game_service.get_player_detail(game_id, player_id)


@router.delete("/{game_id}/prediction-cache")
async def reset_prediction_cache(game_id: str) -> dict:
    """
    Full cache reset for a game — clears ALL per-game locks so the next request
    produces a completely fresh prediction with current odds and injury data.

    Clears:
      • score_cache    — unlocks the predicted final score so it recomputes
      • vegas_cache    — forces ESPN odds to be re-fetched (stale line after injury news)
      • injury_cache   — bypasses the 20-min TTL so updated DNP/Q statuses are picked up
    """
    # 1. Score cache — the locked predicted final score
    score_removed = game_id in _ps._pregame_scores
    if score_removed:
        del _ps._pregame_scores[game_id]
        _ps._save_score_cache(_ps._pregame_scores)

    # 2. Vegas odds cache — allows ESPN line to be re-fetched (e.g. after injury moves the total)
    vegas_removed = game_id in _nas._vegas_cache
    if vegas_removed:
        del _nas._vegas_cache[game_id]
        _nas._save_vegas_cache(_nas._vegas_cache)

    # 3. Injury/lineup cache — bypasses the 20-min TTL so fresh DNP/Q statuses are used
    injury_removed = game_id in _injury_cache
    if injury_removed:
        del _injury_cache[game_id]

    return {
        "game_id": game_id,
        "cache_cleared": score_removed or vegas_removed or injury_removed,
        "score_cache_cleared": score_removed,
        "vegas_cache_cleared": vegas_removed,
        "injury_cache_cleared": injury_removed,
    }


@router.get("/{game_id}")
async def get_game_snapshot(game_id: str):
    return await live_game_service.get_game_snapshot(game_id)
