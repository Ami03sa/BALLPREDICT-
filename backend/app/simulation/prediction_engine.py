from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import numpy as np

from app.schemas.game import ConfidenceBand, PlayerProjection, StatLine, TeamProjection
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState

_DATA_DIR  = Path(__file__).parent.parent.parent / "data"
_MODEL_DIR = _DATA_DIR / "models"
_DB_PATH   = _DATA_DIR / "nba_training.db"

_TARGETS = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov"]


def _load_models() -> dict | None:
    try:
        import xgboost as xgb
        models: dict = {}

        # Mean models (one per stat)
        for t in _TARGETS:
            path = _MODEL_DIR / f"model_{t}.json"
            if not path.exists():
                return None
            m = xgb.XGBRegressor()
            m.load_model(str(path))
            models[t] = m

        # Quantile models — q10 (floor) and q90 (ceiling) for each stat.
        # Trained with reg:quantileerror so CIs are statistically grounded.
        for t in _TARGETS:
            for q in ("q10", "q90"):
                path = _MODEL_DIR / f"model_{t}_{q}.json"
                if path.exists():
                    mq = xgb.XGBRegressor()
                    mq.load_model(str(path))
                    models[f"{t}_{q}"] = mq

        # Win-probability classifier
        wp_path = _MODEL_DIR / "model_win_prob.json"
        if wp_path.exists():
            wp = xgb.XGBClassifier()
            wp.load_model(str(wp_path))
            models["_win_prob"] = wp
            wp_feat_path = _MODEL_DIR / "win_prob_features.json"
            if wp_feat_path.exists():
                with open(wp_feat_path) as f:
                    models["_win_prob_features"] = json.load(f)

        with open(_MODEL_DIR / "features.json") as f:
            models["_features"] = json.load(f)
        return models
    except Exception:
        return None


_MODELS = _load_models()

# ── Player props cache ────────────────────────────────────────────────────────
# Populated daily from The Odds API by nba_api_service.
# Keys are normalized player names (lowercase, letters + spaces only).
_PLAYER_PROPS: dict[str, dict[str, float]] = {}

# ── Synthetic prop cache ───────────────────────────────────────────────────────
# Computed from DB rolling averages when market props are unavailable.
# Keyed by player_id → {pts, reb, ast, fg3m}.
_SYNTHETIC_PROPS: dict[str, dict[str, float]] = {}


def set_player_props(props: dict[str, dict[str, float]]) -> None:
    global _PLAYER_PROPS
    _PLAYER_PROPS = props


def _load_synthetic_props(player_ids: list[str]) -> None:
    """
    Compute synthetic prop lines from DB rolling averages for players without
    real market props. Line = last5_avg × 0.65 + season_avg × 0.35.
    Stored in _SYNTHETIC_PROPS keyed by player_id.
    """
    global _SYNTHETIC_PROPS
    if not player_ids or not _DB_PATH.exists():
        return
    try:
        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            f"""
            SELECT
                player_id,
                AVG(CASE WHEN rn <= 5  THEN pts  END) AS pts_last5,
                AVG(CASE WHEN rn <= 5  THEN reb  END) AS reb_last5,
                AVG(CASE WHEN rn <= 5  THEN ast  END) AS ast_last5,
                AVG(CASE WHEN rn <= 5  THEN fg3m END) AS fg3m_last5,
                AVG(pts)  AS pts_season,
                AVG(reb)  AS reb_season,
                AVG(ast)  AS ast_season,
                AVG(fg3m) AS fg3m_season
            FROM (
                SELECT player_id, pts, reb, ast, fg3m,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
                FROM player_game_logs
                WHERE player_id IN ({placeholders}) AND min >= 10
            )
            GROUP BY player_id
            """,
            player_ids,
        ).fetchall()
        conn.close()
        for row in rows:
            pid = row[0]
            def _blend(last5, season):
                if last5 is None and season is None:
                    return None
                l = float(last5 or 0)
                s = float(season or 0)
                return round(l * 0.65 + s * 0.35, 1)
            _SYNTHETIC_PROPS[pid] = {
                "pts":  _blend(row[1], row[5]),
                "reb":  _blend(row[2], row[6]),
                "ast":  _blend(row[3], row[7]),
                "fg3m": _blend(row[4], row[8]),
            }
    except Exception:
        pass


def _prop_line(player_name: str, stat: str, player_id: str | None = None) -> tuple[float | None, bool]:
    """
    Return (line, is_market) for a player/stat.
    is_market=True  → real Vegas prop (45% blend weight)
    is_market=False → synthetic DB line (30% blend weight)
    Returns (None, False) if neither is available.
    """
    import re
    norm = re.sub(r"[^a-z ]", "", player_name.lower().strip())
    # Real market props first
    if norm in _PLAYER_PROPS:
        v = _PLAYER_PROPS[norm].get(stat)
        if v:
            return v, True
    for key, vals in _PLAYER_PROPS.items():
        if key in norm or norm in key:
            v = vals.get(stat)
            if v:
                return v, True
    # Synthetic fallback from DB rolling averages
    if player_id and player_id in _SYNTHETIC_PROPS:
        v = _SYNTHETIC_PROPS[player_id].get(stat)
        if v:
            return v, False
    return None, False


