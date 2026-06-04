import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

from app.schemas.game import BreakoutStats, ConfidenceBand, GameSnapshot, OTContributor, OTSimulation, PlayerProjection, StatLine
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"
_SCORE_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "score_cache.json"
_GAME_MINUTES = 240.0
_LEAGUE_AVG_DEF_RTG = 114.0  # League-average defensive rating used for opp-adjustment
_LEAGUE_AVG_TOV = 14.0       # League-average team turnovers per game
_LEAGUE_AVG_PACE = 98.0      # Possessions per 48 min, used to convert pts→per-100
_BREAKOUT_THRESHOLD = 30.0   # Points threshold for "breakout" classification

# Pre-game score predictions locked per game_id — persisted to disk so backend
# restarts don't cause the predicted score to change mid-game.
def _load_score_cache() -> dict[str, list[int]]:
    try:
        return json.loads(_SCORE_CACHE_PATH.read_text()) if _SCORE_CACHE_PATH.exists() else {}
    except Exception:
        return {}

def _save_score_cache(cache: dict) -> None:
    try:
        _SCORE_CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass

_pregame_scores: dict[str, list[int]] = _load_score_cache()


# ── Playoff scoring ratio ──────────────────────────────────────────────────────
# Computed once from DB and cached. Typically 0.94–0.97 — playoffs score ~5%
# less than regular season due to slower pace, tighter defensive schemes,
# and targeted opponent prep. Applied as a multiplier (not a fixed subtraction)
# so the calibration scales with how high the projection is.
_PLAYOFF_RATIO_CACHE: dict = {}

def _fetch_playoff_scoring_ratio() -> float:
    """
    Returns avg(playoff team score) / avg(RS team score) from the training DB.

    Clamped to [0.93, 0.99] — should be ~0.95 in practice, consistent across
    all seasons in our data.  Returns 1.0 on any DB error (safe no-op).
    """
    global _PLAYOFF_RATIO_CACHE
    if "ratio" in _PLAYOFF_RATIO_CACHE:
        return _PLAYOFF_RATIO_CACHE["ratio"]
    if not _DB_PATH.exists():
        return 1.0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        playoff_row = conn.execute(
            """
            SELECT AVG(team_pts) FROM (
                SELECT game_id, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE season_type = 'Playoffs'
                GROUP BY game_id
            )
            """
        ).fetchone()
        rs_row = conn.execute(
            """
            SELECT AVG(team_pts) FROM (
                SELECT game_id, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE season_type = 'Regular Season'
                GROUP BY game_id
            )
            """
        ).fetchone()
        conn.close()
        if playoff_row and rs_row and playoff_row[0] and rs_row[0]:
            ratio = float(playoff_row[0]) / float(rs_row[0])
            ratio = max(0.93, min(0.99, ratio))
            _PLAYOFF_RATIO_CACHE["ratio"] = ratio
            logger.info(
                "Playoff scoring ratio: %.4f  (playoff %.1f pts vs RS %.1f pts/team-game)",
                ratio, playoff_row[0], rs_row[0],
            )
            return ratio
    except Exception:
        pass
    _PLAYOFF_RATIO_CACHE["ratio"] = 1.0
    return 1.0


def _fetch_player_volatility(player_ids: list[str]) -> dict[str, dict]:
    """
    Returns per-player volatility from last 30 qualifying games, weighted toward recency.
    Keys: pts_std, ast_std, reb_std, fg3m_std, stl_std, blk_std, breakout_pct, weighted_mean_pts
    """
    if not player_ids or not _DB_PATH.exists():
        return {}
    try:
        import math
        from collections import defaultdict

        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            f"""
            SELECT player_id, pts, ast, reb, fg3m, stl, blk, rn
            FROM (
                SELECT player_id, pts, ast, reb, fg3m, stl, blk,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
                FROM player_game_logs
                WHERE player_id IN ({placeholders}) AND min >= 10
            ) sub
            WHERE rn <= 30
            """,
            player_ids,
        ).fetchall()
        conn.close()

        buckets: dict[str, list] = defaultdict(list)
        for row in rows:
            buckets[row[0]].append(row[1:])  # (pts, ast, reb, fg3m, stl, blk, rn)

        def _std(vals: list[float]) -> float:
            if len(vals) < 2:
                return 0.0
            m = sum(vals) / len(vals)
            return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

        def _weighted_mean(vals_with_rn: list[tuple]) -> float:
            # Exponential decay: most recent game (rn=1) has highest weight
            total_w, total_v = 0.0, 0.0
            for val, rn in vals_with_rn:
                w = 0.95 ** (rn - 1)
                total_w += w
                total_v += w * float(val)
            return total_v / total_w if total_w > 0 else 0.0

        def _cond_mean(stat_vals: list[float], pts_list: list[float]) -> float | None:
            # Average of stat in games where the player scored ≥ threshold.
            vals = [s for s, p in zip(stat_vals, pts_list) if p >= _BREAKOUT_THRESHOLD]
            return round(sum(vals) / len(vals), 1) if vals else None

        result: dict[str, dict] = {}
        for pid, games in buckets.items():
            cols = list(zip(*games))  # (pts, ast, reb, fg3m, stl, blk, rn)
            rn_list = [int(v) for v in cols[6]]
            pts_list = [float(v) for v in cols[0]]
            ast_list = [float(v) for v in cols[1]]
            reb_list = [float(v) for v in cols[2]]
            fg3m_list = [float(v) for v in cols[3]]
            stl_list = [float(v) for v in cols[4]]
            blk_list = [float(v) for v in cols[5]]
            pts_rn = list(zip(pts_list, rn_list))

            weighted_mean = _weighted_mean(pts_rn)
            season_mean = sum(pts_list) / len(pts_list) if pts_list else 0.0

            # ── Hot / Cold streak factor ──────────────────────────────────
            # Last 5 games (rn=1..5) vs the 30-game weighted mean.
            # Hot streak: scoring 15%+ above weighted mean → boost factor
            # Cold streak: scoring 15%+ below weighted mean → penalty factor
            # Scale: 15-25% off = mild, 25%+ = strong. Clamped [0.88, 1.12].
            last5_pts = [pts for pts, rn in zip(pts_list, rn_list) if rn <= 5]
            streak_factor = 1.0
            if last5_pts and weighted_mean > 0:
                last5_mean = sum(last5_pts) / len(last5_pts)
                pct_diff = (last5_mean - weighted_mean) / weighted_mean
                if pct_diff >= 0.25:
                    streak_factor = 1.12   # very hot
                elif pct_diff >= 0.15:
                    streak_factor = 1.07   # hot
                elif pct_diff <= -0.25:
                    streak_factor = 0.88   # very cold
                elif pct_diff <= -0.15:
                    streak_factor = 0.93   # cold

            # ── Personalised breakout threshold ───────────────────────────
            # Fixed 30-pt threshold is wrong for bench players and wrong for
            # superstars. Use 125% of weighted mean, floored at 25 pts.
            personal_breakout_threshold = max(25.0, round(weighted_mean * 1.25))

            # ── Bounce-back signal ────────────────────────────────────────
            # Elite players who scored significantly below their mean last game
            # historically respond with elevated output. This is a real pattern:
            # pride, film study, adjustments — stars don't go quiet two games in a row.
            # last game (rn=1) vs weighted mean:
            #   < -20% below mean → strong bounce-back signal (+35% breakout boost)
            #   < -12% below mean → mild bounce-back signal  (+20% breakout boost)
            last_game_pts = pts_list[0] if pts_list else weighted_mean
            bounce_back_mult = 1.0
            if weighted_mean > 0:
                last_game_pct = (last_game_pts - weighted_mean) / weighted_mean
                if last_game_pct <= -0.20:
                    bounce_back_mult = 1.35   # strongly below average → big bounce-back likely
                elif last_game_pct <= -0.12:
                    bounce_back_mult = 1.20   # mildly below average → moderate bounce-back

            result[pid] = {
                "pts_std":          round(_std(pts_list), 1),
                "ast_std":          round(_std(ast_list), 1),
                "reb_std":          round(_std(reb_list), 1),
                "fg3m_std":         round(_std(fg3m_list), 1),
                "stl_std":          round(_std(stl_list), 1),
                "blk_std":          round(_std(blk_list), 1),
                "breakout_pct":     round(
                    sum(1 for p in pts_list if p >= personal_breakout_threshold) / len(pts_list), 3
                ),
                "weighted_mean_pts":        round(weighted_mean, 1),
                "season_pts_per_game":      round(season_mean, 1),
                "streak_factor":            round(streak_factor, 3),
                "breakout_threshold":       personal_breakout_threshold,
                "bounce_back_mult":         round(bounce_back_mult, 3),
                # Conditional means: what they average on their own breakout nights
                "bo_mean_pts":  _cond_mean(pts_list, pts_list),
                "bo_mean_ast":  _cond_mean(ast_list, pts_list),
                "bo_mean_reb":  _cond_mean(reb_list, pts_list),
                "bo_mean_fg3m": _cond_mean(fg3m_list, pts_list),
                "bo_mean_stl":  _cond_mean(stl_list, pts_list),
                "bo_mean_blk":  _cond_mean(blk_list, pts_list),
            }
        return result
    except Exception:
        return {}


def _fetch_player_series_usage(player_ids: list[str], opp_abbr: str) -> dict[str, dict]:
    """
    Returns per-player stats in the current playoff series against opp_abbr.
    Used to detect usage shifts mid-series (e.g. star taking over after teammate injury).

    Keys per player_id: series_pts, series_ast, series_reb, series_games
    Only returns players who appear in at least 1 series game.
    """
    if not player_ids or not _DB_PATH.exists():
        return {}
    try:
        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            f"""
            SELECT player_id,
                   COUNT(DISTINCT game_id)  AS series_games,
                   AVG(pts)                 AS series_pts,
                   AVG(ast)                 AS series_ast,
                   AVG(reb)                 AS series_reb
            FROM player_game_logs
            WHERE player_id IN ({placeholders})
              AND opponent_abbreviation = ?
              AND season_type = 'Playoffs'
              AND season = (SELECT MAX(season) FROM player_game_logs)
            GROUP BY player_id
            HAVING COUNT(DISTINCT game_id) >= 1
            """,
            player_ids + [opp_abbr.upper()],
        ).fetchall()
        conn.close()
        return {
            r[0]: {
                "series_games": int(r[1]),
                "series_pts":   round(float(r[2]), 1),
                "series_ast":   round(float(r[3]), 1),
                "series_reb":   round(float(r[4]), 1),
            }
            for r in rows
        }
    except Exception:
        return {}


def _fetch_player_game_data(player_ids: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    """
    Returns (avg_min, play_prob) dicts keyed by player_id.
      avg_min   — average minutes over last 10 played games
      play_prob — games_played / team_total_games, clamped [0.25, 1.0]
    """
    if not player_ids or not _DB_PATH.exists():
        return {pid: 15.0 for pid in player_ids}, {pid: 1.0 for pid in player_ids}
    try:
        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))

        min_rows = conn.execute(
            f"""
            SELECT player_id, AVG(min) AS avg_min
            FROM (
                SELECT player_id, min,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
                FROM player_game_logs
                WHERE player_id IN ({placeholders}) AND min > 0
            ) sub
            WHERE rn <= 10
            GROUP BY player_id
            """,
            player_ids,
        ).fetchall()

        gp_rows = conn.execute(
            f"""
            SELECT
                p.player_id,
                COUNT(DISTINCT p.game_id)   AS gp,
                MAX(t.team_games)           AS team_games
            FROM player_game_logs p
            JOIN (
                SELECT team_abbreviation, COUNT(DISTINCT game_id) AS team_games
                FROM player_game_logs
                WHERE season = (SELECT MAX(season) FROM player_game_logs)
                GROUP BY team_abbreviation
            ) t ON t.team_abbreviation = p.team_abbreviation
            WHERE p.player_id IN ({placeholders})
              AND p.season = (SELECT MAX(season) FROM player_game_logs)
            GROUP BY p.player_id
            """,
            player_ids,
        ).fetchall()

        conn.close()

        avg_min: dict[str, float] = {r[0]: float(r[1]) for r in min_rows}
        play_prob: dict[str, float] = {}
        for r in gp_rows:
            pid, gp, team_games = r[0], int(r[1]), int(r[2])
            play_prob[pid] = max(0.25, min(1.0, gp / max(1, team_games)))

        for pid in player_ids:
            avg_min.setdefault(pid, 15.0)
            play_prob.setdefault(pid, 0.75)

        return avg_min, play_prob
    except Exception:
        return {pid: 15.0 for pid in player_ids}, {pid: 1.0 for pid in player_ids}


