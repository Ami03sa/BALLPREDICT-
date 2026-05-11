from app.schemas.game import GameSnapshot
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext


class ProjectionService:
    def build_snapshot(self, context: GameContext) -> GameSnapshot:
        home_projection = prediction_engine.project_team(context, context.home_team, context.away_team, True)
        away_projection = prediction_engine.project_team(context, context.away_team, context.home_team, False)

        player_projections = [
            prediction_engine.project_player(context, context.home_team, context.away_team, player)
            for player in context.home_team.players
        ] + [
            prediction_engine.project_player(context, context.away_team, context.home_team, player)
            for player in context.away_team.players
        ]

        win_series = [
            {"minute": minute, "home": max(0.05, min(0.95, home_projection.win_probability + (minute - 24) * 0.005))}
            for minute in range(0, 49, 4)
        ]
        for row in win_series:
            row["away"] = round(1 - row["home"], 3)
            row["home"] = round(row["home"], 3)

        return GameSnapshot(
            game_id=context.game_id,
            status="live",
            updated_at=__import__("datetime").datetime.utcnow(),
            quarter=context.quarter,
            clock=context.clock,
            home_team=home_projection,
            away_team=away_projection,
            player_projections=player_projections,
            possession_feed=[
                {
                    "quarter": context.quarter,
                    "clock": "08:41",
                    "summary": "Warriors ICE the side pick-and-roll and force a kickout reset.",
                    "leverage": "high",
                },
                {
                    "quarter": context.quarter,
                    "clock": "07:58",
                    "summary": "Mavericks counter with ghost screen spacing to free the weak-side corner.",
                    "leverage": "medium",
                },
                {
                    "quarter": context.quarter,
                    "clock": "07:12",
                    "summary": "A scram switch removes the smaller guard from the post mismatch.",
                    "leverage": "medium",
                },
            ],
            insights=insight_service.build_game_insights(context),
            win_probability_series=win_series,
        )


projection_service = ProjectionService()

