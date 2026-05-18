from __future__ import annotations

import httpx

from app.core.config import settings

_NBA_STATS_URL = "https://stats.nba.com/stats"


class NbaLiveClient:
    def __init__(self) -> None:
        self._cdn_headers = {
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
        self._stats_headers = {
            **self._cdn_headers,
            "Host": "stats.nba.com",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
        }

    async def _cdn_get(self, path: str) -> dict:
        async with httpx.AsyncClient(
            timeout=12.0, headers=self._cdn_headers, follow_redirects=True
        ) as client:
            r = await client.get(f"{settings.nba_live_base_url}/{path}")
            r.raise_for_status()
            return r.json()

    async def _stats_get(self, endpoint: str, params: dict) -> dict:
        async with httpx.AsyncClient(
            timeout=20.0, headers=self._stats_headers, follow_redirects=True
        ) as client:
            r = await client.get(f"{_NBA_STATS_URL}/{endpoint}", params=params)
            r.raise_for_status()
            return r.json()

    async def fetch_scoreboard(self) -> dict:
        return await self._cdn_get("scoreboard/todaysScoreboard_00.json")

    async def fetch_boxscore(self, game_id: str) -> dict:
        """
        Try CDN live boxscore first (works for in-progress games).
        Fall back to stats.nba.com (works for completed games).
        Returns CDN-compatible {game:{homeTeam,awayTeam}} dict.
        """
        try:
            data = await self._cdn_get(f"boxscore/boxscore_{game_id}.json")
            game = data.get("game", {})
            if game.get("homeTeam") and game.get("awayTeam"):
                return data
        except Exception:
            pass

        data = await self._stats_get(
            "boxscoretraditionalv2",
            {
                "GameID": game_id,
                "StartPeriod": 0,
                "EndPeriod": 10,
                "StartRange": 0,
                "EndRange": 0,
                "RangeType": 0,
            },
        )
        return self._parse_stats_boxscore(data)

    async def fetch_playbyplay(self, game_id: str) -> dict:
        return await self._cdn_get(f"playbyplay/playbyplay_{game_id}.json")

    async def fetch_player_season_stats(self, team_id: int) -> list[dict]:
        """Per-game averages for active players on a team over the last 20 games.

        Using LastNGames=20 ensures we only get players currently on the roster —
        players traded away won't have played 20 games for this team, so they
        either won't appear or will have very low GP and get filtered out.
        """
        data = await self._stats_get("leaguedashplayerstats", {
            "TeamID": team_id,
            "PerMode": "PerGame",
            "Season": self._current_season(),
            "SeasonType": "Regular Season",
            "MeasureType": "Base",
            "LeagueID": "00",
            "DateFrom": "", "DateTo": "", "GameScope": "", "GameSegment": "",
            "ISTRound": "", "LastNGames": 20, "Location": "", "Month": 0,
            "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
            "PaceAdjust": "N", "Period": 0, "PlayerExperience": "",
            "PlayerPosition": "", "PlusMinus": "N", "Rank": "N",
            "SeasonSegment": "", "ShotClockRange": "", "StarterBench": "",
            "TwoWay": 0, "VsConference": "", "VsDivision": "",
        })
        rs = next((r for r in data.get("resultSets", []) if r["name"] == "LeagueDashPlayerStats"), {})
        headers = rs.get("headers", [])
        players = [dict(zip(headers, row)) for row in rs.get("rowSet", [])]
        # Must have played at least 3 of the last 20 games for this team
        players = [p for p in players if float(p.get("GP") or 0) >= 3]
        players.sort(key=lambda p: float(p.get("MIN") or 0), reverse=True)
        return players

    def _current_season(self) -> str:
        from datetime import date
        d = date.today()
        return f"{d.year}-{str(d.year + 1)[2:]}" if d.month >= 10 else f"{d.year - 1}-{str(d.year)[2:]}"

    def _parse_stats_boxscore(self, data: dict) -> dict:
        """Convert stats.nba.com resultSets format → CDN-compatible dict."""
        rs_map = {rs["name"]: rs for rs in data.get("resultSets", [])}

        def to_dicts(name: str) -> list[dict]:
            rs = rs_map.get(name, {})
            headers = rs.get("headers", [])
            return [dict(zip(headers, row)) for row in rs.get("rowSet", [])]

        player_rows = to_dicts("PlayerStats")
        team_rows = to_dicts("TeamStats")
        line_score_rows = to_dicts("LineScore")

        teams: dict[str, dict] = {}

        for p in player_rows:
            abbr = p.get("TEAM_ABBREVIATION", "")
            if abbr not in teams:
                teams[abbr] = {
                    "teamTricode": abbr,
                    "teamId": p.get("TEAM_ID"),
                    "teamCity": "",
                    "teamName": "",
                    "score": 0,
                    "statistics": {},
                    "players": [],
                }
            min_str = str(p.get("MIN") or "").strip()
            is_dnp = not min_str or min_str in ("0:00", "00:00")
            teams[abbr]["players"].append({
                "personId": str(p.get("PLAYER_ID", "")),
                "name": p.get("PLAYER_NAME", "Unknown"),
                "starter": bool(p.get("START_POSITION") and p["START_POSITION"] not in ("", "0")),
                "played": not is_dnp,
                "status": "INACTIVE" if is_dnp else "ACTIVE",
                "notPlayingReason": p.get("COMMENT") if is_dnp else None,
                "statistics": {
                    "points": p.get("PTS") or 0,
                    "assists": p.get("AST") or 0,
                    "reboundsTotal": p.get("REB") or 0,
                    "reboundsOffensive": p.get("OREB") or 0,
                    "reboundsDefensive": p.get("DREB") or 0,
                    "steals": p.get("STL") or 0,
                    "blocks": p.get("BLK") or 0,
                    "turnovers": p.get("TO") or 0,
                    "foulsPersonal": p.get("PF") or 0,
                    "threePointersMade": p.get("FG3M") or 0,
                    "threePointersAttempted": p.get("FG3A") or 0,
                    "threePointersPercentage": p.get("FG3_PCT") or 0,
                    "fieldGoalsMade": p.get("FGM") or 0,
                    "fieldGoalsAttempted": p.get("FGA") or 0,
                    "fieldGoalsPercentage": p.get("FG_PCT") or 0,
                    "freeThrowsMade": p.get("FTM") or 0,
                    "freeThrowsAttempted": p.get("FTA") or 0,
                    "freeThrowsPercentage": p.get("FT_PCT") or 0,
                    "minutes": min_str,
                    "minutesCalculated": min_str,
                },
            })

        for t in team_rows:
            abbr = t.get("TEAM_ABBREVIATION", "")
            if abbr in teams:
                teams[abbr]["teamCity"] = t.get("TEAM_CITY", "")
                teams[abbr]["teamName"] = t.get("TEAM_NAME", "")
                teams[abbr]["statistics"] = {
                    "points": t.get("PTS") or 0,
                    "assists": t.get("AST") or 0,
                    "reboundsTotal": t.get("REB") or 0,
                    "reboundsOffensive": t.get("OREB") or 0,
                    "reboundsDefensive": t.get("DREB") or 0,
                    "steals": t.get("STL") or 0,
                    "blocks": t.get("BLK") or 0,
                    "turnoversTotal": t.get("TO") or 0,
                    "foulsPersonal": t.get("PF") or 0,
                    "threePointersAttempted": t.get("FG3A") or 0,
                    "threePointersMade": t.get("FG3M") or 0,
                    "fieldGoalsAttempted": t.get("FGA") or 0,
                    "freeThrowsAttempted": t.get("FTA") or 0,
                }

        # LineScore: visitor row first, home row second
        away_abbr = home_abbr = None
        if len(line_score_rows) >= 2:
            away_abbr = line_score_rows[0].get("TEAM_ABBREVIATION")
            home_abbr = line_score_rows[1].get("TEAM_ABBREVIATION")
            if away_abbr in teams:
                teams[away_abbr]["score"] = int(line_score_rows[0].get("PTS") or 0)
            if home_abbr in teams:
                teams[home_abbr]["score"] = int(line_score_rows[1].get("PTS") or 0)

        team_list = list(teams.values())
        if not team_list:
            return {"game": {}}

        home_team = teams.get(home_abbr, team_list[-1])
        away_team = teams.get(away_abbr, team_list[0])
        return {"game": {"homeTeam": home_team, "awayTeam": away_team}}


nba_live_client = NbaLiveClient()