def _fetch_team_context(team_abbreviation: str) -> dict:
    """
    Returns team-level context from the DB:
      form_factor     — last-5 avg score / season avg score (clamped 0.93–1.07)
      is_b2b          — True if team played yesterday
      days_rest       — days since last game (0 = B2B, 1 = one day rest, etc.)
      rest_factor     — scoring multiplier based on days rest (0 days=-3%, 3+days=+1%)
      road_trip_games — consecutive away games (fatigue builds after 3+)
      road_fatigue    — penalty applied for extended road trips
      motivation      — 0.0-1.0 score based on playoff race position
      motivation_factor — pts adjustment based on motivation (max ±3 pts)
    """
    result = {
        "form_factor": 1.0,
        "is_b2b": False,
        "days_rest": 2,
        "rest_factor": 1.0,
        "road_trip_games": 0,
        "road_fatigue": 0.0,
        "motivation": 0.5,
        "motivation_factor": 0.0,
    }
    if not _DB_PATH.exists():
        return result
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        season_row = conn.execute(
            "SELECT MAX(season) FROM player_game_logs"
        ).fetchone()
        season = season_row[0] if season_row else None

        if season:
            # Recent 5 games: sum pts per game for this team
            recent = conn.execute(
                """
                SELECT game_id, SUM(pts) AS team_score, MAX(game_date) AS gdate,
                       MAX(matchup) AS matchup
                FROM player_game_logs
                WHERE team_abbreviation = ? AND season = ?
                GROUP BY game_id
                ORDER BY gdate DESC
                LIMIT 10
                """,
                (team_abbreviation.upper(), season),
            ).fetchall()

            # Season average team score
            season_avg_row = conn.execute(
                """
                SELECT AVG(team_score) FROM (
                    SELECT game_id, SUM(pts) AS team_score
                    FROM player_game_logs
                    WHERE team_abbreviation = ? AND season = ?
                      AND season_type = 'Regular Season'
                    GROUP BY game_id
                )
                """,
                (team_abbreviation.upper(), season),
            ).fetchone()

            if recent and season_avg_row and season_avg_row[0]:
                recent5 = recent[:5]
                recent_avg = sum(r[1] for r in recent5) / len(recent5)
                season_avg = float(season_avg_row[0])
                raw_factor = recent_avg / max(season_avg, 1)
                result["form_factor"] = max(0.93, min(1.07, raw_factor))

                # ── Rest days ─────────────────────────────────────────────────
                today = date.today()
                yesterday = (today - timedelta(days=1)).isoformat()
                last_game_date = str(recent[0][2])[:10] if recent else ""
                result["is_b2b"] = last_game_date == yesterday

                if last_game_date:
                    try:
                        last_dt = date.fromisoformat(last_game_date)
                        days_rest = (today - last_dt).days
                        result["days_rest"] = days_rest
                        # Rest factor: 0 days = -3%, 1 day = -1%, 2 days = 0%,
                        # 3+ days = +1% (well rested but can be rusty above 5)
                        if days_rest == 0:
                            result["rest_factor"] = 0.97
                        elif days_rest == 1:
                            result["rest_factor"] = 0.99
                        elif days_rest == 2:
                            result["rest_factor"] = 1.0
                        elif days_rest == 3:
                            result["rest_factor"] = 1.01
                        else:  # 4+ days — can get rusty
                            result["rest_factor"] = 1.005
                    except ValueError:
                        pass

                # ── Road trip fatigue ─────────────────────────────────────────
                # Count consecutive away games (matchup contains "@" on road)
                road_streak = 0
                for row in recent:
                    matchup = str(row[3] or "")
                    # Away games have matchup like "LAL @ OKC" (team @ opponent)
                    is_away = "@" in matchup and not matchup.startswith(team_abbreviation.upper())
                    if is_away:
                        road_streak += 1
                    else:
                        break  # home game breaks the streak

                result["road_trip_games"] = road_streak
                # Penalty kicks in after 3 consecutive road games
                if road_streak >= 5:
                    result["road_fatigue"] = -2.5   # brutal road trip
                elif road_streak >= 3:
                    result["road_fatigue"] = -1.5   # noticeable fatigue
                elif road_streak == 2:
                    result["road_fatigue"] = -0.5   # mild fatigue
                else:
                    result["road_fatigue"] = 0.0

                # ── Motivation index ──────────────────────────────────────────
                # Based on win rate in last 15 games vs season win rate.
                # A team on a hot streak fighting for seeding = high motivation.
                # A team already eliminated or locked in = low motivation.
                recent15 = conn.execute(
                    """
                    SELECT game_id, SUM(pts) AS team_pts, MAX(game_date) AS gdate
                    FROM player_game_logs
                    WHERE team_abbreviation = ? AND season = ?
                      AND season_type = 'Regular Season'
                    GROUP BY game_id
                    ORDER BY gdate DESC
                    LIMIT 15
                    """,
                    (team_abbreviation.upper(), season),
                ).fetchall()

                season_games_row = conn.execute(
                    """
                    SELECT COUNT(DISTINCT game_id)
                    FROM player_game_logs
                    WHERE team_abbreviation = ? AND season = ?
                      AND season_type = 'Regular Season'
                    """,
                    (team_abbreviation.upper(), season),
                ).fetchone()

                season_games = season_games_row[0] if season_games_row else 0

                # Win rate in last 15 vs season — delta signals motivation
                if len(recent15) >= 5 and season_games > 0:
                    # Use scoring differential as a win proxy (no W/L in logs)
                    recent_avg15 = sum(r[1] for r in recent15) / len(recent15)
                    momentum_delta = (recent_avg15 - season_avg) / max(season_avg, 1)
                    # Late season (>60 games played) amplifies motivation signal
                    late_season_mult = 1.3 if season_games > 60 else 1.0
                    raw_motivation = 0.5 + (momentum_delta * 2.0 * late_season_mult)
                    motivation = max(0.1, min(0.9, raw_motivation))
                    result["motivation"] = motivation
                    # Convert to pts: range -3 to +3
                    result["motivation_factor"] = round((motivation - 0.5) * 6.0, 1)

        conn.close()
    except Exception:
        pass
    return result


_HCA_CACHE: dict[str, dict] = {}

def _fetch_team_home_away_factor(team_abbr: str) -> dict:
    """
    Computes team-specific home court advantage from actual DB performance.
    Different teams benefit differently at home — MIL gets a massive lift,
    OKC gets a moderate offensive boost but stronger crowd-driven defense,
    some teams (MIN, CHI) actually perform worse at home.

    Returns:
        home_off  — offensive multiplier when playing at home  (e.g. 1.020)
        away_off  — offensive multiplier when playing away     (e.g. 0.980)
        home_def  — how much weaker opponent scores at this arena (ratio < 1 = tougher D)
    All values are clamped to reasonable bounds to prevent outliers corrupting predictions.
    """
    defaults = {"home_off": 1.012, "away_off": 0.988, "home_def": 0.993}
    ta = team_abbr.upper()
    if ta in _HCA_CACHE:
        return _HCA_CACHE[ta]
    if not _DB_PATH.exists():
        return defaults
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA query_only = ON")

        # Team's own scoring: home vs away pts/game
        off_row = conn.execute("""
            SELECT
                AVG(CASE WHEN home_away='H' THEN team_pts END),
                AVG(CASE WHEN home_away='A' THEN team_pts END),
                AVG(team_pts)
            FROM (
                SELECT game_id, home_away, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE team_abbreviation = ?
                  AND season_type = 'Regular Season'
                  AND season IN (SELECT DISTINCT season FROM player_game_logs
                                 ORDER BY season DESC LIMIT 2)
                GROUP BY game_id, home_away
            )
        """, (ta,)).fetchone()

        # Opponent scoring at this team's home vs away — avoid slow self-join.
        # When this team is HOME, opponents play AWAY (home_away='A' for opponent)
        # When this team is AWAY, opponents play HOME (home_away='H' for opponent)
        # We find opponents by querying where opponent_abbreviation = this team.
        def_row = conn.execute("""
            SELECT
                AVG(CASE WHEN home_away='A' THEN game_pts END),
                AVG(CASE WHEN home_away='H' THEN game_pts END)
            FROM (
                SELECT game_id, home_away, SUM(pts) AS game_pts
                FROM player_game_logs
                WHERE opponent_abbreviation = ?
                  AND season_type = 'Regular Season'
                  AND season IN (SELECT DISTINCT season FROM player_game_logs
                                 ORDER BY season DESC LIMIT 2)
                GROUP BY game_id, home_away
            )
        """, (ta,)).fetchone()
        conn.close()

        result = dict(defaults)
        result["home_pts_lift"] = 1.65  # fallback = league avg

        if off_row and off_row[2] and off_row[0] and off_row[1]:
            home_pts, away_pts, overall = float(off_row[0]), float(off_row[1]), float(off_row[2])
            # Clamp: max 2% boost at home, max 2% penalty away (conservative)
            result["home_off"] = max(1.000, min(1.020, home_pts / overall))
            result["away_off"] = max(0.980, min(1.000, away_pts / overall))
            # Flat pts lift: actual home scoring - actual away scoring (team-specific HCA)
            result["home_pts_lift"] = round(home_pts - away_pts, 2)

        if def_row and def_row[0] and def_row[1]:
            home_opp, away_opp = float(def_row[0]), float(def_row[1])
            if away_opp > 0:
                # home_def < 1 means opponents score less at this arena (tougher home D)
                result["home_def"] = max(0.985, min(1.005, home_opp / away_opp))

        _HCA_CACHE[ta] = result
        return result
    except Exception:
        return defaults


def _fetch_h2h_factor(team_abbr: str, opp_abbr: str) -> float:
    """
    Returns a flat pts adjustment based on historical head-to-head performance
    between these two teams over the last 3 seasons.

    Logic:
      - Pull all games where team_abbr played opp_abbr
      - Calculate team's avg score vs opp vs team's overall season avg
      - Delta = how much better/worse this team scores against this specific opponent
      - Clamped to [-4, +4] pts so one outlier matchup can't dominate

    Examples:
      SAS historically holds OKC to fewer pts → OKC gets -2 vs SAS
      NYK always scores well vs CLE → NYK gets +2 vs CLE
    """
    if not _DB_PATH.exists():
        return 0.0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        ta = team_abbr.upper()
        oa = opp_abbr.upper()

        # Get team's avg score specifically against this opponent (last 3 seasons)
        h2h_rows = conn.execute(
            """
            SELECT game_id, SUM(pts) AS team_score
            FROM player_game_logs
            WHERE team_abbreviation = ?
              AND matchup LIKE ?
            GROUP BY game_id
            ORDER BY MAX(game_date) DESC
            LIMIT 20
            """,
            (ta, f"%{oa}%"),
        ).fetchall()

        # Get team's overall season avg for comparison baseline
        season_avg_row = conn.execute(
            """
            SELECT AVG(team_score) FROM (
                SELECT game_id, SUM(pts) AS team_score
                FROM player_game_logs
                WHERE team_abbreviation = ?
                  AND season >= (SELECT MAX(season) FROM player_game_logs) - 2
                GROUP BY game_id
            )
            """,
            (ta,),
        ).fetchone()

        conn.close()

        if not h2h_rows or not season_avg_row or not season_avg_row[0]:
            return 0.0

        h2h_avg = sum(r[1] for r in h2h_rows) / len(h2h_rows)
        season_avg = float(season_avg_row[0])
        delta = h2h_avg - season_avg

        # Clamp to [-4, +4] — H2H is a modifier, not the whole story
        return round(max(-4.0, min(4.0, delta)), 1)

    except Exception:
        return 0.0


