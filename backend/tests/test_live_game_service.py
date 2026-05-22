"""
Tests for LiveGameService — helper methods and full resolution chain.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.live_game_service import (
    LiveGameService,
    _zero_team_proj,
    _zero_player_proj,
    _zero_snapshot,
    live_game_service,
)
from app.schemas.game import (
    ConfidenceBand,
    GameSnapshot,
    InsightCard,
    PlayerProjection,
    StatLine,
    TeamProjection,
)
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_team(team_id="gsw", score=50):
    return TeamGameState(
        team_id=team_id,
        team_name="Golden State Warriors",
        coach_name="Steve Kerr",
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


def _make_player(player_id="p1", team_id="gsw", points=15.0):
    return PlayerGameState(
        player_id=player_id,
        player_name="Stephen Curry",
        team_id=team_id,
        usage_rate=0.30,
        points=points,
        assists=5.0,
        rebounds=4.0,
        steals=1.0,
        blocks=0.5,
        turnovers=2.0,
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
    )


def _make_context(home_score=50, away_score=44, quarter=2):
    home = _make_team("gsw", home_score)
    away = _make_team("dal", away_score)
    away.team_name = "Dallas Mavericks"
    home.players = [_make_player("p1", "gsw", 18)]
    away.players = [_make_player("p2", "dal", 14)]
    return GameContext(
        game_id="demo",
        quarter=quarter,
        clock="08:00",
        home_team=home,
        away_team=away,
        score_margin=home_score - away_score,
        home_advantage=2.4,
        overtime_probability=0.05,
        momentum=0.6,
        fatigue_pressure=0.35,
        whistle_tightness=0.48,
        playoff_intensity=0.55,
        live_pace_multiplier=1.02,
    )


def _make_stat_line(**kwargs):
    return StatLine(**kwargs)


def _make_team_proj(team_id="gsw"):
    return TeamProjection(
        team_id=team_id,
        team_name="Warriors",
        quarter=2,
        score=50,
        projected_score=(25, 25, 25, 25),
        final_score_mean=110,
        final_score_ci=(100, 120),
        pace=100.0,
        offensive_rating=115.0,
        defensive_rating=113.0,
        win_probability=0.55,
    )


def _make_player_proj(player_id="p1"):
    stat = StatLine()
    band = ConfidenceBand(low=stat, mean=stat, high=stat)
    return PlayerProjection(
        player_id=player_id,
        player_name="Curry",
        team_id="gsw",
        quarter=2,
        live_stats=stat,
        projected_stats=band,
        momentum_score=0.7,
        fatigue_index=0.3,
        defensive_pressure=0.4,
        adjustments=[],
    )


def _make_snapshot():
    return GameSnapshot(
        game_id="demo",
        status="live",
        updated_at="2024-01-01T00:00:00",
        quarter=2,
        clock="08:00",
        home_team=_make_team_proj("gsw"),
        away_team=_make_team_proj("dal"),
        player_projections=[_make_player_proj("p1"), _make_player_proj("p2")],
        possession_feed=[],
        insights=[InsightCard(title="T", body="B", severity="info")],
        win_probability_series=[],
    )


# ---------------------------------------------------------------------------
# Module-level helper function tests
# ---------------------------------------------------------------------------

def test_zero_team_proj_clears_scores():
    proj = _make_team_proj()
    zeroed = _zero_team_proj(proj)
    assert zeroed.projected_score == (0, 0, 0, 0)
    assert zeroed.final_score_mean == 0
    assert zeroed.win_probability == 0.5


def test_zero_player_proj_clears_stats():
    proj = _make_player_proj()
    proj = proj.model_copy(update={"projected_stats": ConfidenceBand(
        low=StatLine(points=10), mean=StatLine(points=20), high=StatLine(points=30)
    )})
    zeroed = _zero_player_proj(proj)
    assert zeroed.projected_stats.mean.points == 0
    assert zeroed.projected_stats.low.points == 0
    assert zeroed.projected_stats.high.points == 0


def test_zero_snapshot_zeroes_all():
    snap = _make_snapshot()
    zeroed = _zero_snapshot(snap)
    assert zeroed.home_team.final_score_mean == 0
    assert zeroed.away_team.final_score_mean == 0
    for p in zeroed.player_projections:
        assert p.projected_stats.mean.points == 0


# ---------------------------------------------------------------------------
# LiveGameService helper method tests
# ---------------------------------------------------------------------------

svc = LiveGameService()


class TestSafeFloat:
    def test_none_returns_zero(self):
        assert svc._safe_float(None) == 0.0

    def test_valid_number(self):
        assert svc._safe_float(12.5) == 12.5

    def test_string_number(self):
        assert svc._safe_float("7") == 7.0

    def test_invalid_string(self):
        assert svc._safe_float("abc") == 0.0

    def test_zero(self):
        assert svc._safe_float(0) == 0.0


class TestFormatClock:
    def test_empty_string(self):
        assert svc._format_clock("") == "12:00"

    def test_pt_format(self):
        assert svc._format_clock("PT05M30.00S") == "05:30"

    def test_pt_format_minutes_only(self):
        result = svc._format_clock("PT12M00.00S")
        assert result == "12:00"

    def test_plain_format(self):
        assert svc._format_clock("08:30") == "08:30"


class TestNormalizePct:
    def test_none_returns_default(self):
        assert svc._normalize_pct(None, 0.45) == 0.45

    def test_zero_returns_default(self):
        assert svc._normalize_pct(0, 0.45) == 0.45

    def test_over_1_divides_by_100(self):
        result = svc._normalize_pct(50.0, 0.45)
        assert abs(result - 0.5) < 0.001

    def test_under_1_kept_as_is(self):
        result = svc._normalize_pct(0.48, 0.45)
        assert abs(result - 0.48) < 0.001


class TestParseMinutes:
    def test_none_returns_zero(self):
        assert svc._parse_minutes(None) == 0.0

    def test_int(self):
        assert svc._parse_minutes(30) == 30.0

    def test_float(self):
        assert svc._parse_minutes(18.5) == 18.5

    def test_pt_format(self):
        result = svc._parse_minutes("PT18M30.00S")
        assert abs(result - 18.5) < 0.01

    def test_colon_format(self):
        result = svc._parse_minutes("18:30")
        assert abs(result - 18.5) < 0.01

    def test_plain_string(self):
        assert svc._parse_minutes("22") == 22.0

    def test_invalid_string(self):
        assert svc._parse_minutes("bad") == 0.0


class TestStatusLabel:
    def test_none_is_scheduled(self):
        assert svc._status_label(None) == "scheduled"

    def test_zero_is_scheduled(self):
        assert svc._status_label(0) == "scheduled"

    def test_one_is_scheduled(self):
        assert svc._status_label(1) == "scheduled"

    def test_two_is_live(self):
        assert svc._status_label(2) == "live"

    def test_three_is_final(self):
        assert svc._status_label(3) == "final"


class TestTeamDisplayName:
    def test_city_and_name(self):
        result = svc._team_display_name({"teamCity": "Golden State", "teamName": "Warriors"})
        assert result == "Golden State Warriors"

    def test_name_contains_city(self):
        result = svc._team_display_name({"teamCity": "Dallas", "teamName": "Dallas Mavericks"})
        assert result == "Dallas Mavericks"

    def test_tricode_fallback(self):
        result = svc._team_display_name({"teamTricode": "GSW"})
        assert result == "GSW"

    def test_empty(self):
        result = svc._team_display_name({})
        assert result == "NBA Team"


class TestEstimateMomentum:
    def test_tied_game(self):
        result = svc._estimate_momentum(50, 50)
        assert result == 0.5

    def test_blowout(self):
        result = svc._estimate_momentum(80, 50)
        assert result > 0.5


class TestEstimateBenchDepth:
    def test_empty_players(self):
        assert svc._estimate_bench_depth([]) == 0.4

    def test_with_players(self):
        players = [_make_player(f"p{i}", "gsw") for i in range(8)]
        result = svc._estimate_bench_depth(players)
        assert 0.35 <= result <= 0.75

    def test_dnp_players_excluded(self):
        players = [_make_player(f"p{i}", "gsw") for i in range(3)]
        players[0].minutes_played = 0
        players[0].usage_rate = 0.05  # below threshold
        result = svc._estimate_bench_depth(players)
        assert result >= 0.35


class TestEstimatePossessions:
    def test_with_stats(self):
        stats = {
            "fieldGoalsAttempted": 40,
            "freeThrowsAttempted": 10,
            "reboundsOffensive": 5,
            "turnoversTotal": 4,
        }
        result = svc._estimate_possessions(stats)
        assert result > 0

    def test_empty_stats(self):
        assert svc._estimate_possessions({}) == 0.0


class TestEstimateLivePaceMultiplier:
    def test_pregame(self):
        result = svc._estimate_live_pace_multiplier({}, {}, 0)
        assert result == 1.0

    def test_live_game(self):
        home = {"statistics": {"fieldGoalsAttempted": 40, "freeThrowsAttempted": 10,
                               "reboundsOffensive": 5, "turnoversTotal": 4}}
        away = {"statistics": {"fieldGoalsAttempted": 38, "freeThrowsAttempted": 8,
                               "reboundsOffensive": 4, "turnoversTotal": 3}}
        result = svc._estimate_live_pace_multiplier(home, away, 2)
        assert 0.9 <= result <= 1.12


class TestAverageFatigue:
    def test_empty(self):
        assert svc._average_fatigue([]) == 0.2

    def test_with_players(self):
        players = [_make_player("p1"), _make_player("p2")]
        result = svc._average_fatigue(players)
        assert result == 0.30


class TestBuildPredictionHook:
    def test_no_players(self):
        ctx = _make_context()
        ctx.home_team.players = []
        ctx.away_team.players = []
        result = svc._build_prediction_hook(ctx)
        assert "projection model pending" in result

    def test_with_players(self):
        ctx = _make_context()
        result = svc._build_prediction_hook(ctx)
        assert "BallPredict" in result


class TestBuildLivePredictionHook:
    def test_with_leaders(self):
        result = svc._build_live_prediction_hook(
            {"name": "Curry"},
            {"name": "Luka"},
            {"teamCity": "Golden State", "teamName": "Warriors"},
            {"teamCity": "Dallas", "teamName": "Mavericks"},
        )
        assert "Curry" in result
        assert "BallPredict" in result

    def test_fallback_to_team_name(self):
        result = svc._build_live_prediction_hook(
            {},
            {},
            {"teamCity": "Golden State", "teamName": "Warriors"},
            {"teamCity": "Dallas", "teamName": "Mavericks"},
        )
        assert "Warriors" in result or "Mavericks" in result


class TestExtractArena:
    def test_dict_arena(self):
        game = {"arena": {"arenaName": "Chase Center"}}
        assert svc._extract_arena(game) == "Chase Center"

    def test_missing_arena(self):
        assert svc._extract_arena({}) == "NBA Arena"

    def test_game_label_fallback(self):
        # arena must be a non-dict truthy value to trigger gameLabel branch
        game = {"arena": "legacy-string", "gameLabel": "AT&T Center"}
        assert svc._extract_arena(game) == "AT&T Center"


class TestExtractBroadcast:
    def test_list_of_dicts(self):
        game = {"natlTvBroadcasters": [{"broadcasterDisplay": "ESPN"}]}
        assert svc._extract_broadcast(game) == "ESPN"

    def test_list_of_strings(self):
        game = {"broadcasters": ["TNT"]}
        assert svc._extract_broadcast(game) == "TNT"

    def test_no_broadcast(self):
        assert svc._extract_broadcast({}) == "League Pass"

    def test_dict_value(self):
        game = {"watch": {"broadcasterDisplay": "NBA TV"}}
        assert svc._extract_broadcast(game) == "NBA TV"


class TestFormatTipoff:
    def test_no_raw(self):
        assert svc._format_tipoff({}) == "TBD"

    def test_valid_utc(self):
        game = {"gameEt": "2024-04-20T19:30:00Z"}
        result = svc._format_tipoff(game)
        assert result != "TBD"

    def test_invalid_date(self):
        game = {"gameEt": "not-a-date"}
        result = svc._format_tipoff(game)
        assert result == "not-a-date"


# ---------------------------------------------------------------------------
# Service method tests with mocked HTTP client
# ---------------------------------------------------------------------------

SCOREBOARD = {
    "scoreboard": {
        "games": [
            {
                "gameId": "0042400301",
                "period": 2,
                "gameClock": "PT05M30.00S",
                "gameStatus": 2,
                "gameLabel": "",
                "homeTeam": {
                    "teamId": 1610612744,
                    "teamTricode": "GSW",
                    "teamCity": "Golden State",
                    "teamName": "Warriors",
                    "score": 48,
                    "wins": 20,
                    "losses": 15,
                    "statistics": {
                        "fieldGoalsAttempted": 40,
                        "fieldGoalsMade": 18,
                        "freeThrowsAttempted": 10,
                        "freeThrowsMade": 8,
                        "threePointersAttempted": 15,
                        "threePointersMade": 6,
                        "threePointersPercentage": 40.0,
                        "reboundsOffensive": 5,
                        "reboundsDefensive": 20,
                        "turnoversTotal": 4,
                        "foulsPersonal": 6,
                    },
                },
                "awayTeam": {
                    "teamId": 1610612742,
                    "teamTricode": "DAL",
                    "teamCity": "Dallas",
                    "teamName": "Mavericks",
                    "score": 50,
                    "wins": 22,
                    "losses": 12,
                    "statistics": {
                        "fieldGoalsAttempted": 42,
                        "fieldGoalsMade": 20,
                        "freeThrowsAttempted": 8,
                        "freeThrowsMade": 6,
                        "threePointersAttempted": 16,
                        "threePointersMade": 7,
                        "threePointersPercentage": 43.75,
                        "reboundsOffensive": 6,
                        "reboundsDefensive": 18,
                        "turnoversTotal": 3,
                        "foulsPersonal": 5,
                    },
                },
                "gameLeaders": {
                    "homeLeaders": {"name": "Stephen Curry", "points": 18},
                    "awayLeaders": {"name": "Luka Doncic", "points": 22},
                },
            }
        ]
    }
}


def _player_payload(person_id, name, tricode, starter=True, points=15):
    return {
        "personId": person_id,
        "name": name,
        "teamTricode": tricode,
        "starter": "1" if starter else "0",
        "played": True,
        "statistics": {
            "points": points,
            "assists": 4,
            "reboundsTotal": 5,
            "steals": 1,
            "blocks": 0,
            "turnovers": 2,
            "threePointersMade": 2,
            "threePointersPercentage": 40.0,
            "fieldGoalsAttempted": 12,
            "fieldGoalsMade": 6,
            "fieldGoalsPercentage": 50.0,
            "freeThrowsAttempted": 3,
            "freeThrowsMade": 3,
            "twoPointersMade": 4,
            "foulsPersonal": 2,
            "minutes": "PT18M00.00S",
        },
    }


BOXSCORE = {
    "game": {
        "homeTeam": {
            "teamTricode": "GSW",
            "teamCity": "Golden State",
            "teamName": "Warriors",
            "score": 48,
            "statistics": {
                "fieldGoalsAttempted": 40,
                "fieldGoalsMade": 18,
                "freeThrowsAttempted": 10,
                "threePointersAttempted": 15,
                "threePointersMade": 6,
                "threePointersPercentage": 40.0,
                "reboundsOffensive": 5,
                "reboundsDefensive": 20,
                "turnoversTotal": 4,
                "foulsPersonal": 6,
            },
            "players": [
                _player_payload("200485", "Stephen Curry", "GSW", starter=True, points=18),
                _player_payload("203110", "Draymond Green", "GSW", starter=True, points=5),
            ],
        },
        "awayTeam": {
            "teamTricode": "DAL",
            "teamCity": "Dallas",
            "teamName": "Mavericks",
            "score": 50,
            "statistics": {
                "fieldGoalsAttempted": 42,
                "fieldGoalsMade": 20,
                "freeThrowsAttempted": 8,
                "threePointersAttempted": 16,
                "threePointersMade": 7,
                "threePointersPercentage": 43.75,
                "reboundsOffensive": 6,
                "reboundsDefensive": 18,
                "turnoversTotal": 3,
                "foulsPersonal": 5,
            },
            "players": [
                _player_payload("1629029", "Luka Doncic", "DAL", starter=True, points=22),
                _player_payload("1627783", "Kyrie Irving", "DAL", starter=True, points=16),
            ],
        },
    }
}


@pytest.fixture
def mock_nba_client():
    from app.services.providers.nba_live_client import nba_live_client
    with patch.object(nba_live_client, "fetch_scoreboard", new_callable=AsyncMock) as mock_sb, \
         patch.object(nba_live_client, "fetch_boxscore", new_callable=AsyncMock) as mock_bs:
        mock_sb.return_value = SCOREBOARD
        mock_bs.return_value = BOXSCORE
        yield mock_sb, mock_bs


async def test_list_live_games_success(mock_nba_client):
    result = await live_game_service.list_live_games()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["game_id"] == "0042400301"
    assert result[0]["score"] == "50-48"


async def test_list_live_games_fallback():
    from app.services.providers.nba_live_client import nba_live_client
    svc = LiveGameService()
    ctx = _make_context()
    svc._contexts["demo"] = ctx

    with patch.object(nba_live_client, "fetch_scoreboard", new_callable=AsyncMock) as mock_sb:
        mock_sb.side_effect = httpx.ConnectError("timeout")
        result = await svc.list_live_games()

    assert isinstance(result, list)
    assert any(g["game_id"] == "demo" for g in result)


async def test_list_slate_games_success(mock_nba_client):
    result = await live_game_service.list_slate_games()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["game_id"] == "0042400301"
    assert "headline" in result[0]


async def test_list_slate_games_fallback():
    from app.services.providers.nba_live_client import nba_live_client
    svc = LiveGameService()
    ctx = _make_context()
    svc._contexts["demo"] = ctx
    svc._slate["demo"] = {"game_id": "demo", "prediction_hook": ""}

    with patch.object(nba_live_client, "fetch_scoreboard", new_callable=AsyncMock) as mock_sb:
        mock_sb.side_effect = httpx.ConnectError("timeout")
        result = await svc.list_slate_games()

    assert any(g["game_id"] == "demo" for g in result)


async def test_bootstrap_demo_game_success():
    svc = LiveGameService()
    fake_slate = {"123": {"game_id": "123"}}
    fake_ctx = {"123": _make_context()}

    with patch(
        "app.services.live_game_service.nba_api_service.fetch_today_slate_and_contexts",
        new_callable=AsyncMock,
        return_value=(fake_slate, fake_ctx),
    ):
        await svc.bootstrap_demo_game()

    assert "123" in svc._contexts


async def test_bootstrap_demo_game_empty():
    svc = LiveGameService()
    with patch(
        "app.services.live_game_service.nba_api_service.fetch_today_slate_and_contexts",
        new_callable=AsyncMock,
        return_value=({}, {}),
    ):
        await svc.bootstrap_demo_game()

    assert svc._contexts == {}


async def test_bootstrap_demo_game_exception():
    svc = LiveGameService()
    with patch(
        "app.services.live_game_service.nba_api_service.fetch_today_slate_and_contexts",
        new_callable=AsyncMock,
        side_effect=Exception("network error"),
    ):
        await svc.bootstrap_demo_game()

    assert svc._contexts == {}


async def test_get_game_snapshot_full_chain(mock_nba_client):
    """Full chain: HTTP mock → context build → projection → GameSnapshot."""
    snapshot = await live_game_service.get_game_snapshot("0042400301")
    assert snapshot.game_id == "0042400301"
    assert snapshot.quarter == 2
    assert len(snapshot.player_projections) == 4
    assert snapshot.home_team.team_id == "gsw"
    assert snapshot.away_team.team_id == "dal"


async def test_get_game_preview_full_chain(mock_nba_client):
    result = await live_game_service.get_game_preview("0042400301")
    assert result["game_id"] == "0042400301"
    assert "home_team" in result
    assert "away_team" in result
    assert "players_to_watch" in result


async def test_resolve_context_404():
    svc = LiveGameService()
    from app.services.providers.nba_live_client import nba_live_client
    from fastapi import HTTPException

    with patch.object(nba_live_client, "fetch_scoreboard", new_callable=AsyncMock) as mock_sb:
        mock_sb.return_value = {"scoreboard": {"games": []}}
        with pytest.raises(HTTPException) as exc_info:
            await svc._resolve_context("nonexistent")

    assert exc_info.value.status_code == 404
