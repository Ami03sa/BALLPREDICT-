from __future__ import annotations

import math
import random
from statistics import mean

from app.schemas.game import ConfidenceBand, PlayerProjection, StatLine, TeamProjection
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


class PredictionEngine:
    """Hybrid rules + Monte Carlo starter engine for live in-game basketball forecasting."""

    def _apply_adjustments(self, player: PlayerGameState, adjustments: list[dict[str, float]]) -> dict[str, float]:
        accumulator = {
            "points": player.points,
            "assists": player.assists,
            "rebounds": player.rebounds,
            "steals": player.steals,
            "blocks": player.blocks,
            "turnovers": player.turnovers,
            "3pm": player.threes_made,
            "usage_rate": player.usage_rate,
            "field_goal_pct": player.field_goal_pct,
            "three_point_pct": player.three_point_pct,
        }
        for impact in adjustments:
            accumulator["usage_rate"] += impact.get("usage_rate", 0)
            accumulator["field_goal_pct"] += impact.get("field_goal_pct", 0)
            accumulator["three_point_pct"] += impact.get("three_point_pct", 0)
            accumulator["assists"] += impact.get("assists", 0)
            accumulator["turnovers"] += impact.get("turnovers", 0)
            accumulator["3pm"] += impact.get("teammate_corner_3_rate", 0) * 2.0
        return accumulator

    def project_player(
        self,
        context: GameContext,
        offense: TeamGameState,
        defense: TeamGameState,
        player: PlayerGameState,
    ) -> PlayerProjection:
        if player.availability_status == "dnp":
            zero_line = StatLine()
            return PlayerProjection(
                player_id=player.player_id,
                player_name=player.player_name,
                team_id=player.team_id,
                quarter=context.quarter,
                rotation_role=player.rotation_role,
                availability_status=player.availability_status,
                dnp_reason=player.dnp_reason,
                live_stats=zero_line,
                projected_stats=ConfidenceBand(low=zero_line, mean=zero_line, high=zero_line),
                momentum_score=player.momentum_score,
                fatigue_index=player.fatigue_index,
                defensive_pressure=0.0,
                adjustments=[],
            )

        adjustments = coaching_engine.build_player_counters(context, offense, defense, player)
        impact_maps = [adjustment.impact for adjustment in adjustments]
        state = self._apply_adjustments(player, impact_maps)

        remaining_quarters = max(0, 4 - context.quarter)
        pressure = min(1.0, player.matchup_difficulty + player.fatigue_index + len(adjustments) * 0.08)
        base_minutes = remaining_quarters * 8.5
        usage_multiplier = max(0.78, 1 - pressure * 0.22)
        efficiency_multiplier = max(0.72, 1 - pressure * 0.18)

        mean_line = StatLine(
            points=round(player.points + (player.usage_rate * base_minutes * 1.5 * usage_multiplier), 1),
            assists=round(player.assists + max(0.5, state["assists"] * 0.08 + remaining_quarters * 0.9), 1),
            rebounds=round(player.rebounds + remaining_quarters * (1.1 + (1 - player.fatigue_index)), 1),
            steals=round(player.steals + remaining_quarters * 0.3, 1),
            blocks=round(player.blocks + remaining_quarters * 0.2, 1),
            turnovers=round(player.turnovers + max(0.3, state["turnovers"] * 0.1), 1),
            **{"3pm": round(player.threes_made + remaining_quarters * 0.7 * usage_multiplier, 1)},
            usage_rate=round(max(0.12, min(0.42, state["usage_rate"])), 3),
            field_goal_pct=round(max(0.33, min(0.68, state["field_goal_pct"] * efficiency_multiplier)), 3),
            three_point_pct=round(max(0.25, min(0.55, state["three_point_pct"] * efficiency_multiplier)), 3),
        )

        spread = 1.2 + pressure * 2.2
        low_line = mean_line.model_copy(
            update={
                "points": round(max(0, mean_line.points - spread * 2.4), 1),
                "assists": round(max(0, mean_line.assists - spread * 0.8), 1),
                "rebounds": round(max(0, mean_line.rebounds - spread * 0.7), 1),
                "turnovers": round(max(0, mean_line.turnovers - 0.5), 1),
            }
        )
        high_line = mean_line.model_copy(
            update={
                "points": round(mean_line.points + spread * 2.8, 1),
                "assists": round(mean_line.assists + spread * 1.1, 1),
                "rebounds": round(mean_line.rebounds + spread * 0.9, 1),
                "turnovers": round(mean_line.turnovers + 0.7, 1),
            }
        )

        return PlayerProjection(
            player_id=player.player_id,
            player_name=player.player_name,
            team_id=player.team_id,
            quarter=context.quarter,
            rotation_role=player.rotation_role,
            availability_status=player.availability_status,
            dnp_reason=player.dnp_reason,
            live_stats=StatLine(
                points=player.points,
                assists=player.assists,
                rebounds=player.rebounds,
                steals=player.steals,
                blocks=player.blocks,
                turnovers=player.turnovers,
                **{"3pm": player.threes_made},
                usage_rate=player.usage_rate,
                field_goal_pct=player.field_goal_pct,
                three_point_pct=player.three_point_pct,
            ),
            projected_stats=ConfidenceBand(low=low_line, mean=mean_line, high=high_line),
            momentum_score=player.momentum_score,
            fatigue_index=player.fatigue_index,
            defensive_pressure=pressure,
            adjustments=adjustments,
        )

    def _simulate_team_score(self, team: TeamGameState, opponent: TeamGameState, pace_boost: float, runs: int) -> tuple[int, tuple[int, int], float]:
        samples: list[int] = []
        for _ in range(runs):
            possession_factor = team.pace * 0.55 + pace_boost + random.uniform(-2.4, 2.4)
            shot_quality = team.offensive_rating - opponent.defensive_rating * 0.12
            turnover_penalty = team.turnover_rate * random.uniform(6, 12)
            fatigue_penalty = (mean([p.fatigue_index for p in team.players]) if team.players else 0.2) * 7.5
            samples.append(int(team.score + possession_factor + shot_quality - turnover_penalty - fatigue_penalty))
        samples.sort()
        mean_score = round(mean(samples))
        return mean_score, (samples[int(runs * 0.1)], samples[int(runs * 0.9)]), team.pace + pace_boost

    def project_team(self, context: GameContext, team: TeamGameState, opponent: TeamGameState, is_home: bool) -> TeamProjection:
        runs = 400
        pace_boost = (context.live_pace_multiplier - 1) * 4
        final_mean, ci, projected_pace = self._simulate_team_score(team, opponent, pace_boost, runs)
        if context.quarter <= 0:
            base_quarter = final_mean / 4
            quarter_projection = tuple(max(22, round(base_quarter + delta)) for delta in (-1, 1, -2, 2))
        else:
            quarter_seed = team.score / max(context.quarter, 1)
            quarter_projection = tuple(max(18, round(quarter_seed + delta)) for delta in (0, 2, -1, 1))
        margin = final_mean - context.home_team.score if is_home else final_mean - context.away_team.score
        home_baseline = context.home_team.offensive_rating - context.away_team.defensive_rating * 0.08 + context.home_advantage
        away_baseline = context.away_team.offensive_rating - context.home_team.defensive_rating * 0.08
        home_edge = home_baseline - away_baseline
        win_prob = 1 / (1 + math.exp(-(home_edge + context.score_margin * 0.22)))
        team_win_prob = win_prob if is_home else 1 - win_prob

        return TeamProjection(
            team_id=team.team_id,
            team_name=team.team_name,
            quarter=context.quarter,
            score=team.score,
            projected_score=quarter_projection,
            final_score_mean=final_mean,
            final_score_ci=ci,
            pace=round(projected_pace, 1),
            offensive_rating=round(team.offensive_rating + margin * 0.4, 1),
            defensive_rating=round(opponent.defensive_rating - margin * 0.25, 1),
            win_probability=round(team_win_prob, 3),
        )


prediction_engine = PredictionEngine()
