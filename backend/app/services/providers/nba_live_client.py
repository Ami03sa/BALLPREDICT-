from __future__ import annotations

import httpx

from app.core.config import settings


class NbaLiveClient:
    def __init__(self) -> None:
        self._headers = {
            "User-Agent": "BallPredict/0.1 (+https://github.com/Ami03sa/BALLPREDICT-)",
            "Accept": "application/json,text/plain,*/*",
        }

    async def _get_json(self, path: str) -> dict:
        async with httpx.AsyncClient(
            timeout=12.0,
            headers=self._headers,
            follow_redirects=True,
        ) as client:
            response = await client.get(f"{settings.nba_live_base_url}/{path}")
            response.raise_for_status()
            return response.json()

    async def fetch_scoreboard(self) -> dict:
        return await self._get_json("scoreboard/todaysScoreboard_00.json")

    async def fetch_boxscore(self, game_id: str) -> dict:
        return await self._get_json(f"boxscore/boxscore_{game_id}.json")

    async def fetch_playbyplay(self, game_id: str) -> dict:
        return await self._get_json(f"playbyplay/playbyplay_{game_id}.json")


nba_live_client = NbaLiveClient()