def _hot_factor(player_id: str) -> float:
    """
    Compares last-3-game scoring to last-10-game average.
    Returns a multiplier:
      > 1.0 → player is running hot (takeover candidate)
      < 1.0 → player is cold / being contained
      1.0   → no meaningful trend
    Clamped to [0.70, 1.45] so it doesn't blow up projections.
    """
    if not _DB_PATH.exists():
        return 1.0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT pts, min FROM player_game_logs WHERE player_id = ? AND min > 0 ORDER BY game_date DESC LIMIT 10",
            (player_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return 1.0

    # Require 20+ minutes so foul-trouble games don't skew the ratio
    played = [(r[0], r[1]) for r in rows if float(r[1] or 0) >= 20]
    if len(played) < 4:
        return 1.0

    last3_avg  = sum(p[0] for p in played[:3]) / 3
    last10_avg = sum(p[0] for p in played) / len(played)

    if last10_avg <= 0:
        return 1.0

    ratio = last3_avg / last10_avg
    return round(min(1.45, max(0.70, ratio)), 3)


def _player_history(player_id: str, is_playoffs: bool = False, opp_team_id: str | None = None) -> dict:
    if not _DB_PATH.exists():
        return {}
    cols = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct", "usg_pct"]
    sel = "SELECT pts, ast, reb, stl, blk, fg3m, tov, min, fg_pct, fg3_pct, usg_pct FROM player_game_logs"
    try:
        conn = sqlite3.connect(_DB_PATH)
        if is_playoffs and opp_team_id:
            opp = opp_team_id.upper()
            # Current series games only — the only data that matters for Game 3+
            series_rows = conn.execute(
                f"{sel} WHERE player_id=? AND min>0 AND season_type='Playoffs'"
                " AND opponent_abbreviation=? ORDER BY game_date DESC LIMIT 7",
                (player_id, opp),
            ).fetchall()
            series_count = len(series_rows)
            if series_rows:
                # Series has started: use ONLY these games. Playoff basketball is
                # a different game — regular season data from other contexts pollutes.
                rows = list(series_rows)
                form_rows = None  # series rows ARE the best form data; no split needed
            else:
                # Game 1 (no series data yet): use H2H regular season matchups as
                # the primary history source — captures the structural matchup pattern
                # (how Wembanyama performs specifically vs NYK, not vs OKC).
                rows = conn.execute(
                    f"{sel} WHERE player_id=? AND min>0 AND opponent_abbreviation=?"
                    " ORDER BY game_date DESC LIMIT 10",
                    (player_id, opp),
                ).fetchall()
                if not rows:
                    rows = conn.execute(
                        f"{sel} WHERE player_id=? AND min>0 ORDER BY game_date DESC LIMIT 10",
                        (player_id,),
                    ).fetchall()
                    form_rows = None  # same source; no split needed
                else:
                    # H2H data found — ALSO fetch recent all-game form (last 10 games
                    # across ALL opponents, including the just-finished OKC series).
                    # This gives XGBoost two orthogonal signals:
                    #   • H2H base    → "Wembanyama averages 30 vs NYK" (matchup pattern)
                    #   • Recent form → "he's coming off a 28-pt OKC series" (hot/cold streak)
                    # last5/last10/season_avg will reflect H2H; ewm3/ewm7/ewm15 will use
                    # recent form so the streak signal feeds through to the model correctly.
                    form_rows = conn.execute(
                        f"{sel} WHERE player_id=? AND min>0 ORDER BY game_date DESC LIMIT 10",
                        (player_id,),
                    ).fetchall()
        else:
            rows = conn.execute(
                f"{sel} WHERE player_id=? AND min>0 ORDER BY game_date DESC LIMIT 10",
                (player_id,),
            ).fetchall()
            series_count = 0
            form_rows = None
        conn.close()
    except Exception:
        return {}
    if not rows:
        return {}
    history = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
    # _series_count: how many leading entries are from the current playoff series.
    # last3 is capped to this so it never crosses into other opponents.
    history["_series_count"] = series_count
    # _form_vals: recent all-game form data (used for ewm3/ewm7/ewm15 in _build_features).
    # Only set when we have H2H-specific history as the base — for in-series games or
    # generic last-10 history, the main history IS the form data (no split needed).
    if form_rows:
        history["_form_vals"] = {c: [r[i] for r in form_rows] for i, c in enumerate(cols)}
    return history


def _player_position(player_id: str) -> str:
    """
    Classify a player as G/F/C using per-36-minute career stats.
    Mirrors train_model.py exactly so inference features match training features.
    """
    if not _DB_PATH.exists():
        return "F"
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        row = conn.execute(
            """
            SELECT AVG(reb), AVG(blk), AVG(ast), AVG(fg3m), AVG(min)
            FROM player_game_logs
            WHERE player_id = ? AND min >= 8
            """,
            (player_id,),
        ).fetchone()
        conn.close()
        if not row or row[4] is None or row[4] == 0:
            return "F"
        reb, blk, ast, fg3m, avg_min = (float(x or 0) for x in row)
        min36 = max(avg_min, 1)
        big_per36   = (reb + blk)  / min36 * 36
        guard_per36 = (ast + fg3m) / min36 * 36
        if big_per36 > 6.5:
            return "C"
        if guard_per36 > 4.5:
            return "G"
        return "F"
    except Exception:
        return "F"


def _opponent_def_stats(opponent_id: str, position: str = "F") -> dict:
    """
    Full per-stat matchup vulnerability for the opposing team, broken down by
    position archetype (G/F/C). Team-level stats fill in when position bucket
    has insufficient data.
    """
    defaults = {
        "opp_pts_per_game": 12.0, "opp_fg_pct": 0.46, "opp_fg3_pct": 0.36,
        "opp_ast_pg": 2.8, "opp_reb_pg": 4.6, "opp_fg3m_pg": 1.4,
        "opp_blk_pg": 0.55, "opp_stl_pg": 0.85,
        "opp_pos_pts": 12.0, "opp_pos_ast": 2.8, "opp_pos_reb": 4.6,
        "opp_pos_fg3m": 1.4, "opp_pos_blk": 0.55, "opp_pos_stl": 0.85,
    }
    if not _DB_PATH.exists():
        return defaults
    try:
        conn = sqlite3.connect(_DB_PATH)
        season_row = conn.execute("SELECT MAX(season) FROM player_game_logs").fetchone()
        season = season_row[0] if season_row else "2024-25"

        team_row = conn.execute(
            """
            SELECT AVG(pts), AVG(fg_pct), AVG(fg3_pct),
                   AVG(ast), AVG(reb), AVG(fg3m), AVG(blk), AVG(stl)
            FROM player_game_logs
            WHERE opponent_abbreviation = ? AND season = ?
              AND season_type = 'Regular Season' AND min >= 5
            """,
            (opponent_id.upper(), season),
        ).fetchone()

        result = dict(defaults)
        if team_row and team_row[0] is not None:
            result.update({
                "opp_pts_per_game": team_row[0], "opp_fg_pct": team_row[1],
                "opp_fg3_pct": team_row[2], "opp_ast_pg": team_row[3],
                "opp_reb_pg": team_row[4], "opp_fg3m_pg": team_row[5],
                "opp_blk_pg": team_row[6], "opp_stl_pg": team_row[7],
            })

        pos_row = conn.execute(
            """
            WITH archetypes AS (
                SELECT player_id,
                       CASE
                           WHEN (AVG(reb) + AVG(blk))  / MAX(AVG(min), 1) * 36 > 6.5 THEN 'C'
                           WHEN (AVG(ast) + AVG(fg3m)) / MAX(AVG(min), 1) * 36 > 4.5 THEN 'G'
                           ELSE 'F'
                       END AS pos
                FROM player_game_logs WHERE min >= 8 GROUP BY player_id
            )
            SELECT AVG(l.pts), AVG(l.ast), AVG(l.reb), AVG(l.fg3m), AVG(l.blk), AVG(l.stl)
            FROM player_game_logs l
            JOIN archetypes a ON a.player_id = l.player_id
            WHERE l.opponent_abbreviation = ? AND l.season = ?
              AND l.season_type = 'Regular Season' AND l.min >= 5 AND a.pos = ?
            """,
            (opponent_id.upper(), season, position),
        ).fetchone()
        conn.close()

        if pos_row and pos_row[0] is not None:
            result.update({
                "opp_pos_pts": pos_row[0], "opp_pos_ast": pos_row[1],
                "opp_pos_reb": pos_row[2], "opp_pos_fg3m": pos_row[3],
                "opp_pos_blk": pos_row[4], "opp_pos_stl": pos_row[5],
            })
        else:
            result.update({
                "opp_pos_pts": result["opp_pts_per_game"],
                "opp_pos_ast": result["opp_ast_pg"],
                "opp_pos_reb": result["opp_reb_pg"],
                "opp_pos_fg3m": result["opp_fg3m_pg"],
                "opp_pos_blk": result["opp_blk_pg"],
                "opp_pos_stl": result["opp_stl_pg"],
            })
        return result
    except Exception:
        pass
    return defaults


def _rolling(values: list[float], n: int) -> float:
    subset = values[:n]
    return float(np.mean(subset)) if subset else 0.0


def _rest_days(player_id: str) -> float:
    """Days between the player's last logged game and today. Clamped 1–14."""
    if not _DB_PATH.exists():
        return 2.0
    try:
        from datetime import date
        conn = sqlite3.connect(str(_DB_PATH))
        row = conn.execute(
            "SELECT MAX(game_date) FROM player_game_logs WHERE player_id = ? AND min > 0",
            (player_id,),
        ).fetchone()
        conn.close()
        if not row or not row[0]:
            return 2.0
        last = date.fromisoformat(str(row[0])[:10])
        return float(max(1, min(14, (date.today() - last).days)))
    except Exception:
        return 2.0


def _player_vs_opp(player_id: str, opponent_id: str) -> dict:
    """Historical stats for this player specifically against this opponent team."""
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            """
            SELECT pts, ast, reb
            FROM player_game_logs
            WHERE player_id = ? AND opponent_abbreviation = ? AND min > 0
            ORDER BY game_date DESC LIMIT 10
            """,
            (player_id, opponent_id.upper()),
        ).fetchall()
        conn.close()
        if not rows:
            return {}
        return {"pts": [r[0] for r in rows], "ast": [r[1] for r in rows], "reb": [r[2] for r in rows]}
    except Exception:
        return {}


