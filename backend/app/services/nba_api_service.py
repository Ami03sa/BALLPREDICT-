"""
Fetches live game data from the public NBA CDN.
No auth required. Scoreboard + per-game boxscores.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from app.simulation.state import GameContext, PlayerGameState, TeamGameState

TEAM_FULL_NAMES: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

TEAM_ARENAS: dict[str, str] = {
    "ATL": "State Farm Arena",
    "BOS": "TD Garden",
    "BKN": "Barclays Center",
    "CHA": "Spectrum Center",
    "CHI": "United Center",
    "CLE": "Rocket Mortgage FieldHouse",
    "DAL": "American Airlines Center",
    "DEN": "Ball Arena",
    "DET": "Little Caesars Arena",
    "GSW": "Chase Center",
    "HOU": "Toyota Center",
    "IND": "Gainbridge Fieldhouse",
    "LAC": "Intuit Dome",
    "LAL": "Crypto.com Arena",
    "MEM": "FedExForum",
    "MIA": "Kaseya Center",
    "MIL": "Fiserv Forum",
    "MIN": "Target Center",
    "NOP": "Smoothie King Center",
    "NYK": "Madison Square Garden",
    "OKC": "Paycom Center",
    "ORL": "Amway Center",
    "PHI": "Wells Fargo Center",
    "PHX": "Footprint Center",
    "POR": "Moda Center",
    "SAC": "Golden 1 Center",
    "SAS": "Frost Bank Center",
    "TOR": "Scotiabank Arena",
    "UTA": "Delta Center",
    "WAS": "Capital One Arena",
}

_HEADERS = {
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

_NBA_CDN = "https://cdn.nba.com/static/json/liveData"


def _parse_minutes(pt_str: str) -> float:
    """'PT35M12.00S' → 35.2"""
    if not pt_str:
        return 0.0
    try:
        s = pt_str.replace("PT", "").replace("S", "")
        parts = s.split("M")
        minutes = float(parts[0])
        seconds = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
        return round(minutes + seconds / 60, 1)
    except Exception:
        return 0.0


def _format_tipoff(utc_str: str) -> str:
    """UTC ISO string → 'H:MM PM ET'"""
    if not utc_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        et = dt - timedelta(hours=4)  # EDT (NBA season is April–June)
        hour = et.hour % 12 or 12
        ampm = "PM" if et.hour >= 12 else "AM"
        return f"{hour}:{et.strftime('%M')} {ampm} ET"
    except Exception:
        return "TBD"


def _build_player_state(player_data: dict, team_id: str) -> PlayerGameState | None:
    if player_data.get("status") != "ACTIVE":
        return None
    stats = player_data.get("statistics", {})
    fg_pct = float(stats.get("fieldGoalsPercentage") or 0.48)
    three_pct = float(stats.get("threePointersPercentage") or 0.37)
    minutes = _parse_minutes(stats.get("minutesCalculated") or "")
    return PlayerGameState(
        player_id=str(player_data.get("personId", "0")),
        player_name=player_data.get("name", "Unknown"),
        team_id=team_id,
        usage_rate=0.20,
        points=float(stats.get("points") or 0),
        assists=float(stats.get("assists") or 0),
        rebounds=float(stats.get("reboundsTotal") or 0),
        steals=float(stats.get("steals") or 0),
        blocks=float(stats.get("blocks") or 0),
        turnovers=float(stats.get("turnovers") or 0),
        threes_made=float(stats.get("threePointersMade") or 0),
        field_goal_pct=fg_pct,
        three_point_pct=three_pct,
        minutes_played=minutes,
        fatigue_index=0.15,
        momentum_score=0.50,
        matchup_difficulty=0.50,
        drive_frequency=0.18,
        paint_touches=4,
    )


def _build_minimal_team_state(team_raw: dict, score: int) -> TeamGameState:
    """Build TeamGameState from scoreboard data only (no boxscore / no players)."""
    tricode = team_raw.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = team_raw.get("teamCity", "")
    name = team_raw.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())
    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=98.0,
        offensive_rating=114.0,
        defensive_rating=114.0,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.50,
        adjustment_discipline=0.65,
        players=[],
    )


def _build_team_state(box_team: dict, score: int) -> TeamGameState:
    tricode = box_team.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = box_team.get("teamCity", "")
    name = box_team.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())

    players: list[PlayerGameState] = []
    for p in box_team.get("players", []):
        state = _build_player_state(p, team_id)
        if state is not None:
            players.append(state)

    # Keep top 8 by minutes played (covers full rotation)
    players.sort(key=lambda p: p.minutes_played, reverse=True)
    players = players[:8]

    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=98.0,
        offensive_rating=114.0,
        defensive_rating=114.0,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.50,
        adjustment_discipline=0.65,
        players=players,
    )


async def fetch_today_slate_and_contexts() -> tuple[dict[str, dict], dict[str, GameContext]]:
    """
    Pull today's NBA scoreboard + per-game boxscores from the public CDN.
    Returns:
        slate   – game_id → display metadata dict
        contexts – game_id → GameContext with real roster and live stats
    """
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True) as client:
        sb_resp = await client.get(f"{_NBA_CDN}/scoreboard/todaysScoreboard_00.json")
        sb_resp.raise_for_status()
        games = sb_resp.json()["scoreboard"].get("games", [])

        slate: dict[str, dict] = {}
        contexts: dict[str, GameContext] = {}

        for game in games:
            game_id: str = game["gameId"]
            game_status: int = game.get("gameStatus", 1)
            home_raw = game["homeTeam"]
            away_raw = game["awayTeam"]
            home_tc = home_raw.get("teamTricode", "")
            away_tc = away_raw.get("teamTricode", "")
            home_city = home_raw.get("teamCity", "")
            away_city = away_raw.get("teamCity", "")
            home_name = TEAM_FULL_NAMES.get(home_tc, f"{home_city} {home_raw.get('teamName', '')}".strip())
            away_name = TEAM_FULL_NAMES.get(away_tc, f"{away_city} {away_raw.get('teamName', '')}".strip())

            status_str = {1: "scheduled", 2: "live", 3: "final"}.get(game_status, "scheduled")

            slate[game_id] = {
                "game_id": game_id,
                "status": status_str,
                "tipoff": _format_tipoff(game.get("gameTimeUTC", "")),
                "broadcast": "NBA TV",
                "arena": TEAM_ARENAS.get(home_tc, "Arena"),
                "headline": f"{away_name} at {home_name}",
                "home_team": home_name,
                "away_team": away_name,
                "home_abbreviation": home_tc,
                "away_abbreviation": away_tc,
                "home_record": f"{home_raw.get('wins', 0)}-{home_raw.get('losses', 0)}",
                "away_record": f"{away_raw.get('wins', 0)}-{away_raw.get('losses', 0)}",
            }

            period = game.get("period", 0) if game_status > 1 else 0
            clock = game.get("gameClock", "12:00") or "12:00"
            if game_status == 1:
                period = 0
                clock = "12:00"

            # Try boxscore for full roster; fall back to scoreboard-only if 403/unavailable
            try:
                box_resp = await client.get(f"{_NBA_CDN}/boxscore/boxscore_{game_id}.json")
                box_resp.raise_for_status()
                box = box_resp.json()["game"]
                home_box = box.get("homeTeam", {})
                away_box = box.get("awayTeam", {})
                home_score = int(home_box.get("score") or home_raw.get("score") or 0)
                away_score = int(away_box.get("score") or away_raw.get("score") or 0)
                home_team = _build_team_state(home_box, home_score)
                away_team = _build_team_state(away_box, away_score)
            except Exception as exc:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "Boxscore unavailable for %s (%s) — using scoreboard data only.", game_id, exc
                )
                home_score = int(home_raw.get("score") or 0)
                away_score = int(away_raw.get("score") or 0)
                home_team = _build_minimal_team_state(home_raw, home_score)
                away_team = _build_minimal_team_state(away_raw, away_score)

            contexts[game_id] = GameContext(
                game_id=game_id,
                quarter=period,
                clock=clock,
                home_team=home_team,
                away_team=away_team,
                score_margin=home_score - away_score,
                home_advantage=2.5,
                overtime_probability=0.07,
                momentum=0.50,
                fatigue_pressure=0.20,
                whistle_tightness=0.43,
                playoff_intensity=0.55,
                live_pace_multiplier=1.0,
            )

    return slate, contexts
