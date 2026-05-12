from __future__ import annotations

import httpx

from app.core.config import settings


class NbaLiveClient:
    def __init__(self) -> None:
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
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
