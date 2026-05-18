"""
Daily DB refresh — pulls new NBA game logs and team defensive stats from stats.nba.com.

Only fetches games newer than the latest date already in the DB, so old historical
data (2023-24 season, earlier playoffs) is never touched.

Run manually:
    python scripts/refresh_db.py

Or schedule daily via cron (see bottom of file).
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

DB_PATH = Path(__file__).parent.parent / "data" / "nba_training.db"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Host": "stats.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}

_BASE = "https://stats.nba.com/stats"


def _current_season() -> str:
    d = date.today()
    return f"{d.year}-{str(d.year + 1)[2:]}" if d.month >= 10 else f"{d.year - 1}-{str(d.year)[2:]}"


def _get(endpoint: str, params: dict) -> dict:
    """Single stats.nba.com request with a polite delay."""
    time.sleep(0.6)
    with httpx.Client(timeout=30.0, headers=_HEADERS, follow_redirects=True) as client:
        r = client.get(f"{_BASE}/{endpoint}", params=params)
        r.raise_for_status()
        return r.json()


def _latest_date_in_db(conn: sqlite3.Connection) -> str:
    """Returns the most recent game_date already stored, or season start if DB is empty."""
    row = conn.execute("SELECT MAX(game_date) FROM player_game_logs").fetchone()
    if row and row[0]:
        return row[0]
    return "2023-10-24"  # fallback to season start


def _fetch_game_logs(date_from: str, season: str, season_type: str) -> list[dict]:
    """Fetch all player game logs for a season/type starting from date_from."""
    print(f"  Fetching {season} {season_type} logs from {date_from} ...")
    data = _get("leaguegamelog", {
        "Counter": 0,
        "DateFrom": date_from,
        "DateTo": "",
        "Direction": "ASC",
        "LeagueID": "00",
        "PlayerOrTeam": "P",
        "Season": season,
        "SeasonType": season_type,
        "Sorter": "DATE",
    })
    rs = next((r for r in data.get("resultSets", []) if r["name"] == "LeagueGameLog"), {})
    headers = rs.get("headers", [])
    rows = rs.get("rowSet", [])
    print(f"    → {len(rows)} rows")
    return [dict(zip(headers, r)) for r in rows]


def _parse_log_row(row: dict) -> dict | None:
    """Convert a leaguegamelog row into the DB schema."""
    matchup = row.get("MATCHUP", "")
    # "OKC vs. SAS" → home, "OKC @ SAS" → away
    if " vs. " in matchup:
        home_away = "H"
        parts = matchup.split(" vs. ")
        team_abbr = parts[0].strip()
        opp_abbr = parts[1].strip()
    elif " @ " in matchup:
        home_away = "A"
        parts = matchup.split(" @ ")
        team_abbr = parts[0].strip()
        opp_abbr = parts[1].strip()
    else:
        return None

    raw_min = row.get("MIN")
    try:
        minutes = float(raw_min) if raw_min is not None else 0.0
    except (ValueError, TypeError):
        minutes = 0.0

    # Parse season from SEASON_ID (e.g. "22024" → "2024-25")
    sid = str(row.get("SEASON_ID", ""))
    if len(sid) >= 5:
        yr = int(sid[1:5])
        season_str = f"{yr}-{str(yr + 1)[2:]}"
    else:
        season_str = _current_season()

    # game_date comes as "2025-06-22T00:00:00" or "2025-06-22"
    raw_date = str(row.get("GAME_DATE", ""))[:10]

    fg_pct = row.get("FG_PCT")
    fg3_pct = row.get("FG3_PCT")

    return {
        "player_id":             str(row.get("PLAYER_ID", "")),
        "player_name":           str(row.get("PLAYER_NAME", "")),
        "team_abbreviation":     team_abbr,
        "opponent_abbreviation": opp_abbr,
        "game_id":               str(row.get("GAME_ID", "")),
        "game_date":             raw_date,
        "season":                season_str,
        "season_type":           "Playoffs" if "Playoff" in str(row.get("SEASON_ID", "")) or "Playoff" in str(row.get("season_type", "")) else "Regular Season",
        "home_away":             home_away,
        "min":                   minutes,
        "pts":                   float(row.get("PTS") or 0),
        "ast":                   float(row.get("AST") or 0),
        "reb":                   float(row.get("REB") or 0),
        "stl":                   float(row.get("STL") or 0),
        "blk":                   float(row.get("BLK") or 0),
        "tov":                   float(row.get("TOV") or 0),
        "fg3m":                  float(row.get("FG3M") or 0),
        "fg_pct":                float(fg_pct) if fg_pct is not None else 0.0,
        "fg3_pct":               float(fg3_pct) if fg3_pct is not None else 0.0,
        "plus_minus":            float(row.get("PLUS_MINUS") or 0),
    }


def _upsert_logs(conn: sqlite3.Connection, logs: list[dict]) -> int:
    """Insert new game logs, skipping any already in the DB (by game_id + player_id)."""
    inserted = 0
    for row in logs:
        parsed = _parse_log_row(row)
        if parsed is None:
            continue
        cur = conn.execute(
            "SELECT 1 FROM player_game_logs WHERE game_id = ? AND player_id = ?",
            (parsed["game_id"], parsed["player_id"]),
        )
        if cur.fetchone():
            continue  # already have this game
        conn.execute(
            """
            INSERT INTO player_game_logs
              (player_id, player_name, team_abbreviation, opponent_abbreviation,
               game_id, game_date, season, season_type, home_away,
               min, pts, ast, reb, stl, blk, tov, fg3m, fg_pct, fg3_pct, plus_minus)
            VALUES
              (:player_id, :player_name, :team_abbreviation, :opponent_abbreviation,
               :game_id, :game_date, :season, :season_type, :home_away,
               :min, :pts, :ast, :reb, :stl, :blk, :tov, :fg3m, :fg_pct, :fg3_pct, :plus_minus)
            """,
            parsed,
        )
        inserted += 1
    conn.commit()
    return inserted


def _refresh_defensive_stats(conn: sqlite3.Connection, season: str, season_type: str) -> None:
    """Replace this season/type's team defensive stats with fresh numbers."""
    print(f"  Refreshing team defensive stats: {season} {season_type} ...")
    data = _get("leaguedashteamstats", {
        "Season": season,
        "SeasonType": season_type,
        "MeasureType": "Opponent",
        "PerMode": "PerGame",
        "LeagueID": "00",
        "DateFrom": "", "DateTo": "", "GameScope": "", "GameSegment": "",
        "ISTRound": "", "LastNGames": 0, "Location": "", "Month": 0,
        "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
        "PaceAdjust": "N", "Period": 0, "PlayerExperience": "",
        "PlayerPosition": "", "PlusMinus": "N", "Rank": "N",
        "SeasonSegment": "", "ShotClockRange": "", "StarterBench": "",
        "TwoWay": 0, "VsConference": "", "VsDivision": "",
    })
    rs = next((r for r in data.get("resultSets", []) if r["name"] == "LeagueDashTeamStats"), {})
    headers = rs.get("headers", [])
    rows = rs.get("rowSet", [])

    # Delete stale rows for this season/type, then re-insert
    conn.execute(
        "DELETE FROM team_defensive_stats WHERE season = ? AND season_type = ?",
        (season, season_type),
    )
    for row in rows:
        r = dict(zip(headers, row))
        conn.execute(
            """
            INSERT OR REPLACE INTO team_defensive_stats
              (team_abbreviation, season, season_type, games_played,
               opp_pts_per_game, def_rating, opp_fg_pct, opp_fg3_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("TEAM_ABBREVIATION", ""),
                season,
                season_type,
                int(r.get("GP") or 0),
                float(r.get("OPP_PTS") or 114.0),
                0.0,  # def_rating not in this endpoint
                float(r.get("OPP_FG_PCT") or 0.46),
                float(r.get("OPP_FG3_PCT") or 0.36),
            ),
        )
    conn.commit()
    print(f"    → {len(rows)} teams updated")


def refresh(force_date: str | None = None) -> None:
    conn = sqlite3.connect(str(DB_PATH))

    latest = force_date or _latest_date_in_db(conn)
    # Fetch from the day AFTER the latest stored game
    date_from = (datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    if date_from > today:
        print(f"DB is already up to date (latest: {latest}). Nothing to fetch.")
        conn.close()
        return

    print(f"DB latest game: {latest} → fetching from {date_from}")
    season = _current_season()

    total_inserted = 0
    for season_type in ["Regular Season", "Playoffs"]:
        try:
            logs = _fetch_game_logs(date_from, season, season_type)
            n = _upsert_logs(conn, logs)
            total_inserted += n
            print(f"    → {n} new rows inserted ({season_type})")
        except Exception as e:
            print(f"    ✗ {season_type} logs failed: {e}")

    print(f"\nTotal new game logs inserted: {total_inserted}")

    # Always refresh defensive stats for current season (ratings shift each game)
    for season_type in ["Regular Season", "Playoffs"]:
        try:
            _refresh_defensive_stats(conn, season, season_type)
        except Exception as e:
            print(f"  ✗ Defensive stats ({season_type}) failed: {e}")

    new_latest = _latest_date_in_db(conn)
    total_rows = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
    print(f"\nDone. DB now has {total_rows:,} game log rows (latest: {new_latest})")
    conn.close()


if __name__ == "__main__":
    import sys
    force = sys.argv[1] if len(sys.argv) > 1 else None
    refresh(force_date=force)
