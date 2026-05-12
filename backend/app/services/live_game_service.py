from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException

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
from app.services.providers.nba_live_client import nba_live_client
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
        context, scoreboard_game = await self._resolve_context(game_id)
        slate_row = self._build_live_slate_row(scoreboard_game) if scoreboard_game else self._slate.get(game_id, {"game_id": game_id, "status": "scheduled", "tipoff": "TBD", "broadcast": "", "arena": "", "headline": "", "home_team": "", "away_team": "", "home_abbreviation": "", "away_abbreviation": "", "home_record": "", "away_record": "", "prediction_hook": ""})
        return self._build_preview_payload(context, slate_row)

    async def get_game_snapshot(self, game_id: str) -> GameSnapshot:
        context, scoreboard_game = await self._resolve_context(game_id)
        status = self._status_label(scoreboard_game.get("gameStatus")) if scoreboard_game else "scheduled"
        snapshot = projection_service.build_snapshot(context, status=status, possession_feed=[])
        return _zero_snapshot(snapshot)

    async def get_player_detail(self, game_id: str, player_id: str) -> PlayerDetailResponse:
        context, scoreboard_game = await self._resolve_context(game_id)
        status = self._status_label(scoreboard_game.get("gameStatus")) if scoreboard_game else "scheduled"
        snapshot = projection_service.build_snapshot(context, status=status, possession_feed=[])
        return self._build_player_detail_payload(game_id, player_id, context, _zero_snapshot(snapshot))

    async def _resolve_context(self, game_id: str) -> tuple[GameContext, dict | None]:
        """Try live fetch first; fall back to startup context."""
        try:
            context, scoreboard_game, _, playbyplay = await self._build_live_context_bundle(game_id)
            return context, scoreboard_game
        except StopIteration:
            pass
        except Exception as exc:
            logger.warning("Live fetch failed for %s (%s) — using startup context.", game_id, exc)
        context = self._contexts.get(game_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not available")
        return context, None

    async def _build_live_context_bundle(self, game_id: str) -> tuple[GameContext, dict[str, Any], dict[str, Any], dict[str, Any]]:
        scoreboard = await nba_live_client.fetch_scoreboard()
        games = scoreboard.get("scoreboard", {}).get("games", [])
        scoreboard_game = next(game for game in games if str(game.get("gameId")) == str(game_id))

        boxscore: dict[str, Any] = {}
        try:
            boxscore = await nba_live_client.fetch_boxscore(str(game_id))
        except Exception as exc:
            logger.warning("Boxscore unavailable for %s (%s) — using scoreboard data only.", game_id, exc)

        playbyplay: dict[str, Any] = {}
        try:
            playbyplay = await nba_live_client.fetch_playbyplay(str(game_id))
        except httpx.HTTPError:
            pass

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

    def _build_live_team_state(self, team_payload: dict[str, Any], opponent_payload: dict[str, Any]):
        from app.simulation.state import TeamGameState
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

    def _build_live_players(self, team_payload: dict[str, Any], team_possessions: float):
        from app.simulation.state import PlayerGameState
        players = []
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
                player.get("name")
                or " ".join(filter(None, [player.get("firstName"), player.get("familyName")]))
                or "Unknown Player"
            )
            played = player.get("played") or self._safe_float(stats.get("minutes"))
            not_playing_reason = player.get("notPlayingReason")
            not_playing_description = player.get("notPlayingDescription")
            availability_status = "dnp" if not played and (not_playing_reason or not_playing_description) else "available"
            rotation_role = "starter" if player.get("starter") else "bench"
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
                    player_id=str(player.get("personId") or name.lower().replace(" ", "-")),
                    player_name=name,
                    team_id=str(team_payload.get("teamTricode") or team_payload.get("teamId") or "").lower(),
                    usage_rate=round(usage_rate, 3),
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

        quarter_breakdown = [
            PlayerQuarterProjection(quarter="Q1", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q2", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q3", points=0, assists=0, rebounds=0, threes_made=0),
            PlayerQuarterProjection(quarter="Q4", points=0, assists=0, rebounds=0, threes_made=0),
        ]

        live = projection.live_stats
        proj = projection.projected_stats.mean
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
                {"label": "Points", "live": live.points, "projected": round(proj.points, 1)},
                {"label": "Assists", "live": live.assists, "projected": round(proj.assists, 1)},
                {"label": "Rebounds", "live": live.rebounds, "projected": round(proj.rebounds, 1)},
                {"label": "3PM", "live": live.threes_made, "projected": round(proj.threes_made, 1)},
                {"label": "Turnovers", "live": live.turnovers, "projected": round(proj.turnovers, 1)},
            ],
            matchup_factors=[
                f"Usage load at {(proj.usage_rate * 100):.0f}%",
                f"{opponent.team_name} defensive rating {opponent.defensive_rating:.0f}",
                f"{team.team_name} pace baseline {team.pace:.0f}",
                "weak-side help timing",
                "rotation staggering leverage",
            ],
            confidence={
                "floor_points": round(projection.projected_stats.low.points, 1),
                "median_points": round(proj.points, 1),
                "ceiling_points": round(projection.projected_stats.high.points, 1),
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

    def _estimate_bench_depth(self, players) -> float:
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

    def _average_fatigue(self, players) -> float:
        if not players:
            return 0.2
        return sum(player.fatigue_index for player in players) / len(players)

    def _estimate_momentum(self, home_score: int, away_score: int) -> float:
        total = max(1, home_score + away_score)
        return round(0.5 + abs(home_score - away_score) / total * 0.2, 3)

    def _build_prediction_hook(self, context: GameContext) -> str:
        all_players = context.home_team.players + context.away_team.players
        if not all_players:
            return f"{context.away_team.team_name} at {context.home_team.team_name} — projection model pending."
        lead_creator = max(all_players, key=lambda p: p.usage_rate + p.momentum_score)
        return (
            f"{lead_creator.player_name} is the primary leverage point. "
            "BallPredict will model coaching adjustments around that usage load "
            "once the prediction engine is applied."
        )


live_game_service = LiveGameService()
