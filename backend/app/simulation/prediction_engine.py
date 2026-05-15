from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from statistics import mean

import numpy as np

from app.schemas.game import ConfidenceBand, PlayerProjection, StatLine, TeamProjection
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState

_DATA_DIR  = Path(__file__).parent.parent.parent / "data"
_MODEL_DIR = _DATA_DIR / "models"
_DB_PATH   = _DATA_DIR / "nba_training.db"

_TARGETS  = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov"]


def _load_models() -> dict | None:
    """Load XGBoost models from disk. Returns None if not yet trained."""
    try:
        import xgboost as xgb
        import json
        models = {}
        for t in _TARGETS:
            path = _MODEL_DIR / f"model_{t}.json"
            if not path.exists():
                return None
            m = xgb.XGBRegressor()
            m.load_model(str(path))
            models[t] = m
        with open(_MODEL_DIR / "features.json") as f:
            models["_features"] = json.load(f)
        return models
    except Exception:
        return None


_MODELS = _load_models()


def _player_history(player_id: str) -> dict:
    """Fetch rolling stats for a player from the training DB."""
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute("""
            SELECT pts, ast, reb, stl, blk, fg3m, tov, min, fg_pct, fg3_pct
            FROM player_game_logs
            WHERE player_id = ?
            ORDER BY game_date DESC
            LIMIT 10
        """, (player_id,)).fetchall()
        conn.close()
    except Exception:
        return {}

    if not rows:
        return {}

    cols = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct"]
    history = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
    return history


def _opponent_def_stats(opponent_id: str) -> dict:
    """Fetch opponent defensive profile from the training DB."""
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute("""
            SELECT opp_pts_per_game, opp_fg_pct, opp_fg3_pct
            FROM team_defensive_stats
            WHERE team_abbreviation = ? AND season = '2024-25' AND season_type = 'Regular Season'
        """, (opponent_id.upper(),)).fetchone()
        conn.close()
        if row:
            return {"opp_pts_per_game": row[0], "opp_fg_pct": row[1], "opp_fg3_pct": row[2]}
    except Exception:
        pass
    return {"opp_pts_per_game": 114.0, "opp_fg_pct": 0.46, "opp_fg3_pct": 0.36}


def _rolling(values: list[float], n: int) -> float:
    subset = values[:n]
    return float(np.mean(subset)) if subset else 0.0


def _build_feature_row(
    player: PlayerGameState,
    history: dict,
    opp_def: dict,
    is_home: bool,
    rest_days: float,
) -> dict:
    row: dict[str, float] = {}
    roll_stats = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct"]
    for stat in roll_stats:
        vals = history.get(stat, [])
        row[f"{stat}_last5"]      = _rolling(vals, 5)
        row[f"{stat}_last10"]     = _rolling(vals, 10)
        row[f"{stat}_season_avg"] = float(np.mean(vals)) if vals else 0.0
    row["opp_pts_per_game"] = opp_def.get("opp_pts_per_game", 114.0)
    row["opp_fg_pct"]       = opp_def.get("opp_fg_pct", 0.46)
    row["opp_fg3_pct"]      = opp_def.get("opp_fg3_pct", 0.36)
    row["is_home"]          = float(is_home)
    row["rest_days"]        = float(rest_days)
    return row


def _xgb_predict(player: PlayerGameState, opponent_id: str, is_home: bool) -> dict[str, float] | None:
    """Return per-stat predictions using trained XGBoost models. Returns None if models unavailable."""
    if _MODELS is None:
        return None
    history  = _player_history(player.player_id)
    opp_def  = _opponent_def_stats(opponent_id)
    feat_row = _build_feature_row(player, history, opp_def, is_home, rest_days=2.0)
    feature_cols = _MODELS["_features"]
    X = np.array([[feat_row.get(c, 0.0) for c in feature_cols]])

    return {
        t: float(max(0.0, _MODELS[t].predict(X)[0]))
        for t in _TARGETS
    }


