"""
Pull NBA player game logs from stats.nba.com and store in SQLite.

Fetches:
  - 2023-24 Regular Season + Playoffs
  - 2024-25 Regular Season + Playoffs

Run from backend/:
    python scripts/build_training_data.py

Output: data/nba_training.db
"""

import asyncio
import sqlite3
import time
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "nba_training.db"

SEASONS = ["2023-24", "2024-25"]
SEASON_TYPES = ["Regular Season", "Playoffs"]

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
    "Host": "stats.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


# ── Database ──────────────────────────────────────────────────────────────────

def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS player_game_logs (
            player_id           TEXT NOT NULL,
            player_name         TEXT NOT NULL,
            team_abbreviation   TEXT NOT NULL,
            opponent_abbreviation TEXT NOT NULL,
            game_id             TEXT NOT NULL,
            game_date           TEXT NOT NULL,
            season              TEXT NOT NULL,
            season_type         TEXT NOT NULL,
            home_away           TEXT NOT NULL,   -- 'H' or 'A'
            min                 REAL DEFAULT 0,
            pts                 REAL DEFAULT 0,
            ast                 REAL DEFAULT 0,
            reb                 REAL DEFAULT 0,
            stl                 REAL DEFAULT 0,
            blk                 REAL DEFAULT 0,
            tov                 REAL DEFAULT 0,
            fg3m                REAL DEFAULT 0,
            fg_pct              REAL DEFAULT 0,
            fg3_pct             REAL DEFAULT 0,
            plus_minus          REAL DEFAULT 0,
            PRIMARY KEY (player_id, game_id)
        );

        CREATE TABLE IF NOT EXISTS team_defensive_stats (
            team_abbreviation   TEXT NOT NULL,
            season              TEXT NOT NULL,
            season_type         TEXT NOT NULL,
            games_played        INTEGER DEFAULT 0,
            opp_pts_per_game    REAL DEFAULT 0,
            def_rating          REAL DEFAULT 0,
            opp_fg_pct          REAL DEFAULT 0,
            opp_fg3_pct         REAL DEFAULT 0,
            PRIMARY KEY (team_abbreviation, season, season_type)
        );

        CREATE INDEX IF NOT EXISTS idx_logs_player_date
            ON player_game_logs (player_id, game_date);
        CREATE INDEX IF NOT EXISTS idx_logs_opponent
            ON player_game_logs (opponent_abbreviation, game_date);
    """)
    conn.commit()


# ── Fetch helpers ─────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, endpoint: str, params: dict) -> dict:
    r = await client.get(f"https://stats.nba.com/stats/{endpoint}", params=params)
    r.raise_for_status()
    return r.json()


def _result_set(data: dict, name: str) -> list[dict]:
    rs = next((r for r in data.get("resultSets", []) if r["name"] == name), {})
    headers = rs.get("headers", [])
    return [dict(zip(headers, row)) for row in rs.get("rowSet", [])]


async def fetch_player_game_logs(
    client: httpx.AsyncClient, season: str, season_type: str
) -> list[dict]:
    data = await _get(client, "leaguegamelog", {
        "Counter": "0",
        "DateFrom": "",
        "DateTo": "",
        "Direction": "ASC",
        "LeagueID": "00",
        "PlayerOrTeam": "P",
        "Season": season,
        "SeasonType": season_type,
        "Sorter": "DATE",
    })
    return _result_set(data, "LeagueGameLog")


async def fetch_team_defensive_stats(
    client: httpx.AsyncClient, season: str, season_type: str
) -> list[dict]:
    """Try Opponent measure type; fall back to Base which includes opp stats."""
    base_params = {
        "Season": season,
        "SeasonType": season_type,
        "PerMode": "PerGame",
        "LeagueID": "00",
        "DateFrom": "", "DateTo": "", "GameScope": "", "GameSegment": "",
        "ISTRound": "", "LastNGames": 0, "Location": "", "Month": 0,
        "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
        "PaceAdjust": "N", "Period": 0, "PlayerExperience": "",
        "PlayerPosition": "", "PlusMinus": "N", "Rank": "N",
        "SeasonSegment": "", "ShotClockRange": "", "StarterBench": "",
        "TwoWay": 0, "VsConference": "", "VsDivision": "",
    }
    for measure in ("Opponent", "Base"):
        try:
            data = await _get(client, "leaguedashteamstats", {**base_params, "MeasureType": measure})
            rows = _result_set(data, "LeagueDashTeamStats")
            if rows:
                return rows
        except Exception:
            time.sleep(2)
    return []


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_matchup(matchup: str) -> tuple[str, str]:
    """Return (home_away, opponent_abbreviation) from 'LAL vs. BOS' or 'LAL @ BOS'."""
    if " vs. " in matchup:
        return "H", matchup.split(" vs. ")[1].strip()
    if " @ " in matchup:
        return "A", matchup.split(" @ ")[1].strip()
    return "H", ""


def _parse_min(value) -> float:
    s = str(value or "0").strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return round(float(m) + float(sec) / 60, 2)
        return float(s)
    except ValueError:
        return 0.0


# ── Insert ────────────────────────────────────────────────────────────────────

def insert_player_logs(
    conn: sqlite3.Connection,
    logs: list[dict],
    season: str,
    season_type: str,
) -> int:
    rows = []
    for log in logs:
        home_away, opponent = _parse_matchup(log.get("MATCHUP", ""))
        rows.append((
            str(log["PLAYER_ID"]),
            log.get("PLAYER_NAME", "Unknown"),
            log.get("TEAM_ABBREVIATION", ""),
            opponent,
            log["GAME_ID"],
            log["GAME_DATE"],
            season,
            season_type,
            home_away,
            _parse_min(log.get("MIN")),
            float(log.get("PTS") or 0),
            float(log.get("AST") or 0),
            float(log.get("REB") or 0),
            float(log.get("STL") or 0),
            float(log.get("BLK") or 0),
            float(log.get("TOV") or 0),
            float(log.get("FG3M") or 0),
            float(log.get("FG_PCT") or 0),
            float(log.get("FG3_PCT") or 0),
            float(log.get("PLUS_MINUS") or 0),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO player_game_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


def insert_team_defensive_stats(
    conn: sqlite3.Connection,
    stats: list[dict],
    season: str,
    season_type: str,
) -> int:
    rows = []
    for t in stats:
        rows.append((
            t.get("TEAM_ABBREVIATION", ""),
            season,
            season_type,
            int(t.get("GP") or 0),
            float(t.get("OPP_PTS") or 0),
            float(t.get("DEF_RATING") or 0),
            float(t.get("OPP_FG_PCT") or 0),
            float(t.get("OPP_FG3_PCT") or 0),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO team_defensive_stats VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)

    async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0, follow_redirects=True) as client:
        for season in SEASONS:
            for season_type in SEASON_TYPES:
                tag = f"{season} {season_type}"
                print(f"\n── {tag} ──")

                # Player game logs
                print("  Fetching player game logs...", end=" ", flush=True)
                try:
                    logs = await fetch_player_game_logs(client, season, season_type)
                    n = insert_player_logs(conn, logs, season, season_type)
                    print(f"{n} rows")
                except Exception as e:
                    print(f"FAILED — {e}")

                time.sleep(2)

                # Team defensive stats
                print("  Fetching team defensive stats...", end=" ", flush=True)
                try:
                    stats = await fetch_team_defensive_stats(client, season, season_type)
                    n = insert_team_defensive_stats(conn, stats, season, season_type)
                    print(f"{n} teams")
                except Exception as e:
                    print(f"FAILED — {e}")

                time.sleep(2)

    # Derive missing team defensive stats from player game logs
    print("\n── Deriving missing team defensive stats from game logs ──")
    conn.executescript("""
        INSERT OR IGNORE INTO team_defensive_stats
            (team_abbreviation, season, season_type, games_played,
             opp_pts_per_game, def_rating, opp_fg_pct, opp_fg3_pct)
        SELECT
            opponent_abbreviation           AS team_abbreviation,
            season,
            season_type,
            COUNT(DISTINCT game_id)         AS games_played,
            ROUND(AVG(pts), 2)              AS opp_pts_per_game,
            0.0                             AS def_rating,
            ROUND(AVG(CASE WHEN fg_pct > 0 THEN fg_pct END), 3) AS opp_fg_pct,
            ROUND(AVG(CASE WHEN fg3_pct > 0 THEN fg3_pct END), 3) AS opp_fg3_pct
        FROM (
            SELECT opponent_abbreviation, season, season_type, game_id,
                   SUM(pts) AS pts, AVG(fg_pct) AS fg_pct, AVG(fg3_pct) AS fg3_pct
            FROM player_game_logs
            GROUP BY opponent_abbreviation, season, season_type, game_id
        )
        GROUP BY opponent_abbreviation, season, season_type;
    """)
    conn.commit()
    print("  Done.")

    # Summary
    player_rows = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
    team_rows = conn.execute("SELECT COUNT(*) FROM team_defensive_stats").fetchone()[0]
    seasons_in_db = conn.execute(
        "SELECT season, season_type, COUNT(*) FROM player_game_logs GROUP BY season, season_type"
    ).fetchall()

    print("\n══ Done ══")
    print(f"  player_game_logs : {player_rows:,} rows")
    print(f"  team_defensive_stats : {team_rows} rows")
    print("\nBreakdown:")
    for season, stype, count in seasons_in_db:
        print(f"  {season} {stype}: {count:,} player-game rows")
    print(f"\nDatabase: {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
