import sqlite3
from pathlib import Path

from app.schemas.game import ConfidenceBand, GameSnapshot, PlayerProjection, StatLine
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"
_GAME_MINUTES = 240.0


def _fetch_player_game_data(player_ids: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    """
    One DB query returning two dicts keyed by player_id:
      avg_min   — average minutes over last 10 played games
      play_prob — probability of playing tonight = games_played / team_total_games

    play_prob naturally down-weights fringe players (30-game appearances out of 82)
    and stars who rest (load management reduces their appearance rate).
    """
    if not player_ids or not _DB_PATH.exists():
        return {pid: 15.0 for pid in player_ids}, {pid: 1.0 for pid in player_ids}
    try:
        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))

        # Average minutes over last 10 played games
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

        # Games played per player + max games played on each player's team
        # (team max = how many games the team has played this season)
        gp_rows = conn.execute(
            f"""
            SELECT
                p.player_id,
                COUNT(DISTINCT p.game_id)                          AS gp,
                MAX(t.team_games)                                  AS team_games
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
            # Clamp between 0.25 and 1.0 — even a rarely-used player has some chance;
            # even a star misses some games.
            play_prob[pid] = max(0.25, min(1.0, gp / max(1, team_games)))

        for pid in player_ids:
            avg_min.setdefault(pid, 15.0)
            play_prob.setdefault(pid, 0.75)

        return avg_min, play_prob
    except Exception:
        return {pid: 15.0 for pid in player_ids}, {pid: 1.0 for pid in player_ids}


def _usage_boost(projections: list, avg_min: dict, play_prob: dict) -> float:
    """
    When high-usage players are DNP, their possessions go to active teammates.
    Returns a multiplier (>= 1.0) to apply to every active player's projection.

    Logic: total usage budget is fixed at 1.0 per team.
    If DNP players held U_dnp of that budget, remaining players share it:
      boost = (active_usage + dnp_usage) / active_usage, capped at 1.25.
    """
    dnp = [p for p in projections if p.availability_status == "dnp"]
    active = [p for p in projections if p.availability_status != "dnp"]
    if not dnp or not active:
        return 1.0

    from app.simulation.state import PlayerGameState  # avoid circular at module level
    # We need usage_rate — it's on the raw player states, not projections.
    # Pass-through via play_prob dict as a proxy: avg_min ∝ usage for our purposes.
    # Better: sum projected mean pts as a usage proxy.
    dnp_pts = sum(p.projected_stats.mean.points for p in dnp)
    active_pts = sum(p.projected_stats.mean.points for p in active)
    if active_pts < 1.0:
        return 1.0
    raw_boost = (active_pts + dnp_pts) / active_pts
    return min(1.25, raw_boost)


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

        def _blended_team_total(
            projections: list,
            off_rating: float,
            pace: float,
            vegas_implied: float | None = None,
        ) -> int:
            active = [p for p in projections if p.availability_status != "dnp"]

            # Boost active players when high-usage teammates are DNP
            boost = _usage_boost(projections, avg_min, play_prob)

            # Expected points = XGBoost prediction × P(player plays tonight) × usage boost.
            prob_weighted_pts = sum(
                p.projected_stats.mean.points * play_prob.get(p.player_id, 0.75)
                for p in active
            ) * boost

            # Minutes normalization: scale down when expected minutes exceed 240.
            total_proj_min = sum(
                avg_min.get(p.player_id, 15.0) * play_prob.get(p.player_id, 0.75)
                for p in active
            )
            minute_scale = min(1.0, _GAME_MINUTES / max(1.0, total_proj_min))
            player_estimate = prob_weighted_pts * minute_scale

            # Pace-efficiency anchor: (offensive_rating / 100) × possessions per game
            pace_estimate = (off_rating * pace) / 100.0

            if vegas_implied is not None:
                # Three-way blend: 50% player model, 25% pace, 25% Vegas line
                return round(player_estimate * 0.50 + pace_estimate * 0.25 + vegas_implied * 0.25)
            return round(player_estimate * 0.6 + pace_estimate * 0.4)

        home_total = _blended_team_total(
            home_player_projections,
            context.home_team.offensive_rating,
            context.home_team.pace,
            vegas_implied=context.home_vegas_total,
        )
        away_total = _blended_team_total(
            away_player_projections,
            context.away_team.offensive_rating,
            context.away_team.pace,
            vegas_implied=context.away_vegas_total,
        )

        # Rescale each active player's projected points (weighted by their play probability)
        # so individual scores still add up to the team total.
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

        home_projection = prediction_engine.project_team(
            context, context.home_team, context.away_team, True, player_score_sum=home_total
        )
        away_projection = prediction_engine.project_team(
            context, context.away_team, context.home_team, False, player_score_sum=away_total
        )

        player_projections = home_player_projections + away_player_projections

        win_series = [
            {"minute": minute, "home": max(0.05, min(0.95, home_projection.win_probability + (minute - 24) * 0.005))}
            for minute in range(0, 49, 4)
        ]
        for row in win_series:
            row["away"] = round(1 - row["home"], 3)
            row["home"] = round(row["home"], 3)

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
