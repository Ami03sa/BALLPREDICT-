"""Tests for PredictionEngine — fallback paths and project_team."""
import pytest

from app.simulation.prediction_engine import (
    prediction_engine,
    _rolling,
    _prop_line,
    _hot_factor,
    _player_history,
    _player_position,
    _opponent_def_stats,
    _rest_days,
    _player_vs_opp,
    _home_away_splits,
    _build_features,
    _load_synthetic_props,
    _load_team_elo,
    set_player_props,
)
from app.simulation.state import GameContext, PlayerGameState, TeamGameState
from app.schemas.game import PlayerProjection


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


def _context(score_margin=6, quarter=2):
    home = _team("gsw", 56)
    away = _team("dal", 50)
    return GameContext(
        game_id="demo",
        quarter=quarter,
        clock="08:00",
        home_team=home,
        away_team=away,
        score_margin=score_margin,
        home_advantage=2.4,
        overtime_probability=0.05,
        momentum=0.6,
        fatigue_pressure=0.35,
        whistle_tightness=0.48,
        playoff_intensity=0.55,
        live_pace_multiplier=1.02,
    )


def _player(player_id="p1", team_id="gsw", points=15.0, usage=0.30, status="available"):
    return PlayerGameState(
        player_id=player_id,
        player_name="Stephen Curry",
        team_id=team_id,
        usage_rate=usage,
        points=points,
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
        availability_status=status,
        pts_avg=20.0,
        ast_avg=6.0,
        reb_avg=4.5,
        stl_avg=1.5,
        blk_avg=0.2,
        tov_avg=3.0,
        fg3m_avg=4.5,
    )


class TestRolling:
    def test_empty_values(self):
        assert _rolling([], 5) == 0.0

    def test_fewer_than_n(self):
        result = _rolling([10.0, 20.0], 5)
        assert result == 15.0

    def test_exact_n(self):
        result = _rolling([10.0, 20.0, 30.0], 3)
        assert result == 20.0

    def test_more_than_n(self):
        result = _rolling([10.0, 20.0, 30.0, 40.0], 2)
        assert result == 15.0


class TestPropLine:
    @pytest.fixture(autouse=True)
    def clear_props(self):
        set_player_props({})
        yield
        set_player_props({})

    def test_no_props_returns_none(self):
        line, is_market = _prop_line("Unknown Player", "pts")
        assert line is None
        assert is_market is False

    def test_exact_match(self):
        set_player_props({"stephen curry": {"pts": 29.5}})
        line, is_market = _prop_line("Stephen Curry", "pts")
        assert line == 29.5
        assert is_market is True

    def test_partial_match(self):
        set_player_props({"curry": {"pts": 28.0}})
        line, is_market = _prop_line("Stephen Curry", "pts")
        assert line == 28.0

    def test_missing_stat_key(self):
        set_player_props({"stephen curry": {"pts": 29.5}})
        line, is_market = _prop_line("Stephen Curry", "ast")
        assert line is None


class TestProjectPlayerFallback:
    """Tests the no-model fallback path (no XGBoost models in CI)."""

    def test_returns_player_projection(self):
        ctx = _context()
        player = _player()
        proj = prediction_engine.project_player(ctx, ctx.home_team, ctx.away_team, player)
        assert isinstance(proj, PlayerProjection)
        assert proj.player_id == "p1"
        assert proj.player_name == "Stephen Curry"

    def test_dnp_player_returns_zero_projection(self):
        ctx = _context()
        player = _player(status="dnp")
        proj = prediction_engine.project_player(ctx, ctx.home_team, ctx.away_team, player)
        assert proj.availability_status == "dnp"
        assert proj.projected_stats.mean.points == 0
        assert proj.adjustments == []

    def test_season_avg_used_when_no_models(self):
        ctx = _context()
        player = _player()
        player.pts_avg = 25.0
        proj = prediction_engine.project_player(ctx, ctx.home_team, ctx.away_team, player)
        assert proj.projected_stats.mean.points == 25.0

    def test_confidence_band_floor_below_mean(self):
        ctx = _context()
        player = _player()
        proj = prediction_engine.project_player(ctx, ctx.home_team, ctx.away_team, player)
        assert proj.projected_stats.low.points <= proj.projected_stats.mean.points
        assert proj.projected_stats.high.points >= proj.projected_stats.mean.points

    def test_away_player(self):
        ctx = _context()
        player = _player("p2", "dal")
        proj = prediction_engine.project_player(ctx, ctx.away_team, ctx.home_team, player)
        assert proj.team_id == "dal"

    def test_playoff_intensity(self):
        ctx = _context()
        ctx = GameContext(
            game_id="demo",
            quarter=4,
            clock="02:00",
            home_team=_team("gsw", 56),
            away_team=_team("dal", 50),
            score_margin=6,
            home_advantage=2.4,
            overtime_probability=0.15,
            momentum=0.7,
            fatigue_pressure=0.6,
            whistle_tightness=0.52,
            playoff_intensity=0.70,
            live_pace_multiplier=1.0,
        )
        player = _player()
        proj = prediction_engine.project_player(ctx, ctx.home_team, ctx.away_team, player)
        assert proj is not None


