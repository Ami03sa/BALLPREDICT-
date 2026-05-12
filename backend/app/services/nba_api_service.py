"""
Fetches live game data via nba_live_client (stats.nba.com + NBA CDN).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.simulation.state import GameContext, PlayerGameState, TeamGameState

logger = logging.getLogger(__name__)

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


def _parse_minutes(value: str) -> float:
    """Parse minutes from PT format ('PT35M12.00S') or MM:SS ('35:12')."""
    if not value:
        return 0.0
    try:
        v = str(value).strip()
        if v.startswith("PT"):
            s = v.replace("PT", "").replace("S", "")
            parts = s.split("M")
            mins = float(parts[0])
            secs = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
            return round(mins + secs / 60, 1)
        if ":" in v:
            m, s = v.split(":", 1)
            return round(float(m) + float(s) / 60, 1)
        return float(v)
    except Exception:
        return 0.0


def _format_tipoff(utc_str: str) -> str:
    if not utc_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        et = dt - timedelta(hours=4)
        hour = et.hour % 12 or 12
        ampm = "PM" if et.hour >= 12 else "AM"
        return f"{hour}:{et.strftime('%M')} {ampm} ET"
    except Exception:
        return "TBD"


def _build_player_state(player_data: dict, team_id: str) -> PlayerGameState | None:
    if player_data.get("status") != "ACTIVE":
        return None
    stats = player_data.get("statistics", {})
    fg_pct = float(stats.get("fieldGoalsPercentage") or 0.45)
    three_pct = float(stats.get("threePointersPercentage") or 0.36)
    # stats.nba.com returns decimals (0.556); CDN sometimes returns 55.6 — normalise
    if fg_pct > 1:
        fg_pct /= 100
    if three_pct > 1:
        three_pct /= 100
    minutes = _parse_minutes(stats.get("minutesCalculated") or stats.get("minutes") or "")
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


def _build_team_state_from_season_stats(team_raw: dict, score: int, season_players: list[dict]) -> TeamGameState:
    """Build TeamGameState using per-game season averages as prediction baseline (pre-game)."""
    tricode = team_raw.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = team_raw.get("teamCity", "")
    name = team_raw.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())

    players: list[PlayerGameState] = []
    for p in season_players:
        fg_pct = float(p.get("FG_PCT") or 0.45)
        three_pct = float(p.get("FG3_PCT") or 0.35)
        if fg_pct > 1:
            fg_pct /= 100
        if three_pct > 1:
            three_pct /= 100
        min_avg = float(p.get("MIN") or 0)
        fga_avg = float(p.get("FGA") or 0)
        fta_avg = float(p.get("FTA") or 0)
        tov_avg = float(p.get("TOV") or 0)
        possessions_used = fga_avg + 0.44 * fta_avg + tov_avg
        usage_rate = min(0.42, max(0.08, possessions_used / max(1.0, min_avg * 0.4)))
        players.append(PlayerGameState(
            player_id=str(p.get("PLAYER_ID", "0")),
            player_name=str(p.get("PLAYER_NAME", "Unknown")),
            team_id=team_id,
            rotation_role="starter" if len(players) < 5 else "bench",
            usage_rate=round(usage_rate, 3),
            points=0.0,
            assists=0.0,
            rebounds=0.0,
            steals=0.0,
            blocks=0.0,
            turnovers=0.0,
            threes_made=0.0,
            field_goal_pct=fg_pct,
            three_point_pct=three_pct,
            minutes_played=min_avg,
            fatigue_index=0.10,
            momentum_score=0.55,
            matchup_difficulty=0.45,
            drive_frequency=0.18,
            paint_touches=4,
        ))

    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=98.0,
        offensive_rating=114.0,
        defensive_rating=113.0,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.55,
        adjustment_discipline=0.65,
        players=players,
    )


def _build_minimal_team_state(team_raw: dict, score: int) -> TeamGameState:
    """Build TeamGameState from scoreboard data only (no player-level stats)."""
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


async def fetch_today_slate_and_contexts() -> tuple[dict[str, dict], dict[str, GameContext]]:
    """
    Pull today's NBA slate from the CDN scoreboard and player stats from stats.nba.com.
    Returns:
        slate    – game_id → display metadata dict
        contexts – game_id → GameContext with real roster and live stats
    """
    from app.services.providers.nba_live_client import nba_live_client

    scoreboard = await nba_live_client.fetch_scoreboard()
    games = scoreboard.get("scoreboard", {}).get("games", [])

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

        home_score = int(home_raw.get("score") or 0)
        away_score = int(away_raw.get("score") or 0)
        try:
            box_data = await nba_live_client.fetch_boxscore(game_id)
            box = box_data.get("game", {})
            home_box = box.get("homeTeam")
            away_box = box.get("awayTeam")
            if not home_box or not away_box:
                raise ValueError("Boxscore returned no team data (game not yet started)")
            home_score = int(home_box.get("score") or home_score)
            away_score = int(away_box.get("score") or away_score)
            home_team = _build_team_state(home_box, home_score)
            away_team = _build_team_state(away_box, away_score)
            logger.info("Boxscore loaded for %s — %d players", game_id, len(home_team.players) + len(away_team.players))
        except Exception as exc:
            logger.warning("Boxscore unavailable for %s (%s) — fetching season averages.", game_id, exc)
            try:
                home_team_id = int(home_raw.get("teamId") or 0)
                away_team_id = int(away_raw.get("teamId") or 0)
                home_stats, away_stats = await asyncio.gather(
                    nba_live_client.fetch_player_season_stats(home_team_id),
                    nba_live_client.fetch_player_season_stats(away_team_id),
                )
                home_team = _build_team_state_from_season_stats(home_raw, home_score, home_stats)
                away_team = _build_team_state_from_season_stats(away_raw, away_score, away_stats)
                logger.info("Season stats loaded for %s — %d players", game_id, len(home_team.players) + len(away_team.players))
            except Exception as exc2:
                logger.warning("Season stats also unavailable for %s (%s) — no players.", game_id, exc2)
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
