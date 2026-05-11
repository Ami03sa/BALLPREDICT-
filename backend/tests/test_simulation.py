from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


def _build_context() -> GameContext:
    home = TeamGameState(
        team_id="gsw",
        team_name="Golden State Warriors",
        coach_name="Steve Kerr",
        score=28,
        pace=101.1,
        offensive_rating=117.0,
        defensive_rating=113.5,
        defensive_rebound_pct=0.73,
        turnover_rate=0.13,
        three_point_rate=0.46,
        free_throw_rate=0.21,
        foul_pressure=0.41,
        bench_depth=0.56,
        adjustment_discipline=0.79,
    )
    away = TeamGameState(
        team_id="dal",
        team_name="Dallas Mavericks",
        coach_name="Jason Kidd",
        score=34,
        pace=99.6,
        offensive_rating=118.4,
        defensive_rating=114.4,
        defensive_rebound_pct=0.74,
        turnover_rate=0.12,
        three_point_rate=0.43,
        free_throw_rate=0.22,
        foul_pressure=0.37,
        bench_depth=0.49,
        adjustment_discipline=0.67,
    )
    return GameContext(
        game_id="demo",
        quarter=1,
        clock="03:12",
        home_team=home,
        away_team=away,
        score_margin=-6,
        home_advantage=2.5,
        overtime_probability=0.09,
        momentum=0.7,
        fatigue_pressure=0.32,
        whistle_tightness=0.5,
        playoff_intensity=0.6,
        live_pace_multiplier=1.05,
    )


def test_hot_player_generates_multiple_adjustments() -> None:
    context = _build_context()
    luka = PlayerGameState(
        player_id="luka",
        player_name="Luka Doncic",
        team_id="dal",
        usage_rate=0.38,
        points=15,
        assists=4,
        rebounds=3,
        threes_made=2,
        field_goal_pct=0.61,
        three_point_pct=0.44,
        momentum_score=0.86,
        drive_frequency=0.25,
        paint_touches=7,
    )

    adjustments = coaching_engine.build_player_counters(context, context.away_team, context.home_team, luka)

    assert len(adjustments) >= 3
    assert any(adjustment.title == "Blitz Primary Action" for adjustment in adjustments)

