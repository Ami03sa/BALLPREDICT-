from fastapi import APIRouter

from app.services.live_game_service import live_game_service


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


@router.get("/{game_id}")
async def get_game_snapshot(game_id: str):
    return await live_game_service.get_game_snapshot(game_id)