class PredictionEngine:
    """XGBoost-backed player and team projection engine."""

    def _apply_adjustments(self, player: PlayerGameState, adjustments: list[dict[str, float]]) -> dict[str, float]:
        accumulator = {
            "points": player.points,
            "assists": player.assists,
            "rebounds": player.rebounds,
            "steals": player.steals,
            "blocks": player.blocks,
            "turnovers": player.turnovers,
            "3pm": player.threes_made,
            "usage_rate": player.usage_rate,
            "field_goal_pct": player.field_goal_pct,
            "three_point_pct": player.three_point_pct,
        }
        for impact in adjustments:
            accumulator["usage_rate"]     += impact.get("usage_rate", 0)
            accumulator["field_goal_pct"] += impact.get("field_goal_pct", 0)
            accumulator["three_point_pct"]+= impact.get("three_point_pct", 0)
            accumulator["assists"]        += impact.get("assists", 0)
            accumulator["turnovers"]      += impact.get("turnovers", 0)
            accumulator["3pm"]            += impact.get("teammate_corner_3_rate", 0) * 2.0
        return accumulator

    def project_player(
        self,
        context: GameContext,
        offense: TeamGameState,
        defense: TeamGameState,
        player: PlayerGameState,
    ) -> PlayerProjection:
        if player.availability_status == "dnp":
            zero_line = StatLine()
            return PlayerProjection(
                player_id=player.player_id,
                player_name=player.player_name,
                team_id=player.team_id,
                quarter=context.quarter,
                rotation_role=player.rotation_role,
                availability_status=player.availability_status,
                dnp_reason=player.dnp_reason,
                live_stats=zero_line,
                projected_stats=ConfidenceBand(low=zero_line, mean=zero_line, high=zero_line),
                momentum_score=player.momentum_score,
                fatigue_index=player.fatigue_index,
                defensive_pressure=0.0,
                adjustments=[],
            )

        adjustments = coaching_engine.build_player_counters(context, offense, defense, player)
        pressure = min(1.0, player.matchup_difficulty + player.fatigue_index + len(adjustments) * 0.08)

        is_home = offense.team_id == context.home_team.team_id
        preds = _xgb_predict(player, defense.team_id, is_home)

        if preds is not None:
            # XGBoost full-game projection — adjust for already-played quarters
            remaining_frac = max(0.0, (4 - context.quarter) / 4.0)
            already_pts  = player.points
            already_ast  = player.assists
            already_reb  = player.rebounds
            already_stl  = player.steals
            already_blk  = player.blocks
            already_tov  = player.turnovers
            already_fg3m = player.threes_made

            proj_pts  = round(already_pts  + max(0.0, preds["pts"]  - already_pts)  * remaining_frac, 1)
            proj_ast  = round(already_ast  + max(0.0, preds["ast"]  - already_ast)  * remaining_frac, 1)
            proj_reb  = round(already_reb  + max(0.0, preds["reb"]  - already_reb)  * remaining_frac, 1)
            proj_stl  = round(already_stl  + max(0.0, preds["stl"]  - already_stl)  * remaining_frac, 1)
            proj_blk  = round(already_blk  + max(0.0, preds["blk"]  - already_blk)  * remaining_frac, 1)
            proj_tov  = round(already_tov  + max(0.0, preds["tov"]  - already_tov)  * remaining_frac, 1)
            proj_fg3m = round(already_fg3m + max(0.0, preds["fg3m"] - already_fg3m) * remaining_frac, 1)

            spread = 1.0 + pressure * 1.8
            mean_line = StatLine(
                points=proj_pts, assists=proj_ast, rebounds=proj_reb,
                steals=proj_stl, blocks=proj_blk, turnovers=proj_tov,
                **{"3pm": proj_fg3m},
                usage_rate=round(max(0.10, min(0.42, player.usage_rate)), 3),
                field_goal_pct=round(max(0.33, min(0.68, player.field_goal_pct)), 3),
                three_point_pct=round(max(0.25, min(0.55, player.three_point_pct)), 3),
            )
            low_line = mean_line.model_copy(update={
                "points":    round(max(0, proj_pts  - spread * 2.2), 1),
                "assists":   round(max(0, proj_ast  - spread * 0.8), 1),
                "rebounds":  round(max(0, proj_reb  - spread * 0.7), 1),
                "turnovers": round(max(0, proj_tov  - 0.4), 1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(proj_pts  + spread * 2.5, 1),
                "assists":   round(proj_ast  + spread * 1.0, 1),
                "rebounds":  round(proj_reb  + spread * 0.9, 1),
                "turnovers": round(proj_tov  + 0.6, 1),
            })
        else:
            # Fallback statistical model when XGBoost models not available
            remaining_quarters = max(0, 4 - context.quarter)
            usage_mult = max(0.78, 1 - pressure * 0.22)
            eff_mult   = max(0.72, 1 - pressure * 0.18)
            base_min   = remaining_quarters * 8.5

            mean_line = StatLine(
                points=round(player.points + player.usage_rate * base_min * 1.5 * usage_mult, 1),
                assists=round(player.assists + max(0.5, player.assists * 0.08 + remaining_quarters * 0.9), 1),
                rebounds=round(player.rebounds + remaining_quarters * (1.1 + (1 - player.fatigue_index)), 1),
                steals=round(player.steals + remaining_quarters * 0.3, 1),
                blocks=round(player.blocks + remaining_quarters * 0.2, 1),
                turnovers=round(player.turnovers + max(0.3, player.turnovers * 0.1), 1),
                **{"3pm": round(player.threes_made + remaining_quarters * 0.7 * usage_mult, 1)},
                usage_rate=round(max(0.12, min(0.42, player.usage_rate)), 3),
                field_goal_pct=round(max(0.33, min(0.68, player.field_goal_pct * eff_mult)), 3),
                three_point_pct=round(max(0.25, min(0.55, player.three_point_pct * eff_mult)), 3),
            )
            spread = 1.2 + pressure * 2.2
            low_line = mean_line.model_copy(update={
                "points":    round(max(0, mean_line.points   - spread * 2.4), 1),
                "assists":   round(max(0, mean_line.assists  - spread * 0.8), 1),
                "rebounds":  round(max(0, mean_line.rebounds - spread * 0.7), 1),
                "turnovers": round(max(0, mean_line.turnovers - 0.5), 1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(mean_line.points   + spread * 2.8, 1),
                "assists":   round(mean_line.assists  + spread * 1.1, 1),
                "rebounds":  round(mean_line.rebounds + spread * 0.9, 1),
                "turnovers": round(mean_line.turnovers + 0.7, 1),
            })

        return PlayerProjection(
            player_id=player.player_id,
            player_name=player.player_name,
            team_id=player.team_id,
            quarter=context.quarter,
            rotation_role=player.rotation_role,
            availability_status=player.availability_status,
            dnp_reason=player.dnp_reason,
            live_stats=StatLine(
                points=player.points, assists=player.assists,
                rebounds=player.rebounds, steals=player.steals,
                blocks=player.blocks, turnovers=player.turnovers,
                **{"3pm": player.threes_made},
                usage_rate=player.usage_rate,
                field_goal_pct=player.field_goal_pct,
                three_point_pct=player.three_point_pct,
            ),
            projected_stats=ConfidenceBand(low=low_line, mean=mean_line, high=high_line),
            momentum_score=player.momentum_score,
            fatigue_index=player.fatigue_index,
            defensive_pressure=pressure,
            adjustments=adjustments,
        )

    def project_team(
        self,
        context: GameContext,
        team: TeamGameState,
        opponent: TeamGameState,
        is_home: bool,
        player_score_sum: int = 0,
    ) -> TeamProjection:
        """
        Build team projection.  final_score_mean = sum of player XGBoost point
        projections (passed in from projection_service after players are projected).
        Win probability is derived from score margin + ratings edge.
        """
        final_mean = player_score_sum if player_score_sum > 0 else team.score
        spread     = max(4, int(final_mean * 0.11))
        ci         = (max(0, final_mean - spread), final_mean + spread)

        if context.quarter <= 0:
            base_q = final_mean / 4
            quarter_projection = tuple(max(20, round(base_q + d)) for d in (-1, 1, -2, 2))
        else:
            q_seed = team.score / max(context.quarter, 1)
            quarter_projection = tuple(max(16, round(q_seed + d)) for d in (0, 2, -1, 1))

        home_edge = (
            context.home_team.offensive_rating
            - context.away_team.defensive_rating * 0.08
            + context.home_advantage
        ) - (
            context.away_team.offensive_rating
            - context.home_team.defensive_rating * 0.08
        )
        win_prob      = 1 / (1 + math.exp(-(home_edge + context.score_margin * 0.22)))
        team_win_prob = win_prob if is_home else 1 - win_prob

        return TeamProjection(
            team_id=team.team_id,
            team_name=team.team_name,
            quarter=context.quarter,
            score=team.score,
            projected_score=quarter_projection,
            final_score_mean=final_mean,
            final_score_ci=ci,
            pace=round(team.pace + (context.live_pace_multiplier - 1) * 4, 1),
            offensive_rating=round(team.offensive_rating, 1),
            defensive_rating=round(opponent.defensive_rating, 1),
            win_probability=round(team_win_prob, 3),
        )


prediction_engine = PredictionEngine()
