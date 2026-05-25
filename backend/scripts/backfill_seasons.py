"""
Backfill historical NBA seasons into the training DB.

Pulls 2021-22 and 2022-23 Regular Season + Playoffs from stats.nba.com
and inserts them into player_game_logs so the XGBoost models train on
5 seasons instead of 3 — materially improving prediction accuracy.

Run from backend/:
    python scripts/backfill_seasons.py
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx

DB_PATH = Path(__file__).parent.parent / "data" / "nba_training.db"

SEASONS_TO_BACKFILL = ["2021-22", "2022-23"]
SEASON_TYPES = ["Regular Season", "Playoffs"]

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


def _get(endpoint: str, params: dict, timeout: float = 45.0, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            time.sleep(1.5 + attempt)  # polite delay, grows on retry
            with httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True) as client:
                r = client.get(f"{_BASE}/{endpoint}", params=params)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            if attempt < retries - 1:
                print(f"    ↻ Retry {attempt + 1}/{retries - 1} after error: {e}")
                time.sleep(5)
            else:
                raise


def _fetch_logs(season: str, season_type: str) -> list[dict]:
    print(f"  Fetching {season} {season_type} base logs...")
    data = _get("playergamelogs", {
        "DateFrom": "", "DateTo": "", "GameScope": "", "GameSegment": "",
        "LastNGames": "0", "LeagueID": "00", "Location": "", "MeasureType": "Base",
        "Month": "0", "OpponentTeamID": "0", "Outcome": "", "PORound": "0",
        "PerMode": "PerGame", "Period": "0", "PlayerExperience": "",
        "PlayerPosition": "", "PlusMinus": "N", "Rank": "N",
        "Season": season, "SeasonSegment": "", "SeasonType": season_type,
        "ShotClockRange": "", "StarterBench": "", "TeamID": "0",
        "TwoWay": "0", "VsConference": "", "VsDivision": "",
    })
    rs = next((r for r in data.get("resultSets", []) if r["name"] == "PlayerGameLogs"), {})
    headers = rs.get("headers", [])
    rows = rs.get("rowSet", [])
    print(f"    → {len(rows)} rows")
    return [{**dict(zip(headers, r)), "_season_type": season_type} for r in rows]


def _fetch_advanced(season: str, season_type: str) -> dict:
    print(f"  Fetching {season} {season_type} advanced (USG_PCT)...")
    data = _get("playergamelogs", {
        "MeasureType": "Advanced", "SeasonType": season_type,
        "Season": season, "DateFrom": "", "DateTo": "",
        "LeagueID": "00", "PlayerOrTeam": "P", "PerMode": "PerGame",
    })
    rs = next((r for r in data.get("resultSets", []) if r.get("name") == "PlayerGameLogs"), {})
    headers = rs.get("headers", [])
    rows = rs.get("rowSet", [])
    print(f"    → {len(rows)} advanced rows")
    return {
        (str(r[headers.index("PLAYER_ID")]), str(r[headers.index("GAME_ID")])): float(r[headers.index("USG_PCT")] or 0.0)
        for r in rows
        if "USG_PCT" in headers and "PLAYER_ID" in headers and "GAME_ID" in headers
    }


def _parse_row(r: dict, season: str, usg_map: dict) -> dict | None:
    try:
        player_id  = str(r.get("PLAYER_ID", ""))
        game_id    = str(r.get("GAME_ID", ""))
        game_date  = str(r.get("GAME_DATE", ""))[:10]
        matchup    = str(r.get("MATCHUP", ""))
        is_home    = 1 if "vs." in matchup else 0
        opp        = matchup.split("vs.")[-1].strip() if "vs." in matchup else matchup.split("@")[-1].strip()

        raw_min = r.get("MIN", 0) or 0
        minutes = float(raw_min) if isinstance(raw_min, (int, float)) else 0.0

        if minutes < 5:
            return None

        usg = usg_map.get((player_id, game_id), 0.0)

        return {
            "player_id":             player_id,
            "player_name":           str(r.get("PLAYER_NAME", "")),
            "team_abbreviation":     str(r.get("TEAM_ABBREVIATION", "")),
            "opponent_abbreviation": opp.strip(),
            "game_id":               game_id,
            "game_date":             game_date,
            "season":                season,
            "season_type":           r.get("_season_type", "Regular Season"),
            "home_away":             "home" if is_home else "away",
            "min":                   minutes,
            "pts":                   float(r.get("PTS", 0) or 0),
            "ast":                   float(r.get("AST", 0) or 0),
            "reb":                   float(r.get("REB", 0) or 0),
            "stl":                   float(r.get("STL", 0) or 0),
            "blk":                   float(r.get("BLK", 0) or 0),
            "tov":                   float(r.get("TOV", 0) or 0),
            "fg3m":                  float(r.get("FG3M", 0) or 0),
            "fg_pct":                float(r.get("FG_PCT", 0) or 0),
            "fg3_pct":               float(r.get("FG3_PCT", 0) or 0),
            "usg_pct":               usg,
        }
    except Exception as e:
        print(f"    ✗ Row parse error: {e}")
        return None


def _insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO player_game_logs (
                    player_id, player_name, team_abbreviation, opponent_abbreviation,
                    game_id, game_date, season, season_type, home_away,
                    min, pts, ast, reb, stl, blk, tov, fg3m, fg_pct, fg3_pct, usg_pct
                ) VALUES (
                    :player_id, :player_name, :team_abbreviation, :opponent_abbreviation,
                    :game_id, :game_date, :season, :season_type, :home_away,
                    :min, :pts, :ast, :reb, :stl, :blk, :tov, :fg3m, :fg_pct, :fg3_pct, :usg_pct
                )
            """, row)
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            print(f"    ✗ Insert error: {e}")
    conn.commit()
    return inserted


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))

    # Check existing seasons
    existing = [r[0] for r in conn.execute("SELECT DISTINCT season FROM player_game_logs").fetchall()]
    print(f"Existing seasons in DB: {existing}")

    total_inserted = 0

    for season in SEASONS_TO_BACKFILL:
        if season in existing:
            print(f"\n✓ {season} already in DB — skipping")
            continue

        print(f"\n{'='*50}")
        print(f"Backfilling {season}...")

        for season_type in SEASON_TYPES:
            try:
                logs = _fetch_logs(season, season_type)
                usg_map = _fetch_advanced(season, season_type)
                parsed = [r for raw in logs if (r := _parse_row(raw, season, usg_map)) is not None]
                n = _insert_rows(conn, parsed)
                total_inserted += n
                print(f"    ✓ Inserted {n} new rows ({season} {season_type})")
            except Exception as e:
                print(f"    ✗ Failed {season} {season_type}: {e}")

    conn.close()
    print(f"\n{'='*50}")
    print(f"Done. Total new rows inserted: {total_inserted}")
    print(f"\nNow run: python scripts/train_model.py")


if __name__ == "__main__":
    main()