def _detect_coach_adjustment(
    team_abbr: str,
    series_eff: dict | None,
    series_deficit: int,
    is_elimination: bool,
) -> float:
    """
    Detects in-series coaching tactical adjustments and returns a flat pts modifier.

    Logic:
      - Compares team's 3PM rate and scoring in the current series vs their
        regular season baseline from the training DB.
      - If a LOSING team has significantly changed their shot profile (3PM up ≥ 1.0)
        they've gone more aggressive → small scoring boost (+1.0 to +1.5 pts).
      - If a LOSING team is scoring much less than RS baseline in the series,
        the opponent's defensive adjustment is working → small extra penalty (-1.0 pts).
      - Winning teams who are outperforming their RS avg → small extra confidence boost.
      - Clamped to [-1.5, +1.5] so it's a refinement, not a driver.

    Examples:
      NYK in playoffs suddenly jacking 3s after losing 2 straight → +1.0
      SAS scoring 12 fewer pts/game vs their RS avg while down 1-2 → −1.0
    """
    if not series_eff or not _DB_PATH.exists():
        return 0.0

    games_played = series_eff.get("games_played", 0)
    if games_played < 2:
        return 0.0  # Need at least 2 games of series evidence

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        ta = team_abbr.upper()

        # Fetch team's regular season baseline (current + last season)
        rs_row = conn.execute(
            """
            SELECT AVG(team_pts), AVG(team_fg3m)
            FROM (
                SELECT game_id,
                       SUM(pts)  AS team_pts,
                       SUM(fg3m) AS team_fg3m
                FROM player_game_logs
                WHERE team_abbreviation = ?
                  AND season_type = 'Regular Season'
                  AND season >= (SELECT MAX(season) FROM player_game_logs) - 1
                GROUP BY game_id
            )
            """,
            (ta,),
        ).fetchone()
        conn.close()

        if not rs_row or not rs_row[0]:
            return 0.0

        rs_pts  = float(rs_row[0])
        rs_fg3m = float(rs_row[1] or 0.0)

        series_pts  = series_eff.get("pts_per_game", 0.0)
        series_fg3m = series_eff.get("fg3m_per_game", 0.0)

        is_losing = series_deficit > 0 or is_elimination
        pts_delta  = series_pts - rs_pts
        fg3m_delta = series_fg3m - rs_fg3m

        adjustment = 0.0

        if is_losing:
            # Losing team pivoted to 3pt heavy game — desperation or real adjustment?
            # Both are real signal: they're trying something different
            if fg3m_delta >= 1.0:
                # Coach opened up the 3pt game — offensive adaptation
                adjustment += min(1.5, fg3m_delta * 0.5)

            # Losing team scoring far below their RS average — opp defense working
            if pts_delta <= -8.0:
                adjustment -= 1.0
            elif pts_delta <= -5.0:
                adjustment -= 0.5
        else:
            # Winning team: if they're outperforming RS avg, defensive gameplan is working
            if pts_delta >= 5.0:
                adjustment += 0.5  # small continuation bonus

        # Clamp hard — this is a refinement signal, not a primary driver
        return round(max(-1.5, min(1.5, adjustment)), 1)

    except Exception:
        return 0.0


def _fetch_series_record(home_abbr: str, away_abbr: str) -> tuple[int, int]:
    """
    Returns (home_wins, away_wins) by comparing per-game scores in the playoff series.
    Used to detect elimination games, closeout attempts, and high-stakes deficits.
    """
    if not _DB_PATH.exists():
        return 0, 0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        ta, oa = home_abbr.upper(), away_abbr.upper()
        rows = conn.execute(
            """
            SELECT h.game_id, h.team_pts, a.team_pts
            FROM (
                SELECT game_id, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE season_type = 'Playoffs'
                  AND team_abbreviation = ? AND opponent_abbreviation = ?
                GROUP BY game_id
            ) h
            JOIN (
                SELECT game_id, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE season_type = 'Playoffs'
                  AND team_abbreviation = ? AND opponent_abbreviation = ?
                GROUP BY game_id
            ) a ON h.game_id = a.game_id
            """,
            (ta, oa, oa, ta),
        ).fetchall()
        conn.close()
        home_wins = sum(1 for _, h, a in rows if h > a)
        away_wins = sum(1 for _, h, a in rows if a > h)
        return home_wins, away_wins
    except Exception:
        return 0, 0


def _fetch_series_team_efficiency(team_abbr: str, opp_abbr: str) -> dict:
    """
    Returns series-specific team performance metrics aggregated from actual box scores.
    Used to supplement/replace season-long ratings with in-series evidence.

    Keys: games_played, pts_per_game, tov_per_game, reb_per_game, fg3m_per_game,
          pts_allowed_per_game (opponent scoring against this team in the series).
    """
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        ta = team_abbr.upper()
        oa = opp_abbr.upper()

        rows = conn.execute(
            """
            SELECT game_id,
                   SUM(pts) AS team_pts,
                   SUM(tov) AS team_tov,
                   SUM(reb) AS team_reb,
                   SUM(fg3m) AS team_fg3m
            FROM player_game_logs
            WHERE season_type = 'Playoffs'
              AND team_abbreviation = ?
              AND opponent_abbreviation = ?
            GROUP BY game_id
            ORDER BY MAX(game_date) DESC
            """,
            (ta, oa),
        ).fetchall()

        # Opponent's pts scored against this team (= pts this team allowed)
        opp_rows = conn.execute(
            """
            SELECT game_id, SUM(pts) AS opp_pts
            FROM player_game_logs
            WHERE season_type = 'Playoffs'
              AND team_abbreviation = ?
              AND opponent_abbreviation = ?
            GROUP BY game_id
            """,
            (oa, ta),
        ).fetchall()
        conn.close()

        if not rows:
            return {}

        n = len(rows)
        # ── Recency weighting ──────────────────────────────────────────────
        # Rows are ordered DESC (most recent first). Recent games matter more:
        # G_most_recent gets weight n, G_next gets weight n-1, ..., G_oldest gets 1.
        # For 3 games: G3 weight=3, G2 weight=2, G1 weight=1 → G3 counts 3× G1.
        # This surfaces the real trend (e.g. OKC winning by 7, 9, 15 in series)
        # rather than averaging in a stale early-series result at equal weight.
        weights = list(range(n, 0, -1))   # [n, n-1, ..., 1] — most recent first
        total_w = sum(weights)

        def _wavg(vals: list) -> float:
            return sum(v * w for v, w in zip(vals, weights)) / total_w

        result = {
            "games_played":  n,
            "pts_per_game":  round(_wavg([r[1] for r in rows]), 1),
            "tov_per_game":  round(_wavg([r[2] for r in rows]), 1),
            "reb_per_game":  round(_wavg([r[3] for r in rows]), 1),
            "fg3m_per_game": round(_wavg([r[4] for r in rows]), 1),
        }
        if opp_rows:
            # Match opp_rows to same game order as rows for correct recency weighting
            opp_by_game = {r[0]: r[1] for r in opp_rows}
            opp_pts_ordered = [opp_by_game.get(r[0], 0) for r in rows]
            result["pts_allowed_per_game"] = round(_wavg(opp_pts_ordered), 1)
        return result
    except Exception:
        return {}


def _series_win_prob(w: int, l: int, memo: dict | None = None) -> float:
    """
    P(team wins best-of-7 series) from state (w wins, l losses),
    assuming each individual game is 50/50.
    Computed recursively with memoization.
    """
    if memo is None:
        memo = {}
    if w == 4:
        return 1.0
    if l == 4:
        return 0.0
    if (w, l) in memo:
        return memo[(w, l)]
    result = 0.5 * _series_win_prob(w + 1, l, memo) + 0.5 * _series_win_prob(w, l + 1, memo)
    memo[(w, l)] = result
    return result


def _compute_series_intensity(team_wins: int, opp_wins: int, is_playoffs: bool) -> float:
    """
    Returns a flat pts boost/penalty based on series position, using combinatorial
    game leverage rather than hardcoded constants.

    Formula:
        leverage      = P(win series | win game) − P(win series | lose game)
        series_win_p  = P(win series from current state)   [recursive, 50/50 per game]

    Trailing team (desperate):  motivation = leverage × series_win_p × 1.5  → × 32
    Leading team  (focused):    motivation = leverage × (1−series_win_p) × 0.6 → × 40

    Normalisation constants calibrated so that:
        2-3 elimination  →  +6.0 pts  (max trailing desperation)
        3-2 closeout     →  +3.0 pts  (max leading focus)
        0-3 facing sweep →  −2.0 pts  (demoralization penalty)
        1-3 elimination  →  +1.5 pts  (some hope, still fighting)
        Tied games       →   0.0 pts  (no directional modifier)
    """
    if not is_playoffs:
        return 0.0

    # Special: facing sweep — team has mentally checked out
    if opp_wins == 3 and team_wins == 0:
        return -2.0

    memo: dict = {}
    series_win_p = _series_win_prob(team_wins, opp_wins, memo)
    leverage = (
        _series_win_prob(team_wins + 1, opp_wins, memo)
        - _series_win_prob(team_wins, opp_wins + 1, memo)
    )
    leverage = max(0.0, leverage)

    if opp_wins > team_wins:
        # Trailing team — scale desperation by whether it's elimination or just trailing
        role_mult = 1.5 if opp_wins == 3 else 0.4
        motivation = leverage * series_win_p * role_mult
        return round(min(motivation * 32.0, 7.0), 1)

    if team_wins > opp_wins:
        # Leading team — professional focus, not desperate
        motivation = leverage * (1.0 - series_win_p) * 0.6
        return round(min(motivation * 40.0, 5.0), 1)

    # Tied — no directional intensity modifier
    return 0.0


def _compute_flat_hca(team_hca: dict | None, is_home: bool, is_playoffs: bool) -> float:
    """
    Data-driven home court advantage as a flat pts bonus.

    Uses each team's actual home/away scoring differential (stored in team_hca
    as 'home_pts_lift'), regressed 30% toward the league mean to reduce schedule
    noise, then scaled up 25% for playoffs (louder crowds, higher stakes).

    Returns a positive value for home teams, negative for away teams.
    """
    LEAGUE_AVG_HCA = 1.65   # observed from DB: average (home_ppg − away_ppg) across all teams
    REGRESSION     = 0.70   # 70% own data, 30% league mean — smooths out schedule variance
    PLAYOFF_SCALE  = 1.25   # playoffs amplify home court by ~25%

    raw_lift = (team_hca or {}).get("home_pts_lift", LEAGUE_AVG_HCA)
    regressed = raw_lift * REGRESSION + LEAGUE_AVG_HCA * (1.0 - REGRESSION)
    final = regressed * (PLAYOFF_SCALE if is_playoffs else 1.0)
    # Clamp: no team should get more than +6 or less than -4 from pure HCA
    final = max(-4.0, min(6.0, final))
    return final if is_home else -final


def _fetch_series_participants(home_abbr: str, away_abbr: str) -> dict[str, float]:
    """
    Returns {player_id: avg_series_minutes} for every player who appeared in
    at least one game of the current playoff series between home_abbr and away_abbr.
    Players not in this dict did not play and should have near-zero play probability.
    """
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            """
            SELECT player_id, AVG(min) AS avg_min
            FROM player_game_logs
            WHERE season_type = 'Playoffs'
              AND team_abbreviation IN (?, ?)
              AND opponent_abbreviation IN (?, ?)
              AND min > 0
            GROUP BY player_id
            """,
            (home_abbr, away_abbr, home_abbr, away_abbr),
        ).fetchall()
        conn.close()
        return {str(r[0]): float(r[1]) for r in rows}
    except Exception:
        return {}


def _fetch_series_ot_scoring_avgs(
    home_abbr: str,
    away_abbr: str,
) -> tuple[float | None, float | None]:
    """
    Returns (home_avg, away_avg) — the per-game scoring averages for each team
    in games played at the HOME team's arena in this playoff series.

    Used to anchor OT simulation to actual playoff series pace/scoring rather
    than regular-season ratings, which significantly overstate scoring pace.

    Falls back to overall series average if fewer than 2 home games exist,
    and to None if no series data is available at all (caller uses offRtg formula).
    """
    if not _DB_PATH.exists():
        return None, None
    try:
        conn = sqlite3.connect(str(_DB_PATH))

        # Identify which home_away values correspond to the home team being at home
        # home_abbr plays 'H'/'home' in their home games
        rows = conn.execute(
            """
            SELECT g.game_id,
                   MAX(CASE WHEN g.team_abbreviation = ? THEN g.team_pts END) AS home_pts,
                   MAX(CASE WHEN g.team_abbreviation = ? THEN g.team_pts END) AS away_pts,
                   MAX(CASE WHEN g.team_abbreviation = ? THEN g.home_away END) AS home_loc
            FROM (
                SELECT game_id, team_abbreviation, home_away, SUM(pts) AS team_pts
                FROM player_game_logs
                WHERE season_type = 'Playoffs'
                  AND team_abbreviation IN (?, ?)
                  AND opponent_abbreviation IN (?, ?)
                GROUP BY game_id, team_abbreviation
            ) g
            GROUP BY g.game_id
            """,
            (home_abbr, away_abbr, home_abbr,
             home_abbr, away_abbr, home_abbr, away_abbr),
        ).fetchall()
        conn.close()

        # Filter to games played at home_abbr's arena
        home_games = [
            r for r in rows
            if r[1] is not None and r[2] is not None
            and str(r[3] or "").upper() in ("H", "HOME")
        ]

        if len(home_games) >= 2:
            avg_h = sum(float(r[1]) for r in home_games) / len(home_games)
            avg_a = sum(float(r[2]) for r in home_games) / len(home_games)
            return avg_h, avg_a

        # Fallback: overall series average
        all_games = [r for r in rows if r[1] is not None and r[2] is not None]
        if all_games:
            avg_h = sum(float(r[1]) for r in all_games) / len(all_games)
            avg_a = sum(float(r[2]) for r in all_games) / len(all_games)
            return avg_h, avg_a

        return None, None
    except Exception:
        return None, None