class TestProjectTeam:
    def test_pregame_distributes_evenly(self):
        ctx = _context(quarter=0)
        team = _team("gsw", 0)
        opp = _team("dal", 0)
        proj = prediction_engine.project_team(ctx, team, opp, is_home=True)
        assert len(proj.projected_score) == 4
        assert sum(proj.projected_score) == proj.final_score_mean

    def test_live_game_uses_actual_score(self):
        ctx = _context(quarter=2)
        team = _team("gsw", 50)
        opp = _team("dal", 44)
        proj = prediction_engine.project_team(ctx, team, opp, is_home=True)
        assert proj.score == 50
        assert 0.0 <= proj.win_probability <= 1.0

    def test_away_team_win_probability_complement(self):
        ctx = _context(quarter=2)
        home = _team("gsw", 50)
        away = _team("dal", 44)
        home_proj = prediction_engine.project_team(ctx, home, away, is_home=True)
        away_proj = prediction_engine.project_team(ctx, away, home, is_home=False)
        assert abs(home_proj.win_probability + away_proj.win_probability - 1.0) < 0.01

    def test_player_score_sum_used(self):
        ctx = _context(quarter=2)
        team = _team("gsw", 50)
        opp = _team("dal", 44)
        proj = prediction_engine.project_team(ctx, team, opp, is_home=True, player_score_sum=115)
        assert proj.final_score_mean == 115


class TestDbFallbackFunctions:
    """All these functions return safe defaults when the training DB is absent."""

    def test_hot_factor_no_db(self):
        assert _hot_factor("any-player") == 1.0

    def test_player_history_no_db(self):
        assert _player_history("any-player") == {}

    def test_player_position_no_db(self):
        assert _player_position("any-player") == "F"

    def test_opponent_def_stats_no_db(self):
        result = _opponent_def_stats("GSW")
        assert "opp_pts_per_game" in result
        assert isinstance(result["opp_pts_per_game"], float)

    def test_rest_days_no_db(self):
        assert _rest_days("any-player") == 2.0

    def test_player_vs_opp_no_db(self):
        assert _player_vs_opp("any-player", "GSW") == {}

    def test_home_away_splits_no_db(self):
        result = _home_away_splits("any-player")
        assert result == {"home_pts_avg": 0.0, "away_pts_avg": 0.0}

    def test_load_synthetic_props_empty_list(self):
        # Early-returns without DB access when player_ids is empty
        _load_synthetic_props([])

    def test_load_team_elo_no_db(self):
        result = _load_team_elo()
        assert isinstance(result, dict)


class TestBuildFeatures:
    def _player(self):
        return PlayerGameState(
            player_id="p1",
            player_name="Curry",
            team_id="gsw",
            usage_rate=0.30,
            points=20.0,
            assists=5.0,
            rebounds=4.0,
            threes_made=3.0,
            field_goal_pct=0.50,
            three_point_pct=0.42,
            minutes_played=32.0,
            fatigue_index=0.30,
            foul_count=2,
            matchup_difficulty=0.50,
            momentum_score=0.75,
            drive_frequency=0.20,
            paint_touches=6,
            pts_avg=22.0,
            ast_avg=6.0,
            reb_avg=4.5,
            stl_avg=1.5,
            blk_avg=0.2,
            tov_avg=3.0,
            fg3m_avg=4.5,
        )

    def test_returns_feature_dict(self):
        player = self._player()
        opp_def = _opponent_def_stats("dal")
        row = _build_features(player, {}, opp_def, is_home=True)
        assert isinstance(row, dict)
        assert "is_home" in row
        assert row["is_home"] == 1.0

    def test_away_player(self):
        player = self._player()
        row = _build_features(player, {}, {}, is_home=False)
        assert row["is_home"] == 0.0

    def test_rolling_stats_with_history(self):
        player = self._player()
        history = {
            "pts": [20.0, 25.0, 18.0, 22.0, 19.0, 21.0],
            "ast": [5.0, 6.0, 4.0, 5.0, 5.5, 4.5],
        }
        row = _build_features(player, history, {}, is_home=True)
        assert row["pts_last5"] > 0
        assert row["pts_last10"] > 0

    def test_h2h_stats_used_when_available(self):
        player = self._player()
        h2h = {"pts": [28.0, 32.0, 25.0], "ast": [6.0, 7.0, 5.0], "reb": [4.0, 5.0, 3.0]}
        row = _build_features(player, {}, {}, is_home=True, h2h=h2h)
        assert row["pts_vs_opp_last3"] > 0

    def test_elo_diff_computed(self):
        player = self._player()
        row = _build_features(player, {}, {}, is_home=True, team_elo=1550.0, opp_elo=1480.0)
        assert row["elo_diff"] == pytest.approx(70.0)
