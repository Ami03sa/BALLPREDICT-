"""Tests for CoachingAdjustmentEngine — player and team-level adjustments."""
import pytest
from app.simulation.coaching_engine import CoachingAdjustmentEngine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


def _team(team_id="gsw", score=50, bench_depth=0.55):
    return TeamGameState(
        team_id=team_id,
        team_name="Warriors",
        coach_name="Kerr",
        score=score,
        pace=100.0,
        offensive_rating=115.0,
        defensive_rating=113.0,
        defensive_rebound_pct=0.72,
        turnover_rate=0.13,
        three_point_rate=0.44,
        free_throw_rate=0.22,
        foul_pressure=0.40,
        bench_depth=bench_depth,
        adjustment_discipline=0.75,
    )


def _context(score_margin=6, quarter=2, fatigue=0.35, playoff=0.55):
    return GameContext(
        game_id="demo",
        quarter=quarter,
        clock="08:00",
        home_team=_team("gsw", 56),
        away_team=_team("dal", 50),
        score_margin=score_margin,
        home_advantage=2.4,
        overtime_probability=0.05,
        momentum=0.6,
        fatigue_pressure=fatigue,
        whistle_tightness=0.48,
        playoff_intensity=playoff,
        live_pace_multiplier=1.02,
    )


def _player(
    player_id="p1",
    team_id="gsw",
    points=15.0,
    usage=0.30,
    momentum=0.75,
    threes=2,
    three_pct=0.42,
    drive_freq=0.20,
    paint=6,
    fouls=2,
):
    return PlayerGameState(
        player_id=player_id,
        player_name="Curry",
        team_id=team_id,
        usage_rate=usage,
        points=points,
        assists=5.0,
        rebounds=4.0,
        threes_made=threes,
        three_point_pct=three_pct,
        drive_frequency=drive_freq,
        paint_touches=paint,
        momentum_score=momentum,
        foul_count=fouls,
    )


engine = CoachingAdjustmentEngine()


class TestBuildPlayerCounters:
    def test_hot_high_usage_triggers_blitz(self):
        ctx = _context()
        player = _player(points=15, usage=0.35, momentum=0.80, threes=2)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Blitz Primary Action" in titles

    def test_shooter_gravity_triggers_top_lock(self):
        ctx = _context()
        player = _player(points=5, usage=0.20, momentum=0.50, threes=3, three_pct=0.44)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Top-Lock Off-Ball Actions" in titles

    def test_downhill_pressure_shrinks_floor(self):
        ctx = _context()
        player = _player(points=8, usage=0.25, momentum=0.55, drive_freq=0.25, paint=7)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Shrink the Floor" in titles

    def test_foul_trouble_triggers_rotation_protection(self):
        ctx = _context(quarter=2)
        player = _player(fouls=3, usage=0.28, points=10, momentum=0.60)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Rotation Protection" in titles

    def test_blowout_lead_triggers_tempo_control(self):
        ctx = _context(score_margin=10, quarter=3)
        player = _player(points=5, usage=0.20, momentum=0.50, threes=0)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Tempo Control" in titles

    def test_cold_player_no_blitz(self):
        ctx = _context()
        player = _player(points=2, usage=0.15, momentum=0.30, threes=0, three_pct=0.25)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        titles = [a.title for a in adjustments]
        assert "Blitz Primary Action" not in titles

    def test_returns_list_of_coaching_adjustments(self):
        ctx = _context()
        player = _player(points=20, usage=0.38, momentum=0.86, threes=3, drive_freq=0.25, paint=7)
        adjustments = engine.build_player_counters(ctx, ctx.home_team, ctx.away_team, player)
        assert len(adjustments) >= 3
        for adj in adjustments:
            assert adj.side in {"offense", "defense", "rotation", "pace"}


class TestBuildTeamLevelAdjustments:
    def test_shallow_bench_plus_fatigue(self):
        ctx = _context(fatigue=0.65)
        shallow_team = _team(bench_depth=0.40)
        adjustments = engine.build_team_level_adjustments(ctx, shallow_team)
        titles = [a.title for a in adjustments]
        assert "Extended Starter Stagger" in titles

    def test_playoff_intensity_triggers_compression(self):
        ctx = _context(playoff=0.75)
        adjustments = engine.build_team_level_adjustments(ctx, _team())
        titles = [a.title for a in adjustments]
        assert "Playoff Matchup Compression" in titles

    def test_normal_conditions_no_adjustments(self):
        ctx = _context(fatigue=0.30, playoff=0.50)
        adjustments = engine.build_team_level_adjustments(ctx, _team(bench_depth=0.60))
        assert adjustments == []
