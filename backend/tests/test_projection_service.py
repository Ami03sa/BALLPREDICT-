"""Tests for projection_service helper functions and build_snapshot."""
import pytest

from app.schemas.game import ConfidenceBand, PlayerProjection, StatLine
from app.services.projection_service import (
    ProjectionService,
    _usage_boost,
    _rescale_player_pts,
)
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


def _stat(pts=20.0):
    return StatLine(points=pts, assists=5, rebounds=4)


def _band(pts=20.0):
    return ConfidenceBand(low=_stat(pts - 4), mean=_stat(pts), high=_stat(pts + 6))


def _player_proj(player_id="p1", team_id="gsw", pts=20.0, status="available"):
    return PlayerProjection(
        player_id=player_id,
        player_name="Curry",
        team_id=team_id,
        quarter=2,
        live_stats=_stat(pts),
        projected_stats=_band(pts),
        momentum_score=0.75,
        fatigue_index=0.3,
        defensive_pressure=0.4,
        adjustments=[],
        availability_status=status,
    )


class TestUsageBoost:
    def test_no_dnp_returns_one(self):
        projections = [_player_proj("p1"), _player_proj("p2")]
        assert _usage_boost(projections, {}, {}) == 1.0

    def test_no_active_returns_one(self):
        projections = [_player_proj("p1", status="dnp")]
        assert _usage_boost(projections, {}, {}) == 1.0

    def test_dnp_with_active_boosts(self):
        active = _player_proj("p1", pts=20.0)
        dnp = _player_proj("p2", pts=10.0, status="dnp")
        result = _usage_boost([active, dnp], {}, {})
        assert result > 1.0
        assert result <= 1.25

    def test_cap_at_1_25(self):
        active = _player_proj("p1", pts=5.0)
        dnp1 = _player_proj("p2", pts=30.0, status="dnp")
        dnp2 = _player_proj("p3", pts=30.0, status="dnp")
        result = _usage_boost([active, dnp1, dnp2], {}, {})
        assert result == 1.25

    def test_zero_active_pts_returns_one(self):
        active = _player_proj("p1", pts=0.0)
        dnp = _player_proj("p2", pts=10.0, status="dnp")
        assert _usage_boost([active, dnp], {}, {}) == 1.0


class TestRescalePlayerPts:
    def test_dnp_player_unchanged(self):
        proj = _player_proj(status="dnp", pts=0.0)
        result = _rescale_player_pts(proj, 1.5)
        assert result is proj

    def test_scale_of_one_unchanged(self):
        proj = _player_proj(pts=20.0)
        result = _rescale_player_pts(proj, 1.0)
        assert result is proj

    def test_scale_changes_points(self):
        proj = _player_proj(pts=20.0)
        result = _rescale_player_pts(proj, 1.2)
        assert result.projected_stats.mean.points == round(20.0 * 1.2, 1)
        assert result.projected_stats.low.points == round(16.0 * 1.2, 1)
        assert result.projected_stats.high.points == round(26.0 * 1.2, 1)

    def test_scale_below_one_reduces_points(self):
        proj = _player_proj(pts=20.0)
        result = _rescale_player_pts(proj, 0.8)
        assert result.projected_stats.mean.points < 20.0


def _team(team_id="gsw", score=50):
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
        bench_depth=0.55,
        adjustment_discipline=0.75,
    )


def _player_state(pid="p1", team_id="gsw", pts=15.0):
    return PlayerGameState(
        player_id=pid,
        player_name="Curry",
        team_id=team_id,
        usage_rate=0.30,
        points=pts,
        assists=5.0,
        rebounds=4.0,
        threes_made=3.0,
        field_goal_pct=0.50,
        three_point_pct=0.42,
        minutes_played=20.0,
        fatigue_index=0.30,
        foul_count=2,
        matchup_difficulty=0.50,
        momentum_score=0.75,
        drive_frequency=0.20,
        paint_touches=6,
        pts_avg=18.0,
        ast_avg=5.5,
        reb_avg=4.0,
        fg3m_avg=4.0,
    )


def _context_with_players():
    home = _team("gsw", 50)
    away = _team("dal", 44)
    home.players = [_player_state("p1", "gsw", 18), _player_state("p2", "gsw", 12)]
    away.players = [_player_state("p3", "dal", 22), _player_state("p4", "dal", 15)]
    return GameContext(
        game_id="snap-test",
        quarter=2,
        clock="08:00",
        home_team=home,
        away_team=away,
        score_margin=6,
        home_advantage=2.4,
        overtime_probability=0.05,
        momentum=0.6,
        fatigue_pressure=0.35,
        whistle_tightness=0.48,
        playoff_intensity=0.55,
        live_pace_multiplier=1.02,
    )


class TestBuildSnapshot:
    def test_returns_game_snapshot(self):
        from app.schemas.game import GameSnapshot
        svc = ProjectionService()
        ctx = _context_with_players()
        snap = svc.build_snapshot(ctx, status="live")
        assert isinstance(snap, GameSnapshot)
        assert snap.game_id == "snap-test"
        assert snap.quarter == 2

    def test_player_count_matches_roster(self):
        svc = ProjectionService()
        ctx = _context_with_players()
        snap = svc.build_snapshot(ctx, status="live")
        assert len(snap.player_projections) == 4

    def test_status_final(self):
        from app.schemas.game import GameSnapshot
        svc = ProjectionService()
        ctx = _context_with_players()
        snap = svc.build_snapshot(ctx, status="final")
        assert isinstance(snap, GameSnapshot)

    def test_status_scheduled(self):
        from app.schemas.game import GameSnapshot
        svc = ProjectionService()
        ctx = _context_with_players()
        ctx.quarter = 0
        snap = svc.build_snapshot(ctx, status="scheduled")
        assert isinstance(snap, GameSnapshot)

    def test_no_players_produces_empty_projections(self):
        svc = ProjectionService()
        ctx = _context_with_players()
        ctx.home_team.players = []
        ctx.away_team.players = []
        snap = svc.build_snapshot(ctx, status="live")
        assert snap.player_projections == []

    def test_win_probabilities_sum_to_one(self):
        svc = ProjectionService()
        ctx = _context_with_players()
        snap = svc.build_snapshot(ctx, status="live")
        total = snap.home_team.win_probability + snap.away_team.win_probability
        assert abs(total - 1.0) < 0.01
