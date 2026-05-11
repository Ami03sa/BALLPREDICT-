from datetime import datetime

from app.schemas.game import GameSnapshot, PlayerDetailResponse, PlayerQuarterProjection, SimulationResponse
from app.services.projection_service import projection_service
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


class LiveGameService:
    def __init__(self) -> None:
        self._contexts: dict[str, GameContext] = {}
        self._slate: dict[str, dict] = {}

    async def bootstrap_demo_game(self) -> None:
        if self._contexts:
            return

        self._contexts["gsw-dal-demo"] = self._build_context(
            game_id="gsw-dal-demo",
            quarter=0,
            clock="12:00",
            home_team=TeamGameState(
                team_id="gsw",
                team_name="Golden State Warriors",
                coach_name="Steve Kerr",
                score=0,
                pace=101.4,
                offensive_rating=117.3,
                defensive_rating=113.9,
                defensive_rebound_pct=0.73,
                turnover_rate=0.132,
                three_point_rate=0.47,
                free_throw_rate=0.19,
                foul_pressure=0.42,
                bench_depth=0.58,
                adjustment_discipline=0.77,
                players=[
                    PlayerGameState(
                        player_id="steph",
                        player_name="Stephen Curry",
                        team_id="gsw",
                        usage_rate=0.31,
                        points=0,
                        assists=0,
                        rebounds=0,
                        threes_made=0,
                        field_goal_pct=0.57,
                        three_point_pct=0.40,
                        minutes_played=0,
                        fatigue_index=0.12,
                        momentum_score=0.62,
                        matchup_difficulty=0.58,
                        drive_frequency=0.14,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="jimmy",
                        player_name="Jimmy Butler",
                        team_id="gsw",
                        usage_rate=0.27,
                        points=0,
                        assists=0,
                        rebounds=0,
                        turnovers=0,
                        field_goal_pct=0.49,
                        three_point_pct=0.33,
                        minutes_played=0,
                        fatigue_index=0.17,
                        momentum_score=0.55,
                        matchup_difficulty=0.54,
                        drive_frequency=0.22,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="draymond",
                        player_name="Draymond Green",
                        team_id="gsw",
                        usage_rate=0.17,
                        assists=0,
                        rebounds=0,
                        field_goal_pct=0.48,
                        three_point_pct=0.34,
                        fatigue_index=0.16,
                        momentum_score=0.47,
                        matchup_difficulty=0.53,
                        drive_frequency=0.10,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="podz",
                        player_name="Brandin Podziemski",
                        team_id="gsw",
                        usage_rate=0.16,
                        field_goal_pct=0.46,
                        three_point_pct=0.37,
                        fatigue_index=0.12,
                        momentum_score=0.44,
                        matchup_difficulty=0.51,
                        drive_frequency=0.12,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="hield",
                        player_name="Buddy Hield",
                        team_id="gsw",
                        usage_rate=0.18,
                        threes_made=0,
                        field_goal_pct=0.45,
                        three_point_pct=0.39,
                        fatigue_index=0.11,
                        momentum_score=0.49,
                        matchup_difficulty=0.52,
                        drive_frequency=0.08,
                        paint_touches=1,
                    ),
                ],
            ),
            away_team=TeamGameState(
                team_id="dal",
                team_name="Dallas Mavericks",
                coach_name="Jason Kidd",
                score=0,
                pace=99.8,
                offensive_rating=118.9,
                defensive_rating=114.8,
                defensive_rebound_pct=0.75,
                turnover_rate=0.121,
                three_point_rate=0.43,
                free_throw_rate=0.22,
                foul_pressure=0.39,
                bench_depth=0.51,
                adjustment_discipline=0.69,
                players=[
                    PlayerGameState(
                        player_id="luka",
                        player_name="Luka Doncic",
                        team_id="dal",
                        usage_rate=0.39,
                        points=0,
                        assists=0,
                        rebounds=0,
                        turnovers=0,
                        threes_made=0,
                        field_goal_pct=0.62,
                        three_point_pct=0.39,
                        minutes_played=0,
                        fatigue_index=0.14,
                        momentum_score=0.68,
                        matchup_difficulty=0.44,
                        drive_frequency=0.25,
                        paint_touches=6,
                    ),
                    PlayerGameState(
                        player_id="kai",
                        player_name="Kyrie Irving",
                        team_id="dal",
                        usage_rate=0.28,
                        points=0,
                        assists=0,
                        rebounds=0,
                        threes_made=0,
                        field_goal_pct=0.50,
                        three_point_pct=0.38,
                        minutes_played=0,
                        fatigue_index=0.12,
                        momentum_score=0.61,
                        matchup_difficulty=0.49,
                        drive_frequency=0.19,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="klay",
                        player_name="Klay Thompson",
                        team_id="dal",
                        usage_rate=0.19,
                        field_goal_pct=0.44,
                        three_point_pct=0.38,
                        fatigue_index=0.13,
                        momentum_score=0.46,
                        matchup_difficulty=0.56,
                        drive_frequency=0.07,
                        paint_touches=1,
                    ),
                    PlayerGameState(
                        player_id="gafford",
                        player_name="Daniel Gafford",
                        team_id="dal",
                        usage_rate=0.15,
                        field_goal_pct=0.65,
                        three_point_pct=0.0,
                        fatigue_index=0.14,
                        momentum_score=0.42,
                        matchup_difficulty=0.48,
                        drive_frequency=0.06,
                        paint_touches=6,
                    ),
                    PlayerGameState(
                        player_id="washington",
                        player_name="P.J. Washington",
                        team_id="dal",
                        usage_rate=0.17,
                        field_goal_pct=0.46,
                        three_point_pct=0.36,
                        fatigue_index=0.12,
                        momentum_score=0.45,
                        matchup_difficulty=0.50,
                        drive_frequency=0.11,
                        paint_touches=3,
                    ),
                ],
            ),
            score_margin=0,
            home_advantage=2.6,
            overtime_probability=0.08,
            momentum=0.50,
            fatigue_pressure=0.20,
            whistle_tightness=0.46,
            playoff_intensity=0.58,
            live_pace_multiplier=1.00,
            injury_risk_flags=[],
            back_to_back=False,
        )
        self._contexts["bos-lal-demo"] = self._build_context(
            game_id="bos-lal-demo",
            quarter=0,
            clock="12:00",
            home_team=TeamGameState(
                team_id="lal",
                team_name="Los Angeles Lakers",
                coach_name="JJ Redick",
                score=0,
                pace=100.1,
                offensive_rating=115.1,
                defensive_rating=114.3,
                defensive_rebound_pct=0.72,
                turnover_rate=0.138,
                three_point_rate=0.39,
                free_throw_rate=0.24,
                foul_pressure=0.44,
                bench_depth=0.46,
                adjustment_discipline=0.63,
                players=[
                    PlayerGameState(
                        player_id="lebron",
                        player_name="LeBron James",
                        team_id="lal",
                        usage_rate=0.30,
                        momentum_score=0.60,
                        fatigue_index=0.19,
                        matchup_difficulty=0.55,
                        drive_frequency=0.21,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="ad",
                        player_name="Anthony Davis",
                        team_id="lal",
                        usage_rate=0.29,
                        momentum_score=0.58,
                        fatigue_index=0.21,
                        matchup_difficulty=0.60,
                        drive_frequency=0.16,
                        paint_touches=7,
                    ),
                    PlayerGameState(
                        player_id="reaves",
                        player_name="Austin Reaves",
                        team_id="lal",
                        usage_rate=0.23,
                        momentum_score=0.51,
                        fatigue_index=0.13,
                        matchup_difficulty=0.52,
                        drive_frequency=0.17,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="rui",
                        player_name="Rui Hachimura",
                        team_id="lal",
                        usage_rate=0.17,
                        momentum_score=0.43,
                        fatigue_index=0.12,
                        matchup_difficulty=0.53,
                        drive_frequency=0.12,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="vando",
                        player_name="Jarred Vanderbilt",
                        team_id="lal",
                        usage_rate=0.11,
                        momentum_score=0.38,
                        fatigue_index=0.12,
                        matchup_difficulty=0.58,
                        drive_frequency=0.09,
                        paint_touches=2,
                    ),
                ],
            ),
            away_team=TeamGameState(
                team_id="bos",
                team_name="Boston Celtics",
                coach_name="Joe Mazzulla",
                score=0,
                pace=99.4,
                offensive_rating=119.6,
                defensive_rating=111.4,
                defensive_rebound_pct=0.76,
                turnover_rate=0.119,
                three_point_rate=0.49,
                free_throw_rate=0.20,
                foul_pressure=0.35,
                bench_depth=0.59,
                adjustment_discipline=0.74,
                players=[
                    PlayerGameState(
                        player_id="tatum",
                        player_name="Jayson Tatum",
                        team_id="bos",
                        usage_rate=0.31,
                        momentum_score=0.64,
                        fatigue_index=0.13,
                        matchup_difficulty=0.47,
                        drive_frequency=0.20,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="brown",
                        player_name="Jaylen Brown",
                        team_id="bos",
                        usage_rate=0.28,
                        momentum_score=0.57,
                        fatigue_index=0.14,
                        matchup_difficulty=0.48,
                        drive_frequency=0.22,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="holiday",
                        player_name="Jrue Holiday",
                        team_id="bos",
                        usage_rate=0.18,
                        momentum_score=0.49,
                        fatigue_index=0.11,
                        matchup_difficulty=0.46,
                        drive_frequency=0.12,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="white",
                        player_name="Derrick White",
                        team_id="bos",
                        usage_rate=0.20,
                        momentum_score=0.52,
                        fatigue_index=0.12,
                        matchup_difficulty=0.45,
                        drive_frequency=0.14,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="porzingis",
                        player_name="Kristaps Porzingis",
                        team_id="bos",
                        usage_rate=0.24,
                        momentum_score=0.50,
                        fatigue_index=0.15,
                        matchup_difficulty=0.47,
                        drive_frequency=0.08,
                        paint_touches=5,
                    ),
                ],
            ),
            score_margin=0,
            home_advantage=2.9,
            overtime_probability=0.07,
            momentum=0.50,
            fatigue_pressure=0.22,
            whistle_tightness=0.43,
            playoff_intensity=0.62,
            live_pace_multiplier=0.99,
            injury_risk_flags=["Anthony Davis minute load watch"],
            back_to_back=False,
        )
        self._contexts["den-phx-demo"] = self._build_context(
            game_id="den-phx-demo",
            quarter=0,
            clock="12:00",
            home_team=TeamGameState(
                team_id="phx",
                team_name="Phoenix Suns",
                coach_name="Mike Budenholzer",
                score=0,
                pace=98.7,
                offensive_rating=116.0,
                defensive_rating=114.7,
                defensive_rebound_pct=0.71,
                turnover_rate=0.129,
                three_point_rate=0.44,
                free_throw_rate=0.21,
                foul_pressure=0.38,
                bench_depth=0.47,
                adjustment_discipline=0.66,
                players=[
                    PlayerGameState(
                        player_id="booker",
                        player_name="Devin Booker",
                        team_id="phx",
                        usage_rate=0.31,
                        momentum_score=0.59,
                        fatigue_index=0.16,
                        matchup_difficulty=0.54,
                        drive_frequency=0.19,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="durant",
                        player_name="Kevin Durant",
                        team_id="phx",
                        usage_rate=0.30,
                        momentum_score=0.63,
                        fatigue_index=0.17,
                        matchup_difficulty=0.56,
                        drive_frequency=0.14,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="beal",
                        player_name="Bradley Beal",
                        team_id="phx",
                        usage_rate=0.22,
                        momentum_score=0.48,
                        fatigue_index=0.14,
                        matchup_difficulty=0.53,
                        drive_frequency=0.16,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="allen",
                        player_name="Grayson Allen",
                        team_id="phx",
                        usage_rate=0.14,
                        momentum_score=0.39,
                        fatigue_index=0.10,
                        matchup_difficulty=0.50,
                        drive_frequency=0.07,
                        paint_touches=1,
                    ),
                    PlayerGameState(
                        player_id="richards",
                        player_name="Nick Richards",
                        team_id="phx",
                        usage_rate=0.12,
                        momentum_score=0.35,
                        fatigue_index=0.11,
                        matchup_difficulty=0.56,
                        drive_frequency=0.05,
                        paint_touches=5,
                    ),
                ],
            ),
            away_team=TeamGameState(
                team_id="den",
                team_name="Denver Nuggets",
                coach_name="Michael Malone",
                score=0,
                pace=97.9,
                offensive_rating=117.1,
                defensive_rating=112.9,
                defensive_rebound_pct=0.78,
                turnover_rate=0.123,
                three_point_rate=0.37,
                free_throw_rate=0.23,
                foul_pressure=0.36,
                bench_depth=0.43,
                adjustment_discipline=0.72,
                players=[
                    PlayerGameState(
                        player_id="jokic",
                        player_name="Nikola Jokic",
                        team_id="den",
                        usage_rate=0.33,
                        momentum_score=0.66,
                        fatigue_index=0.12,
                        matchup_difficulty=0.41,
                        drive_frequency=0.10,
                        paint_touches=8,
                    ),
                    PlayerGameState(
                        player_id="murray",
                        player_name="Jamal Murray",
                        team_id="den",
                        usage_rate=0.27,
                        momentum_score=0.54,
                        fatigue_index=0.15,
                        matchup_difficulty=0.50,
                        drive_frequency=0.18,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="gordon",
                        player_name="Aaron Gordon",
                        team_id="den",
                        usage_rate=0.17,
                        momentum_score=0.41,
                        fatigue_index=0.12,
                        matchup_difficulty=0.49,
                        drive_frequency=0.15,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="mpj",
                        player_name="Michael Porter Jr.",
                        team_id="den",
                        usage_rate=0.21,
                        momentum_score=0.45,
                        fatigue_index=0.13,
                        matchup_difficulty=0.47,
                        drive_frequency=0.09,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="braun",
                        player_name="Christian Braun",
                        team_id="den",
                        usage_rate=0.12,
                        momentum_score=0.37,
                        fatigue_index=0.11,
                        matchup_difficulty=0.48,
                        drive_frequency=0.11,
                        paint_touches=2,
                    ),
                ],
            ),
            score_margin=0,
            home_advantage=2.7,
            overtime_probability=0.06,
            momentum=0.50,
            fatigue_pressure=0.21,
            whistle_tightness=0.41,
            playoff_intensity=0.60,
            live_pace_multiplier=0.98,
            injury_risk_flags=[],
            back_to_back=True,
        )

        self._slate = {
            "gsw-dal-demo": {
                "game_id": "gsw-dal-demo",
                "status": "scheduled",
                "tipoff": "7:30 PM ET",
                "broadcast": "ESPN",
                "arena": "Chase Center",
                "headline": "Ball-screen chess between Luka's usage and Kerr's coverage counters.",
                "home_team": "Golden State Warriors",
                "away_team": "Dallas Mavericks",
            },
            "bos-lal-demo": {
                "game_id": "bos-lal-demo",
                "status": "scheduled",
                "tipoff": "8:00 PM ET",
                "broadcast": "ABC",
                "arena": "Crypto.com Arena",
                "headline": "Five-out spacing pressure against a star-driven interior matchup.",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
            },
            "den-phx-demo": {
                "game_id": "den-phx-demo",
                "status": "scheduled",
                "tipoff": "10:00 PM ET",
                "broadcast": "TNT",
                "arena": "Footprint Center",
                "headline": "Jokic hub offense against midrange shotmaking and late-switch counters.",
                "home_team": "Phoenix Suns",
                "away_team": "Denver Nuggets",
            },
        }

    def _build_context(self, **kwargs) -> GameContext:
        return GameContext(**kwargs)

    async def list_live_games(self) -> list[dict]:
        return [
            {
                "game_id": game_id,
                "matchup": f"{context.away_team.team_name} at {context.home_team.team_name}",
                "quarter": context.quarter,
                "clock": context.clock,
                "score": f"{context.away_team.score}-{context.home_team.score}",
                "updated_at": datetime.utcnow().isoformat(),
            }
            for game_id, context in self._contexts.items()
        ]

    async def list_slate_games(self) -> list[dict]:
        games = []
        for game_id, slate_row in self._slate.items():
            context = self._contexts[game_id]
            games.append(
                {
                    **slate_row,
                    "home_abbreviation": context.home_team.team_id.upper(),
                    "away_abbreviation": context.away_team.team_id.upper(),
                    "home_record": self._project_record(context.home_team.offensive_rating, context.home_team.defensive_rating),
                    "away_record": self._project_record(context.away_team.offensive_rating, context.away_team.defensive_rating),
                    "prediction_hook": self._build_prediction_hook(context),
                }
            )
        return games

    async def get_game_preview(self, game_id: str) -> dict:
        context = self._contexts[game_id]
        slate = self._slate[game_id]
        return {
            "game_id": game_id,
            "status": slate["status"],
            "tipoff": slate["tipoff"],
            "broadcast": slate["broadcast"],
            "arena": slate["arena"],
            "headline": slate["headline"],
            "home_team": {
                "team_id": context.home_team.team_id,
                "team_name": context.home_team.team_name,
                "coach_name": context.home_team.coach_name,
                "offensive_rating": context.home_team.offensive_rating,
                "defensive_rating": context.home_team.defensive_rating,
                "pace": context.home_team.pace,
                "three_point_rate": context.home_team.three_point_rate,
                "bench_depth": context.home_team.bench_depth,
            },
            "away_team": {
                "team_id": context.away_team.team_id,
                "team_name": context.away_team.team_name,
                "coach_name": context.away_team.coach_name,
                "offensive_rating": context.away_team.offensive_rating,
                "defensive_rating": context.away_team.defensive_rating,
                "pace": context.away_team.pace,
                "three_point_rate": context.away_team.three_point_rate,
                "bench_depth": context.away_team.bench_depth,
            },
            "players_to_watch": [
                {
                    "player_id": player.player_id,
                    "player_name": player.player_name,
                    "team_id": player.team_id,
                    "usage_rate": player.usage_rate,
                    "momentum_score": player.momentum_score,
                    "fatigue_index": player.fatigue_index,
                    "matchup_difficulty": player.matchup_difficulty,
                }
                for player in context.home_team.players + context.away_team.players
            ],
            "game_factors": [
                "pace pressure",
                "lineup staggering",
                "half-court shot creation",
                "weak-side help timing",
                "back-to-back fatigue" if context.back_to_back else "rest advantage",
            ],
            "prediction_summary": self._build_prediction_hook(context),
        }

    async def get_game_snapshot(self, game_id: str) -> GameSnapshot:
        context = self._contexts[game_id]
        return projection_service.build_snapshot(context)

    async def get_player_detail(self, game_id: str, player_id: str) -> PlayerDetailResponse:
        context = self._contexts[game_id]
        snapshot = projection_service.build_snapshot(context)
        projection = next(player for player in snapshot.player_projections if player.player_id == player_id)

        if projection.team_id == context.home_team.team_id:
            team = context.home_team
            opponent = context.away_team
        else:
            team = context.away_team
            opponent = context.home_team

        stat_mean = projection.projected_stats.mean
        quarter_breakdown = [
            PlayerQuarterProjection(
                quarter="Q1",
                points=round(stat_mean.points * 0.27, 1),
                assists=round(stat_mean.assists * 0.24, 1),
                rebounds=round(stat_mean.rebounds * 0.24, 1),
                threes_made=round(stat_mean.threes_made * 0.28, 1),
            ),
            PlayerQuarterProjection(
                quarter="Q2",
                points=round(stat_mean.points * 0.23, 1),
                assists=round(stat_mean.assists * 0.22, 1),
                rebounds=round(stat_mean.rebounds * 0.22, 1),
                threes_made=round(stat_mean.threes_made * 0.22, 1),
            ),
            PlayerQuarterProjection(
                quarter="Q3",
                points=round(stat_mean.points * 0.24, 1),
                assists=round(stat_mean.assists * 0.25, 1),
                rebounds=round(stat_mean.rebounds * 0.25, 1),
                threes_made=round(stat_mean.threes_made * 0.24, 1),
            ),
            PlayerQuarterProjection(
                quarter="Q4",
                points=round(stat_mean.points * 0.26, 1),
                assists=round(stat_mean.assists * 0.29, 1),
                rebounds=round(stat_mean.rebounds * 0.29, 1),
                threes_made=round(stat_mean.threes_made * 0.26, 1),
            ),
        ]

        return PlayerDetailResponse(
            game_id=game_id,
            player_id=projection.player_id,
            player_name=projection.player_name,
            team_id=projection.team_id,
            team_name=team.team_name,
            opponent_team_name=opponent.team_name,
            coach_counter_summary=(
                f"{opponent.coach_name} is the most likely coach to bend coverages around {projection.player_name}, "
                "changing help location, ball-screen coverage, and late-clock matchup assignments."
            ),
            projection=projection,
            quarter_breakdown=quarter_breakdown,
            stat_profile=[
                {"label": "Points", "live": projection.live_stats.points, "projected": stat_mean.points},
                {"label": "Assists", "live": projection.live_stats.assists, "projected": stat_mean.assists},
                {"label": "Rebounds", "live": projection.live_stats.rebounds, "projected": stat_mean.rebounds},
                {"label": "3PM", "live": projection.live_stats.threes_made, "projected": stat_mean.threes_made},
                {"label": "Turnovers", "live": projection.live_stats.turnovers, "projected": stat_mean.turnovers},
            ],
            matchup_factors=[
                f"Usage load at {(stat_mean.usage_rate * 100):.0f}%",
                f"{opponent.team_name} defensive rating {opponent.defensive_rating}",
                f"{team.coach_name} pace baseline {team.pace}",
                "weak-side help timing",
                "rotation staggering leverage",
            ],
            confidence={
                "floor_points": projection.projected_stats.low.points,
                "median_points": projection.projected_stats.mean.points,
                "ceiling_points": projection.projected_stats.high.points,
                "pressure": projection.defensive_pressure,
            },
            player_insights=[
                {
                    "title": "Scoring Shape",
                    "body": (
                        f"{projection.player_name}'s projection is being driven by a high on-ball creation load, "
                        "with the biggest value coming from early-clock paint touches and pull-up shot quality."
                    ),
                    "severity": "advantage",
                },
                {
                    "title": "Defensive Response",
                    "body": (
                        f"{opponent.coach_name} is expected to vary help position and screen coverage once "
                        f"{projection.player_name} strings together efficient touch sequences."
                    ),
                    "severity": "warning",
                },
                {
                    "title": "Playmaking Spillover",
                    "body": (
                        "If the defense sends two to the ball, the projection shifts some scoring equity into assists "
                        "and weak-side creation for teammates."
                    ),
                    "severity": "info",
                },
            ],
        )

    async def simulate_matchup(self, home_team: str, away_team: str, strategy_tags: list[str]) -> SimulationResponse:
        context = next(iter(self._contexts.values()))
        base_adjustments = coaching_engine.build_team_level_adjustments(context, context.home_team)
        extra = []
        if "switch-everything" in strategy_tags:
            extra.append(
                {
                    "title": "Switch-Everything Closing Group",
                    "side": "defense",
                    "trigger": "User strategy override",
                    "explanation": "The defense trades rebounding risk for isolation suppression and ball-pressure continuity.",
                    "counters": ["switch 1-5", "late scram on post mismatch"],
                    "impact": {"field_goal_pct_allowed": -0.02, "defensive_rebound_pct": -0.03},
                }
            )

        return SimulationResponse(
            summary=(
                f"{home_team} projects as the slightly stronger half-court environment, but {away_team} retains a live-upside path "
                "if its lead creator wins the paint-touch battle and forces repeated low-man help."
            ),
            home_win_probability=0.57,
            away_win_probability=0.43,
            projected_score={home_team: 118, away_team: 113},
            key_adjustments=base_adjustments + extra,
            player_edges=[
                {
                    "title": "Primary Creator Leverage",
                    "body": "When the weak-side wing tags early, the ball-handler's scoring dips but corner assist equity spikes.",
                    "severity": "info",
                },
                {
                    "title": "Second Unit Swing",
                    "body": "Bench spacing quality is the biggest variable in quarter-to-quarter scoring swings for this matchup.",
                    "severity": "advantage",
                },
            ],
        )

    def _project_record(self, offensive_rating: float, defensive_rating: float) -> str:
        wins = round(41 + (offensive_rating - defensive_rating) * 1.8)
        wins = max(22, min(61, wins))
        return f"{wins}-{82 - wins}"

    def _build_prediction_hook(self, context: GameContext) -> str:
        lead_creator = max(
            context.home_team.players + context.away_team.players,
            key=lambda player: player.usage_rate + player.momentum_score,
        )
        return (
            f"{lead_creator.player_name} is the primary leverage point. BallPredict expects "
            f"{context.home_team.coach_name if lead_creator.team_id == context.away_team.team_id else context.away_team.coach_name} "
            "to adjust shell help, screen coverage, and rotation staggering around that usage load."
        )


live_game_service = LiveGameService()
