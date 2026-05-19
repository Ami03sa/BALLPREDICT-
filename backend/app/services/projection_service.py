import sqlite3
from pathlib import Path

from app.schemas.game import GameSnapshot
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"

# Total player-minutes per team per game (5 players × 48 min).
_GAME_MINUTES = 240.0


def _fetch_avg_minutes(player_ids: list[str]) -> dict[str, float]:
    """Fetch each player's average minutes over last 10 played games in one query."""
    if not player_ids or not _DB_PATH.exists():
        return {pid: 15.0 for pid in player_ids}
    try:
        placeholders = ",".join("?" * len(player_ids))
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
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
        conn.close()
        result = {r[0]: float(r[1]) for r in rows}
        for pid in player_ids:
            if pid not in result:
                result[pid] = 15.0
        return result
    except Exception:
        return {pid: 15.0 for pid in player_ids}


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

        # One DB round-trip to get avg minutes for all active players.
        all_active_ids = [
            p.player_id for p in home_player_projections + away_player_projections
            if p.availability_status != "dnp"
        ]
        avg_min = _fetch_avg_minutes(all_active_ids)

        def _team_pts_sum(projections: list, off_rating: float, pace: float) -> int:
            active = [p for p in projections if p.availability_status != "dnp"]

            # --- Player-model estimate ---
            # Each XGBoost prediction reflects a player's typical per-game output.
            # But summing 12+ players whose average minutes exceed 240 double-counts
            # production, so we scale by how much the minute budget is over 240.
            total_proj_min = sum(avg_min.get(p.player_id, 15.0) for p in active)
            minute_scale = min(1.0, _GAME_MINUTES / max(1.0, total_proj_min))
            player_estimate = sum(p.projected_stats.mean.points for p in active) * minute_scale

            # --- Pace-efficiency anchor ---
            # Expected team pts = (offensive rating / 100) × possessions per game.
            # This grounds the prediction in the team's actual scoring efficiency
            # independent of how many players the model includes.
            pace_estimate = (off_rating * pace) / 100.0

            # Blend: 60% player model, 40% pace anchor.
            # The player model captures matchup/player-level nuance;
            # the pace anchor prevents the sum from drifting too far from team baselines.
            return round(player_estimate * 0.6 + pace_estimate * 0.4)

        home_pts_sum = _team_pts_sum(
            home_player_projections,
            context.home_team.offensive_rating,
            context.home_team.pace,
        )
        away_pts_sum = _team_pts_sum(
            away_player_projections,
            context.away_team.offensive_rating,
            context.away_team.pace,
        )

        home_projection = prediction_engine.project_team(
            context, context.home_team, context.away_team, True, player_score_sum=home_pts_sum
        )
        away_projection = prediction_engine.project_team(
            context, context.away_team, context.home_team, False, player_score_sum=away_pts_sum
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