_SERIES_CACHE: dict[tuple, dict] = {}

def _series_context(team_id: str, opp_id: str, is_playoffs: bool) -> dict:
    """
    Returns series_game_num, team_series_wins, opp_series_wins, series_advantage.
    Result is cached per matchup so DB is hit once per game, not once per player.
    """
    defaults = {"series_game_num": 1, "team_series_wins": 0, "opp_series_wins": 0, "series_advantage": 0, "team_series_tov": 0.0}
    if not is_playoffs or not _DB_PATH.exists():
        return defaults

    t, o = team_id.upper(), opp_id.upper()
    cache_key = (t, o)
    if cache_key in _SERIES_CACHE:
        return _SERIES_CACHE[cache_key]

    try:
        conn = sqlite3.connect(_DB_PATH)
        season = (conn.execute("SELECT MAX(season) FROM player_game_logs").fetchone() or [None])[0]
        if not season:
            conn.close()
            return defaults

        rows = conn.execute("""
            SELECT g.game_id, SUM(g.pts) AS team_score, SUM(og.pts) AS opp_score
            FROM player_game_logs g
            JOIN player_game_logs og ON og.game_id = g.game_id
                AND og.team_abbreviation = ?
            WHERE g.team_abbreviation = ?
              AND g.opponent_abbreviation = ?
              AND g.season = ?
              AND g.season_type = 'Playoffs'
              AND g.min >= 5
            GROUP BY g.game_id
            ORDER BY MIN(g.game_date)
        """, (o, t, o, season)).fetchall()
        conn.close()

        games_played = len(rows)
        team_wins = sum(1 for r in rows if r[1] > r[2])
        opp_wins  = sum(1 for r in rows if r[2] > r[1])
        adv = 1 if team_wins > opp_wins else (-1 if team_wins < opp_wins else 0)

        # Fetch team's avg TOV per game in this series (used as a model feature)
        team_series_tov = 0.0
        if games_played > 0:
            try:
                conn2 = sqlite3.connect(_DB_PATH)
                tov_rows = conn2.execute("""
                    SELECT AVG(game_tov) FROM (
                        SELECT game_id, SUM(tov) AS game_tov
                        FROM player_game_logs
                        WHERE team_abbreviation = ? AND opponent_abbreviation = ?
                          AND season_type = 'Playoffs' AND season = ?
                        GROUP BY game_id
                    )
                """, (t, o, season)).fetchone()
                conn2.close()
                if tov_rows and tov_rows[0] is not None:
                    team_series_tov = float(tov_rows[0])
            except Exception:
                pass

        result = {
            "series_game_num":  games_played + 1,
            "team_series_wins": team_wins,
            "opp_series_wins":  opp_wins,
            "series_advantage": adv,
            "team_series_tov":  team_series_tov,
        }
        _SERIES_CACHE[cache_key] = result
        return result
    except Exception:
        return defaults


