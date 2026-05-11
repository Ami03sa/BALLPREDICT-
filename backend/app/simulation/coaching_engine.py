from app.schemas.game import CoachingAdjustment
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


class CoachingAdjustmentEngine:
    """Models real NBA-style counters that coaches deploy against hot actions and personnel."""

    def build_player_counters(
        self,
        context: GameContext,
        offense: TeamGameState,
        defense: TeamGameState,
        player: PlayerGameState,
    ) -> list[CoachingAdjustment]:
        adjustments: list[CoachingAdjustment] = []
        hot_hand = player.points >= 12 or player.momentum_score > 0.7
        high_usage = player.usage_rate >= 0.3
        downhill_pressure = player.drive_frequency >= 0.2 or player.paint_touches >= 5
        shooter_gravity = player.threes_made >= 2 or player.three_point_pct >= 0.4

        if hot_hand and high_usage:
            adjustments.append(
                CoachingAdjustment(
                    title="Blitz Primary Action",
                    side="defense",
                    trigger=f"{player.player_name} is controlling first-action usage",
                    explanation=(
                        f"{defense.coach_name} sends a second defender on high pick-and-rolls, "
                        "forcing early pickups and reducing clean pull-up volume."
                    ),
                    counters=["trap at level", "weak-side tag", "scram switch on short roll"],
                    impact={
                        "field_goal_pct": -0.05,
                        "usage_rate": -0.03,
                        "assists": 0.8,
                        "turnovers": 0.6,
                        "teammate_corner_3_rate": 0.09,
                    },
                )
            )

        if shooter_gravity:
            adjustments.append(
                CoachingAdjustment(
                    title="Top-Lock Off-Ball Actions",
                    side="defense",
                    trigger="Movement shooting gravity is stretching weak-side help",
                    explanation=(
                        "Defenders top-lock pindowns, lock-and-trail off floppy action, "
                        "and pre-switch bigger wings into screening actions."
                    ),
                    counters=["top-lock", "lock-and-trail", "pre-switch into pindown"],
                    impact={
                        "three_point_pct": -0.04,
                        "usage_rate": -0.01,
                        "assists": 0.2,
                        "secondary_handler_usage": 0.05,
                    },
                )
            )

        if downhill_pressure:
            adjustments.append(
                CoachingAdjustment(
                    title="Shrink the Floor",
                    side="defense",
                    trigger="Rim pressure is creating paint collapse",
                    explanation=(
                        "The defense pulls extra nail help, sends early low-man rotations, "
                        "ICEs side pick-and-rolls, and crowds the dotted line."
                    ),
                    counters=["nail help", "low-man tag", "ICE side pick-and-roll", "gap shrink"],
                    impact={
                        "field_goal_pct": -0.03,
                        "free_throw_rate": -0.02,
                        "assists": 0.5,
                        "skip_pass_frequency": 0.08,
                    },
                )
            )

        if context.score_margin > 8 and context.quarter >= 3:
            adjustments.append(
                CoachingAdjustment(
                    title="Tempo Control",
                    side="pace",
                    trigger="Leading team wants lower variance possessions",
                    explanation=(
                        "The offense shortens the game with later-clock entries, more post touches, "
                        "and deliberate matchup hunting to avoid live-ball turnovers."
                    ),
                    counters=["late-clock entry", "mismatch post-up", "bench stabilization shift"],
                    impact={"pace": -2.4, "turnovers": -0.3, "halfcourt_frequency": 0.11},
                )
            )

        if player.foul_count >= 3 and context.quarter <= 3:
            adjustments.append(
                CoachingAdjustment(
                    title="Rotation Protection",
                    side="rotation",
                    trigger="Foul trouble threatens star availability",
                    explanation=(
                        "The staff shortens point-of-attack responsibilities, cross-matches on defense, "
                        "and staggers bench units to preserve the star for winning time."
                    ),
                    counters=["cross-match", "hide on spacer", "stagger rotations"],
                    impact={"usage_rate": -0.02, "minutes_ceiling": -3, "teammate_usage": 0.04},
                )
            )

        return adjustments

    def build_team_level_adjustments(self, context: GameContext, team: TeamGameState) -> list[CoachingAdjustment]:
        adjustments: list[CoachingAdjustment] = []
        if team.bench_depth < 0.45 and context.fatigue_pressure > 0.6:
            adjustments.append(
                CoachingAdjustment(
                    title="Extended Starter Stagger",
                    side="rotation",
                    trigger="Bench units are leaking two-way value",
                    explanation=(
                        f"{team.coach_name} keeps one creator on the floor at all times, "
                        "sacrificing rest to stabilize shot quality and turnover control."
                    ),
                    counters=["1-star stagger", "double-big bench cover", "switch-all second unit"],
                    impact={"pace": -0.8, "offensive_rating": 2.1, "fatigue_index": 0.06},
                )
            )

        if context.playoff_intensity > 0.7:
            adjustments.append(
                CoachingAdjustment(
                    title="Playoff Matchup Compression",
                    side="defense",
                    trigger="Series-style game is reducing schematic surprises",
                    explanation=(
                        "Coaches toggle between scram switches, peel switching on drives, "
                        "full-front post denial, and aggressive rear-view contests."
                    ),
                    counters=["scram switch", "peel switch", "full-front post", "rear-view contest"],
                    impact={"field_goal_pct_allowed": -0.02, "pace": -1.0, "turnover_rate_forced": 0.01},
                )
            )

        return adjustments


coaching_engine = CoachingAdjustmentEngine()

