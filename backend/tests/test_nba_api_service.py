"""Tests for nba_api_service — pure/deterministic functions (no live HTTP)."""
import pytest

from app.services.nba_api_service import (
    TEAM_ARENAS,
    TEAM_FULL_NAMES,
    _apply_injury_report,
    _build_minimal_team_state,
    _build_player_state,
    _build_team_state,
    _build_team_state_from_season_stats,
    _format_tipoff,
    _parse_minutes,
    _recent_dnp,
    _save_vegas_cache,
    _team_ratings,
    get_quarter_weights,
)
from app.simulation.state import TeamGameState


class TestTeamDicts:
    def test_team_full_names_has_all_30(self):
        assert len(TEAM_FULL_NAMES) == 30
        assert TEAM_FULL_NAMES["GSW"] == "Golden State Warriors"

    def test_team_arenas_has_all_30(self):
        assert len(TEAM_ARENAS) == 30
        assert TEAM_ARENAS["BOS"] == "TD Garden"


class TestSaveVegasCache:
    def test_silently_handles_write_error(self):
        # Path may or may not exist; either way no exception should propagate
        _save_vegas_cache({"test": {"home": 112.5}})


class TestRecentDnp:
    def test_no_db_returns_false(self):
        assert _recent_dnp("any-player-id") is False


class TestGetQuarterWeights:
    def test_no_db_returns_none(self):
        assert get_quarter_weights("any-player-id") is None


class TestParseMinutes:
    def test_empty_string(self):
        assert _parse_minutes("") == 0.0

    def test_pt_format(self):
        result = _parse_minutes("PT35M12.00S")
        assert abs(result - 35.2) < 0.1

    def test_pt_format_no_seconds(self):
        result = _parse_minutes("PT20M")
        assert result == 20.0

    def test_mm_ss_format(self):
        result = _parse_minutes("24:30")
        assert abs(result - 24.5) < 0.1

    def test_raw_float_string(self):
        result = _parse_minutes("18.5")
        assert result == 18.5

    def test_invalid_falls_back_to_zero(self):
        assert _parse_minutes("not-a-time") == 0.0


class TestFormatTipoff:
    def test_empty_returns_tbd(self):
        assert _format_tipoff("") == "TBD"

    def test_valid_utc_pm(self):
        result = _format_tipoff("2024-04-20T23:30:00Z")
        assert "PM ET" in result

    def test_valid_utc_am(self):
        result = _format_tipoff("2024-04-20T14:00:00Z")
        assert "AM ET" in result

    def test_invalid_returns_tbd(self):
        assert _format_tipoff("not-a-date") == "TBD"


class TestBuildPlayerState:
    def _active_player(self, fg_pct=0.50, three_pct=0.40):
        return {
            "status": "ACTIVE",
            "personId": 123,
            "name": "Test Player",
            "statistics": {
                "fieldGoalsPercentage": fg_pct,
                "threePointersPercentage": three_pct,
                "points": 18,
                "assists": 5,
                "reboundsTotal": 4,
                "steals": 1,
                "blocks": 0,
                "turnovers": 2,
                "threePointersMade": 3,
                "minutesCalculated": "PT28M00.00S",
            },
        }

    def test_non_active_returns_none(self):
        assert _build_player_state({"status": "INACTIVE"}, "gsw") is None

    def test_active_builds_player_state(self):
        data = self._active_player()
        state = _build_player_state(data, "gsw")
        assert state is not None
        assert state.player_id == "123"
        assert state.points == 18
        assert state.team_id == "gsw"

    def test_pct_over_1_normalised(self):
        data = self._active_player(fg_pct=55.6, three_pct=44.0)
        state = _build_player_state(data, "gsw")
        assert state.field_goal_pct <= 1.0
        assert state.three_point_pct <= 1.0


class TestTeamRatings:
    def test_known_tricode_returns_ratings(self):
        ratings = {"GSW": {"off_rating": 118.0, "def_rating": 112.0, "pace": 101.0}}
        off, def_, pace = _team_ratings("GSW", ratings)
        assert off == 118.0
        assert def_ == 112.0
        assert pace == 101.0

    def test_unknown_tricode_returns_defaults(self):
        off, def_, pace = _team_ratings("XYZ", {})
        assert off == 114.0
        assert def_ == 114.0
        assert pace == 98.0


