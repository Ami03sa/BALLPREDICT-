from app.schemas.game import GameSnapshot
from app.services.insight_service import insight_service
from app.simulation.prediction_engine import prediction_engine
from app.simulation.state import GameContext


class ProjectionService:
    def _reconcile_player_points_to_team_total(self, players: list, target_points: int) -> list:
        if not players:
            return players

        raw_total = sum(player.projected_stats.mean.points for player in players)
        if raw_total <= 0:
            even_share = round(target_points / len(players), 1)
            return [
                player.model_copy(
                    update={
                        "projected_stats": player.projected_stats.model_copy(
                            update={
                                "mean": player.projected_stats.mean.model_copy(update={"points": even_share}),
                            }
                        )
                    }
                )
                for player in players
            ]

        scale = target_points / raw_total
        reconciled = []
        for player in players:
            low = player.projected_stats.low.points
            mean = player.projected_stats.mean.points
            high = player.projected_stats.high.points
            reconciled.append(
                player.model_copy(
                    update={
                        "projected_stats": player.projected_stats.model_copy(
                            update={
                                "low": player.projected_stats.low.model_copy(
                                    update={"points": round(max(0, low * scale), 1)}
                                ),
                                "mean": player.projected_stats.mean.model_copy(
                                    update={"points": round(max(0, mean * scale), 1)}
                                ),
                                "high": player.projected_stats.high.model_copy(
                                    update={"points": round(max(0, high * scale), 1)}
                                ),
                            }
                        )
                    }
                )
            )

        adjusted_total = round(sum(player.projected_stats.mean.points for player in reconciled), 1)
        delta = round(target_points - adjusted_total, 1)
        if reconciled and abs(delta) >= 0.1:
            lead_index = max(range(len(reconciled)), key=lambda idx: reconciled[idx].projected_stats.mean.points)
            lead = reconciled[lead_index]
            reconciled[lead_index] = lead.model_copy(
                update={
                    "projected_stats": lead.projected_stats.model_copy(
                        update={
                            "mean": lead.projected_stats.mean.model_copy(
                                update={"points": round(max(0, lead.projected_stats.mean.points + delta), 1)}
                            )
                        }
                    )
                }
            )
        return reconciled

    def build_snapshot(
        self,
        context: GameContext,
        *,
        status: str = "live",
        possession_feed: list[dict] | None = None,
    ) -> GameSnapshot:
        home_projection = prediction_engine.project_team(context, context.home_team, context.away_team, True)
        away_projection = prediction_engine.project_team(context, context.away_team, context.home_team, False)

        home_player_projections = [
            prediction_engine.project_player(context, context.home_team, context.away_team, player)
            for player in context.home_team.players
        ]
        away_player_projections = [
            prediction_engine.project_player(context, context.away_team, context.home_team, player)
            for player in context.away_team.players
        ]
        home_player_projections = self._reconcile_player_points_to_team_total(
            home_player_projections,
            home_projection.final_score_mean,
        )
        away_player_projections = self._reconcile_player_points_to_team_total(
            away_player_projections,
            away_projection.final_score_mean,
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