def _home_away_splits(player_id: str) -> dict:
    """Career home and away scoring averages."""
    if not _DB_PATH.exists():
        return {"home_pts_avg": 0.0, "away_pts_avg": 0.0}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT home_away, AVG(pts) FROM player_game_logs WHERE player_id = ? AND min > 0 GROUP BY home_away",
            (player_id,),
        ).fetchall()
        conn.close()
        result = {"home_pts_avg": 0.0, "away_pts_avg": 0.0}
        for r in rows:
            if r[0] == "H":
                result["home_pts_avg"] = float(r[1])
            elif r[0] == "A":
                result["away_pts_avg"] = float(r[1])
        return result
    except Exception:
        return {"home_pts_avg": 0.0, "away_pts_avg": 0.0}


def _build_features(
    player: PlayerGameState,
    history: dict,
    opp_def: dict,
    is_home: bool,
    h2h: dict | None = None,
    is_playoffs: bool = False,
    splits: dict | None = None,
    team_elo: float = 1500.0,
    opp_elo: float = 1500.0,
    series: dict | None = None,
) -> dict:
    row: dict[str, float] = {}

    # _series_count > 0 means we're in playoffs and the first N entries are
    # from the current series only. last3 must not cross into other opponents.
    series_count = int(history.get("_series_count", 0))

    # _form_vals: recent all-game history (all opponents, last 10 games).
    # Set only when the primary history is H2H-specific (playoff Game 1 before series starts).
    # When available, EWM streak signals are derived from this so the model sees
    # "how has this player been performing lately overall" separately from
    # "how do they typically perform vs THIS opponent".
    form_history = history.get("_form_vals") or history

    def _ewm(v: np.ndarray, span: int) -> float:
        if len(v) == 0:
            return 0.0
        alpha = 2.0 / (span + 1.0)
        result = v[0]
        for x in v[1:]:
            result = alpha * x + (1 - alpha) * result
        return float(result)

    for stat in ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct", "usg_pct"]:
        vals = history.get(stat, [])
        row[f"{stat}_last5"]      = _rolling(vals, 5)
        row[f"{stat}_last10"]     = _rolling(vals, 10)
        row[f"{stat}_season_avg"] = float(np.mean(vals)) if vals else 0.0

        # Exponentially weighted moving averages — use recent all-game form data
        # (not H2H-only) so the hot/cold streak signal reflects how the player
        # is playing right now across ALL opponents, not just vs this one team.
        # ewm3 captures immediate streak, ewm7 medium form, ewm15 season arc.
        form_vals = form_history.get(stat, vals)
        if form_vals:
            arr = np.array(form_vals[:15], dtype=float)  # enough history for ewm15
            row[f"{stat}_ewm3"]  = _ewm(arr, 3)
            row[f"{stat}_ewm7"]  = _ewm(arr, 7)
            row[f"{stat}_ewm15"] = _ewm(arr, 15)
        else:
            row[f"{stat}_ewm3"]  = 0.0
            row[f"{stat}_ewm7"]  = 0.0
            row[f"{stat}_ewm15"] = 0.0

    # last3: strictly limited to current-series games during playoffs
    for stat in ["pts", "ast", "reb", "fg3m"]:
        vals = history.get(stat, [])
        series_vals = vals[:series_count] if series_count > 0 else vals
        row[f"{stat}_last3"] = _rolling(series_vals, 3)

    # Minutes consistency — high std = unpredictable role (foul trouble, coach decisions)
    min_vals = history.get("min", [])
    row["min_std_last10"] = float(np.std(min_vals)) if len(min_vals) >= 3 else 5.0

    # Per-stat volatility — std of last 10 games.
    # High-variance players (stars who explode or go quiet) get naturally wider CIs
    # from the q10/q90 quantile models when this feature is present.
    for stat in ["pts", "ast", "reb"]:
        vals = history.get(stat, [])
        recent = vals[:10]
        if len(recent) >= 3:
            row[f"{stat}_std_last10"] = float(np.std(recent))
        else:
            # Fallback: 30% of rolling mean as estimated dispersion
            row[f"{stat}_std_last10"] = row.get(f"{stat}_last10", 0.0) * 0.30

    row["opp_pts_per_game"] = opp_def.get("opp_pts_per_game", 12.0)
    row["opp_fg_pct"]       = opp_def.get("opp_fg_pct", 0.46)
    row["opp_fg3_pct"]      = opp_def.get("opp_fg3_pct", 0.36)
    row["opp_ast_pg"]       = opp_def.get("opp_ast_pg",  2.8)
    row["opp_reb_pg"]       = opp_def.get("opp_reb_pg",  4.6)
    row["opp_fg3m_pg"]      = opp_def.get("opp_fg3m_pg", 1.4)
    row["opp_blk_pg"]       = opp_def.get("opp_blk_pg",  0.55)
    row["opp_stl_pg"]       = opp_def.get("opp_stl_pg",  0.85)
    row["opp_pos_pts"]      = opp_def.get("opp_pos_pts",  12.0)
    row["opp_pos_ast"]      = opp_def.get("opp_pos_ast",  2.8)
    row["opp_pos_reb"]      = opp_def.get("opp_pos_reb",  4.6)
    row["opp_pos_fg3m"]     = opp_def.get("opp_pos_fg3m", 1.4)
    row["opp_pos_blk"]      = opp_def.get("opp_pos_blk",  0.55)
    row["opp_pos_stl"]      = opp_def.get("opp_pos_stl",  0.85)
    row["is_home"]          = float(is_home)
    row["is_playoffs"]      = float(is_playoffs)
    row["rest_days"]        = _rest_days(player.player_id)

    # Home/away career splits
    splits = splits or {}
    season_pts = row["pts_season_avg"]
    row["home_pts_avg"] = splits.get("home_pts_avg") or season_pts
    row["away_pts_avg"] = splits.get("away_pts_avg") or season_pts

    # Head-to-head history vs this specific opponent
    h2h = h2h or {}
    for stat in ["pts", "ast", "reb"]:
        vals = h2h.get(stat, [])
        fallback = row.get(f"{stat}_season_avg", 0.0)
        row[f"{stat}_vs_opp_last3"] = _rolling(vals, 3) if vals else fallback
        row[f"{stat}_vs_opp_avg"]   = float(np.mean(vals)) if vals else fallback

    # Team ELO — captures cumulative team quality better than season ratings
    row["team_elo"] = team_elo
    row["opp_elo"]  = opp_elo
    row["elo_diff"] = team_elo - opp_elo

    # Playoff series context — which game in the series, and who's leading
    s = series or {}
    row["series_game_num"]  = float(s.get("series_game_num",  1))
    row["team_series_wins"] = float(s.get("team_series_wins", 0))
    row["opp_series_wins"]  = float(s.get("opp_series_wins",  0))
    row["series_advantage"] = float(s.get("series_advantage", 0))

    # Player-level series performance — how this player has actually done in this series.
    # series_count > 0 means we have series-specific history; use it directly.
    # Values are 0 for non-playoff games or Game 1 (the model treats 0 as "no series data").
    row["series_games"] = float(series_count)
    for stat in ["pts", "ast", "reb", "fg3m"]:
        vals = history.get(stat, [])
        series_vals = vals[:series_count] if series_count > 0 else []
        row[f"series_{stat}_avg"] = float(np.mean(series_vals)) if series_vals else 0.0
    # Team-level series TOV — passed in via series dict (populated by projection_service)
    row["team_series_tov"] = float(s.get("team_series_tov", 0.0))

    return row