class TestBuildTeamState:
    def _box_team(self, tricode="GSW", score=108, players=None):
        return {
            "teamTricode": tricode,
            "teamCity": "Golden State",
            "teamName": "Warriors",
            "players": players or [],
        }

    def test_builds_team_state(self):
        box = self._box_team()
        state = _build_team_state(box, 108)
        assert isinstance(state, TeamGameState)
        assert state.team_id == "gsw"
        assert state.score == 108

    def test_with_active_player(self):
        player = {
            "status": "ACTIVE",
            "personId": 1,
            "name": "Curry",
            "statistics": {
                "fieldGoalsPercentage": 0.50,
                "threePointersPercentage": 0.42,
                "points": 25,
                "assists": 6,
                "reboundsTotal": 5,
                "steals": 1,
                "blocks": 0,
                "turnovers": 3,
                "threePointersMade": 4,
                "minutesCalculated": "PT32M00.00S",
            },
        }
        box = self._box_team(players=[player])
        state = _build_team_state(box, 110)
        assert len(state.players) == 1

    def test_unknown_tricode_falls_back_to_city_name(self):
        box = {"teamTricode": "ZZZ", "teamCity": "Fake", "teamName": "Team", "players": []}
        state = _build_team_state(box, 0)
        assert "Fake" in state.team_name


class TestBuildTeamStateFromSeasonStats:
    def _season_player(self, pid="1", name="Curry", pts=22.0, min_avg=32.0):
        return {
            "PLAYER_ID": pid,
            "PLAYER_NAME": name,
            "PTS": pts,
            "AST": 6.0,
            "REB": 4.5,
            "STL": 1.2,
            "BLK": 0.3,
            "TOV": 3.1,
            "FG3M": 4.5,
            "FG_PCT": 0.48,
            "FG3_PCT": 0.40,
            "FGA": 18.0,
            "FTA": 5.0,
            "MIN": min_avg,
        }

    def test_builds_from_season_stats(self):
        team_raw = {"teamTricode": "GSW", "teamCity": "Golden State", "teamName": "Warriors"}
        players = [self._season_player(), self._season_player("2", "Draymond", pts=8.0, min_avg=30.0)]
        state = _build_team_state_from_season_stats(team_raw, 0, players)
        assert isinstance(state, TeamGameState)
        assert len(state.players) == 2

    def test_skips_low_minute_players(self):
        team_raw = {"teamTricode": "GSW", "teamCity": "Golden State", "teamName": "Warriors"}
        bench = self._season_player("99", "Bench Guy", pts=4.0, min_avg=5.0)
        state = _build_team_state_from_season_stats(team_raw, 0, [bench])
        assert len(state.players) == 0


class TestBuildMinimalTeamState:
    def test_builds_from_scoreboard(self):
        raw = {"teamTricode": "DAL", "teamCity": "Dallas", "teamName": "Mavericks"}
        state = _build_minimal_team_state(raw, 44)
        assert state.team_id == "dal"
        assert state.score == 44
        assert state.players == []


class TestApplyInjuryReport:
    def _team_with_players(self):
        from app.simulation.state import PlayerGameState

        class FakeTeam:
            players = [
                PlayerGameState(
                    player_id="123",
                    player_name="Curry",
                    team_id="gsw",
                    usage_rate=0.30,
                    availability_status="available",
                ),
                PlayerGameState(
                    player_id="456",
                    player_name="Green",
                    team_id="gsw",
                    usage_rate=0.20,
                    availability_status="dnp",
                ),
            ]

        return FakeTeam()

    def test_out_player_marked_dnp(self):
        team = self._team_with_players()
        _apply_injury_report(team, {"123": "Out"})
        assert team.players[0].availability_status == "dnp"

    def test_existing_dnp_skipped(self):
        team = self._team_with_players()
        _apply_injury_report(team, {"456": "Out"})
        # Already dnp, should still be dnp but dnp_reason stays unchanged
        assert team.players[1].availability_status == "dnp"

    def test_questionable_not_marked_dnp(self):
        team = self._team_with_players()
        _apply_injury_report(team, {"123": "Questionable"})
        assert team.players[0].availability_status == "available"
