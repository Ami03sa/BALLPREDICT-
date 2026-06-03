"""
Fetches live game data via nba_live_client (stats.nba.com + NBA CDN).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.simulation.state import GameContext, PlayerGameState, TeamGameState

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"
_VEGAS_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "vegas_cache.json"

# Vegas implied totals locked per game_id at first startup.
# Keyed by game_id → {"home": float, "away": float}.
# Written once; never overwritten so ESPN going dark mid-game doesn't lose the line.
def _load_vegas_cache() -> dict[str, dict]:
    try:
        return json.loads(_VEGAS_CACHE_PATH.read_text()) if _VEGAS_CACHE_PATH.exists() else {}
    except Exception:
        return {}

def _save_vegas_cache(cache: dict) -> None:
    try:
        _VEGAS_CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass

_vegas_cache: dict[str, dict] = _load_vegas_cache()


def _recent_dnp(player_id: str) -> tuple[bool, str | None]:
    """
    Returns (is_dnp, reason) for the player.

    Two signals — either triggers a DNP flag:
      1. Zero-minutes streak: last 5 *logged* games all show 0 min.
      2. Absence streak: player missing from 3+ of their team's last 5 game
         dates (no log entry at all). This is the stronger signal for playoff
         injuries — injured players simply aren't in the box score.
    """
    if not _DB_PATH.exists():
        return False, None
    try:
        conn = sqlite3.connect(str(_DB_PATH))

        # ── Signal 1: all recent logged minutes are zero ──────────────────────
        rows = conn.execute(
            "SELECT min FROM player_game_logs WHERE player_id = ? ORDER BY game_date DESC LIMIT 5",
            (player_id,),
        ).fetchall()
        if rows and all(float(r[0] or 0) == 0.0 for r in rows):
            conn.close()
            return True, "DNP — 0 minutes in last 5 games"

        # ── Signal 2: absent from majority of team's recent games ─────────────
        # Find the player's current team from their most recent log entry.
        team_row = conn.execute(
            "SELECT team_abbreviation FROM player_game_logs WHERE player_id = ? ORDER BY game_date DESC LIMIT 1",
            (player_id,),
        ).fetchone()

        if team_row:
            team_abbr = team_row[0]
            # Last 5 distinct game dates the team played
            team_dates = conn.execute(
                "SELECT DISTINCT game_date FROM player_game_logs WHERE team_abbreviation = ? ORDER BY game_date DESC LIMIT 5",
                (team_abbr,),
            ).fetchall()

            if len(team_dates) >= 4:
                date_list = [d[0] for d in team_dates]
                placeholders = ",".join("?" * len(date_list))
                player_dates = conn.execute(
                    f"SELECT DISTINCT game_date FROM player_game_logs WHERE player_id = ? AND game_date IN ({placeholders})",
                    [player_id] + date_list,
                ).fetchall()
                player_date_set = {r[0] for r in player_dates}
                absences = sum(1 for d in date_list if d not in player_date_set)
                if absences >= 3:
                    conn.close()
                    return True, f"Missed {absences} of last {len(date_list)} games"

        conn.close()
        return False, None
    except Exception:
        return False, None

def get_quarter_weights(player_id: str) -> dict[str, list[float]] | None:
    """
    Return per-stat quarter weights derived from real historical per-quarter averages.

    Returns a dict with keys 'pts', 'ast', 'reb', 'fg3m', each mapping to
    [q1_w, q2_w, q3_w, q4_w] normalized to sum=1.0.
    Returns None if the player has no data (caller falls back to coaching-pressure weights).
    """
    if not _DB_PATH.exists():
        return None
    try:
        from itertools import groupby

        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            """
            SELECT season, season_type, quarter, pts, ast, reb, fg3m
            FROM player_quarter_splits
            WHERE player_id = ? AND quarter BETWEEN 1 AND 4 AND gp >= 3
            ORDER BY season DESC, CASE season_type WHEN 'Playoffs' THEN 0 ELSE 1 END, quarter
            """,
            (player_id,),
        ).fetchall()
        conn.close()

        for (season, stype), group in groupby(rows, key=lambda r: (r[0], r[1])):
            by_q = {r[2]: r for r in group}
            if len(by_q) < 4:
                continue

            result: dict[str, list[float]] = {}
            for col_idx, stat_key in enumerate(["pts", "ast", "reb", "fg3m"], start=3):
                vals = {q: by_q[q][col_idx] for q in [1, 2, 3, 4]}
                total = sum(vals.values())
                if total > 0:
                    result[stat_key] = [vals[q] / total for q in [1, 2, 3, 4]]
                else:
                    result[stat_key] = [0.25, 0.25, 0.25, 0.25]

            return result if result else None
        return None
    except Exception:
        return None


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


def _team_ratings(tricode: str, ratings: dict[str, dict]) -> tuple[float, float, float]:
    """Return (off_rating, def_rating, pace) for a team, with league-average fallbacks."""
    r = ratings.get(tricode, {})
    return r.get("off_rating", 114.0), r.get("def_rating", 114.0), r.get("pace", 98.0)


def _build_team_state(box_team: dict, score: int, ratings: dict[str, dict] | None = None) -> TeamGameState:
    tricode = box_team.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = box_team.get("teamCity", "")
    name = box_team.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())
    off_rating, def_rating, pace = _team_ratings(tricode, ratings or {})

    players: list[PlayerGameState] = []
    for p in box_team.get("players", []):
        state = _build_player_state(p, team_id)
        if state is not None:
            players.append(state)

    players.sort(key=lambda p: p.minutes_played, reverse=True)

    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=pace,
        offensive_rating=off_rating,
        defensive_rating=def_rating,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.50,
        adjustment_discipline=0.65,
        players=players,
    )


def _build_team_state_from_season_stats(team_raw: dict, score: int, season_players: list[dict], ratings: dict[str, dict] | None = None) -> TeamGameState:
    """Build TeamGameState using per-game season averages as prediction baseline (pre-game)."""
    tricode = team_raw.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = team_raw.get("teamCity", "")
    name = team_raw.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())
    off_rating, def_rating, pace = _team_ratings(tricode, ratings or {})

    players: list[PlayerGameState] = []
    for p in season_players:
        min_avg = float(p.get("MIN") or 0)
        # Only exclude players who truly never play (two-way inactive, etc.)
        # Deep bench guys (2-7 min) still show on the roster UI and get low
        # play_prob via the minutes-normalisation step, so they don't inflate totals.
        if min_avg < 2.0:
            continue
        fg_pct = float(p.get("FG_PCT") or 0.45)
        three_pct = float(p.get("FG3_PCT") or 0.35)
        if fg_pct > 1:
            fg_pct /= 100
        if three_pct > 1:
            three_pct /= 100
        fga_avg = float(p.get("FGA") or 0)
        fta_avg = float(p.get("FTA") or 0)
        tov_avg_raw = float(p.get("TOV") or 0)
        pts_avg = float(p.get("PTS") or 0)
        ast_avg = float(p.get("AST") or 0)
        reb_avg = float(p.get("REB") or 0)
        stl_avg = float(p.get("STL") or 0)
        blk_avg = float(p.get("BLK") or 0)
        fg3m_avg = float(p.get("FG3M") or 0)
        # NBA usage rate: possessions / (min × team_pace_per_min)
        # Approximation: poss_used * 0.48 / min_avg gives ~10-35% realistic range
        possessions_used = fga_avg + 0.44 * fta_avg + tov_avg_raw
        usage_rate = min(0.38, max(0.08, (possessions_used * 0.48) / max(1.0, min_avg)))
        player_id_str = str(p.get("PLAYER_ID", "0"))
        is_dnp, dnp_reason_str = _recent_dnp(player_id_str)
        players.append(PlayerGameState(
            player_id=player_id_str,
            player_name=str(p.get("PLAYER_NAME", "Unknown")),
            team_id=team_id,
            rotation_role="starter" if len(players) < 5 else "bench",
            availability_status="dnp" if is_dnp else "available",
            dnp_reason=dnp_reason_str if is_dnp else None,
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
            pts_avg=pts_avg,
            ast_avg=ast_avg,
            reb_avg=reb_avg,
            stl_avg=stl_avg,
            blk_avg=blk_avg,
            tov_avg=tov_avg_raw,
            fg3m_avg=fg3m_avg,
        ))

    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=pace,
        offensive_rating=off_rating,
        defensive_rating=def_rating,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.55,
        adjustment_discipline=0.65,
        players=players,
    )


def _build_minimal_team_state(team_raw: dict, score: int, ratings: dict[str, dict] | None = None) -> TeamGameState:
    """Build TeamGameState from scoreboard data only (no player-level stats)."""
    tricode = team_raw.get("teamTricode", "UNK")
    team_id = tricode.lower()
    city = team_raw.get("teamCity", "")
    name = team_raw.get("teamName", "")
    team_name = TEAM_FULL_NAMES.get(tricode, f"{city} {name}".strip())
    off_rating, def_rating, pace = _team_ratings(tricode, ratings or {})
    return TeamGameState(
        team_id=team_id,
        team_name=team_name,
        coach_name="Head Coach",
        score=score,
        pace=pace,
        offensive_rating=off_rating,
        defensive_rating=def_rating,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.42,
        free_throw_rate=0.21,
        foul_pressure=0.40,
        bench_depth=0.50,
        adjustment_discipline=0.65,
        players=[],
    )


def _apply_injury_report(team: "TeamGameState", injury_report: dict[str, str]) -> None:
    """Mark players Out/Doubtful on the official injury report as DNP in-place."""
    for player in team.players:
        if player.availability_status == "dnp":
            continue
        status = injury_report.get(player.player_id, "")
        if status in ("Out", "Doubtful"):
            player.availability_status = "dnp"
            player.dnp_reason = f"Injury report: {status}"


async def fetch_today_slate_and_contexts() -> tuple[dict[str, dict], dict[str, GameContext]]:
    """
    Pull today's NBA slate from the CDN scoreboard and player stats from stats.nba.com.
    Returns:
        slate    – game_id → display metadata dict
        contexts – game_id → GameContext with real roster and live stats
    """
    from app.core.config import settings
    from app.services.providers.nba_live_client import nba_live_client

    # Fetch injury report and team ratings in parallel.
    # Odds API (paid) has been removed — ESPN BET is the sole odds source.
    # This keeps the pipeline stable across quota resets and doesn't require
    # a paid subscription. When we re-enable a paid provider later, just
    # restore the fetch_vegas_totals(settings.odds_api_key) call here.
    injury_report, team_ratings = await asyncio.gather(
        nba_live_client.fetch_injury_report(),
        nba_live_client.fetch_team_ratings(),
    )
    if injury_report:
        logger.info("Injury report loaded: %d players flagged", len(injury_report))
    if team_ratings:
        logger.info("Team ratings loaded: %d teams", len(team_ratings))

    # ESPN BET is now the primary (and only) odds source for team game totals.
    # Locked per game_id on first fetch so the line stays stable all day even if
    # ESPN's feed goes dark later (vegas_cache.json persistence).
    vegas_totals: dict = {}
    vegas_spreads: dict = {}
    espn_totals, espn_spreads = await nba_live_client.fetch_vegas_totals_espn()
    if espn_totals:
        vegas_totals = espn_totals
        vegas_spreads = espn_spreads
        logger.info("ESPN BET odds loaded: %d games", len(vegas_totals))
    else:
        logger.info("ESPN BET odds unavailable — model will run without Vegas anchor")

    # Player props: no paid provider → synthetic DB props only.
    # Synthetic = last5_avg × 0.65 + season_avg × 0.35, loaded automatically
    # by _load_synthetic_props() inside prediction_engine for each player.
    # Weight in prop blend: synthetic 15% vs market 45% — lower weight reflects
    # that these are model-derived, not sharp-money lines.
    from app.simulation.prediction_engine import set_player_props, _load_synthetic_props
    set_player_props({})  # clear any stale market props; synthetic props load on demand

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
            home_team = _build_team_state(home_box, home_score, team_ratings)
            away_team = _build_team_state(away_box, away_score, team_ratings)
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
                home_team = _build_team_state_from_season_stats(home_raw, home_score, home_stats, team_ratings)
                away_team = _build_team_state_from_season_stats(away_raw, away_score, away_stats, team_ratings)
                logger.info("Season stats loaded for %s — %d players", game_id, len(home_team.players) + len(away_team.players))
            except Exception as exc2:
                logger.warning("Season stats also unavailable for %s (%s) — no players.", game_id, exc2)
                home_team = _build_minimal_team_state(home_raw, home_score, team_ratings)
                away_team = _build_minimal_team_state(away_raw, away_score, team_ratings)

        # Apply official injury report — overrides _recent_dnp for actively listed players
        if injury_report:
            _apply_injury_report(home_team, injury_report)
            _apply_injury_report(away_team, injury_report)

        # ── ESPN real-time injury + lineup supplement ─────────────────────────
        # Runs after NBA stats API injury report — catches players that the NBA
        # stats endpoint misses (e.g. newly added IR entries, game-day scratches).
        # Also pulls confirmed starters when lineups are posted (~60 min pre-tip).
        try:
            from app.services.injury_lineup_service import (
                get_injury_statuses,
                get_confirmed_starters,
                _OUT_STATUSES,
                _RISKY_STATUSES,
            )
            espn_injuries = get_injury_statuses(game_id, home_tc, away_tc)

            # Apply ESPN injuries to both rosters
            for team_state in (home_team, away_team):
                for player in team_state.players:
                    if player.availability_status == "dnp":
                        continue   # already marked — don't downgrade
                    inj = espn_injuries.get(player.player_id)
                    if inj is None:
                        continue
                    if inj.confirmed_dnp:
                        player.availability_status = "dnp"
                        player.dnp_reason = inj.display_reason
                    elif inj.status in _RISKY_STATUSES and player.dnp_reason is None:
                        # Not confirmed out — flag the uncertainty in dnp_reason
                        # but keep availability_status as "available"
                        player.dnp_reason = f"⚠ {inj.display_reason}"

            # Apply confirmed starters — upgrade rotation_role if ESPN says starter
            starters = get_confirmed_starters(game_id)
            if starters:
                for team_state in (home_team, away_team):
                    for player in team_state.players:
                        if player.player_id in starters:
                            confirmed = starters[player.player_id]
                            if confirmed and player.rotation_role not in ("star",):
                                player.rotation_role = "starter"
                            elif not confirmed and player.rotation_role == "starter":
                                player.rotation_role = "rotation"
                logger.info("Confirmed starters applied for %s: %d players", game_id, len(starters))
        except Exception as espn_exc:
            logger.debug("ESPN injury/lineup supplement skipped: %s", espn_exc)

        # Derive differentiated home/away implied totals from over/under + spread.
        # Formula: home_implied = (total - home_spread) / 2
        #          away_implied = (total + home_spread) / 2
        # e.g. total=216.5, home_spread=-6.5 → home=111.5, away=105.0
        #
        # Write to disk cache on first encounter; read from cache if ESPN has
        # already taken the line down (game live / finished).
        game_total = vegas_totals.get((home_tc, away_tc))
        if game_total:
            home_spread = vegas_spreads.get((home_tc, away_tc), 0.0)
            home_vegas = round((game_total - home_spread) / 2.0, 2)
            away_vegas = round((game_total + home_spread) / 2.0, 2)
            if game_id not in _vegas_cache:
                _vegas_cache[game_id] = {"home": home_vegas, "away": away_vegas}
                _save_vegas_cache(_vegas_cache)
                logger.info("Vegas odds locked for %s: home=%.1f away=%.1f", game_id, home_vegas, away_vegas)
        elif game_id in _vegas_cache:
            home_vegas = _vegas_cache[game_id]["home"]
            away_vegas = _vegas_cache[game_id]["away"]
            logger.info("Vegas odds restored from cache for %s: home=%.1f away=%.1f", game_id, home_vegas, away_vegas)
        else:
            home_vegas = None
            away_vegas = None

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
            home_vegas_total=home_vegas,
            away_vegas_total=away_vegas,
        )

    # Load synthetic props for all players across all games.
    # These are used at 30% blend weight whenever real market props are unavailable.
    all_player_ids = [
        p.player_id
        for ctx in contexts.values()
        for p in ctx.home_team.players + ctx.away_team.players
    ]
    if all_player_ids:
        _load_synthetic_props(all_player_ids)
        logger.info("Synthetic props computed for %d players", len(all_player_ids))

    return slate, contexts