_NOISE_SCALES: dict[str, float] = {
    # Rolling stats
    "pts_last5": 3.0,   "pts_last10": 1.8,   "pts_season_avg": 1.0,   "pts_last3": 4.0,
    "ast_last5": 1.0,   "ast_last10": 0.6,   "ast_season_avg": 0.3,   "ast_last3": 1.5,
    "reb_last5": 1.5,   "reb_last10": 0.9,   "reb_season_avg": 0.5,   "reb_last3": 2.0,
    "stl_last5": 0.4,   "stl_last10": 0.25,  "stl_season_avg": 0.15,
    "blk_last5": 0.5,   "blk_last10": 0.3,   "blk_season_avg": 0.2,
    "fg3m_last5": 0.8,  "fg3m_last10": 0.5,  "fg3m_season_avg": 0.3,  "fg3m_last3": 1.0,
    "tov_last5": 0.5,   "tov_last10": 0.3,   "tov_season_avg": 0.2,
    "min_last5": 2.5,   "min_last10": 1.5,   "min_season_avg": 1.0,
    "fg_pct_last5": 0.030,  "fg_pct_last10": 0.018,  "fg_pct_season_avg": 0.010,
    "fg3_pct_last5": 0.040, "fg3_pct_last10": 0.025, "fg3_pct_season_avg": 0.015,
    "usg_pct_last5": 0.03,  "usg_pct_last10": 0.02,  "usg_pct_season_avg": 0.01,
    # EWM features — similar scale to their simple-rolling counterparts
    "pts_ewm3": 3.5,    "pts_ewm7": 2.5,    "pts_ewm15": 1.5,
    "ast_ewm3": 1.2,    "ast_ewm7": 0.8,    "ast_ewm15": 0.5,
    "reb_ewm3": 1.8,    "reb_ewm7": 1.2,    "reb_ewm15": 0.8,
    "stl_ewm3": 0.45,   "stl_ewm7": 0.3,    "stl_ewm15": 0.2,
    "blk_ewm3": 0.55,   "blk_ewm7": 0.35,   "blk_ewm15": 0.25,
    "fg3m_ewm3": 0.9,   "fg3m_ewm7": 0.6,   "fg3m_ewm15": 0.4,
    "tov_ewm3": 0.6,    "tov_ewm7": 0.4,    "tov_ewm15": 0.25,
    "min_ewm3": 3.0,    "min_ewm7": 2.0,    "min_ewm15": 1.2,
    "fg_pct_ewm3": 0.035, "fg_pct_ewm7": 0.022, "fg_pct_ewm15": 0.012,
    "fg3_pct_ewm3": 0.045,"fg3_pct_ewm7": 0.028,"fg3_pct_ewm15": 0.018,
    "usg_pct_ewm3": 0.035,"usg_pct_ewm7": 0.022,"usg_pct_ewm15": 0.012,
    "opp_pts_per_game": 1.5, "opp_fg_pct": 0.020, "opp_fg3_pct": 0.025,
    "opp_ast_pg": 0.4, "opp_reb_pg": 0.5, "opp_fg3m_pg": 0.15, "opp_blk_pg": 0.08, "opp_stl_pg": 0.10,
    "opp_pos_pts": 1.5, "opp_pos_ast": 0.4, "opp_pos_reb": 0.5, "opp_pos_fg3m": 0.15, "opp_pos_blk": 0.08, "opp_pos_stl": 0.10,
    "rest_days": 0.8,
    "min_std_last10": 0.5,
    "home_pts_avg": 2.0, "away_pts_avg": 2.0,
    "pts_vs_opp_last3": 4.5, "pts_vs_opp_avg": 2.5,
    "team_elo": 15.0, "opp_elo": 15.0, "elo_diff": 20.0,
    "series_game_num": 0.0, "team_series_wins": 0.0, "opp_series_wins": 0.0, "series_advantage": 0.0,
    "series_games": 0.0, "series_pts_avg": 0.0, "series_ast_avg": 0.0,
    "series_reb_avg": 0.0, "series_fg3m_avg": 0.0, "team_series_tov": 0.0,
    "ast_vs_opp_last3": 1.5, "ast_vs_opp_avg": 0.8,
    "reb_vs_opp_last3": 2.0, "reb_vs_opp_avg": 1.0,
}

