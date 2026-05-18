from app.schemas.game import GameSnapshot
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext


class ProjectionService:
    def build_snapshot(
        self,
        context: GameContext,
        *,
        status: str = "live",
        possession_feed: list[dict] | None = None,
    ) -> GameSnapshot:
        # Project players first so we can sum their XGBoost point projections
        # and use that sum as the authoritative team final-score prediction.
        home_player_projections = [
            prediction_engine.project_player(context, context.home_team, context.away_team, player)
            for player in context.home_team.players
        ]
        away_player_projections = [
            prediction_engine.project_player(context, context.away_team, context.home_team, player)
            for player in context.away_team.players
        ]

        # Sum top active contributors only — exclude DNPs, cap at 8 (realistic rotation).
        # Also cap the total at 140 to guard against model inflation.
        def _team_pts_sum(projections: list) -> int:
            active = [p for p in projections if p.availability_status != "dnp"]
            top8 = sorted(active, key=lambda p: p.projected_stats.mean.points, reverse=True)[:8]
            raw = sum(p.projected_stats.mean.points for p in top8)
            return round(min(140, raw))

        home_pts_sum = _team_pts_sum(home_player_projections)
        away_pts_sum = _team_pts_sum(away_player_projections)

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