def _usage_boost(projections: list, avg_min: dict, play_prob: dict) -> float:
    """
    When DNP players held a share of projected pts, boost remaining active players.
    Capped at 1.25× to prevent over-inflation.
    """
    dnp = [p for p in projections if p.availability_status == "dnp"]
    active = [p for p in projections if p.availability_status != "dnp"]
    if not dnp or not active:
        return 1.0
    dnp_pts = sum(p.projected_stats.mean.points for p in dnp)
    active_pts = sum(p.projected_stats.mean.points for p in active)
    if active_pts < 1.0:
        return 1.0
    return min(1.18, (active_pts + dnp_pts) / active_pts)


def _rescale_player_pts(proj: PlayerProjection, scale: float) -> PlayerProjection:
    """Rescale a player's projected points (mean/low/high) by the team calibration factor."""
    if proj.availability_status == "dnp" or abs(scale - 1.0) < 0.001:
        return proj

    def _scale_line(line: StatLine) -> StatLine:
        return line.model_copy(update={"points": round(line.points * scale, 1)})

    new_band = ConfidenceBand(
        low=_scale_line(proj.projected_stats.low),
        mean=_scale_line(proj.projected_stats.mean),
        high=_scale_line(proj.projected_stats.high),
    )
    return proj.model_copy(update={"projected_stats": new_band})


def _compute_blowout_bonus(
    series_eff: dict | None,
    opp_is_b2b: bool,
    game_pace: float,
    opp_def_rating: float,
) -> float:
    """
    Extra scoring bonus/penalty when multiple blowout signals corroborate.

    Signals:
      1. Extreme series dominance (margin ≥ 10 pts over 2+ games)
      2. Opponent on a back-to-back (tired legs → give up more pts)
      3. Fast pace + weak opponent defense (scoring explosion conditions)

    Single signals are halved to avoid false positives.
    Two or more signals get full weight.
    Total capped at ±9 pts to prevent overcorrection.
    """
    signals: list[float] = []

    # Signal 1: Extreme series dominance
    if series_eff and series_eff.get("games_played", 0) >= 2:
        pts     = series_eff.get("pts_per_game", 0.0)
        allowed = series_eff.get("pts_allowed_per_game", 0.0)
        if pts > 0 and allowed > 0:
            margin = pts - allowed
            if abs(margin) >= 10:
                # Linear below 10, steeper above 10 to capture compounding blowouts
                raw = (abs(margin) - 8) * 0.6
                signals.append(min(5.0, raw) if margin > 0 else -min(5.0, raw))

    # Signal 2: Opponent on B2B — we score more when they are tired
    # (our own B2B fatigue is already applied via the 3% penalty above)
    if opp_is_b2b:
        signals.append(3.0)

    # Signal 3: Fast game vs weak defense → scoring above the pace model ceiling
    if game_pace > 100 and opp_def_rating > 117:
        extra = (game_pace - 100) * 0.20 + (opp_def_rating - 117) * 0.15
        signals.append(min(3.0, extra))

    if not signals:
        return 0.0

    total = sum(signals)
    if len(signals) == 1:
        # Single signal: apply at half-strength (not enough corroboration)
        total *= 0.5

    return round(max(-9.0, min(9.0, total)), 1)


def _compute_blowout_info(
    home_total: int,
    away_total: int,
    home_series_eff: dict,
    away_series_eff: dict,
    home_is_b2b: bool,
    away_is_b2b: bool,
    home_off_rtg: float,
    away_off_rtg: float,
    home_def_rtg: float,
    away_def_rtg: float,
    home_pace: float,
    away_pace: float,
    is_playoffs: bool,
    home_abbr: str,
    away_abbr: str,
) -> dict:
    """
    Runs INDEPENDENTLY of the base prediction — never changes home_total / away_total.

    Checks four blowout signals:
      1. Series dominance  — one team winning by 10+ pts/game over 2+ playoff games
      2. Rest mismatch     — one team on B2B while the opponent is fully rested
      3. Rating mismatch   — off_rating vs opp_def_rating gap exceeds 10 pts
      4. Pace explosion    — fast combined pace (>100) vs weak opponent defense (>116)

    Returns a dict:
      is_blowout  — True when 2+ signals fire AND extra_margin >= 8 pts
      home        — amplified home score (if blowout)
      away        — amplified away score (if blowout)
      signals     — list of human-readable signal strings
    """
    signals: list[str] = []
    home_bonus = 0.0  # positive = home blowout candidate, negative = away
    away_bonus = 0.0

    game_pace = (home_pace + away_pace) / 2.0

    # ── Signal 1: Series dominance (playoffs, 2+ games) ─────────────────
    if is_playoffs:
        for eff, label, is_home_team in [
            (home_series_eff, home_abbr, True),
            (away_series_eff, away_abbr, False),
        ]:
            if eff and eff.get("games_played", 0) >= 2:
                pts     = eff.get("pts_per_game", 0.0)
                allowed = eff.get("pts_allowed_per_game", 0.0)
                if pts > 0 and allowed > 0:
                    margin = pts - allowed
                    if margin >= 10:
                        bonus = min(7.0, (margin - 8) * 0.55)
                        signals.append(
                            f"{label.upper()} series dominance: +{margin:.0f} pts/game avg"
                        )
                        if is_home_team:
                            home_bonus += bonus
                        else:
                            away_bonus += bonus

    # ── Signal 2: Rest mismatch ─────────────────────────────────────────
    if home_is_b2b and not away_is_b2b:
        signals.append(f"{home_abbr.upper()} on back-to-back — {away_abbr.upper()} fully rested")
        away_bonus += 4.5  # away benefits
    elif away_is_b2b and not home_is_b2b:
        signals.append(f"{away_abbr.upper()} on back-to-back — {home_abbr.upper()} fully rested")
        home_bonus += 4.5  # home benefits

    # ── Signal 3: Offensive vs defensive rating gap ──────────────────────
    home_rtg_gap = home_off_rtg - away_def_rtg   # positive = home offence >> away D
    away_rtg_gap = away_off_rtg - home_def_rtg   # positive = away offence >> home D
    if home_rtg_gap > 10:
        bonus = min(4.0, (home_rtg_gap - 10) * 0.40)
        signals.append(
            f"{home_abbr.upper()} elite offense ({home_off_rtg:.0f}) vs weak {away_abbr.upper()} defense ({away_def_rtg:.0f})"
        )
        home_bonus += bonus
    if away_rtg_gap > 10:
        bonus = min(4.0, (away_rtg_gap - 10) * 0.40)
        signals.append(
            f"{away_abbr.upper()} elite offense ({away_off_rtg:.0f}) vs weak {home_abbr.upper()} defense ({home_def_rtg:.0f})"
        )
        away_bonus += bonus

    # ── Signal 4: Pace explosion ─────────────────────────────────────────
    if game_pace > 100:
        if away_def_rtg > 116:
            bonus = min(3.0, (game_pace - 100) * 0.20 + (away_def_rtg - 116) * 0.15)
            signals.append(f"Fast pace ({game_pace:.0f} poss) + weak {away_abbr.upper()} defense ({away_def_rtg:.0f} Drtg)")
            home_bonus += bonus
        if home_def_rtg > 116:
            bonus = min(3.0, (game_pace - 100) * 0.20 + (home_def_rtg - 116) * 0.15)
            signals.append(f"Fast pace ({game_pace:.0f} poss) + weak {home_abbr.upper()} defense ({home_def_rtg:.0f} Drtg)")
            away_bonus += bonus

    # ── Determine blowout direction ──────────────────────────────────────
    # Only fire when 2+ distinct signals are present
    net = home_bonus - away_bonus
    extra_margin = abs(net)

    if len(signals) < 2 or extra_margin < 8:
        return {"is_blowout": False, "home": home_total, "away": away_total, "signals": signals}

    # Amplify the existing prediction — winner gets 60% of extra margin, loser loses 40%
    if net > 0:
        # Home blowout
        blowout_home = home_total + round(extra_margin * 0.60)
        blowout_away = away_total - round(extra_margin * 0.40)
    else:
        # Away blowout
        blowout_home = home_total - round(extra_margin * 0.40)
        blowout_away = away_total + round(extra_margin * 0.60)

    return {
        "is_blowout": True,
        "home": blowout_home,
        "away": blowout_away,
        "signals": signals,
    }


