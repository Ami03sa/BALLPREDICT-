from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.schemas.game import GameSnapshot, PlayerDetailResponse, PlayerQuarterProjection, SimulationResponse
from app.services.projection_service import projection_service
from app.services.providers.nba_live_client import nba_live_client
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
                        threes_made=0,
                        field_goal_pct=0.45,
                        three_point_pct=0.39,
                        fatigue_index=0.11,
                        momentum_score=0.49,
                        matchup_difficulty=0.52,
                        drive_frequency=0.08,
                        paint_touches=1,
                    ),
                    PlayerGameState(
                        player_id="looney",
                        player_name="Kevon Looney",
                        team_id="gsw",
                        usage_rate=0.09,
                        rotation_role="bench",
                        field_goal_pct=0.57,
                        three_point_pct=0.0,
                        fatigue_index=0.12,
                        momentum_score=0.34,
                        matchup_difficulty=0.48,
                        drive_frequency=0.06,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="moody",
                        player_name="Moses Moody",
                        team_id="gsw",
                        usage_rate=0.10,
                        rotation_role="bench",
                        field_goal_pct=0.44,
                        three_point_pct=0.37,
                        fatigue_index=0.11,
                        momentum_score=0.36,
                        matchup_difficulty=0.47,
                        drive_frequency=0.09,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="kuminga",
                        player_name="Jonathan Kuminga",
                        team_id="gsw",
                        usage_rate=0.12,
                        rotation_role="bench",
                        field_goal_pct=0.48,
                        three_point_pct=0.31,
                        fatigue_index=0.11,
                        momentum_score=0.40,
                        matchup_difficulty=0.50,
                        drive_frequency=0.16,
                        paint_touches=4,
                    ),
                    PlayerGameState(
                        player_id="santos",
                        player_name="Gui Santos",
                        team_id="gsw",
                        usage_rate=0.06,
                        rotation_role="bench",
                        field_goal_pct=0.43,
                        three_point_pct=0.34,
                        fatigue_index=0.10,
                        momentum_score=0.28,
                        matchup_difficulty=0.46,
                        drive_frequency=0.08,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="spencer",
                        player_name="Pat Spencer",
                        team_id="gsw",
                        usage_rate=0.03,
                        rotation_role="bench",
                        field_goal_pct=0.40,
                        three_point_pct=0.30,
                        fatigue_index=0.09,
                        momentum_score=0.20,
                        matchup_difficulty=0.44,
                        drive_frequency=0.08,
                        paint_touches=1,
                    ),
                    PlayerGameState(
                        player_id="post",
                        player_name="Quinten Post",
                        team_id="gsw",
                        usage_rate=0.04,
                        rotation_role="bench",
                        field_goal_pct=0.42,
                        three_point_pct=0.33,
                        fatigue_index=0.09,
                        momentum_score=0.22,
                        matchup_difficulty=0.45,
                        drive_frequency=0.05,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="payton",
                        player_name="Gary Payton II",
                        team_id="gsw",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Coach's Decision",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="jackson-davis",
                        player_name="Trayce Jackson-Davis",
                        team_id="gsw",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Coach's Decision",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="waters",
                        player_name="Lindy Waters III",
                        team_id="gsw",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Inactive",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="slomo",
                        player_name="Kyle Anderson",
                        team_id="gsw",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Inactive",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
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
                        rotation_role="starter",
                        field_goal_pct=0.46,
                        three_point_pct=0.36,
                        fatigue_index=0.12,
                        momentum_score=0.45,
                        matchup_difficulty=0.50,
                        drive_frequency=0.11,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="marshall",
                        player_name="Naji Marshall",
                        team_id="dal",
                        usage_rate=0.10,
                        rotation_role="bench",
                        field_goal_pct=0.46,
                        three_point_pct=0.33,
                        fatigue_index=0.11,
                        momentum_score=0.35,
                        matchup_difficulty=0.47,
                        drive_frequency=0.11,
                        paint_touches=3,
                    ),
                    PlayerGameState(
                        player_id="lively",
                        player_name="Dereck Lively II",
                        team_id="dal",
                        usage_rate=0.09,
                        rotation_role="bench",
                        field_goal_pct=0.62,
                        three_point_pct=0.0,
                        fatigue_index=0.12,
                        momentum_score=0.31,
                        matchup_difficulty=0.44,
                        drive_frequency=0.05,
                        paint_touches=5,
                    ),
                    PlayerGameState(
                        player_id="hardy",
                        player_name="Jaden Hardy",
                        team_id="dal",
                        usage_rate=0.08,
                        rotation_role="bench",
                        field_goal_pct=0.43,
                        three_point_pct=0.35,
                        fatigue_index=0.10,
                        momentum_score=0.29,
                        matchup_difficulty=0.46,
                        drive_frequency=0.10,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="powell",
                        player_name="Dwight Powell",
                        team_id="dal",
                        usage_rate=0.04,
                        rotation_role="bench",
                        field_goal_pct=0.55,
                        three_point_pct=0.0,
                        fatigue_index=0.10,
                        momentum_score=0.21,
                        matchup_difficulty=0.44,
                        drive_frequency=0.05,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="martin",
                        player_name="Caleb Martin",
                        team_id="dal",
                        usage_rate=0.07,
                        rotation_role="bench",
                        field_goal_pct=0.42,
                        three_point_pct=0.34,
                        fatigue_index=0.10,
                        momentum_score=0.27,
                        matchup_difficulty=0.45,
                        drive_frequency=0.08,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="dinwiddie",
                        player_name="Spencer Dinwiddie",
                        team_id="dal",
                        usage_rate=0.08,
                        rotation_role="bench",
                        field_goal_pct=0.41,
                        three_point_pct=0.35,
                        fatigue_index=0.10,
                        momentum_score=0.30,
                        matchup_difficulty=0.46,
                        drive_frequency=0.10,
                        paint_touches=2,
                    ),
                    PlayerGameState(
                        player_id="exum",
                        player_name="Dante Exum",
                        team_id="dal",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Injury Management",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="christie",
                        player_name="Max Christie",
                        team_id="dal",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Coach's Decision",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="omax",
                        player_name="Olivier-Maxence Prosper",
                        team_id="dal",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Coach's Decision",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="lawson",
                        player_name="A.J. Lawson",
                        team_id="dal",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Inactive",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
                    ),
                    PlayerGameState(
                        player_id="edwards",
                        player_name="Kessler Edwards",
                        team_id="dal",
                        usage_rate=0.0,
                        rotation_role="dnp",
                        availability_status="dnp",
                        dnp_reason="Inactive",
                        field_goal_pct=0.0,
                        three_point_pct=0.0,
                        fatigue_index=0.08,
                        momentum_score=0.08,
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
        try:
            scoreboard = await nba_live_client.fetch_scoreboard()
            return [
                {
                    "game_id": str(game["gameId"]),
                    "matchup": f"{self._team_display_name(game['awayTeam'])} at {self._team_display_name(game['homeTeam'])}",
                    "quarter": int(game.get("period") or 0),
                    "clock": self._format_clock(game.get("gameClock", "")),
                    "score": f"{game['awayTeam'].get('score', 0)}-{game['homeTeam'].get('score', 0)}",
                    "updated_at": datetime.utcnow().isoformat(),
                }
                for game in scoreboard.get("scoreboard", {}).get("games", [])
                if int(game.get("gameStatus", 0)) >= 2
            ]
        except (httpx.HTTPError, KeyError, ValueError):
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
        try:
            scoreboard = await nba_live_client.fetch_scoreboard()
            games = scoreboard.get("scoreboard", {}).get("games", [])
            return [self._build_live_slate_row(game) for game in games]
        except (httpx.HTTPError, KeyError, ValueError):
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
        try:
            context, scoreboard_game, _, _ = await self._build_live_context_bundle(game_id)
            return self._build_preview_payload(context, self._build_live_slate_row(scoreboard_game))
        except (httpx.HTTPError, KeyError, ValueError, StopIteration):
            context = self._contexts[game_id]
            slate = self._slate[game_id]
            return self._build_preview_payload(context, slate)

    async def get_game_snapshot(self, game_id: str) -> GameSnapshot:
        try:
            context, scoreboard_game, _, playbyplay = await self._build_live_context_bundle(game_id)
            return projection_service.build_snapshot(
                context,
                status=self._status_label(scoreboard_game.get("gameStatus")),
                possession_feed=self._build_live_possession_feed(playbyplay),
            )
        except (httpx.HTTPError, KeyError, ValueError, StopIteration):
            context = self._contexts[game_id]
            return projection_service.build_snapshot(context, status="demo")

    async def get_player_detail(self, game_id: str, player_id: str) -> PlayerDetailResponse:
        try:
            context, scoreboard_game, _, playbyplay = await self._build_live_context_bundle(game_id)
            snapshot = projection_service.build_snapshot(
                context,
                status=self._status_label(scoreboard_game.get("gameStatus")),
                possession_feed=self._build_live_possession_feed(playbyplay),
            )
            return self._build_player_detail_payload(game_id, player_id, context, snapshot)
        except (httpx.HTTPError, KeyError, ValueError, StopIteration):
            context = self._contexts[game_id]
            snapshot = projection_service.build_snapshot(context, status="demo")
            return self._build_player_detail_payload(game_id, player_id, context, snapshot)

    async def _build_live_context_bundle(self, game_id: str) -> tuple[GameContext, dict[str, Any], dict[str, Any], dict[str, Any]]:
        scoreboard = await nba_live_client.fetch_scoreboard()
        games = scoreboard.get("scoreboard", {}).get("games", [])
        scoreboard_game = next(game for game in games if str(game.get("gameId")) == str(game_id))
        boxscore = await nba_live_client.fetch_boxscore(str(game_id))
        try:
            playbyplay = await nba_live_client.fetch_playbyplay(str(game_id))
        except httpx.HTTPError:
            playbyplay = {}
        context = self._build_live_context(scoreboard_game, boxscore)
        return context, scoreboard_game, boxscore, playbyplay

    def _build_live_context(self, scoreboard_game: dict[str, Any], boxscore: dict[str, Any]) -> GameContext:
        game = boxscore.get("game", {})
        home_payload = game.get("homeTeam") or scoreboard_game.get("homeTeam", {})
        away_payload = game.get("awayTeam") or scoreboard_game.get("awayTeam", {})

        home_team = self._build_live_team_state(home_payload, away_payload)
        away_team = self._build_live_team_state(away_payload, home_payload)
        quarter = int(scoreboard_game.get("period") or game.get("period") or 0)
        clock = self._format_clock(scoreboard_game.get("gameClock", ""))
        score_margin = home_team.score - away_team.score
        pace_multiplier = self._estimate_live_pace_multiplier(home_payload, away_payload, quarter)

        return GameContext(
            game_id=str(scoreboard_game.get("gameId")),
            quarter=quarter,
            clock=clock,
            home_team=home_team,
            away_team=away_team,
            score_margin=score_margin,
            home_advantage=2.4,
            overtime_probability=0.05 if abs(score_margin) <= 5 and quarter >= 4 else 0.02,
            momentum=self._estimate_momentum(home_team.score, away_team.score),
            fatigue_pressure=min(0.75, self._average_fatigue(home_team.players + away_team.players) + quarter * 0.05),
            whistle_tightness=0.48,
            playoff_intensity=0.68 if "Conf." in (scoreboard_game.get("gameLabel") or "") else 0.54,
            live_pace_multiplier=pace_multiplier,
            injury_risk_flags=[],
            back_to_back=False,
        )

    def _build_live_team_state(self, team_payload: dict[str, Any], opponent_payload: dict[str, Any]) -> TeamGameState:
        team_stats = team_payload.get("statistics", {})
        opponent_stats = opponent_payload.get("statistics", {})
        team_possessions = max(1.0, self._estimate_possessions(team_stats))
        opponent_possessions = max(1.0, self._estimate_possessions(opponent_stats))
        players = self._build_live_players(team_payload, team_possessions)
        score = int(team_payload.get("score") or 0)
        opponent_score = int(opponent_payload.get("score") or 0)
        pace = round(96 + min(12, team_possessions * 0.45), 1)
        offensive_rating = round((score / team_possessions) * 100, 1) if score > 0 else 114.0
        defensive_rating = round((opponent_score / opponent_possessions) * 100, 1) if opponent_score > 0 else 113.5
        team_actions = max(1.0, self._safe_float(team_stats.get("fieldGoalsAttempted")) + 0.44 * self._safe_float(team_stats.get("freeThrowsAttempted")) + self._safe_float(team_stats.get("turnoversTotal") or team_stats.get("turnovers")))
        three_point_rate = self._safe_float(team_stats.get("threePointersAttempted")) / max(1.0, self._safe_float(team_stats.get("fieldGoalsAttempted")))
        free_throw_rate = self._safe_float(team_stats.get("freeThrowsAttempted")) / max(1.0, self._safe_float(team_stats.get("fieldGoalsAttempted")))
        defensive_rebound_pct = self._safe_float(team_stats.get("reboundsDefensive")) / max(
            1.0,
            self._safe_float(team_stats.get("reboundsDefensive")) + self._safe_float(opponent_stats.get("reboundsOffensive")),
        )

        return TeamGameState(
            team_id=str(team_payload.get("teamTricode") or team_payload.get("teamId") or "").lower(),
            team_name=self._team_display_name(team_payload),
            coach_name=f"{self._team_display_name(team_payload)} Staff",
            score=score,
            pace=pace,
            offensive_rating=offensive_rating,
            defensive_rating=defensive_rating,
            defensive_rebound_pct=round(defensive_rebound_pct, 3),
            turnover_rate=round(self._safe_float(team_stats.get("turnoversTotal") or team_stats.get("turnovers")) / team_actions, 3),
            three_point_rate=round(three_point_rate, 3),
            free_throw_rate=round(free_throw_rate, 3),
            foul_pressure=round(self._safe_float(team_stats.get("foulsPersonal")) / 25.0, 3),
            bench_depth=round(self._estimate_bench_depth(players), 3),
            adjustment_discipline=0.62,
            players=players,
        )

    def _build_live_players(self, team_payload: dict[str, Any], team_possessions: float) -> list[PlayerGameState]:
        players: list[PlayerGameState] = []
        raw_players = team_payload.get("players", [])
        team_actions = sum(
            self._safe_float(player.get("statistics", {}).get("fieldGoalsAttempted"))
            + 0.44 * self._safe_float(player.get("statistics", {}).get("freeThrowsAttempted"))
            + self._safe_float(player.get("statistics", {}).get("turnovers"))
            for player in raw_players
        )
        team_actions = max(1.0, team_actions)

        for player in raw_players:
            stats = player.get("statistics", {})
            name = (
                stats.get("name")
                or player.get("name")
                or " ".join(filter(None, [stats.get("firstName"), stats.get("familyName")]))
                or "Unknown Player"
            )
            played = player.get("played") or self._safe_float(stats.get("minutes"))
            not_playing_reason = player.get("notPlayingReason")
            not_playing_description = player.get("notPlayingDescription")
            availability_status = "dnp" if not played and (not_playing_reason or not_playing_description) else "available"
            starter_flag = player.get("starter")
            rotation_role = "starter" if starter_flag else "bench"
            if availability_status == "dnp":
                rotation_role = "dnp"

            field_goal_pct = self._normalize_pct(stats.get("fieldGoalsPercentage"), 0.45)
            three_point_pct = self._normalize_pct(stats.get("threePointersPercentage"), 0.36)
            minutes_played = self._parse_minutes(stats.get("minutes") or stats.get("minutesCalculated"))
            player_actions = (
                self._safe_float(stats.get("fieldGoalsAttempted"))
                + 0.44 * self._safe_float(stats.get("freeThrowsAttempted"))
                + self._safe_float(stats.get("turnovers"))
            )
            usage_rate = max(0.08, min(0.42, player_actions / team_actions))
            paint_proxy = self._safe_float(stats.get("twoPointersMade")) + self._safe_float(stats.get("freeThrowsAttempted")) * 0.3
            drive_frequency = min(0.34, paint_proxy / max(1.0, player_actions + 2))
            momentum = min(
                0.95,
                0.35
                + self._safe_float(stats.get("points")) / 40.0
                + self._safe_float(stats.get("threePointersMade")) * 0.04
                + field_goal_pct * 0.08,
            )

            players.append(
                PlayerGameState(
                    player_id=str(player.get("personId") or player.get("person_id") or name.lower().replace(" ", "-")),
                    player_name=name,
                    team_id=str(team_payload.get("teamTricode") or team_payload.get("teamId") or "").lower(),
                    usage_rate=round(usage_rate, 3),
                    rotation_role=rotation_role,
                    availability_status=availability_status,
                    dnp_reason=not_playing_description or not_playing_reason,
                    points=self._safe_float(stats.get("points")),
                    assists=self._safe_float(stats.get("assists")),
                    rebounds=self._safe_float(stats.get("reboundsTotal")),
                    steals=self._safe_float(stats.get("steals")),
                    blocks=self._safe_float(stats.get("blocks")),
                    turnovers=self._safe_float(stats.get("turnovers")),
                    threes_made=self._safe_float(stats.get("threePointersMade")),
                    field_goal_pct=field_goal_pct,
                    three_point_pct=three_point_pct,
                    minutes_played=minutes_played,
                    fatigue_index=min(0.88, 0.1 + minutes_played / 48.0 + self._safe_float(stats.get("foulsPersonal")) * 0.03),
                    foul_count=int(self._safe_float(stats.get("foulsPersonal"))),
                    matchup_difficulty=min(0.9, 0.42 + self._safe_float(stats.get("turnovers")) * 0.03),
                    momentum_score=momentum,
                    touch_time=5.5 + usage_rate * 8,
                    drive_frequency=round(drive_frequency, 3),
                    paint_touches=max(1, round(paint_proxy)),
                )
            )

        return players

    def _build_preview_payload(self, context: GameContext, slate_row: dict[str, Any]) -> dict[str, Any]:
        players = sorted(
            context.home_team.players + context.away_team.players,
            key=lambda player: (player.usage_rate, player.momentum_score, player.points),
            reverse=True,
        )[:8]
        return {
            "game_id": slate_row["game_id"],
            "status": slate_row["status"],
            "tipoff": slate_row["tipoff"],
            "broadcast": slate_row["broadcast"],
            "arena": slate_row["arena"],
            "headline": slate_row["headline"],
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
                for player in players
            ],
            "game_factors": [
                "live pace pressure" if context.quarter > 0 else "pregame pace pressure",
                "lineup staggering",
                "half-court shot creation",
                "weak-side help timing",
                "late-game leverage" if context.quarter >= 4 else "opening rotation stability",
            ],
            "prediction_summary": self._build_prediction_hook(context),
        }

    def _build_player_detail_payload(
        self,
        game_id: str,
        player_id: str,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> PlayerDetailResponse:
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
                f"{opponent.coach_name} is the most likely coaching staff to bend coverages around {projection.player_name}, "
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

    def _build_live_slate_row(self, game: dict[str, Any]) -> dict[str, Any]:
        home_team = game.get("homeTeam", {})
        away_team = game.get("awayTeam", {})
        leaders = game.get("gameLeaders", {})
        home_leader = leaders.get("homeLeaders", {})
        away_leader = leaders.get("awayLeaders", {})
        headline = (
            f"{away_leader.get('name', self._team_display_name(away_team))} vs. "
            f"{home_leader.get('name', self._team_display_name(home_team))} shapes the live tactical story."
        )
        return {
            "game_id": str(game.get("gameId")),
            "status": self._status_label(game.get("gameStatus")),
            "tipoff": self._format_tipoff(game),
            "broadcast": self._extract_broadcast(game),
            "arena": self._extract_arena(game),
            "headline": headline,
            "home_team": self._team_display_name(home_team),
            "away_team": self._team_display_name(away_team),
            "home_abbreviation": str(home_team.get("teamTricode", "")).upper(),
            "away_abbreviation": str(away_team.get("teamTricode", "")).upper(),
            "home_record": f"{home_team.get('wins', 0)}-{home_team.get('losses', 0)}",
            "away_record": f"{away_team.get('wins', 0)}-{away_team.get('losses', 0)}",
            "prediction_hook": self._build_live_prediction_hook(home_leader, away_leader, home_team, away_team),
        }

    def _build_live_prediction_hook(
        self,
        home_leader: dict[str, Any],
        away_leader: dict[str, Any],
        home_team: dict[str, Any],
        away_team: dict[str, Any],
    ) -> str:
        away_name = away_leader.get("name") or self._team_display_name(away_team)
        home_name = home_leader.get("name") or self._team_display_name(home_team)
        return (
            f"{away_name} and {home_name} are the first leverage points. BallPredict will reshape projected efficiency, "
            "pace, and teammate creation once the live usage and scoring burden becomes clear."
        )

    def _build_live_possession_feed(self, playbyplay: dict[str, Any]) -> list[dict]:
        actions = playbyplay.get("game", {}).get("actions", [])
        feed: list[dict] = []
        for action in actions[-6:]:
            summary = action.get("description") or f"{action.get('playerName', 'Team')} {action.get('actionType', 'action')}"
            feed.append(
                {
                    "quarter": int(action.get("period") or 0),
                    "clock": self._format_clock(action.get("clock", "")),
                    "summary": summary,
                    "leverage": self._action_leverage(action),
                }
            )
        return list(reversed(feed))

    def _action_leverage(self, action: dict[str, Any]) -> str:
        period = int(action.get("period") or 0)
        action_type = str(action.get("actionType", "")).lower()
        if period >= 4 or action_type in {"turnover", "foul", "made shot", "rebound"}:
            return "high"
        if action_type in {"missed shot", "substitution"}:
            return "medium"
        return "low"

    def _status_label(self, game_status: Any) -> str:
        status_int = int(game_status or 0)
        if status_int <= 1:
            return "scheduled"
        if status_int == 2:
            return "live"
        return "final"

    def _format_tipoff(self, game: dict[str, Any]) -> str:
        raw = game.get("gameEt") or game.get("gameTimeUTC")
        if not raw:
            return "TBD"
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed.strftime("%-I:%M %p ET")
        except ValueError:
            return str(raw)

    def _extract_broadcast(self, game: dict[str, Any]) -> str:
        for key in ("natlTvBroadcasters", "broadcasters", "watch"):
            value = game.get(key)
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    return first.get("broadcasterDisplay") or first.get("longName") or first.get("shortName") or "League Pass"
                return str(first)
            if isinstance(value, dict):
                return value.get("broadcasterDisplay") or value.get("longName") or value.get("shortName") or "League Pass"
        return "League Pass"

    def _extract_arena(self, game: dict[str, Any]) -> str:
        arena = game.get("arena") or {}
        if isinstance(arena, dict):
            return arena.get("arenaName") or "NBA Arena"
        return game.get("gameLabel") or "NBA Arena"

    def _team_display_name(self, team_payload: dict[str, Any]) -> str:
        city = str(team_payload.get("teamCity") or "").strip()
        name = str(team_payload.get("teamName") or "").strip()
        if city and name and city not in name:
            return f"{city} {name}"
        return name or city or str(team_payload.get("teamTricode") or "NBA Team")

    def _format_clock(self, raw_clock: str) -> str:
        if not raw_clock:
            return "12:00"
        if raw_clock.startswith("PT"):
            cleaned = raw_clock.replace("PT", "").replace("M", ":").replace(".00S", "").replace("S", "")
            minutes, _, seconds = cleaned.partition(":")
            return f"{minutes.zfill(2)}:{seconds.zfill(2)}"
        return raw_clock

    def _normalize_pct(self, value: Any, default: float) -> float:
        pct = self._safe_float(value)
        if pct <= 0:
            return default
        return round(pct / 100.0, 3) if pct > 1 else round(pct, 3)

    def _parse_minutes(self, value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value)
        if text.startswith("PT"):
            cleaned = text.replace("PT", "").replace("S", "")
            if "M" in cleaned:
                minutes, seconds = cleaned.split("M", 1)
                seconds = seconds or "0"
                return round(float(minutes) + float(seconds) / 60.0, 2)
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return round(float(minutes) + float(seconds) / 60.0, 2)
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _estimate_possessions(self, team_stats: dict[str, Any]) -> float:
        return (
            self._safe_float(team_stats.get("fieldGoalsAttempted"))
            + 0.44 * self._safe_float(team_stats.get("freeThrowsAttempted"))
            - self._safe_float(team_stats.get("reboundsOffensive"))
            + self._safe_float(team_stats.get("turnoversTotal") or team_stats.get("turnovers"))
        )

    def _estimate_bench_depth(self, players: list[PlayerGameState]) -> float:
        if not players:
            return 0.4
        rotation_players = [player for player in players if player.minutes_played > 0 or player.usage_rate >= 0.12]
        return min(0.75, max(0.35, len(rotation_players) / 15.0))

    def _estimate_live_pace_multiplier(self, home_payload: dict[str, Any], away_payload: dict[str, Any], quarter: int) -> float:
        if quarter <= 0:
            return 1.0
        possessions = (self._estimate_possessions(home_payload.get("statistics", {})) + self._estimate_possessions(away_payload.get("statistics", {}))) / 2
        expected_possessions = max(1.0, quarter * 25)
        return round(max(0.9, min(1.12, possessions / expected_possessions)), 3)

    def _average_fatigue(self, players: list[PlayerGameState]) -> float:
        if not players:
            return 0.2
        return sum(player.fatigue_index for player in players) / len(players)

    def _estimate_momentum(self, home_score: int, away_score: int) -> float:
        total = max(1, home_score + away_score)
        return round(0.5 + abs(home_score - away_score) / total * 0.2, 3)

    def _project_record(self, offensive_rating: float, defensive_rating: float) -> str:
        wins = round(41 + (offensive_rating - defensive_rating) * 1.8)
        wins = max(22, min(61, wins))
        return f"{wins}-{82 - wins}"

    def _build_prediction_hook(self, context: GameContext) -> str:
        if not (context.home_team.players + context.away_team.players):
            return "BallPredict is waiting on live player participation data before locking stronger matchup-specific usage assumptions."
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