_N_RUNS = 200  # number of perturbed runs per prediction


_ELO_CACHE: dict[str, float] = {}
_ELO_CACHE_LOADED = False

def _load_team_elo() -> dict[str, float]:
    """
    Compute each team's current ELO from all game results in the DB.
    ELO before each game is tracked chronologically; the final value is the
    team's current strength estimate. Cached in memory after first call.
    """
    global _ELO_CACHE_LOADED
    if _ELO_CACHE_LOADED:
        return _ELO_CACHE
    _ELO_CACHE_LOADED = True
    if not _DB_PATH.exists():
        return _ELO_CACHE
    try:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute("""
            SELECT g.game_date, g.game_id, g.team, g.opp, g.team_score, o.team_score AS opp_score
            FROM (
                SELECT game_date, game_id, team_abbreviation AS team, opponent_abbreviation AS opp,
                       SUM(pts) AS team_score
                FROM player_game_logs WHERE min >= 5
                GROUP BY game_id, team_abbreviation, opponent_abbreviation, game_date
            ) g
            JOIN (
                SELECT game_id, team_abbreviation AS opp, SUM(pts) AS team_score
                FROM player_game_logs WHERE min >= 5
                GROUP BY game_id, team_abbreviation
            ) o ON g.game_id = o.game_id AND g.opp = o.opp
            ORDER BY g.game_date
        """).fetchall()
        conn.close()

        elo: dict[str, float] = {}
        K, INIT = 20.0, 1500.0
        for game_date, game_id, team, opp, t_score, o_score in rows:
            t_elo = elo.get(team, INIT)
            o_elo = elo.get(opp, INIT)
            exp_t = 1.0 / (1.0 + 10 ** ((o_elo - t_elo) / 400.0))
            actual = 1.0 if t_score > o_score else 0.5 if t_score == o_score else 0.0
            elo[team] = t_elo + K * (actual - exp_t)
            elo[opp]  = o_elo + K * ((1 - actual) - (1 - exp_t))

        _ELO_CACHE.update(elo)
    except Exception:
        pass
    return _ELO_CACHE


def _xgb_predict(player: PlayerGameState, opponent_id: str, is_home: bool, is_playoffs: bool = False) -> dict[str, dict] | None:
    """
    Run the XGBoost mean model plus q10/q90 quantile models for each stat.

    Returns per-stat dicts with keys: mean, floor (q10), ceiling (q90).
    The quantile models were trained with reg:quantileerror and produce
    statistically grounded CI bands — ~80% of actuals should fall inside.
    """
    if _MODELS is None:
        return None
    history  = _player_history(player.player_id, is_playoffs=is_playoffs, opp_team_id=opponent_id)
    position = _player_position(player.player_id)
    opp_def  = _opponent_def_stats(opponent_id, position)
    h2h      = _player_vs_opp(player.player_id, opponent_id)
    splits   = _home_away_splits(player.player_id)
    elo_ratings = _load_team_elo()
    team_id_upper = player.team_id.upper()
    opp_id_upper  = opponent_id.upper()
    team_elo = elo_ratings.get(team_id_upper, 1500.0)
    opp_elo  = elo_ratings.get(opp_id_upper, 1500.0)
    series   = _series_context(team_id_upper, opp_id_upper, is_playoffs)
    feat_row = _build_features(player, history, opp_def, is_home, h2h, is_playoffs, splits, team_elo, opp_elo, series)
    feature_cols = _MODELS["_features"]

    X = np.array([feat_row.get(c, 0.0) for c in feature_cols]).reshape(1, -1)

    results: dict[str, dict] = {}
    for t in _TARGETS:
        mean_pred = float(np.clip(_MODELS[t].predict(X), 0, None)[0])

        # Use quantile models if available, else fall back to std-based estimate
        q10_key = f"{t}_q10"
        q90_key = f"{t}_q90"
        if q10_key in _MODELS and q90_key in _MODELS:
            floor_pred   = float(np.clip(_MODELS[q10_key].predict(X), 0, None)[0])
            ceiling_pred = float(np.clip(_MODELS[q90_key].predict(X), 0, None)[0])
            # Ensure floor ≤ mean ≤ ceiling (quantile crossing can occur)
            floor_pred   = min(floor_pred, mean_pred)
            ceiling_pred = max(ceiling_pred, mean_pred)
        else:
            # Fallback: symmetric ±30% band
            floor_pred   = mean_pred * 0.70
            ceiling_pred = mean_pred * 1.30

        results[t] = {
            "mean":    mean_pred,
            "floor":   floor_pred,
            "ceiling": ceiling_pred,
        }

    # Playoff series override: blend XGBoost output with actual series averages
    # for every player automatically. XGBoost is anchored to career baselines and
    # undersells role players who step up (e.g. Caruso averaging 24 in the series
    # but XGBoost only predicts 11 from career data).
    # Weight grows with number of series games played (more data = more trust).
    # Residual series correction: the model now receives series_pts_avg / series_games
    # as direct input features and has been trained on them. Keep a small residual blend
    # (max 30%) as a safety net in case XGBoost underweights a strong series signal.
    series_count = int(history.get("_series_count", 0))
    if is_playoffs and series_count > 0:
        series_weight = min(0.30, 0.15 * series_count)  # 0.15 per game, cap at 0.30
        for t in _TARGETS:
            vals = history.get(t, [])[:series_count]
            if vals:
                series_avg = float(np.mean(vals))
                xgb_mean   = results[t]["mean"]
                results[t]["mean"] = xgb_mean * (1 - series_weight) + series_avg * series_weight

    return results


