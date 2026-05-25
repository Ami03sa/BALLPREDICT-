from fastapi import APIRouter

from app.services.live_game_service import live_game_service
from app.services import projection_service as _ps


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
    Clears the locked prediction for a game so the next call recomputes fresh.
    Use before tipoff when major news (injury, lineup change) warrants a new prediction.
    """
    removed = game_id in _ps._pregame_scores
    if removed:
        del _ps._pregame_scores[game_id]
        _ps._save_score_cache(_ps._pregame_scores)
    return {"game_id": game_id, "cache_cleared": removed}


@router.get("/{game_id}")
async def get_game_snapshot(game_id: str):
    return await live_game_service.get_game_snapshot(game_id)