def _run_ot_simulation(
    game_id: str,
    home_total: int,
    away_total: int,
    home_projections: list,
    away_projections: list,
    *,
    home_off_rtg: float = 110.0,
    home_def_rtg: float = 110.0,
    away_off_rtg: float = 110.0,
    away_def_rtg: float = 110.0,
    home_pace: float = 98.0,
    away_pace: float = 98.0,
    home_series_wins: int = 0,
    away_series_wins: int = 0,
    home_series_avg: float | None = None,
    away_series_avg: float | None = None,
) -> OTSimulation:
    """
    Simulates a hypothetical 5-minute NBA overtime period when the predicted
    regulation margin is ≤ 2 pts.

    Scoring model — series-first, offRtg fallback:
        Primary: if actual home-game scoring averages for this series are available,
          base_mu = series_avg × (5 / 48)
          This uses real playoff pace and intensity rather than regular-season ratings,
          which significantly overstate scoring and pace in playoff settings.
        Fallback: if no series data exists (early in a series / pre-season),
          base_mu = (avg_pace × 5/48) × (offRtg/100) × (league_avg_defRtg/opp_defRtg)

        Adjustments (applied on top of whichever base is used):
          · Net-rating gap  — stronger team scores slightly more in crunch time
          · Series edge     — team leading the series is battle-hardened (+0.2 pts/win diff)
          · HCA             — home court holds in OT, though smaller than regulation (+0.5 pts)
        std dev ≈ 18 % of μ (Poisson-inspired overdispersion), floored at 1.2

    Tiebreaker (if OT scores match after rounding):
        The team with the better net-rating + series edge wins rather than
        blindly favouring home — if the visitor is clearly superior they deserve
        the edge.

    Seeded by game_id hash so the same game always produces the same scenario
    (deterministic across page loads / refreshes).

    Player attribution:
        Top 4 active players by projected pts (usage-weighted closers) split OT
        pts proportionally to their projected scoring share, reflecting that stars
        dominate the ball in crunch time.
    """
    import hashlib
    import random

    # ── Deterministic seed ────────────────────────────────────────────────────
    seed = int(hashlib.md5(game_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # ── Base expected OT score ────────────────────────────────────────────────
    # Prefer actual playoff series scoring averages — these already bake in
    # real playoff pace, defensive intensity, and fatigue.
    # Fall back to the offRtg × possession model only when series data is absent.
    if home_series_avg is not None and away_series_avg is not None:
        # Scale 48-min series average down to a 5-min OT period
        base_home_mu = home_series_avg * (5.0 / 48.0)
        base_away_mu = away_series_avg * (5.0 / 48.0)
    else:
        # Fallback: possession-based model using regular-season ratings
        avg_pace    = (home_pace + away_pace) / 2.0
        possessions = avg_pace * 5.0 / 48.0
        base_home_mu = possessions * (home_off_rtg / 100.0) * (_LEAGUE_AVG_DEF_RTG / away_def_rtg)
        base_away_mu = possessions * (away_off_rtg / 100.0) * (_LEAGUE_AVG_DEF_RTG / home_def_rtg)

    # ── Team-strength adjustments ─────────────────────────────────────────────
    home_net = home_off_rtg - home_def_rtg   # positive = good team
    away_net = away_off_rtg - away_def_rtg
    net_diff = home_net - away_net           # positive = home is the stronger side

    # Series edge: each win in the series represents proven clutch performance.
    # A team up 3-2 has closed more tight games than the other side.
    series_diff = home_series_wins - away_series_wins  # positive = home leads

    # Composed adjustments (small — OT is inherently high-variance)
    #   net-rating gap:  ±0.04 pts per rating point of differential
    #   series edge:     ±0.20 pts per win ahead in the series
    #   HCA in OT:       +0.50 pts for the home team (real but diminished vs regulation)
    home_mu = base_home_mu + net_diff * 0.04 + series_diff * 0.20 + 0.50
    away_mu = base_away_mu - net_diff * 0.04 - series_diff * 0.20

    # ── Variance ──────────────────────────────────────────────────────────────
    home_sigma = max(1.2, home_mu * 0.18)
    away_sigma = max(1.2, away_mu * 0.18)

    home_ot = max(2, round(rng.gauss(home_mu, home_sigma)))
    away_ot = max(2, round(rng.gauss(away_mu, away_sigma)))

    # ── Tiebreaker — favour the objectively stronger side ────────────────────
    if home_ot == away_ot:
        # Composite strength score: net rating + series advantage weighting
        home_strength = home_net + series_diff * 2.0
        away_strength = away_net - series_diff * 2.0
        if home_strength >= away_strength:
            home_ot += 1
        else:
            away_ot += 1

    # ── Player attribution ────────────────────────────────────────────────────
    def _ot_contributors(projections: list, team_ot_pts: int) -> list[OTContributor]:
        active  = [p for p in projections if p.availability_status != "dnp"]
        # Usage-weighted closers: best scorers dominate crunch-time possessions
        closers = sorted(active, key=lambda p: p.projected_stats.mean.points, reverse=True)[:4]
        if not closers:
            return []

        total_proj = sum(p.projected_stats.mean.points for p in closers)
        if total_proj == 0:
            return []

        contributors: list[OTContributor] = []
        allocated = 0
        for i, player in enumerate(closers):
            if i == len(closers) - 1:
                pts = max(0, team_ot_pts - allocated)
            else:
                share = player.projected_stats.mean.points / total_proj
                pts   = max(0, round(team_ot_pts * share))
                allocated += pts

            if pts > 0:
                contributors.append(OTContributor(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    team_id=player.team_id,
                    ot_points=pts,
                ))

        return contributors

    home_contributors = _ot_contributors(home_projections, home_ot)
    away_contributors = _ot_contributors(away_projections, away_ot)

    return OTSimulation(
        home_ot_pts=home_ot,
        away_ot_pts=away_ot,
        home_final=home_total + home_ot,
        away_final=away_total + away_ot,
        ot_winner="home" if home_ot > away_ot else "away",
        contributors=home_contributors + away_contributors,
    )


class ProjectionService:
    pass

    def build_snapshot(
        self,
        context: GameContext,
        *,
        status: str = "live",
        possession_feed: list[dict] | None = None,
    ) -> GameSnapshot:
        home_player_projections = [
            prediction_engine.project_player(context, context.home_team, context.away_team, player)
            for player in context.home_team.players
        ]
        away_player_projections = [
            prediction_engine.project_player(context, context.away_team, context.home_team, player)
            for player in context.away_team.players
        ]

        all_active_ids = [
            p.player_id for p in home_player_projections + away_player_projections
            if p.availability_status != "dnp"
        ]
        avg_min, play_prob = _fetch_player_game_data(all_active_ids)
        volatility = _fetch_player_volatility(all_active_ids)

        # ── Feature 4: Minutes projection based on availability status ────────
        # If a player is listed as questionable or doubtful, reduce their projected
        # minutes and play probability accordingly. This prevents the model from
        # projecting a full game from someone who may only play 20 min or not at all.
        _status_adjustments = {
            "probable":     (0.95, 0.95),   # (play_prob_mult, avg_min_mult)
            "questionable": (0.65, 0.85),   # likely plays but limited
            "doubtful":     (0.25, 0.75),   # unlikely to play full game
        }
        for p in home_player_projections + away_player_projections:
            status_lower = (p.availability_status or "").lower()
            if status_lower in _status_adjustments:
                pp_mult, min_mult = _status_adjustments[status_lower]
                pid = p.player_id
                if pid in play_prob:
                    play_prob[pid] = round(play_prob[pid] * pp_mult, 3)
                if pid in avg_min:
                    avg_min[pid] = round(avg_min[pid] * min_mult, 1)

        # Fetch team-level context (form + B2B) for both teams
        home_tc = context.home_team.team_id.upper()
        away_tc = context.away_team.team_id.upper()
        home_ctx = _fetch_team_context(home_tc)
        away_ctx = _fetch_team_context(away_tc)

        # For playoff series: use actual series minutes to determine who plays
        # and how much. Players not in the series get excluded entirely.
        # Players in the series get avg_min updated from real series data so the
        # 240-minute normalization reflects actual playoff rotations.
        is_playoffs = context.playoff_intensity >= 0.55
        home_series_eff: dict = {}
        away_series_eff: dict = {}
        if is_playoffs:
            series_participants = _fetch_series_participants(home_tc, away_tc)
            if series_participants:
                all_pids = [p.player_id for p in context.home_team.players + context.away_team.players]
                for pid in all_pids:
                    if pid in series_participants:
                        # Override avg_min with actual series playing time
                        avg_min[pid] = series_participants[pid]
                    else:
                        # Not in series rotation — exclude completely
                        avg_min[pid] = 0.0
                        play_prob[pid] = 0.0
            # Fetch series-level team efficiency (pts, tov, reb, def) for both sides
            home_series_eff = _fetch_series_team_efficiency(home_tc, away_tc)
            away_series_eff = _fetch_series_team_efficiency(away_tc, home_tc)

        # Floor play probability for stars/starters now that is_playoffs is known.
        # Stars and starters almost always play — cap DNP risk at a low level.
        # Regular season: 0.88 / 0.85 floor.
        # Playoffs: 0.95 floor — teams never rest stars in the postseason, so the
        # historical season play_prob (e.g. 0.92 for 75/82 RS games) substantially
        # understates actual playoff participation.  Without this floor, play_prob
        # is applied twice in _apply_scale, compressing star projections by ~8-15%.
        _pl_star_floor    = 0.95 if is_playoffs else 0.88
        _pl_starter_floor = 0.95 if is_playoffs else 0.85
        _all_players = context.home_team.players + context.away_team.players
        _star_ids = {
            p.player_id for p in _all_players
            if p.rotation_role == "star"
            and (p.availability_status or "").lower() not in _status_adjustments
        }
        _starter_ids = {
            p.player_id for p in _all_players
            if p.rotation_role == "starter"
            and (p.availability_status or "").lower() not in _status_adjustments
        }
        for pid in _star_ids:
            if pid in play_prob:
                play_prob[pid] = max(_pl_star_floor, play_prob[pid])
        for pid in _starter_ids:
            if pid in play_prob:
                play_prob[pid] = max(_pl_starter_floor, play_prob[pid])

        # ── Feature 3: Per-player series usage (usage shift detection) ────────
        # Fetch how each player is actually performing in THIS series vs this opponent.
        # Used in _apply_volatility to detect stars taking over / usage shifts.
        player_series_usage: dict[str, dict] = {}
        if is_playoffs:
            player_series_usage = _fetch_player_series_usage(all_active_ids, away_tc)
            # Also fetch home-team players' series stats vs the away opponent
            home_ids = [p.player_id for p in home_player_projections if p.availability_status != "dnp"]
            away_ids = [p.player_id for p in away_player_projections if p.availability_status != "dnp"]
            player_series_usage.update(_fetch_player_series_usage(home_ids, away_tc))
            player_series_usage.update(_fetch_player_series_usage(away_ids, home_tc))

        # ── Playoff series progressive blending ─────────────────────────
        # As series games accumulate, the series data becomes more reliable
        # than historical season data. We replace the XGBoost base projection
        # with a blend that shifts progressively toward actual series averages:
        #   Game 1 (0 series games): 100% historical
        #   Game 2 (1 game played):  80% historical / 20% series
        #   Game 3 (2 games):        60% historical / 40% series
        #   Game 4 (3 games):        40% historical / 60% series
        #   Game 5 (4 games):        20% historical / 80% series
        #   Game 6+ (5+ games):      10% historical / 90% series
        # This ensures individual player shares reflect WHO IS ACTUALLY
        # producing in THIS matchup, not generic season averages.
        if is_playoffs and player_series_usage:
            def _apply_series_blend(proj_list: list) -> list:
                blended_list = []
                for p in proj_list:
                    if p.availability_status == "dnp":
                        blended_list.append(p)
                        continue
                    sd = player_series_usage.get(p.player_id, {})
                    sg = sd.get("series_games", 0)
                    if sg < 1:
                        blended_list.append(p)
                        continue
                    series_w = min(0.90, sg * 0.20)   # 0.20 per game, cap at 0.90
                    hist_w   = 1.0 - series_w
                    m   = p.projected_stats.mean
                    lo  = p.projected_stats.low
                    hi  = p.projected_stats.high
                    s_pts = sd.get("series_pts", m.points)
                    s_ast = sd.get("series_ast", m.assists)
                    s_reb = sd.get("series_reb", m.rebounds)
                    new_pts = round(hist_w * m.points   + series_w * s_pts, 1)
                    new_ast = round(hist_w * m.assists  + series_w * s_ast, 1)
                    new_reb = round(hist_w * m.rebounds + series_w * s_reb, 1)
                    # Scale low/high bands by the same ratio so ceiling > median > floor
                    pts_ratio = new_pts / m.points if m.points > 0 else 1.0
                    ast_ratio = new_ast / m.assists if m.assists > 0 else 1.0
                    reb_ratio = new_reb / m.rebounds if m.rebounds > 0 else 1.0
                    updated_mean = m.model_copy(update={"points": new_pts, "assists": new_ast, "rebounds": new_reb})
                    updated_low  = lo.model_copy(update={
                        "points":   round(lo.points   * pts_ratio, 1),
                        "assists":  round(lo.assists   * ast_ratio, 1),
                        "rebounds": round(lo.rebounds  * reb_ratio, 1),
                    })
                    updated_high = hi.model_copy(update={
                        "points":   round(hi.points   * pts_ratio, 1),
                        "assists":  round(hi.assists   * ast_ratio, 1),
                        "rebounds": round(hi.rebounds  * reb_ratio, 1),
                    })
                    updated_band = p.projected_stats.model_copy(update={
                        "mean": updated_mean,
                        "low":  updated_low,
                        "high": updated_high,
                    })
                    blended_list.append(p.model_copy(update={"projected_stats": updated_band}))
                return blended_list

            home_player_projections = _apply_series_blend(home_player_projections)
            away_player_projections = _apply_series_blend(away_player_projections)

        # ── Series record & elimination/stakes context ──────────────────
        # Used to apply intensity boosts for must-win situations.
        # home_series_deficit > 0  → home team is trailing in the series
        # is_elimination           → team is one loss from going home
        # is_closeout              → team can eliminate opponent with a win
        home_series_wins, away_series_wins = 0, 0
        home_series_deficit = 0
        away_series_deficit = 0
        home_is_elimination = False
        away_is_elimination = False
        home_is_closeout = False
        away_is_closeout = False

        if is_playoffs:
            home_series_wins, away_series_wins = _fetch_series_record(home_tc, away_tc)
            home_series_deficit = away_series_wins - home_series_wins
            away_series_deficit = home_series_wins - away_series_wins
            # Elimination: opponent is at 3 wins (next loss = out)
            home_is_elimination = away_series_wins == 3
            away_is_elimination = home_series_wins == 3
            # Closeout: this team can win the series with a win today
            home_is_closeout = home_series_wins == 3
            away_is_closeout = away_series_wins == 3
            logger.debug(
                "Series record [%s vs %s]: home %d–%d away | "
                "home_elim=%s away_elim=%s home_close=%s away_close=%s",
                home_tc, away_tc, home_series_wins, away_series_wins,
                home_is_elimination, away_is_elimination,
                home_is_closeout, away_is_closeout,
            )

        # Team-specific home court factors — computed from actual home/away
        # performance history so OKC, MIL, NYK etc. each get their real boost.
        # Fetched unconditionally (regular season games use them too).
        home_hca = _fetch_team_home_away_factor(home_tc)
        away_hca = _fetch_team_home_away_factor(away_tc)

        home_advantage = context.home_advantage  # typically 2.4–2.5 pts

        def _blended_team_total(
            projections: list,
            off_rating: float,
            pace: float,
            opp_def_rating: float,
            opp_pace: float,
            is_home: bool,
            form_factor: float,
            is_b2b: bool,
            vegas_implied: float | None = None,
            series_eff: dict | None = None,
            opp_series_eff: dict | None = None,
            team_hca: dict | None = None,
            opp_hca: dict | None = None,
            series_deficit: int = 0,
            is_elimination: bool = False,
            is_closeout: bool = False,
            team_wins: int = 0,
            opp_wins: int = 0,
            rest_factor: float = 1.0,
            road_fatigue: float = 0.0,
            motivation_factor: float = 0.0,
            h2h_factor: float = 0.0,
            coach_adjustment: float = 0.0,
        ) -> int:
            active = [p for p in projections if p.availability_status != "dnp"]

            # ── Player model estimate ───────────────────────────────────────
            boost = _usage_boost(projections, avg_min, play_prob)

            # XGBoost predicts full-game stats per player — already calibrated to
            # each player's typical playing time from training data.  We apply
            # play_prob only as a DNP-risk discount (starters ≈ 0.92–0.98, fringe
            # bench ≈ 0.65–0.75).  We do NOT apply an extra minute-normalization on
            # top, because that double-counts: the model already knows a bench player
            # averages 8 minutes, so predicting 3 pts for them is already correct —
            # cutting it again by 240/total_proj_min would under-estimate team scoring
            # by 20–30% and produce unrealistically low scores (e.g. 97-95 instead
            # of the Vegas-implied 111-107).
            prob_weighted_pts = sum(
                p.projected_stats.mean.points * play_prob.get(p.player_id, 0.75)
                for p in active
            ) * boost
            player_estimate = prob_weighted_pts

            # Recent team form: hot teams score more, cold teams score less
            player_estimate *= form_factor

            # Back-to-back penalty: teams on B2B historically score ~3% less
            if is_b2b:
                player_estimate *= 0.97

            # ── Rest days factor ──────────────────────────────────────────────
            # 0 days rest = -3%, 1 day = -1%, 2 days = baseline,
            # 3 days = +1%, 4+ days = +0.5% (can get rusty)
            player_estimate *= rest_factor

            # ── Playoff scoring calibration — REMOVED ────────────────────────
            # The historical RS→playoff deflation ratio (~0.9488) was previously
            # applied here as a blanket -5% reduction to player_estimate.
            #
            # This was double-counting: the form-first model's hot_factor already
            # captures each player's actual recent scoring (last-5 games), which
            # for playoff games ARE the playoff games themselves.  Brunson scoring
            # 30/38 in the current series already shows up as hot_factor > 1.0 in
            # project_player(); shrinking the team total by another 5% then forces
            # _apply_scale to compress all individual projections down (e.g. 24.6 → 20.7).
            #
            # The opp_factor from XGBoost also already adjusts for the specific
            # opponent's defensive quality, so there is no unpriced "playoff tightness"
            # left to correct.  Series-level calibration (lines below) handles any
            # remaining team-total drift once 1+ games of series data exist.
            # ─────────────────────────────────────────────────────────────────

            # ── Road trip fatigue ─────────────────────────────────────────────
            # Consecutive away games drain energy — penalty added flat after blend

            # ── Motivation factor ─────────────────────────────────────────────
            # Teams fighting for seeding/survival score more; coasting teams less

            # ── H2H matchup factor ────────────────────────────────────────────
            # How this team historically scores vs THIS specific opponent
            # Some teams just own certain matchups regardless of record

            # ── Playoff intensity boost — combinatorial leverage formula ──────
            # Replaces hardcoded constants with a data-driven formula:
            #   leverage     = P(win series|win game) − P(win series|lose game)
            #   series_win_p = P(win series from current state) at 50/50 per game
            #   trailing: motivation = leverage × series_win_p × 1.5 × 32
            #   leading:  motivation = leverage × (1−series_win_p) × 0.6 × 40
            # Calibrated so 2-3 elim → +6 pts, 3-2 closeout → +3 pts, sweep → −2 pts.
            intensity_boost = _compute_series_intensity(team_wins, opp_wins, is_playoffs)

            # ── Regular season: simple model, no series complexity ──────────
            # For non-playoff games there is no series data and the extra
            # calibration layers add noise rather than signal. Use a clean
            # player + Vegas + pace blend identical to the original model.
            if not is_playoffs:
                _team_hca = team_hca or {"home_off": 1.012, "away_off": 0.988, "home_def": 0.993}
                _opp_hca  = opp_hca  or {"home_off": 1.012, "away_off": 0.988, "home_def": 0.993}
                if is_home:
                    player_estimate *= _team_hca["home_off"]
                    eff_opp_def = opp_def_rating / max(_opp_hca["home_def"], 0.85)
                else:
                    player_estimate *= _team_hca["away_off"]
                    eff_opp_def = opp_def_rating * _opp_hca["home_def"]
                flat = 1.0 if is_home else -1.0
                gp = (pace + opp_pace) / 2.0
                pa = 1.0 + max(0.0, (gp - _LEAGUE_AVG_PACE) / _LEAGUE_AVG_PACE) * 0.6
                adj = off_rating * (max(eff_opp_def, 90.0) / _LEAGUE_AVG_DEF_RTG)
                pace_est = (adj * gp) / 100.0 * pa
                if vegas_implied is not None:
                    # Vegas is very accurate for regular season games. Player model
                    # (now without minute_scale bias) is an accurate pre-game signal.
                    blended = player_estimate * 0.40 + pace_est * 0.10 + vegas_implied * 0.50
                else:
                    blended = player_estimate * 0.65 + pace_est * 0.35
                # Regular season flat adjustments: road fatigue + motivation + H2H
                flat_adj = flat + road_fatigue + motivation_factor + h2h_factor
                logger.debug(
                    "SCORE BLEND RS [is_home=%s]: player=%.1f pace=%.1f vegas=%s → %.1f",
                    is_home, player_estimate, pace_est,
                    f"{vegas_implied:.1f}" if vegas_implied else "N/A",
                    round(blended + flat_adj),
                )
                return round(blended + flat_adj)

            # ── Series team-level adjustments ──────────────────────────────
            # These capture team dynamics that individual player projections miss:
            # (a) Turnover rate: extra turnovers = fewer scoring possessions.
            # (b) Series calibration: blend player estimate toward actual series pace.
            # (c) Opponent series defense: replace season def_rtg with series evidence.
            if series_eff and series_eff.get("games_played", 0) >= 1:
                sg = series_eff["games_played"]

                # (a) TOV penalty — every extra turnover above league avg costs ~1.2 pts
                tov_delta = series_eff.get("tov_per_game", _LEAGUE_AVG_TOV) - _LEAGUE_AVG_TOV
                player_estimate -= tov_delta * 1.2

                # (b) Blend player model with actual series scoring.
                # Each game adds 30% trust in series reality — by game 2 we trust
                # series data at 60%, fully overriding inflated season ratings.
                series_scoring_weight = min(0.65, 0.30 * sg)
                series_pts = series_eff["pts_per_game"]
                player_estimate = (
                    player_estimate * (1 - series_scoring_weight)
                    + series_pts * series_scoring_weight
                )

                # (c) Series dominance adjustment — if this team is outscoring/being
                # outscored vs the opponent in the series, amplify that gap.
                pts_allowed = series_eff.get("pts_allowed_per_game")
                if pts_allowed and pts_allowed > 0 and series_pts > 0:
                    series_margin = series_pts - pts_allowed
                    # Scale: every 10pts of series margin → ~2pts boost/penalty
                    dominance_bonus = series_margin * 0.20
                    # Cap to avoid overcorrecting from small sample
                    dominance_bonus = max(-6.0, min(6.0, dominance_bonus))
                    player_estimate += dominance_bonus

            # ── Pace anchor (opponent-adjusted) ────────────────────────────
            # Lower opp_def_rating = elite defense = should suppress scoring.
            # Correct formula: off_rating * (opp_def / league_avg).
            # When series data exists, supplement season def_rating with
            # the opponent's actual pts-allowed in this series (more current).
            effective_opp_def = opp_def_rating
            if opp_series_eff and opp_series_eff.get("games_played", 0) >= 1:
                og = opp_series_eff["games_played"]
                if "pts_allowed_per_game" in opp_series_eff:
                    # Convert series pts-allowed/game to approximate per-100 rating
                    series_implied_def = opp_series_eff["pts_allowed_per_game"] * (100 / _LEAGUE_AVG_PACE)
                    series_def_weight = min(0.50, 0.25 * og)
                    effective_opp_def = (
                        opp_def_rating * (1 - series_def_weight)
                        + series_implied_def * series_def_weight
                    )

            # ── Team-specific home court advantage ─────────────────────────
            # Every team benefits differently at home. MIL gets a +6.7 pt
            # offensive boost, OKC gets +2.7, MIN actually plays worse at home.
            # Use each team's real home/away differential from historical data
            # instead of a one-size-fits-all multiplier.
            #
            # off_mult  — this team's actual home (or away) offensive factor
            # opp_def_mult — how much the opponent's defense weakens/strengthens
            #                based on their location (road teams defend slightly worse)
            # Playoff amplifier: crowd/stakes matter more → scale effect up 15%.
            is_pl = context.playoff_intensity >= 0.55

            _team_hca = team_hca or {"home_off": 1.012, "away_off": 0.988, "home_def": 0.993}
            _opp_hca  = opp_hca  or {"home_off": 1.012, "away_off": 0.988, "home_def": 0.993}

            if is_home:
                raw_off_mult = _team_hca["home_off"]
                raw_def_mult = 1.0 / _opp_hca["home_def"]
            else:
                raw_off_mult = _team_hca["away_off"]
                raw_def_mult = _opp_hca["home_def"]

            # No playoff amplifier — OKC won on the road by 7 in Game 3, proving
            # playoffs don't reliably magnify home court. Keep the base DB-derived
            # multipliers (already conservative: ±1-4%) with no extra scaling.
            player_estimate *= raw_off_mult
            effective_opp_def *= raw_def_mult

            # Flat HCA: derived from each team's actual home/away scoring differential,
            # regressed toward league mean, scaled for playoffs. Replaces hardcoded ±3/±1.
            flat_bonus = _compute_flat_hca(team_hca, is_home, is_playoffs)

            # Pace model — amplify when both teams play fast (more possessions = more pts)
            game_pace = (pace + opp_pace) / 2
            pace_amp = 1.0 + max(0.0, (game_pace - _LEAGUE_AVG_PACE) / _LEAGUE_AVG_PACE) * 0.6
            adjusted_off_rtg = off_rating * (max(effective_opp_def, 90.0) / _LEAGUE_AVG_DEF_RTG)
            formula_pace_estimate = (adjusted_off_rtg * game_pace) / 100.0 * pace_amp

            series_games = (series_eff or {}).get("games_played", 0)

            # When series data exists, use actual series scoring as the pace anchor.
            # Season ratings (118 for both CLE and NYK) mask that CLE is only
            # scoring 98.5/game in this specific series. Series reality > pre-series model.
            if series_games >= 2 and series_eff:
                pace_estimate = series_eff["pts_per_game"]
            elif series_games == 1 and series_eff:
                # Blend formula and series equally for small sample
                pace_estimate = (formula_pace_estimate + series_eff["pts_per_game"]) / 2
            else:
                pace_estimate = formula_pace_estimate

            if vegas_implied is not None:
                # Vegas is accurate pre-series (Game 1) but increasingly stale
                # as series evidence accumulates. By Game 4, 3 real box scores
                # tell us far more than the opening line — reduce Vegas aggressively.
                # Vegas also has a known home-team bias in playoffs (crowds, narratives)
                # that causes it to underestimate road dominance like OKC's 2025 run.
                #
                # Note: minute_scale was removed — XGBoost predicts full-game stats
                # already calibrated to playing time, so player_estimate is now an
                # accurate pre-game signal. Weights below are tuned accordingly.
                if series_games >= 3:
                    # 3+ games: player model + series data drives, Vegas informative
                    player_w, vegas_w, pace_w = 0.70, 0.25, 0.05
                elif series_games == 2:
                    player_w, vegas_w, pace_w = 0.65, 0.30, 0.05
                elif series_games == 1:
                    player_w, vegas_w, pace_w = 0.55, 0.40, 0.05
                else:
                    # No series data (Game 1): Vegas is the best independent anchor.
                    # Player model (now without minute_scale bias) gets equal weight.
                    player_w, vegas_w, pace_w = 0.45, 0.50, 0.05
                blended = player_estimate * player_w + pace_estimate * pace_w + vegas_implied * vegas_w
                blended += flat_bonus + intensity_boost + road_fatigue + motivation_factor + h2h_factor + coach_adjustment
                logger.debug(
                    "SCORE BLEND [is_home=%s sg=%d]: "
                    "prob_wt=%.1f player=%.1f pace=%.1f vegas=%.1f w=(%.2f/%.2f/%.2f) → %.1f",
                    is_home, series_games, prob_weighted_pts, player_estimate,
                    pace_estimate, vegas_implied, player_w, pace_w, vegas_w, blended,
                )
                return round(blended)

            # No Vegas:
            # 2+ series games → player_estimate already has series calib + dominance
            # baked in at 60%+ weight. Adding pace on top dilutes that signal.
            # Trust the series-adjusted player estimate directly.
            if series_games >= 2:
                return round(player_estimate + flat_bonus + intensity_boost + road_fatigue + motivation_factor + h2h_factor + coach_adjustment)
            elif series_games == 1:
                blended = player_estimate * 0.80 + pace_estimate * 0.20
            else:
                # Game 1 / no series data: form-first individual projections are our
                # best signal.  Weight the player model heavily so the team total
                # stays close to the sum of form-first individual predictions and
                # _apply_scale has minimal compression to apply.
                blended = player_estimate * 0.85 + pace_estimate * 0.15

            blended += flat_bonus + intensity_boost + road_fatigue + motivation_factor + h2h_factor + coach_adjustment
            return round(blended)

        logger.debug(
            "Score blend [%s]: home_vegas=%s away_vegas=%s",
            context.game_id,
            context.home_vegas_total,
            context.away_vegas_total,
        )

        # ── Coach adjustment detection ───────────────────────────────────────
        # Compare team's in-series stats vs their regular season baseline.
        # Losing teams changing shot profile or pace → coaching response detected.
        home_coach_adj = _detect_coach_adjustment(
            home_tc, home_series_eff, home_series_deficit, home_is_elimination
        )
        away_coach_adj = _detect_coach_adjustment(
            away_tc, away_series_eff, away_series_deficit, away_is_elimination
        )

        home_total = _blended_team_total(
            home_player_projections,
            context.home_team.offensive_rating,
            context.home_team.pace,
            opp_def_rating=context.away_team.defensive_rating,
            opp_pace=context.away_team.pace,
            is_home=True,
            form_factor=home_ctx["form_factor"],
            is_b2b=home_ctx["is_b2b"],
            vegas_implied=context.home_vegas_total,
            series_eff=home_series_eff,
            opp_series_eff=away_series_eff,
            team_hca=home_hca,
            opp_hca=away_hca,
            series_deficit=home_series_deficit,
            is_elimination=home_is_elimination,
            is_closeout=home_is_closeout,
            team_wins=home_series_wins,
            opp_wins=away_series_wins,
            rest_factor=home_ctx["rest_factor"],
            road_fatigue=home_ctx["road_fatigue"],
            motivation_factor=home_ctx["motivation_factor"],
            h2h_factor=_fetch_h2h_factor(home_tc, away_tc),
            coach_adjustment=home_coach_adj,
        )
        away_total = _blended_team_total(
            away_player_projections,
            context.away_team.offensive_rating,
            context.away_team.pace,
            opp_def_rating=context.home_team.defensive_rating,
            opp_pace=context.home_team.pace,
            is_home=False,
            form_factor=away_ctx["form_factor"],
            is_b2b=away_ctx["is_b2b"],
            vegas_implied=context.away_vegas_total,
            series_eff=away_series_eff,
            opp_series_eff=home_series_eff,
            team_hca=away_hca,
            opp_hca=home_hca,
            series_deficit=away_series_deficit,
            is_elimination=away_is_elimination,
            is_closeout=away_is_closeout,
            team_wins=away_series_wins,
            opp_wins=home_series_wins,
            rest_factor=away_ctx["rest_factor"],
            road_fatigue=away_ctx["road_fatigue"],
            motivation_factor=away_ctx["motivation_factor"],
            h2h_factor=_fetch_h2h_factor(away_tc, home_tc),
            coach_adjustment=away_coach_adj,
        )

        # ── Defensive intensity penalty ───────────────────────────────────────
        # When a team elevates in a must-win/elimination game, their defence
        # spikes too — the opponent scores fewer points because the desperate
        # team locks in harder. Penalty = 40% of that team's intensity boost.
        # Uses the same combinatorial formula as the offence boost above.
        if is_playoffs:
            home_intensity = _compute_series_intensity(home_series_wins, away_series_wins, is_playoffs)
            away_intensity = _compute_series_intensity(away_series_wins, home_series_wins, is_playoffs)

            # Only positive boosts create a defensive spike (demoralized teams don't lock in)
            away_total = round(away_total - max(0.0, home_intensity) * 0.4)
            home_total = round(home_total - max(0.0, away_intensity) * 0.4)

            # Floor: never let a penalty push a team below 85 pts
            home_total = max(85, home_total)
            away_total = max(85, away_total)

        # Rescale individual players so their scores sum to the team total.
        # This keeps individual predictions correlated with the final score —
        # if the team total moves up/down, every player moves proportionally.
        # Role-based ceiling: max multiplier any player can receive from DNP scaling.
        # Prevents bench/rotation players from absorbing a star's full load —
        # in reality, the points are redistributed in smaller pieces across many players,
        # not all flowing to one role player.
        #   star:     1.40× their XGBoost base (primary option, can truly step up)
        #   starter:  1.30× (secondary options take on more, but not a full star load)
        #   rotation: 1.20× (rotation players get meaningful extra minutes, not stars)
        #   bench:    1.12× (spot minutes — cannot replicate a star's production)
        # Tightened from {1.50/1.40/1.30/1.20} — the wider caps allowed bench/rotation
        # players to absorb too much DNP load, over-inflating team totals.
        _ROLE_BOOST_CAP = {"star": 1.40, "starter": 1.30, "rotation": 1.20, "bench": 1.12}

        def _apply_scale(projections: list, team_total: int) -> list[PlayerProjection]:
            active = [p for p in projections if p.availability_status != "dnp"]
            prob_weighted_raw = sum(
                p.projected_stats.mean.points * play_prob.get(p.player_id, 0.75)
                for p in active
            )
            team_scale = team_total / max(1.0, prob_weighted_raw)
            scaled = []
            for p in projections:
                if p.availability_status == "dnp":
                    scaled.append(p)
                    continue
                combined = team_scale * play_prob.get(p.player_id, 0.75)
                # Cap: no player's pts can grow more than their role allows.
                # e.g. Caruso (bench, 8 pts base) → max 8 × 1.20 = 9.6 pts
                role_cap = _ROLE_BOOST_CAP.get(p.rotation_role, 1.25)
                capped   = min(combined, role_cap)
                scaled.append(_rescale_player_pts(p, capped))
            return scaled

        home_player_projections = _apply_scale(home_player_projections, home_total)
        away_player_projections = _apply_scale(away_player_projections, away_total)

        # ── Post-scale hot-form redistribution ────────────────────────────────
        # _apply_scale normalises to the team total, which can nullify the
        # hot-factor signal applied in project_player().  Fix: re-apply hot
        # factor and playoff lift AFTER scaling as a relative redistribution.
        #
        # Algorithm (preserves team total):
        #   1. Compute boost_i = hot_nudge_i × playoff_lift_i for each player.
        #   2. boosted_pts_i = scaled_pts_i × boost_i
        #   3. Re-normalise so sum(boosted_pts) = team_total.
        #   4. Hot players steal share from cold/neutral players; sum is conserved.
        from app.simulation.prediction_engine import _get_playoff_lift
        _is_playoffs_redist = context.playoff_intensity >= 0.55

        def _redistribute(projections: list, team_total: int) -> list[PlayerProjection]:
            """
            Post-scale redistribution: apply playoff role-lift weights to shift
            scoring share toward stars/starters in playoff games.

            Hot factor is already baked into each player's initial projection by
            project_player() (form-first model), so we do NOT re-apply it here.
            Only the DB-derived playoff role lift is used as the redistribution
            weight — this keeps stars slightly above their scaled share in
            high-intensity playoff situations without double-counting form.
            """
            active = [p for p in projections if p.availability_status != "dnp"]
            if not active:
                return projections

            boosts: dict[str, float] = {}
            for p in active:
                # Playoff role lift (data-driven): star > starter > rotation > bench
                # In RS (no playoff lift), all players get weight=1.0 → no redistribution.
                lift = _get_playoff_lift(p.rotation_role) if _is_playoffs_redist else 1.0
                boosts[p.player_id] = lift

            # Apply boosts to current (already-scaled) pts
            boosted = {
                p.player_id: p.projected_stats.mean.points * boosts[p.player_id]
                for p in active
            }
            total_boosted = sum(boosted.values())
            if total_boosted < 1.0:
                return projections

            # Re-normalise to preserve team total
            norm = team_total / total_boosted
            result = []
            for p in projections:
                if p.availability_status == "dnp":
                    result.append(p)
                    continue
                orig = p.projected_stats.mean.points
                if orig > 0:
                    new_scale = boosted[p.player_id] * norm / orig
                    role_cap  = _ROLE_BOOST_CAP.get(p.rotation_role, 1.25)
                    new_scale = min(new_scale, role_cap)
                    result.append(_rescale_player_pts(p, new_scale))
                else:
                    result.append(p)
            return result

        home_player_projections = _redistribute(home_player_projections, home_total)
        away_player_projections = _redistribute(away_player_projections, away_total)

        # Compute breakout_stats as a SEPARATE column — projected_stats (XGBoost
        # floor/mean/ceiling) is left completely untouched. Volatility ceilings live
        # exclusively in breakout_stats so both can be shown side by side.
        #
        # Breakout probability formula:
        #   1. raw_breakout_pct — fraction of last 30 games with 30+ pts (sample base)
        #   2. opp_factor — scales raw rate by how weak/strong the opponent defense is
        #      vs league average (weak D → higher probability, elite D → lower)
        #   3. ceiling_signal — how far the volatility ceiling is above 30 pts (0→0.5)
        #   4. playoff_mult — stars elevate in playoffs; applies 15% boost if applicable
        #   Final: clamp(opp_adj_rate × 0.55 + ceiling_signal × 0.45, 0, 0.95) × playoff_mult
        is_playoffs = context.playoff_intensity >= 0.65
        playoff_mult = 1.15 if is_playoffs else 1.0

        # Elimination breakout boost: top-2 usage players on a must-win team
        # elevate in do-or-die situations — stars step up when the season is on the line.
        # Identify the two highest-usage active players per team facing elimination.
        _elim_boost_pids: set[str] = set()
        if is_playoffs:
            for team_projs, is_elim in [
                (home_player_projections, home_is_elimination),
                (away_player_projections, away_is_elimination),
            ]:
                if is_elim:
                    top2 = sorted(
                        [p for p in team_projs if p.availability_status != "dnp"],
                        key=lambda p: p.projected_stats.mean.points,
                        reverse=True,
                    )[:2]
                    _elim_boost_pids.update(p.player_id for p in top2)
            # Also boost top scorers on teams down 1 or 2 games
            for team_projs, deficit in [
                (home_player_projections, home_series_deficit),
                (away_player_projections, away_series_deficit),
            ]:
                if deficit >= 1:
                    # Top 2 scorers for teams down 2, top 1 for teams down 1
                    n = 2 if deficit >= 2 else 1
                    top_n = sorted(
                        [p for p in team_projs if p.availability_status != "dnp"],
                        key=lambda p: p.projected_stats.mean.points,
                        reverse=True,
                    )[:n]
                    _elim_boost_pids.update(p.player_id for p in top_n)

        def _apply_volatility(
            proj: PlayerProjection,
            opp_def_rtg: float,
        ) -> PlayerProjection:
            if proj.availability_status == "dnp":
                return proj
            vol = volatility.get(proj.player_id, {})
            raw_breakout_pct = vol.get("breakout_pct", 0.0)

            # ── Feature 1: Hot / Cold streak adjustment ───────────────────────
            # Redistributes scoring within the team — doesn't change team total,
            # just reflects that a hot player's SHARE of the team output is higher.
            streak_factor = vol.get("streak_factor", 1.0)

            # ── Feature 2: Personalised breakout threshold ────────────────────
            # Each player's "breakout night" is defined relative to their own avg,
            # not a one-size-fits-all 30-pt threshold.
            personal_threshold = vol.get("breakout_threshold", _BREAKOUT_THRESHOLD)

            # ── Feature 3: Series usage shift ────────────────────────────────
            # If a player is scoring significantly more in this series than their
            # season baseline, their usage has shifted — factor that into projection.
            usage_shift_factor = 1.0
            if is_playoffs:
                series_data = player_series_usage.get(proj.player_id, {})
                series_games = series_data.get("series_games", 0)
                if series_games >= 2:
                    series_pts = series_data.get("series_pts", 0.0)
                    season_pts = vol.get("season_pts_per_game", 0.0)
                    if season_pts > 0:
                        shift = (series_pts - season_pts) / season_pts
                        # Only boost/penalise if shift is meaningful (>10%)
                        # Clamped: max +15% boost, max -12% penalty
                        if shift > 0.10:
                            usage_shift_factor = min(1.15, 1.0 + shift * 0.5)
                        elif shift < -0.10:
                            usage_shift_factor = max(0.88, 1.0 + shift * 0.5)

            # Opponent adjustment: weaker defense → higher breakout odds.
            # opp_factor > 1 when opp is worse than league avg, < 1 when elite.
            opp_factor = min(1.4, max(0.6, opp_def_rtg / _LEAGUE_AVG_DEF_RTG))
            adj_breakout_pct = min(1.0, raw_breakout_pct * opp_factor)

            # ── Bounce-back signal ────────────────────────────────────────
            # Elite players who went well below their average last game respond.
            # Stars don't go quiet two games in a row — pride + film study.
            bounce_back_mult = vol.get("bounce_back_mult", 1.0)
            adj_breakout_pct = min(1.0, adj_breakout_pct * bounce_back_mult)

            # Elimination / high-stakes star boost: top players on must-win teams
            # elevate their breakout probability — stars rise to the moment.
            # Elimination (0-3, 1-3, 2-3): +40% breakout chance
            # Series deficit >= 2: +30% breakout chance
            # Series deficit == 1: +20% breakout chance
            if proj.player_id in _elim_boost_pids:
                # Determine which tier this player's team is in
                is_in_elim_team = any(
                    p.player_id == proj.player_id and is_elim
                    for team_p, is_elim in [
                        (home_player_projections, home_is_elimination),
                        (away_player_projections, away_is_elimination),
                    ]
                    for p in team_p
                )
                is_in_deficit2_team = any(
                    p.player_id == proj.player_id and deficit >= 2
                    for team_p, deficit in [
                        (home_player_projections, home_series_deficit),
                        (away_player_projections, away_series_deficit),
                    ]
                    for p in team_p
                )
                if is_in_elim_team:
                    adj_breakout_pct = min(1.0, adj_breakout_pct * 1.40)
                elif is_in_deficit2_team:
                    adj_breakout_pct = min(1.0, adj_breakout_pct * 1.30)
                else:
                    adj_breakout_pct = min(1.0, adj_breakout_pct * 1.20)

            m = proj.projected_stats.mean

            # Apply streak factor + usage shift to base projected stats.
            # Combined factor redistributes scoring within the team — hot players
            # get a larger share, cold players get less. Team total unchanged.
            combined_factor = round(streak_factor * usage_shift_factor, 3)
            adj_pts = round(m.points  * combined_factor, 1)
            adj_ast = round(m.assists * combined_factor, 1)
            adj_reb = round(m.rebounds * combined_factor, 1)

            # Use actual conditional mean (avg stats on their own breakout nights).
            # Floor at adjusted mean — breakout section should never show lower.
            def _bo_mean(bo_key: str, mean_val: float, std_key: str) -> float:
                v = vol.get(bo_key)
                raw = v if v is not None else round(mean_val + vol.get(std_key, 2.0), 1)
                return round(max(mean_val, raw), 1)

            bo_pts  = _bo_mean("bo_mean_pts",  adj_pts,       "pts_std")
            bo_ast  = _bo_mean("bo_mean_ast",  adj_ast,       "ast_std")
            bo_reb  = _bo_mean("bo_mean_reb",  adj_reb,       "reb_std")
            bo_fg3m = _bo_mean("bo_mean_fg3m", m.threes_made, "fg3m_std")
            bo_stl  = _bo_mean("bo_mean_stl",  m.steals,      "stl_std")
            bo_blk  = _bo_mean("bo_mean_blk",  m.blocks,      "blk_std")

            # ceiling_signal uses personalised threshold — superstars have a higher bar
            pts_ceil_signal = adj_pts + 2.0 * vol.get("pts_std", 2.0)
            ceiling_signal = min(0.5, max(0.0, (pts_ceil_signal - personal_threshold) / 20.0))
            raw_prob = adj_breakout_pct * 0.55 + ceiling_signal * 0.45
            breakout_prob = round(min(0.95, raw_prob * playoff_mult), 2)
            breakout_alert = breakout_prob >= 0.20 or bo_pts >= personal_threshold

            # Rebuild projected_stats with streak + usage adjustments applied.
            # Low / high bands shift proportionally so the UI stays consistent.
            updated_mean = m.model_copy(update={
                "points":   adj_pts,
                "assists":  adj_ast,
                "rebounds": adj_reb,
            })
            low_s  = proj.projected_stats.low
            high_s = proj.projected_stats.high
            updated_low = low_s.model_copy(update={
                "points":   round(low_s.points   * combined_factor, 1),
                "assists":  round(low_s.assists  * combined_factor, 1),
                "rebounds": round(low_s.rebounds * combined_factor, 1),
            })
            updated_high = high_s.model_copy(update={
                "points":   round(high_s.points   * combined_factor, 1),
                "assists":  round(high_s.assists  * combined_factor, 1),
                "rebounds": round(high_s.rebounds * combined_factor, 1),
            })
            updated_stats = proj.projected_stats.model_copy(update={
                "mean": updated_mean,
                "low":  updated_low,
                "high": updated_high,
            })

            return proj.model_copy(update={
                "projected_stats": updated_stats,
                "breakout_stats": BreakoutStats(
                    mean_pts=bo_pts,
                    mean_ast=bo_ast,
                    mean_reb=bo_reb,
                    mean_fg3m=bo_fg3m,
                    mean_stl=bo_stl,
                    mean_blk=bo_blk,
                    breakout_probability=breakout_prob,
                    breakout_alert=breakout_alert,
                ),
                "breakout_probability": breakout_prob,
                "breakout_alert": breakout_alert,
            })

        home_player_projections = [
            _apply_volatility(p, context.away_team.defensive_rating)
            for p in home_player_projections
        ]
        away_player_projections = [
            _apply_volatility(p, context.home_team.defensive_rating)
            for p in away_player_projections
        ]

        # Breakout boost: when a star has elevated breakout probability, nudge the
        # team total up slightly. Only applied when Vegas is present — Vegas acts as
        # the upper-bound constraint so the boost doesn't send uncapped estimates wild.
        def _breakout_boost(projections: list[PlayerProjection], vegas_implied: float | None) -> int:
            if vegas_implied is None:
                return 0
            max_prob = max(
                (p.breakout_probability for p in projections if p.availability_status != "dnp"),
                default=0.0,
            )
            return round(max_prob * 6)  # 25% → +2 pts, 50% → +3 pts

        home_total += _breakout_boost(home_player_projections, context.home_vegas_total)
        away_total += _breakout_boost(away_player_projections, context.away_vegas_total)

        # ── Blowout detection (separate from base prediction) ────────────
        blowout_info = _compute_blowout_info(
            home_total=home_total,
            away_total=away_total,
            home_series_eff=home_series_eff,
            away_series_eff=away_series_eff,
            home_is_b2b=home_ctx["is_b2b"],
            away_is_b2b=away_ctx["is_b2b"],
            home_off_rtg=context.home_team.offensive_rating,
            away_off_rtg=context.away_team.offensive_rating,
            home_def_rtg=context.home_team.defensive_rating,
            away_def_rtg=context.away_team.defensive_rating,
            home_pace=context.home_team.pace,
            away_pace=context.away_team.pace,
            is_playoffs=is_playoffs,
            home_abbr=home_tc,
            away_abbr=away_tc,
        )

        game_id = context.game_id

        if status == "final":
            # Game over — always use the locked score, nothing to update.
            if game_id in _pregame_scores:
                home_total, away_total = _pregame_scores[game_id]
        elif status == "live":
            if game_id not in _pregame_scores:
                _pregame_scores[game_id] = [home_total, away_total]
                _save_score_cache(_pregame_scores)
                logger.info(
                    "Locked live score for %s: %d-%d (first live call)",
                    game_id, home_total, away_total,
                )
            home_total, away_total = _pregame_scores[game_id]
        else:
            if game_id not in _pregame_scores:
                _pregame_scores[game_id] = [home_total, away_total]
                _save_score_cache(_pregame_scores)
                logger.info(
                    "Locked pre-game score for %s: %d-%d (first prediction)",
                    game_id, home_total, away_total,
                )
            home_total, away_total = _pregame_scores[game_id]

        # Tie-breaker: home teams win ~59% of NBA playoff games.
        if home_total == away_total:
            home_total += 1

        # ── OT simulation ────────────────────────────────────────────────────
        # When regulation ends within 2 pts the game is genuinely a coin flip.
        # Silently simulate a 5-min OT: the resulting score becomes the final
        # prediction shown to users. OT pts are also added to the projected
        # stats of the players most likely to be on the floor.
        # The "Too Close To Call" badge is shown — no OT mechanics are exposed.
        _reg_margin = abs(home_total - away_total)
        _is_ot_game = _reg_margin <= 2
        if _is_ot_game:
            _ot_home_avg, _ot_away_avg = _fetch_series_ot_scoring_avgs(home_tc, away_tc)
            _ot = _run_ot_simulation(
                game_id=game_id,
                home_total=home_total,
                away_total=away_total,
                home_projections=home_player_projections,
                away_projections=away_player_projections,
                home_off_rtg=context.home_team.offensive_rating,
                home_def_rtg=context.home_team.defensive_rating,
                away_off_rtg=context.away_team.offensive_rating,
                away_def_rtg=context.away_team.defensive_rating,
                home_pace=context.home_team.pace,
                away_pace=context.away_team.pace,
                home_series_wins=home_series_wins,
                away_series_wins=away_series_wins,
                home_series_avg=_ot_home_avg,
                away_series_avg=_ot_away_avg,
            )
            # Lift final totals to include OT scoring
            home_total = _ot.home_final
            away_total = _ot.away_final

            # Add OT pts directly to each contributor's projected stat line so
            # the player cards reflect the extra production without explanation.
            _ot_pts_map: dict[str, int] = {c.player_id: c.ot_points for c in _ot.contributors}

            def _add_ot_pts(proj_list: list) -> list:
                updated = []
                for p in proj_list:
                    extra = _ot_pts_map.get(p.player_id, 0)
                    if extra > 0:
                        m  = p.projected_stats.mean
                        lo = p.projected_stats.low
                        hi = p.projected_stats.high
                        new_m  = m.model_copy(update={"points": round(m.points + extra, 1)})
                        new_lo = lo.model_copy(update={"points": round(lo.points + extra * 0.7, 1)})
                        new_hi = hi.model_copy(update={"points": round(hi.points + extra * 1.2, 1)})
                        new_band = p.projected_stats.model_copy(
                            update={"mean": new_m, "low": new_lo, "high": new_hi}
                        )
                        updated.append(p.model_copy(update={"projected_stats": new_band}))
                    else:
                        updated.append(p)
                return updated

            home_player_projections = _add_ot_pts(home_player_projections)
            away_player_projections = _add_ot_pts(away_player_projections)

        home_projection = prediction_engine.project_team(
            context, context.home_team, context.away_team, True,
            player_score_sum=home_total, opponent_score_sum=away_total,
        )
        away_projection = prediction_engine.project_team(
            context, context.away_team, context.home_team, False,
            player_score_sum=away_total, opponent_score_sum=home_total,
        )

        player_projections = home_player_projections + away_player_projections

        base_wp = home_projection.win_probability
        win_series = []
        for minute in range(0, 49, 4):
            fraction_played = minute / 48.0
            time_wp = 0.5 + (base_wp - 0.5) * (0.25 + 0.75 * fraction_played)
            time_wp = max(0.05, min(0.95, time_wp))
            win_series.append({"minute": minute, "home": round(time_wp, 3), "away": round(1 - time_wp, 3)})

        default_feed = [
            {
                "quarter": max(context.quarter, 1),
                "clock": "08:41",
                "summary": "BallPredict is waiting for richer possession detail and using the latest team context to anchor projections.",
                "leverage": "medium",
            }
        ]

        margin = abs(home_total - away_total)

        # Build blowout schema objects from detection result
        from app.schemas.game import BlowoutScore as _BlowoutScore
        blowout_score_obj = (
            _BlowoutScore(home=blowout_info["home"], away=blowout_info["away"])
            if blowout_info["is_blowout"] else None
        )

        return GameSnapshot(
            game_id=context.game_id,
            status=status,
            updated_at=__import__("datetime").datetime.utcnow(),
            quarter=context.quarter,
            clock=context.clock,
            home_team=home_projection,
            away_team=away_projection,
            player_projections=player_projections,
            possession_feed=possession_feed or default_feed,
            insights=insight_service.build_game_insights(context),
            win_probability_series=win_series,
            is_close_game=_is_ot_game,
            predicted_margin=home_total - away_total,
            ot_simulation=None,
            blowout_alert=blowout_info["is_blowout"],
            blowout_score=blowout_score_obj,
            blowout_signals=blowout_info["signals"],
        )


projection_service = ProjectionService()
