import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.schemas.game import ConfidenceBand, GameSnapshot, PlayerProjection, StatLine
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"
_GAME_MINUTES = 240.0
_LEAGUE_AVG_DEF_RTG = 114.0  # League-average defensive rating used for opp-adjustment
_BREAKOUT_THRESHOLD = 30.0   # Points threshold for "breakout" classification


def _fetch_player_volatility(player_ids: list[str]) -> dict[str, dict]:
    """
    Returns per-player volatility for all tracked stats from last 10 qualifying games.
    Keys per player: pts_std, ast_std, reb_std, fg3m_std, stl_std, blk_std, breakout_pct
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
            SELECT player_id, pts, ast, reb, fg3m, stl, blk
            FROM (
                SELECT player_id, pts, ast, reb, fg3m, stl, blk,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
                FROM player_game_logs
                WHERE player_id IN ({placeholders}) AND min >= 10
            ) sub
            WHERE rn <= 10
            """,
            player_ids,
        ).fetchall()
        conn.close()

        buckets: dict[str, list] = defaultdict(list)
        for row in rows:
            buckets[row[0]].append(row[1:])  # (pts, ast, reb, fg3m, stl, blk)

        def _std(vals: list[float]) -> float:
            if len(vals) < 2:
                return 0.0
            m = sum(vals) / len(vals)
            return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

        result: dict[str, dict] = {}
        for pid, games in buckets.items():
            cols = list(zip(*games))  # transpose to per-stat lists
            pts_list = [float(v) for v in cols[0]]
            result[pid] = {
                "pts_std":  round(_std(pts_list), 1),
                "ast_std":  round(_std([float(v) for v in cols[1]]), 1),
                "reb_std":  round(_std([float(v) for v in cols[2]]), 1),
                "fg3m_std": round(_std([float(v) for v in cols[3]]), 1),
                "stl_std":  round(_std([float(v) for v in cols[4]]), 1),
                "blk_std":  round(_std([float(v) for v in cols[5]]), 1),
                "breakout_pct": round(
                    sum(1 for p in pts_list if p >= _BREAKOUT_THRESHOLD) / len(pts_list), 2
                ),
            }
        return result
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
      form_factor — last-5 avg score / season avg score (clamped 0.93–1.07)
      is_b2b      — True if team played yesterday
    Both are used to adjust the player estimate before blending.
    """
    result = {"form_factor": 1.0, "is_b2b": False}
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
                SELECT game_id, SUM(pts) AS team_score, MAX(game_date) AS gdate
                FROM player_game_logs
                WHERE team_abbreviation = ? AND season = ?
                  AND season_type = 'Regular Season'
                GROUP BY game_id
                ORDER BY gdate DESC
                LIMIT 5
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
                recent_avg = sum(r[1] for r in recent) / len(recent)
                season_avg = float(season_avg_row[0])
                raw_factor = recent_avg / max(season_avg, 1)
                result["form_factor"] = max(0.93, min(1.07, raw_factor))

                # Back-to-back: did they play yesterday?
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                last_game_date = str(recent[0][2])[:10] if recent else ""
                result["is_b2b"] = last_game_date == yesterday

        conn.close()
    except Exception:
        pass
    return result


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
    return min(1.25, (active_pts + dnp_pts) / active_pts)


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


class ProjectionService:
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

        # Floor play probability at 0.85 for confirmed starters — they almost always play.
        starter_ids = {
            p.player_id
            for p in context.home_team.players + context.away_team.players
            if p.rotation_role == "starter"
        }
        for pid in starter_ids:
            if pid in play_prob:
                play_prob[pid] = max(0.85, play_prob[pid])

        # Fetch team-level context (form + B2B) for both teams
        home_tc = context.home_team.team_id.upper()
        away_tc = context.away_team.team_id.upper()
        home_ctx = _fetch_team_context(home_tc)
        away_ctx = _fetch_team_context(away_tc)

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
        ) -> int:
            active = [p for p in projections if p.availability_status != "dnp"]

            # ── Player model estimate ───────────────────────────────────────
            boost = _usage_boost(projections, avg_min, play_prob)

            prob_weighted_pts = sum(
                p.projected_stats.mean.points * play_prob.get(p.player_id, 0.75)
                for p in active
            ) * boost

            # Minutes normalization: keep total minutes ≤ 240
            total_proj_min = sum(
                avg_min.get(p.player_id, 15.0) * play_prob.get(p.player_id, 0.75)
                for p in active
            )
            minute_scale = min(1.0, _GAME_MINUTES / max(1.0, total_proj_min))
            player_estimate = prob_weighted_pts * minute_scale

            # Recent team form: hot teams score more, cold teams score less
            player_estimate *= form_factor

            # Back-to-back penalty: teams on B2B historically score ~3% less
            if is_b2b:
                player_estimate *= 0.97

            # ── Pace anchor (opponent-adjusted) ────────────────────────────
            # Standard formula: adjust OffRtg by how much better/worse than
            # league average the opponent defends, then use avg game pace.
            # opp_def_rating < 114 = elite defense (suppresses scoring)
            # opp_def_rating > 114 = weak defense (gives up more)
            game_pace = (pace + opp_pace) / 2
            adjusted_off_rtg = off_rating * (_LEAGUE_AVG_DEF_RTG / max(opp_def_rating, 90.0))
            pace_estimate = (adjusted_off_rtg * game_pace) / 100.0

            # Home court edge on pace anchor only (XGBoost already captures it
            # for individual players via is_home feature; Vegas already prices it in).
            # Apply only when no Vegas to avoid double-counting.
            if vegas_implied is None:
                pace_estimate += 1.5 if is_home else -1.5

            # ── Blend ──────────────────────────────────────────────────────
            # Player model is the primary driver — it uses real roster quality,
            # matchup vulnerability, and individual form. Pace and Vegas are
            # anchors that prevent the sum from going out of range.
            if vegas_implied is not None:
                # Vegas is very accurate — give it meaningful weight,
                # but keep player model as the majority driver.
                return round(player_estimate * 0.55 + pace_estimate * 0.15 + vegas_implied * 0.30)
            return round(player_estimate * 0.65 + pace_estimate * 0.35)

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
        )

        # Rescale individual players so their scores sum to the team total.
        # This keeps individual predictions correlated with the final score —
        # if the team total moves up/down, every player moves proportionally.
        def _apply_scale(projections: list, team_total: int) -> list[PlayerProjection]:
            active = [p for p in projections if p.availability_status != "dnp"]
            prob_weighted_raw = sum(
                p.projected_stats.mean.points * play_prob.get(p.player_id, 0.75)
                for p in active
            )
            team_scale = team_total / max(1.0, prob_weighted_raw)
            return [
                _rescale_player_pts(p, team_scale * play_prob.get(p.player_id, 0.75))
                for p in projections
            ]

        home_player_projections = _apply_scale(home_player_projections, home_total)
        away_player_projections = _apply_scale(away_player_projections, away_total)

        # Widen ALL stat high bands using historical volatility — XGBoost bands are
        # based on small feature perturbations and are too narrow for high-variance
        # players. Use mean + 1.5×stat_std as the floor for each stat's ceiling.
        def _apply_volatility(proj: PlayerProjection) -> PlayerProjection:
            if proj.availability_status == "dnp":
                return proj
            vol = volatility.get(proj.player_id, {})
            raw_breakout_pct = vol.get("breakout_pct", 0.0)

            def _widen(mean_val: float, current_high: float, std_key: str) -> float:
                std = vol.get(std_key, 2.0)
                return round(max(current_high, mean_val + 1.5 * std), 1)

            m = proj.projected_stats.mean
            h = proj.projected_stats.high
            new_high_pts  = _widen(m.points,      h.points,      "pts_std")
            new_high_ast  = _widen(m.assists,     h.assists,     "ast_std")
            new_high_reb  = _widen(m.rebounds,    h.rebounds,    "reb_std")
            new_high_fg3m = _widen(m.threes_made, h.threes_made, "fg3m_std")
            new_high_stl  = _widen(m.steals,      h.steals,      "stl_std")
            new_high_blk  = _widen(m.blocks,      h.blocks,      "blk_std")

            ceiling_signal = min(0.5, max(0.0, (new_high_pts - _BREAKOUT_THRESHOLD) / 20.0))
            breakout_prob  = round(min(0.95, raw_breakout_pct * 0.6 + ceiling_signal * 0.4), 2)
            breakout_alert = breakout_prob >= 0.25 or new_high_pts >= _BREAKOUT_THRESHOLD

            new_high_line = h.model_copy(update={
                "points":      new_high_pts,
                "assists":     new_high_ast,
                "rebounds":    new_high_reb,
                "threes_made": new_high_fg3m,
                "steals":      new_high_stl,
                "blocks":      new_high_blk,
            })
            return proj.model_copy(update={
                "projected_stats": proj.projected_stats.model_copy(update={"high": new_high_line}),
                "breakout_probability": breakout_prob,
                "breakout_alert": breakout_alert,
            })

        home_player_projections = [_apply_volatility(p) for p in home_player_projections]
        away_player_projections = [_apply_volatility(p) for p in away_player_projections]

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

        home_projection = prediction_engine.project_team(
            context, context.home_team, context.away_team, True, player_score_sum=home_total
        )
        away_projection = prediction_engine.project_team(
            context, context.away_team, context.home_team, False, player_score_sum=away_total
        )

        player_projections = home_player_projections + away_player_projections

        # Win probability series: anchor to the model's pre-game estimate, then
        # show how uncertainty compresses as more of the game is played.
        # At minute 0 (full game ahead) uncertainty is highest → closer to 0.5.
        # At minute 48 (game over) uncertainty collapses → converges to the projection.
        base_wp = home_projection.win_probability
        win_series = []
        for minute in range(0, 49, 4):
            fraction_played = minute / 48.0
            # Interpolate between 0.5 (max uncertainty) and base_wp (full certainty)
            # using a gentle curve so early minutes don't swing too far from 0.5.
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
        )


projection_service = ProjectionService()
