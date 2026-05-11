from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router
from app.api.routes.simulations import router as simulations_router
from app.core.config import settings
from app.services.live_game_service import live_game_service
from app.services.ws_manager import ws_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    await live_game_service.bootstrap_demo_game()
    yield


app = FastAPI(
    title="BallPredict API",
    version="0.1.0",
    description="NBA predictive analytics and coaching-adjustment simulation platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(games_router, prefix="/api/v1")
app.include_router(simulations_router, prefix="/api/v1")


@app.websocket("/ws/games/{game_id}")
async def game_stream(websocket: WebSocket, game_id: str) -> None:
    await ws_manager.connect(game_id, websocket)
    try:
        snapshot = await live_game_service.get_game_snapshot(game_id)
        await websocket.send_json(snapshot.model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(game_id, websocket)

