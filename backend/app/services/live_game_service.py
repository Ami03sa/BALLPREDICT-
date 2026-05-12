import logging
from datetime import datetime

from app.schemas.game import (
    ConfidenceBand,
    GameSnapshot,
    PlayerDetailResponse,
    PlayerProjection,
    PlayerQuarterProjection,
    SimulationResponse,
    StatLine,
    TeamProjection,
)
from app.services import nba_api_service
from app.services.projection_service import projection_service
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext

logger = logging.getLogger(__name__)

_ZERO_STAT = StatLine()
_ZERO_BAND = ConfidenceBand(low=_ZERO_STAT, mean=_ZERO_STAT, high=_ZERO_STAT)


def _zero_team_proj(proj: TeamProjection) -> TeamProjection:
    return proj.model_copy(
        update={
            "projected_score": (0, 0, 0, 0),
            "final_score_mean": 0,
            "final_score_ci": (0, 0),
            "win_probability": 0.5,
        }
    )


def _zero_player_proj(proj: PlayerProjection) -> PlayerProjection:
    return proj.model_copy(update={"projected_stats": _ZERO_BAND})


def _zero_snapshot(snapshot: GameSnapshot) -> GameSnapshot:
    """Zero out all predicted values; keep live_stats and game state intact."""
    return snapshot.model_copy(
        update={
            "home_team": _zero_team_proj(snapshot.home_team),
            "away_team": _zero_team_proj(snapshot.away_team),
            "player_projections": [_zero_player_proj(p) for p in snapshot.player_projections],
        }
    )


class LiveGameService:
    def __init__(self) -> None:
        self._contexts: dict[str, GameContext] = {}
        self._slate: dict[str, dict] = {}

    async def bootstrap_demo_game(self) -> None:
        """Called on startup — fetches today's real NBA games from the public CDN."""
        try:
            slate, contexts = await nba_api_service.fetch_today_slate_and_contexts()
            if contexts:
                self._slate = slate
                self._contexts = contexts
                logger.info("Loaded %d live NBA game(s) from CDN.", len(contexts))
            else:
                logger.warning("No NBA games found for today — slate will be empty.")
        except Exception as exc:
            logger.error("NBA CDN fetch failed (%s). Slate will be empty.", exc)

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
            context = self._contexts.get(game_id)
            if context is None:
                continue
            games.append(
                {
                    **slate_row,
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
        snapshot = projection_service.build_snapshot(context)
        return _zero_snapshot(snapshot)

    async def get_player_detail(self, game_id: str, player_id: str) -> PlayerDetailResponse:
        context = self._contexts[game_id]
        snapshot = projection_service.build_snapshot(context)
        snapshot = _zero_snapshot(snapshot)
        projection = next(
            player for player in snapshot.player_projections if player.player_id == player_id
        )

        if projection.team_id == context.home_team.team_id:
            team = context.home_team
            opponent = context.away_team
        else:
            team = context.away_team
            opponent = context.home_team

        quarter_breakdown = [
            PlayerQuarterProjection(quarter="Q1", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q2", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q3", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q4", points=0, assists=0, rebounds=0, threes_made=0),
        ]

        live = projection.live_stats
        return PlayerDetailResponse(
            game_id=game_id,
            player_id=projection.player_id,
            player_name=projection.player_name,
            team_id=projection.team_id,
            team_name=team.team_name,
            opponent_team_name=opponent.team_name,
            coach_counter_summary=(
                f"{opponent.team_name} will need to adjust coverages around "
                f"{projection.player_name}'s usage load and shot diet."
            ),
            projection=projection,
            quarter_breakdown=quarter_breakdown,
            stat_profile=[
                {"label": "Points", "live": live.points, "projected": 0},
                {"label": "Assists", "live": live.assists, "projected": 0},
                {"label": "Rebounds", "live": live.rebounds, "projected": 0},
                {"label": "3PM", "live": live.threes_made, "projected": 0},
                {"label": "Turnovers", "live": live.turnovers, "projected": 0},
            ],
            matchup_factors=[
                f"Usage load at {(projection.projected_stats.mean.usage_rate * 100):.0f}%",
                f"{opponent.team_name} defensive rating {opponent.defensive_rating}",
                f"{team.team_name} pace baseline {team.pace}",
                "weak-side help timing",
                "rotation staggering leverage",
            ],
            confidence={
                "floor_points": 0,
                "median_points": 0,
                "ceiling_points": 0,
                "pressure": projection.defensive_pressure,
            },
            player_insights=[
                {
                    "title": "Live Stats",
                    "body": (
                        f"{projection.player_name} has {int(live.points)} pts, "
                        f"{int(live.assists)} ast, {int(live.rebounds)} reb so far."
                    ),
                    "severity": "info",
                },
                {
                    "title": "Defensive Attention",
                    "body": (
                        f"{opponent.team_name} is expected to vary help position and screen coverage "
                        f"around {projection.player_name}'s usage sequences."
                    ),
                    "severity": "warning",
                },
                {
                    "title": "Projection Pending",
                    "body": "Statistical projections will be available once the prediction model is applied.",
                    "severity": "info",
                },
            ],
        )

    async def simulate_matchup(
        self, home_team: str, away_team: str, strategy_tags: list[str]
    ) -> SimulationResponse:
        context = next(iter(self._contexts.values()))
        base_adjustments = coaching_engine.build_team_level_adjustments(context, context.home_team)
        extra = []
        if "switch-everything" in strategy_tags:
            extra.append(
                {
                    "title": "Switch-Everything Closing Group",
                    "side": "defense",
                    "trigger": "User strategy override",
                    "explanation": (
                        "The defense trades rebounding risk for isolation suppression "
                        "and ball-pressure continuity."
                    ),
                    "counters": ["switch 1-5", "late scram on post mismatch"],
                    "impact": {"field_goal_pct_allowed": -0.02, "defensive_rebound_pct": -0.03},
                }
            )

        return SimulationResponse(
            summary=(
                f"{home_team} projects as the slightly stronger half-court environment, "
                f"but {away_team} retains a live-upside path if its lead creator wins "
                "the paint-touch battle and forces repeated low-man help."
            ),
            home_win_probability=0.5,
            away_win_probability=0.5,
            projected_score={home_team: 0, away_team: 0},
            key_adjustments=base_adjustments + extra,
            player_edges=[
                {
                    "title": "Primary Creator Leverage",
                    "body": (
                        "When the weak-side wing tags early, the ball-handler's scoring "
                        "dips but corner assist equity spikes."
                    ),
                    "severity": "info",
                },
                {
                    "title": "Second Unit Swing",
                    "body": (
                        "Bench spacing quality is the biggest variable in quarter-to-quarter "
                        "scoring swings for this matchup."
                    ),
                    "severity": "advantage",
                },
            ],
        )

    def _build_prediction_hook(self, context: GameContext) -> str:
        all_players = context.home_team.players + context.away_team.players
        if not all_players:
            return f"{context.away_team.team_name} at {context.home_team.team_name} — projection model pending."
        lead_creator = max(all_players, key=lambda p: p.usage_rate + p.momentum_score)
        return (
            f"{lead_creator.player_name} is the primary leverage point. "
            f"BallPredict will model coaching adjustments around that usage load "
            f"once the prediction engine is applied."
        )


live_game_service = LiveGameService()
