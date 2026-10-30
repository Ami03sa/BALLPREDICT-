"""
Build data/player_averages.json by shrinking early-season per-game averages toward
each player's full prior-season regular-season averages (from the training DB).

Preseason / first-weeks samples (GP 1-5, starters on minute limits) are far too noisy
to anchor projections on: a star who played 21 min in preseason would otherwise be
projected as a 16-point scorer. Each stat is blended as

    blended = (gp * current + K * prior) / (gp + K)

so the prior season dominates early and the current season takes over as GP grows.
Players with no prior-season logs (rookies, call-ups) keep their current-season numbers.

Run after refreshing the raw current-season file:
    python scripts/blend_player_averages.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
RAW_PATH = DATA_DIR / "raw" / "player_averages_preseason_2026-27.json"
OUT_PATH = DATA_DIR / "player_averages.json"
DB_PATH = DATA_DIR / "nba_training.db"

PRIOR_SEASON = "2025-26"
PRIOR_WEIGHT_GAMES = 12  # K: how many games' worth of evidence the prior season counts for

_BLENDED = {"MIN": "min", "PTS": "pts", "AST": "ast", "REB": "reb", "STL": "stl",
            "BLK": "blk", "TOV": "tov", "FG3M": "fg3m", "FG_PCT": "fg_pct", "FG3_PCT": "fg3_pct"}
_SHOT_VOLUME = ("FGA", "FTA")  # not in the DB; scaled with points so usage stays consistent


def _prior_averages(conn: sqlite3.Connection) -> dict[int, dict[str, float]]:
    cols = ", ".join(f"AVG({db}) AS {db}" for db in _BLENDED.values())
    rows = conn.execute(
        f"""
        SELECT player_id, COUNT(*) AS gp, {cols}
        FROM player_game_logs
        WHERE season = ? AND season_type = 'Regular Season' AND min > 0
        GROUP BY player_id
        HAVING gp >= 10
        """,
        (PRIOR_SEASON,),
    ).fetchall()
    names = ["player_id", "gp", *_BLENDED.values()]
    return {int(r[0]): dict(zip(names, r)) for r in rows}


def main() -> None:
    raw = json.loads(RAW_PATH.read_text())
    conn = sqlite3.connect(str(DB_PATH))
    prior = _prior_averages(conn)
    conn.close()

    blended_count = kept_count = 0
    out: dict[str, list[dict]] = {}
    for team, players in raw.items():
        out[team] = []
        for p in players:
            row = dict(p)
            pr = prior.get(int(p["PLAYER_ID"]))
            gp = float(p.get("GP") or 0)
            if pr and gp >= 0:
                w_cur = gp / (gp + PRIOR_WEIGHT_GAMES)
                for key, db_key in _BLENDED.items():
                    cur, old = float(p.get(key) or 0.0), float(pr[db_key] or 0.0)
                    row[key] = round(w_cur * cur + (1 - w_cur) * old, 3)
                pts_cur = float(p.get("PTS") or 0.0)
                if pts_cur > 1.0:
                    scale = row["PTS"] / pts_cur
                    for key in _SHOT_VOLUME:
                        row[key] = round(float(p.get(key) or 0.0) * scale, 2)
                blended_count += 1
            else:
                kept_count += 1
            out[team].append(row)

    OUT_PATH.write_text(json.dumps(out))
    print(f"Blended {blended_count} players with {PRIOR_SEASON} priors; kept {kept_count} unchanged -> {OUT_PATH}")


if __name__ == "__main__":
    main()
