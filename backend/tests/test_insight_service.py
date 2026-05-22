from app.services.insight_service import InsightService
from app.simulation.state import GameContext, PlayerGameState, TeamGameState


def _team(team_id="gsw"):
    return TeamGameState(
        team_id=team_id,
        team_name="Warriors",
        coach_name="Kerr",
        score=50,
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


def _player(player_id="p1", team_id="gsw"):
    return PlayerGameState(
        player_id=player_id,
        player_name="Curry",
        team_id=team_id,
        usage_rate=0.30,
        points=22.0,
        momentum_score=0.85,
    )


def _context(with_players=True):
    home = _team("gsw")
    away = _team("dal")
    if with_players:
        home.players = [_player("p1", "gsw")]
        away.players = [_player("p2", "dal")]
    return GameContext(
        game_id="demo",
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


def test_no_players_returns_pending_card():
    svc = InsightService()
    ctx = _context(with_players=False)
    insights = svc.build_game_insights(ctx)
    assert len(insights) == 1
    assert insights[0].title == "Live Context Pending"
    assert insights[0].severity == "info"


def test_with_players_returns_multiple_cards():
    svc = InsightService()
    ctx = _context(with_players=True)
    insights = svc.build_game_insights(ctx)
    assert len(insights) >= 2
    titles = [i.title for i in insights]
    assert "Primary Defensive Shift" in titles
    severities = {i.severity for i in insights}
    assert severities <= {"info", "warning", "advantage"}