class PredictionEngine:

    def project_player(
        self,
        context: GameContext,
        offense: TeamGameState,
        defense: TeamGameState,
        player: PlayerGameState,
    ) -> PlayerProjection:
        zero_line = StatLine()

        if player.availability_status == "dnp":
            return PlayerProjection(
                player_id=player.player_id,
                player_name=player.player_name,
                team_id=player.team_id,
                quarter=context.quarter,
                rotation_role=player.rotation_role,
                availability_status="dnp",
                dnp_reason=player.dnp_reason,
                live_stats=zero_line,
                projected_stats=ConfidenceBand(low=zero_line, mean=zero_line, high=zero_line),
                momentum_score=0.5,
                fatigue_index=0.0,
                defensive_pressure=0.0,
                adjustments=[],
            )

        adjustments = coaching_engine.build_player_counters(context, offense, defense, player)
        pressure     = min(1.0, player.matchup_difficulty + player.fatigue_index + len(adjustments) * 0.08)
        is_home      = offense.team_id == context.home_team.team_id
        # Match the same threshold used in projection_service (_blended_team_total)
        # so the H2H opponent-specific history branch activates for playoff games.
        # With playoff_intensity=0.55 set at startup, 0.65 was never reached and
        # _player_history was fetching last-10-generic instead of H2H vs THIS opponent.
        is_playoffs  = context.playoff_intensity >= 0.55

        hot = _hot_factor(player.player_id)

        preds = _xgb_predict(player, defense.team_id, is_home, is_playoffs)

        if preds is not None:
            proj_pts  = round(preds["pts"]["mean"],  1)
            proj_ast  = round(preds["ast"]["mean"],  1)
            proj_reb  = round(preds["reb"]["mean"],  1)
            proj_stl  = round(preds["stl"]["mean"],  1)
            proj_blk  = round(preds["blk"]["mean"],  1)
            proj_tov  = round(preds["tov"]["mean"],  1)
            proj_fg3m = round(preds["fg3m"]["mean"], 1)

            # Blend with prop lines:
            #   Real market props (Odds API)  → 45% weight  — sharp money signal
            #   Synthetic DB props (free)     → 15% weight  — light historical anchor
            for stat_key, proj_var in [("pts", "proj_pts"), ("reb", "proj_reb"), ("ast", "proj_ast"), ("fg3m", "proj_fg3m")]:
                prop, is_market = _prop_line(player.player_name, stat_key, player.player_id)
                if prop is not None and prop > 0:
                    w = 0.45 if is_market else 0.15
                    blended = round((1 - w) * locals()[proj_var] + w * prop, 1)
                    if stat_key == "pts":
                        proj_pts = blended
                    elif stat_key == "reb":
                        proj_reb = blended
                    elif stat_key == "ast":
                        proj_ast = blended
                    elif stat_key == "fg3m":
                        proj_fg3m = blended

            # Quantile CI bands — statistically grounded floor (q10) and ceiling (q90).
            # Hot players stretch the ceiling further; cold players widen the floor.
            pts_floor   = preds["pts"]["floor"]
            pts_ceiling = preds["pts"]["ceiling"]
            spread      = pts_ceiling - pts_floor  # kept for legacy hot_factor scaling
        else:
            # XGBoost unavailable — season average is the full-game prediction.
            proj_pts  = round(player.pts_avg,  1) if player.pts_avg  > 0 else 0.0
            proj_ast  = round(player.ast_avg,  1) if player.ast_avg  > 0 else 0.0
            proj_reb  = round(player.reb_avg,  1) if player.reb_avg  > 0 else 0.0
            proj_stl  = round(player.stl_avg,  1) if player.stl_avg  > 0 else 0.0
            proj_blk  = round(player.blk_avg,  1) if player.blk_avg  > 0 else 0.0
            proj_tov  = round(player.tov_avg,  1) if player.tov_avg  > 0 else 0.0
            proj_fg3m = round(player.fg3m_avg, 1) if player.fg3m_avg > 0 else 0.0
            spread = 1.2 + pressure * 2.0

        mean_line = StatLine(
            points=proj_pts, assists=proj_ast, rebounds=proj_reb,
            steals=proj_stl, blocks=proj_blk, turnovers=proj_tov,
            **{"3pm": proj_fg3m},
            usage_rate=round(max(0.10, min(0.42, player.usage_rate)), 3),
            field_goal_pct=round(max(0.33, min(0.68, player.field_goal_pct)), 3),
            three_point_pct=round(max(0.25, min(0.55, player.three_point_pct)), 3),
        )
        # Floor/ceiling from quantile regression (q10/q90) — statistically grounded.
        # Hot-factor nudges the ceiling further up; cold nudges floor further down.
        ceiling_mult = 1.0 + (hot - 1.0) * 1.8
        floor_mult   = 1.0 - (hot - 1.0) * 0.4

        if preds is not None:
            # Apply hot/cold scaling symmetrically around the mean
            raw_pts_floor   = preds["pts"]["floor"]
            raw_pts_ceiling = preds["pts"]["ceiling"]
            raw_ast_floor   = preds["ast"]["floor"]
            raw_ast_ceiling = preds["ast"]["ceiling"]
            raw_reb_floor   = preds["reb"]["floor"]
            raw_reb_ceiling = preds["reb"]["ceiling"]
            raw_tov_floor   = preds["tov"]["floor"]
            raw_tov_ceiling = preds["tov"]["ceiling"]

            # Stretch floor/ceiling by hot factor: hot players push ceiling higher,
            # cold players push floor lower — but mean stays pinned.
            def _scale_floor(mean_val: float, q_floor: float, mult: float) -> float:
                gap = mean_val - q_floor
                return max(0.0, mean_val - gap * mult)

            def _scale_ceiling(mean_val: float, q_ceiling: float, mult: float) -> float:
                gap = q_ceiling - mean_val
                return mean_val + gap * mult

            low_line = mean_line.model_copy(update={
                "points":    round(_scale_floor(proj_pts,  raw_pts_floor,   floor_mult),   1),
                "assists":   round(_scale_floor(proj_ast,  raw_ast_floor,   floor_mult),   1),
                "rebounds":  round(_scale_floor(proj_reb,  raw_reb_floor,   floor_mult),   1),
                "turnovers": round(_scale_floor(proj_tov,  raw_tov_floor,   1.0),          1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(_scale_ceiling(proj_pts,  raw_pts_ceiling,   ceiling_mult), 1),
                "assists":   round(_scale_ceiling(proj_ast,  raw_ast_ceiling,   ceiling_mult), 1),
                "rebounds":  round(_scale_ceiling(proj_reb,  raw_reb_ceiling,   ceiling_mult), 1),
                "turnovers": round(_scale_ceiling(proj_tov,  raw_tov_ceiling,   1.0),          1),
            })
        else:
            # Fallback: manual band when XGBoost unavailable
            low_line = mean_line.model_copy(update={
                "points":    round(max(0, proj_pts  - spread * 0.25), 1),
                "assists":   round(max(0, proj_ast  - spread * 0.15), 1),
                "rebounds":  round(max(0, proj_reb  - spread * 0.18), 1),
                "turnovers": round(max(0, proj_tov  - 0.4), 1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(proj_pts  + spread * 0.35 * ceiling_mult, 1),
                "assists":   round(proj_ast  + spread * 0.20 * ceiling_mult, 1),
                "rebounds":  round(proj_reb  + spread * 0.22 * ceiling_mult, 1),
                "turnovers": round(proj_tov  + 0.6, 1),
            })

        return PlayerProjection(
            player_id=player.player_id,
            player_name=player.player_name,
            team_id=player.team_id,
            quarter=context.quarter,
            rotation_role=player.rotation_role,
            availability_status=player.availability_status,
            dnp_reason=player.dnp_reason,
            live_stats=StatLine(
                points=player.points, assists=player.assists,
                rebounds=player.rebounds, steals=player.steals,
                blocks=player.blocks, turnovers=player.turnovers,
                **{"3pm": player.threes_made},
                usage_rate=player.usage_rate,
                field_goal_pct=player.field_goal_pct,
                three_point_pct=player.three_point_pct,
            ),
            projected_stats=ConfidenceBand(low=low_line, mean=mean_line, high=high_line),
            momentum_score=player.momentum_score,
            fatigue_index=player.fatigue_index,
            defensive_pressure=pressure,
            hot_factor=hot,
            adjustments=adjustments,
        )

    def project_team(
        self,
        context: GameContext,
        team: TeamGameState,
        opponent: TeamGameState,
        is_home: bool,
        player_score_sum: int = 0,
        opponent_score_sum: int = 0,
    ) -> TeamProjection:
        final_mean = player_score_sum if player_score_sum > 0 else team.score
        spread = max(4, int(final_mean * 0.10))

        # Win probability — always pre-game, never uses live score.
        # Two signals, equal weight:
        #   1. XGBoost classifier trained on pre-game context (HCA, rest, ratings, ELO)
        #   2. Logistic formula over the PROJECTED score margin from player projections
        # Neither signal touches actual live scores or quarter data.
        if player_score_sum > 0 and opponent_score_sum > 0:
            proj_margin = player_score_sum - opponent_score_sum if is_home else opponent_score_sum - player_score_sum
        else:
            proj_margin = 0  # no projections yet — neutral, let classifier carry it
        formula_prob     = 1 / (1 + math.exp(-(proj_margin / 10.0)))
        formula_win_prob = formula_prob if is_home else 1 - formula_prob

        classifier_win_prob: float | None = None
        wp_model    = _MODELS.get("_win_prob")
        wp_features: list[str] = _MODELS.get("_win_prob_features", [])  # type: ignore[assignment]
        if wp_model is not None and wp_features:
            try:
                # Pre-game feature vector — use team season ratings as proxies
                rest_days = 0 if context.back_to_back else 2
                elo_diff  = (team.offensive_rating - opponent.offensive_rating) * 2.5
                feat_map  = {
                    "is_home":        float(is_home),
                    "rest_days":      float(rest_days),
                    "is_playoffs":    float(context.playoff_intensity >= 0.65),
                    "elo_diff":       elo_diff if is_home else -elo_diff,
                    "pts_last5_avg":  team.offensive_rating,
                    "pts_last10_avg": team.offensive_rating,
                    "pts_diff_l5":    team.offensive_rating - opponent.defensive_rating,
                }
                X_wp = np.array([[feat_map.get(f, 0.0) for f in wp_features]])
                prob = float(wp_model.predict_proba(X_wp)[0][1])
                classifier_win_prob = prob if is_home else 1 - prob
            except Exception:
                pass  # fall through to formula-only

        if classifier_win_prob is not None:
            # 50/50 blend — both signals are pre-game, neither is live
            team_win_prob = 0.50 * classifier_win_prob + 0.50 * formula_win_prob
        else:
            team_win_prob = formula_win_prob

        # Build per-quarter score breakdown.
        q = context.quarter
        if q == 0:
            # Pre-game: distribute projected total evenly across 4 quarters.
            q_base = final_mean // 4
            projected_score = (q_base, q_base, q_base, final_mean - q_base * 3)
        else:
            # Live/final: approximate past quarters from actual cumulative score,
            # project future quarters from the remaining expected points.
            remaining_q = max(0, 4 - q)
            actual_per_q = round(team.score / q) if q > 0 else 0
            future_per_q = round((final_mean - team.score) / remaining_q) if remaining_q > 0 else 0
            quarters = [actual_per_q] * min(q, 4) + [future_per_q] * remaining_q
            projected_score = tuple(quarters[:4])  # type: ignore[assignment]

        return TeamProjection(
            team_id=team.team_id,
            team_name=team.team_name,
            quarter=context.quarter,
            score=team.score,
            projected_score=projected_score,
            final_score_mean=final_mean,
            final_score_ci=(max(0, final_mean - spread), final_mean + spread),
            pace=round(team.pace, 1),
            offensive_rating=round(team.offensive_rating, 1),
            defensive_rating=round(opponent.defensive_rating, 1),
            win_probability=round(team_win_prob, 3),
        )


prediction_engine = PredictionEngine()
