from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import partial
from typing import Any

_LEAGUE_PASS = "League Pass"

import httpx
from fastapi import HTTPException

from app.schemas.game import (
    GameSnapshot,
    PlayerDetailResponse,
    PlayerProjection,
    PlayerQuarterProjection,
    SimulationResponse,
)
from app.services import nba_api_service
from app.services.nba_api_service import get_quarter_weights
from app.services.projection_service import projection_service
from app.services.providers.nba_live_client import nba_live_client
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext

logger = logging.getLogger(__name__)


_GAME_CACHE_PATH = (
    __import__("pathlib").Path(__file__).parent.parent.parent / "data" / "last_game_cache.json"
)


class LiveGameService:
    def __init__(self) -> None:
        self._contexts: dict[str, GameContext] = {}
        self._slate: dict[str, dict] = {}

    # ── Persistence helpers ────────────────────────────────────────────────

    def _save_game_cache(self, slate: dict, contexts: dict) -> None:
        """Persist minimal game metadata so the last game survives a server restart."""
        import json as _json
        try:
            payload = {}
            for game_id, ctx in contexts.items():
                meta = slate.get(game_id, {})
                payload[game_id] = {
                    "game_id": game_id,
                    "home_tc":      ctx.home_team.team_id.upper(),
                    "away_tc":      ctx.away_team.team_id.upper(),
                    "home_name":    ctx.home_team.team_name,
                    "away_name":    ctx.away_team.team_name,
                    "home_team_id": meta.get("home_team_id", 0),
                    "away_team_id": meta.get("away_team_id", 0),
                    "home_score":   ctx.home_team.score,
                    "away_score":   ctx.away_team.score,
                    "status":       meta.get("status", "final"),
                    "tipoff":       meta.get("tipoff", ""),
                    "headline":     meta.get("headline", ""),
                    "home_record":  meta.get("home_record", ""),
                    "away_record":  meta.get("away_record", ""),
                    "playoff_intensity": ctx.playoff_intensity,
                    # Team ratings — needed for quality projections
                    "home_off_rtg": ctx.home_team.offensive_rating,
                    "home_def_rtg": ctx.home_team.defensive_rating,
                    "home_pace":    ctx.home_team.pace,
                    "away_off_rtg": ctx.away_team.offensive_rating,
                    "away_def_rtg": ctx.away_team.defensive_rating,
                    "away_pace":    ctx.away_team.pace,
                    "home_vegas":   ctx.home_vegas_total,
                    "away_vegas":   ctx.away_vegas_total,
                    # Date the game was played — used to expire the cache at midnight
                    "game_date":    __import__("datetime").date.today().isoformat(),
                }
            _GAME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _GAME_CACHE_PATH.write_text(_json.dumps(payload, indent=2))
            logger.info("Game cache saved: %d game(s) → %s", len(payload), _GAME_CACHE_PATH)
        except Exception as exc:
            logger.warning("Could not save game cache: %s", exc)

    async def _bootstrap_from_cache(self) -> bool:
        """
        Load last known game(s) from disk and rebuild contexts using current
        DB season averages.  Only restores if the cached game was played TODAY —
        once the day rolls over the slate resets to empty so the app is ready
        for the next game day.
        Returns True if at least one game was restored.
        """
        import json as _json
        from datetime import date as _date
        if not _GAME_CACHE_PATH.exists():
            return False
        try:
            payload = _json.loads(_GAME_CACHE_PATH.read_text())
        except Exception as exc:
            logger.warning("Could not read game cache: %s", exc)
            return False

        if not payload:
            return False

        # Expire cache at midnight — only restore if every cached game was today.
        today = _date.today().isoformat()
        cached_dates = {meta.get("game_date", "") for meta in payload.values()}
        if not all(d == today for d in cached_dates):
            logger.info(
                "Game cache is from a previous day (%s) — slate will be empty until today's games start.",
                ", ".join(cached_dates),
            )
            return False

        from app.services.providers.nba_live_client import nba_live_client
        from app.services.nba_api_service import (
            _build_team_state_from_season_stats,
            _enrich_players_from_db,
        )
        from app.simulation.state import GameContext, TeamGameState

        restored = 0
        for game_id, meta in payload.items():
            try:
                home_tc = meta["home_tc"]
                away_tc = meta["away_tc"]
                home_team_id = int(meta.get("home_team_id") or 0)
                away_team_id = int(meta.get("away_team_id") or 0)

                # Fetch fresh season stats from API; fall back to empty (DB fills gaps)
                home_season, away_season = [], []
                try:
                    home_season, away_season = await asyncio.gather(
                        nba_live_client.fetch_player_season_stats(home_team_id),
                        nba_live_client.fetch_player_season_stats(away_team_id),
                    )
                except Exception:
                    pass  # _enrich_players_from_db will cover it

                # Minimal team_raw dicts for the builder
                home_raw = {"teamTricode": home_tc, "teamId": home_team_id,
                            "teamCity": "", "teamName": meta.get("home_name", home_tc)}
                away_raw = {"teamTricode": away_tc, "teamId": away_team_id,
                            "teamCity": "", "teamName": meta.get("away_name", away_tc)}

                # Build teams with season-avg ratings from cache
                _fake_ratings = {
                    home_tc: {"off_rating": meta["home_off_rtg"], "def_rating": meta["home_def_rtg"], "pace": meta["home_pace"]},
                    away_tc: {"off_rating": meta["away_off_rtg"], "def_rating": meta["away_def_rtg"], "pace": meta["away_pace"]},
                }

                if home_season and away_season:
                    home_team = _build_team_state_from_season_stats(
                        home_raw, meta.get("home_score", 0), home_season, _fake_ratings
                    )
                    away_team = _build_team_state_from_season_stats(
                        away_raw, meta.get("away_score", 0), away_season, _fake_ratings
                    )
                else:
                    # No API data — we'll rely entirely on DB enrichment below
                    from app.services.nba_api_service import _build_minimal_team_state
                    home_team = _build_minimal_team_state(home_raw, meta.get("home_score", 0), _fake_ratings)
                    away_team = _build_minimal_team_state(away_raw, meta.get("away_score", 0), _fake_ratings)

                # DB enrichment fills any remaining pts_avg=0 gaps
                _enrich_players_from_db(home_team)
                _enrich_players_from_db(away_team)

                ctx = GameContext(
                    game_id=game_id,
                    quarter=4,
                    clock="0:00",
                    home_team=home_team,
                    away_team=away_team,
                    score_margin=meta.get("home_score", 0) - meta.get("away_score", 0),
                    home_advantage=2.4,
                    overtime_probability=0.02,
                    momentum=0.0,
                    fatigue_pressure=0.5,
                    whistle_tightness=0.48,
                    playoff_intensity=meta.get("playoff_intensity", 0.60),
                    live_pace_multiplier=1.0,
                    injury_risk_flags=[],
                    back_to_back=False,
                    home_vegas_total=meta.get("home_vegas"),
                    away_vegas_total=meta.get("away_vegas"),
                )

                slate_row = {
                    "game_id": game_id,
                    "status": meta.get("status", "final"),
                    "tipoff": meta.get("tipoff", ""),
                    "broadcast": "NBA TV",
                    "arena": "",
                    "headline": meta.get("headline", f"{away_tc} at {home_tc}"),
                    "home_team": meta.get("home_name", home_tc),
                    "away_team": meta.get("away_name", away_tc),
                    "home_abbreviation": home_tc,
                    "away_abbreviation": away_tc,
                    "home_record": meta.get("home_record", ""),
                    "away_record": meta.get("away_record", ""),
                }

                self._slate[game_id] = slate_row
                self._contexts[game_id] = ctx
                restored += 1
                logger.info(
                    "Restored cached game %s (%s vs %s) — %d home / %d away players",
                    game_id, home_tc, away_tc,
                    len(home_team.players), len(away_team.players),
                )
            except Exception as exc:
                logger.warning("Could not restore cached game %s: %s", game_id, exc)

        return restored > 0

    async def bootstrap_demo_game(self) -> None:
        """Called on startup — fetches today's real NBA games from the public CDN.
        If the scoreboard is empty but today's game was already played (final),
        restores the final score from disk so it stays visible for the rest of
        the day.  Once the date rolls over the cache is ignored and the slate
        resets to empty, ready for the next game day."""
        try:
            slate, contexts = await nba_api_service.fetch_today_slate_and_contexts()
            if contexts:
                self._slate = slate
                self._contexts = contexts
                # Persist team_id info needed for cache reconstruction
                for game_id, meta in slate.items():
                    ctx = contexts.get(game_id)
                    if ctx:
                        meta.setdefault("home_team_id", 0)
                        meta.setdefault("away_team_id", 0)
                self._save_game_cache(slate, contexts)
                logger.info("Loaded %d live NBA game(s) from CDN.", len(contexts))
            else:
                logger.warning("No NBA games today — restoring last known game from cache.")
                restored = await self._bootstrap_from_cache()
                if not restored:
                    logger.warning("No cached game available — slate will be empty.")
        except Exception as exc:
            logger.error("NBA CDN fetch failed (%s) — trying cache restore.", exc)
            try:
                await self._bootstrap_from_cache()
            except Exception:
                pass

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
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for game in scoreboard.get("scoreboard", {}).get("games", [])
                if int(game.get("gameStatus", 0)) >= 2
            ]
        except Exception:
            return [
                {
                    "game_id": game_id,
                    "matchup": f"{context.away_team.team_name} at {context.home_team.team_name}",
                    "quarter": context.quarter,
                    "clock": context.clock,
                    "score": f"{context.away_team.score}-{context.home_team.score}",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for game_id, context in self._contexts.items()
            ]

    async def list_slate_games(self) -> list[dict]:
        from datetime import date, timedelta

        results: list[dict] = []

        # ── Today's games from NBA CDN ──────────────────────────────────
        try:
            scoreboard = await nba_live_client.fetch_scoreboard()
            today_games = scoreboard.get("scoreboard", {}).get("games", [])
            for g in today_games:
                results.append(self._build_live_slate_row(g))
        except Exception:
            for game_id, slate_row in self._slate.items():
                if self._contexts.get(game_id):
                    results.append({**slate_row, "prediction_hook": self._build_prediction_hook(self._contexts[game_id])})

        today_ids = {r["game_id"] for r in results}

        # ── Upcoming games (today if CDN empty + next 2 days) from ESPN ────
        # When the NBA CDN has no games yet (pre-tip, CDN lags ~1h before tip-off)
        # we also check ESPN for tonight so the game shows up all day.
        # Games locked (days_until > 0) until it's their actual game day.
        espn_start = 0 if not results else 1   # include today only if CDN returned nothing
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                for delta in range(espn_start, 3):
                    future_date = (date.today() + timedelta(days=delta)).strftime("%Y%m%d")
                    r = await client.get(
                        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                        params={"dates": future_date},
                    )
                    if r.status_code != 200:
                        continue
                    for event in r.json().get("events", []):
                        comps = event.get("competitions", [{}])[0]
                        competitors = comps.get("competitors", [])
                        away_c = next((t for t in competitors if t["homeAway"] == "away"), {})
                        home_c = next((t for t in competitors if t["homeAway"] == "home"), {})
                        home_abbr = home_c.get("team", {}).get("abbreviation", "")
                        away_abbr = away_c.get("team", {}).get("abbreviation", "")
                        # Normalise ESPN "SA" → "SAS"
                        if home_abbr == "SA": home_abbr = "SAS"
                        if away_abbr == "SA": away_abbr = "SAS"
                        home_name = home_c.get("team", {}).get("displayName", home_abbr)
                        away_name = away_c.get("team", {}).get("displayName", away_abbr)
                        espn_id = event.get("id", "")
                        # Build a stable game_id we can reuse (prefixed so it's clear it's upcoming)
                        fake_game_id = f"upcoming_{espn_id}"
                        if fake_game_id in today_ids:
                            continue
                        game_date_str = event.get("date", "")
                        # Format tipoff for display
                        try:
                            from datetime import datetime, timezone
                            dt = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
                            # Convert to ET (UTC-4 during EDT)
                            dt_et = dt.replace(tzinfo=timezone.utc) - timedelta(hours=4)
                            tipoff_str = dt_et.strftime("%-I:%M %p ET")
                            game_date_display = dt_et.strftime("%a %b %-d")
                        except Exception:
                            tipoff_str = "TBD"
                            game_date_display = f"+{delta}d"

                        results.append({
                            "game_id": fake_game_id,
                            "status": "upcoming",
                            "tipoff": tipoff_str,
                            "game_date": game_date_display,
                            "days_until": delta,
                            "broadcast": comps.get("broadcasts", [{}])[0].get("names", [""])[0] if comps.get("broadcasts") else "",
                            "arena": comps.get("venue", {}).get("fullName", ""),
                            "headline": f"{away_name} at {home_name}",
                            "home_team": home_name,
                            "away_team": away_name,
                            "home_abbreviation": home_abbr,
                            "away_abbreviation": away_abbr,
                            # Use cached series record (e.g. "1-0") not ESPN's RS record (e.g. "62-20")
                            "home_record": self._series_record_for(home_abbr),
                            "away_record": self._series_record_for(away_abbr),
                            "prediction_hook": "Get Prediction" if delta <= 1 else f"Prediction available day before ({game_date_display})",
                        })
        except Exception as exc:
            logger.debug("Upcoming games fetch failed: %s", exc)

        return results

    async def get_game_preview(self, game_id: str) -> dict:
        # upcoming_ IDs come from ESPN pre-tip cards (NBA CDN hasn't posted the game yet).
        # Build a pre-game context from the cached slate row so predictions work all day.
        if game_id.startswith("upcoming_"):
            context, slate_row = await self._resolve_upcoming_context(game_id)
            return self._build_preview_payload(context, slate_row)
        context, scoreboard_game = await self._resolve_context(game_id)
        slate_row = self._build_live_slate_row(scoreboard_game) if scoreboard_game else self._slate.get(game_id, {"game_id": game_id, "status": "scheduled", "tipoff": "TBD", "broadcast": "", "arena": "", "headline": "", "home_team": "", "away_team": "", "home_abbreviation": "", "away_abbreviation": "", "home_record": "", "away_record": "", "prediction_hook": ""})
        return self._build_preview_payload(context, slate_row)

    async def get_game_snapshot(self, game_id: str) -> GameSnapshot:
        if game_id.startswith("upcoming_"):
            context, _ = await self._resolve_upcoming_context(game_id)
            status = "scheduled"
        else:
            context, scoreboard_game = await self._resolve_context(game_id)
            status = self._status_label(scoreboard_game.get("gameStatus")) if scoreboard_game else "scheduled"
        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(
            None, partial(projection_service.build_snapshot, context, status=status, possession_feed=[])
        )
        return snapshot

    async def get_player_detail(self, game_id: str, player_id: str) -> PlayerDetailResponse:
        if game_id.startswith("upcoming_"):
            context, _ = await self._resolve_upcoming_context(game_id)
            status = "scheduled"
        else:
            context, scoreboard_game = await self._resolve_context(game_id)
            status = self._status_label(scoreboard_game.get("gameStatus")) if scoreboard_game else "scheduled"
        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(
            None, partial(projection_service.build_snapshot, context, status=status, possession_feed=[])
        )
        return self._build_player_detail_payload(game_id, player_id, context, snapshot)

    async def _resolve_upcoming_context(self, game_id: str) -> tuple[GameContext, dict]:
        """Build a pre-game prediction context for an ESPN upcoming_ game_id."""
        # ── 1. Find the slate row ────────────────────────────────────────────
        slate_row: dict = {}
        for r in await self.list_slate_games():
            if r.get("game_id") == game_id:
                slate_row = r
                break
        if not slate_row:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not available on today's slate")

        home_tc = slate_row.get("home_abbreviation", "")
        away_tc = slate_row.get("away_abbreviation", "")

        # ── 2. Return cached context if already built ────────────────────────
        if game_id in self._contexts:
            return self._contexts[game_id], slate_row

        # ── 3. Try CDN – it may have come online since startup ───────────────
        try:
            _, contexts = await nba_api_service.fetch_today_slate_and_contexts()
            for real_id, ctx in (contexts or {}).items():
                ht = ctx.home_team.team_id.upper()
                at = ctx.away_team.team_id.upper()
                if ht == home_tc.upper() and at == away_tc.upper():
                    self._contexts[game_id] = ctx
                    logger.info("upcoming %s resolved from CDN as %s", game_id, real_id)
                    return ctx, slate_row
        except Exception:
            pass

        # ── 4. Same pipeline as Game 1: live season stats API → build team ──────
        import json as _json
        from app.services.nba_api_service import (
            _build_team_state_from_season_stats,
            _enrich_players_from_db,
            _build_minimal_team_state,
        )

        _ESPN_FIX = {"NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP"}
        home_tc_norm = _ESPN_FIX.get(home_tc.upper(), home_tc.upper())
        away_tc_norm = _ESPN_FIX.get(away_tc.upper(), away_tc.upper())

        # Look up NBA team IDs from the last game cache (stored by fetch_today_slate_and_contexts)
        home_team_id = 0
        away_team_id = 0
        try:
            if _GAME_CACHE_PATH.exists():
                cached = _json.loads(_GAME_CACHE_PATH.read_text())
                for meta in cached.values():
                    if meta.get("home_tc", "").upper() == home_tc_norm:
                        home_team_id = int(meta.get("home_team_id") or 0)
                    if meta.get("away_tc", "").upper() == away_tc_norm:
                        away_team_id = int(meta.get("away_team_id") or 0)
                    if meta.get("home_tc", "").upper() == away_tc_norm:
                        away_team_id = int(meta.get("home_team_id") or 0)
                    if meta.get("away_tc", "").upper() == home_tc_norm:
                        home_team_id = int(meta.get("away_team_id") or 0)
        except Exception:
            pass

        team_ratings: dict = {}
        try:
            team_ratings = await nba_live_client.fetch_team_ratings() or {}
        except Exception:
            pass

        home_raw = {"teamTricode": home_tc_norm, "teamId": home_team_id, "teamCity": "", "teamName": slate_row.get("home_team", home_tc)}
        away_raw = {"teamTricode": away_tc_norm, "teamId": away_team_id, "teamCity": "", "teamName": slate_row.get("away_team", away_tc)}

        # Fetch season stats — exact same call as fetch_today_slate_and_contexts for Game 1
        home_season_stats, away_season_stats = [], []
        try:
            home_season_stats, away_season_stats = await asyncio.gather(
                nba_live_client.fetch_player_season_stats(home_team_id),
                nba_live_client.fetch_player_season_stats(away_team_id),
            )
        except Exception as exc:
            logger.warning("Season stats fetch failed for upcoming %s: %s", game_id, exc)

        if home_season_stats and away_season_stats:
            home_team = _build_team_state_from_season_stats(home_raw, 0, home_season_stats, team_ratings)
            away_team = _build_team_state_from_season_stats(away_raw, 0, away_season_stats, team_ratings)
            logger.info("Upcoming %s: built from live season stats (%d + %d players)", game_id, len(home_team.players), len(away_team.players))
        else:
            # Last resort — minimal (no players); DB enrichment below won't add players but at least no crash
            home_team = _build_minimal_team_state(home_raw, 0, team_ratings)
            away_team = _build_minimal_team_state(away_raw, 0, team_ratings)
            logger.warning("Upcoming %s: season stats unavailable, using minimal team state", game_id)

        # DB enrichment fallback — same as fetch_today_slate_and_contexts
        _enrich_players_from_db(home_team)
        _enrich_players_from_db(away_team)

        ctx = GameContext(
            game_id=game_id,
            quarter=0,
            clock="",
            home_team=home_team,
            away_team=away_team,
            score_margin=0,
            home_advantage=2.4,
            overtime_probability=0.02,
            momentum=0.0,
            fatigue_pressure=0.5,
            whistle_tightness=0.48,
            playoff_intensity=0.55,
            live_pace_multiplier=1.0,
            injury_risk_flags=[],
            back_to_back=False,
            home_vegas_total=None,
            away_vegas_total=None,
        )
        self._contexts[game_id] = ctx
        logger.info("Built pre-game context for upcoming game %s (%s vs %s)", game_id, home_tc_norm, away_tc_norm)
        return ctx, slate_row

    async def _resolve_context(self, game_id: str) -> tuple[GameContext, dict | None]:
        """Try live fetch first; fall back to startup context."""
        from dataclasses import replace as dc_replace
        try:
            context, scoreboard_game, _ = await self._build_live_context_bundle(game_id)
            # If the live fetch produced no players (e.g. pre-game, boxscore unavailable),
            # enrich with the startup context's season-average rosters.
            startup = self._contexts.get(game_id)
            if startup:
                # Only fall back to startup (season-avg) players when the live context
                # has no players at all — i.e. boxscore unavailable (pre-game).
                # If the live context has players with real stats, keep them as-is.
                def _has_live_stats(players) -> bool:
                    return any(p.points > 0 or p.assists > 0 or p.rebounds > 0 for p in players)

                home_players = (
                    context.home_team.players
                    if context.home_team.players and _has_live_stats(context.home_team.players)
                    else (context.home_team.players or startup.home_team.players)
                )
                away_players = (
                    context.away_team.players
                    if context.away_team.players and _has_live_stats(context.away_team.players)
                    else (context.away_team.players or startup.away_team.players)
                )

                # ── Overlay season averages onto live players ─────────────────────
                # Live boxscore players have real game stats (points=30, assists=8, etc.)
                # but pts_avg/ast_avg/reb_avg are 0 because the boxscore endpoint doesn't
                # provide season averages. The form-first prediction model needs these to
                # anchor projections (form_pts = pts_avg × hot_factor).
                # Fix: for each live player, look up their matching startup player by
                # player_id and copy the season-average fields.
                def _overlay_season_avgs(live_list, startup_list):
                    if not startup_list:
                        return live_list
                    startup_map = {p.player_id: p for p in startup_list}
                    result = []
                    for lp in live_list:
                        sp = startup_map.get(lp.player_id)
                        if sp is None:
                            result.append(lp)
                            continue
                        # Copy season avg fields from startup; keep live game stats
                        result.append(dc_replace(
                            lp,
                            pts_avg=sp.pts_avg if sp.pts_avg > 0 else lp.pts_avg,
                            ast_avg=sp.ast_avg if sp.ast_avg > 0 else lp.ast_avg,
                            reb_avg=sp.reb_avg if sp.reb_avg > 0 else lp.reb_avg,
                            stl_avg=sp.stl_avg if sp.stl_avg > 0 else lp.stl_avg,
                            blk_avg=sp.blk_avg if sp.blk_avg > 0 else lp.blk_avg,
                            tov_avg=sp.tov_avg if sp.tov_avg > 0 else lp.tov_avg,
                            fg3m_avg=sp.fg3m_avg if sp.fg3m_avg > 0 else lp.fg3m_avg,
                            # Also use startup's usage_rate (more stable than single-game calc)
                            usage_rate=sp.usage_rate if sp.usage_rate > 0 else lp.usage_rate,
                            # Preserve usage-rate-based role we already computed for live player
                        ))
                    return result

                if _has_live_stats(home_players):
                    home_players = _overlay_season_avgs(home_players, startup.home_team.players)
                if _has_live_stats(away_players):
                    away_players = _overlay_season_avgs(away_players, startup.away_team.players)

                # Re-classify rotation_role after usage_rate overlay.
                # Uses same adjusted thresholds as nba_api_service.py (0.265 vs 0.28)
                # to compensate for the approximation formula underestimating usage.
                # pts_avg > 20 acts as a secondary star signal.
                def _reclassify_roles(players):
                    out = []
                    for p in players:
                        if p.availability_status == "dnp":
                            out.append(p)
                            continue
                        u = p.usage_rate
                        pts = p.pts_avg
                        role = ("star"     if u > 0.265 or pts > 20.0 else
                                "starter"  if u > 0.18  or pts > 11.0 else
                                "rotation" if u > 0.11  else "bench")
                        out.append(dc_replace(p, rotation_role=role))
                    return out

                home_players = _reclassify_roles(home_players)
                away_players = _reclassify_roles(away_players)

                # Always inject startup team ratings and Vegas totals — the live boxscore
                # context computes ratings from partial scores (score=0 pre-game → off_rating=114),
                # while startup fetched the real season OffRtg/DefRtg/Pace for every team.
                context = dc_replace(
                    context,
                    home_team=dc_replace(
                        context.home_team,
                        offensive_rating=startup.home_team.offensive_rating,
                        defensive_rating=startup.home_team.defensive_rating,
                        pace=startup.home_team.pace,
                        players=home_players or context.home_team.players,
                    ),
                    away_team=dc_replace(
                        context.away_team,
                        offensive_rating=startup.away_team.offensive_rating,
                        defensive_rating=startup.away_team.defensive_rating,
                        pace=startup.away_team.pace,
                        players=away_players or context.away_team.players,
                    ),
                    home_vegas_total=startup.home_vegas_total,
                    away_vegas_total=startup.away_vegas_total,
                )

            # DB enrichment: always populate pts_avg/usage_rate for players
            # that are still at 0 after the startup-overlay step.  This covers
            # historical games, pre-season tests, and any game where the live
            # API didn't return season-average stats.
            nba_api_service._enrich_players_from_db(context.home_team)
            nba_api_service._enrich_players_from_db(context.away_team)
            return context, scoreboard_game
        except StopIteration:
            pass
        except Exception as exc:
            logger.warning("Live fetch failed for %s (%s) — using startup context.", game_id, exc)
        context = self._contexts.get(game_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not available")
        return context, None

    async def _build_live_context_bundle(self, game_id: str) -> tuple[GameContext, dict[str, Any], dict[str, Any]]:
        scoreboard = await nba_live_client.fetch_scoreboard()
        games = scoreboard.get("scoreboard", {}).get("games", [])
        scoreboard_game = next(game for game in games if str(game.get("gameId")) == str(game_id))

        boxscore: dict[str, Any] = {}
        try:
            boxscore = await nba_live_client.fetch_boxscore(str(game_id))
        except Exception as exc:
            logger.warning("Boxscore unavailable for %s (%s) — using scoreboard data only.", game_id, exc)

        context = self._build_live_context(scoreboard_game, boxscore)
        return context, scoreboard_game, boxscore

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
            playoff_intensity=0.68 if "Conf." in (scoreboard_game.get("gameLabel") or "") else 0.60,
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

    def _build_live_players(self, team_payload: dict[str, Any], _team_possessions: float):
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
            if availability_status == "dnp":
                rotation_role = "dnp"
            else:
                # Assign rotation_role later based on usage_rate (after it's computed).
                # Placeholder — will be overwritten below.
                rotation_role = "bench"

            field_goal_pct = self._normalize_pct(stats.get("fieldGoalsPercentage"), 0.45)
            three_point_pct = self._normalize_pct(stats.get("threePointersPercentage"), 0.36)
            minutes_played = self._parse_minutes(stats.get("minutes") or stats.get("minutesCalculated"))
            player_actions = (
                self._safe_float(stats.get("fieldGoalsAttempted"))
                + 0.44 * self._safe_float(stats.get("freeThrowsAttempted"))
                + self._safe_float(stats.get("turnovers"))
            )
            usage_rate = max(0.08, min(0.42, player_actions / team_actions))

            # Usage-rate based role: adjusted threshold (0.265 vs 0.28) because
            # the single-game action ratio underestimates true season usage by ~2%.
            # Will be re-classified after season-avg overlay in _resolve_context.
            if availability_status != "dnp":
                if usage_rate > 0.265:
                    rotation_role = "star"
                elif usage_rate > 0.18:
                    rotation_role = "starter"
                elif usage_rate > 0.11:
                    rotation_role = "rotation"
                else:
                    rotation_role = "bench"

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
                    rotation_role=rotation_role,
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
        projection = next((player for player in snapshot.player_projections if player.player_id == player_id), None)
        if projection is None:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found in game {game_id}")

        if projection.team_id == context.home_team.team_id:
            team = context.home_team
            opponent = context.away_team
        else:
            team = context.away_team
            opponent = context.home_team

        live = projection.live_stats
        proj = projection.projected_stats.mean

        q = context.quarter

        n_adj    = len(projection.adjustments)
        pressure = projection.defensive_pressure   # 0.0 – 1.0
        hot      = projection.hot_factor           # 0.70 – 1.45
        takeover_shift = (hot - 1.0) * 0.06

        # Coaching suppression factors: Q1 is free, Q2-Q4 tighten as adjustments stack.
        suppression = [
            1.0,
            max(0.65, 1.0 - n_adj * 0.06),
            max(0.55, 1.0 - n_adj * 0.14),
            max(0.45, 1.0 - n_adj * 0.20 - pressure * 0.15),
        ]
        fallback_base = [
            0.28,
            max(0.18, 0.26 - n_adj * 0.015),
            max(0.15, 0.25 - n_adj * 0.035),
            max(0.12, 0.21 - n_adj * 0.05 - pressure * 0.04),
        ]

        # Real per-stat quarter weights from DB (pts, ast, reb, fg3m tracked separately).
        real_stat_weights = get_quarter_weights(projection.player_id)

        def _weights_for(stat_key: str) -> list[float]:
            if real_stat_weights and stat_key in real_stat_weights:
                base = [w * s for w, s in zip(real_stat_weights[stat_key], suppression)]
            elif real_stat_weights:
                # Unknown stat — use pts distribution as a proxy
                base = [w * s for w, s in zip(real_stat_weights["pts"], suppression)]
            else:
                base = fallback_base

            raw_w = [
                base[0] - takeover_shift * 1.5,
                base[1] - takeover_shift * 0.5,
                base[2] + takeover_shift * 0.8,
                base[3] + takeover_shift * 1.2,
            ]
            raw_w = [max(0.08, w) for w in raw_w]
            total = sum(raw_w)
            return [w / total for w in raw_w]

        def _split(projected: float, stat_key: str) -> list[float]:
            return [round(projected * w, 1) for w in _weights_for(stat_key)]

        pts_q  = _split(proj.points,      "pts")
        ast_q  = _split(proj.assists,     "ast")
        reb_q  = _split(proj.rebounds,    "reb")
        fg3_q  = _split(proj.threes_made, "fg3m")

        quarter_breakdown = [
            PlayerQuarterProjection(quarter="Q1", points=pts_q[0], assists=ast_q[0], rebounds=reb_q[0], threes_made=fg3_q[0]),
            PlayerQuarterProjection(quarter="Q2", points=pts_q[1], assists=ast_q[1], rebounds=reb_q[1], threes_made=fg3_q[1]),
            PlayerQuarterProjection(quarter="Q3", points=pts_q[2], assists=ast_q[2], rebounds=reb_q[2], threes_made=fg3_q[2]),
            PlayerQuarterProjection(quarter="Q4", points=pts_q[3], assists=ast_q[3], rebounds=reb_q[3], threes_made=fg3_q[3]),
        ]
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
                {"label": "Steals", "live": live.steals, "projected": round(proj.steals, 1)},
                {"label": "Blocks", "live": live.blocks, "projected": round(proj.blocks, 1)},
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

    def simulate_matchup(
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

    def _series_record_for(self, team_abbr: str) -> str:
        """Return the playoff series record (e.g. '1-0') for a team from the last game cache.
        Falls back to empty string if not found."""
        import json as _json
        # ESPN uses shortened codes that differ from NBA tricodes (NY→NYK, SA→SAS, GS→GSW, etc.)
        _ESPN_FIX = {"NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP", "OKC": "OKC"}
        abbr = _ESPN_FIX.get(team_abbr.upper(), team_abbr.upper())
        try:
            if not _GAME_CACHE_PATH.exists():
                return ""
            payload = _json.loads(_GAME_CACHE_PATH.read_text())
            for meta in payload.values():
                if meta.get("home_tc", "").upper() == abbr:
                    return meta.get("home_record", "")
                if meta.get("away_tc", "").upper() == abbr:
                    return meta.get("away_record", "")
        except Exception:
            pass
        return ""

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
                    return first.get("broadcasterDisplay") or first.get("longName") or first.get("shortName") or _LEAGUE_PASS
                return str(first)
            if isinstance(value, dict):
                return value.get("broadcasterDisplay") or value.get("longName") or value.get("shortName") or _LEAGUE_PASS
        return _LEAGUE_PASS

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
