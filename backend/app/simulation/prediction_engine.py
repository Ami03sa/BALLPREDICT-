from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import numpy as np

from app.schemas.game import ConfidenceBand, PlayerProjection, StatLine, TeamProjection
from app.simulation.coaching_engine import coaching_engine
from app.simulation.state import GameContext, PlayerGameState, TeamGameState

_DATA_DIR  = Path(__file__).parent.parent.parent / "data"
_MODEL_DIR = _DATA_DIR / "models"
_DB_PATH   = _DATA_DIR / "nba_training.db"

_TARGETS = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov"]


def _load_models() -> dict | None:
    try:
        import xgboost as xgb
        models: dict = {}
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


def _hot_factor(player_id: str) -> float:
    """
    Compares last-3-game scoring to last-10-game average.
    Returns a multiplier:
      > 1.0 → player is running hot (takeover candidate)
      < 1.0 → player is cold / being contained
      1.0   → no meaningful trend
    Clamped to [0.70, 1.45] so it doesn't blow up projections.
    """
    if not _DB_PATH.exists():
        return 1.0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT pts, min FROM player_game_logs WHERE player_id = ? AND min > 0 ORDER BY game_date DESC LIMIT 10",
            (player_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return 1.0

    # Require 20+ minutes so foul-trouble games don't skew the ratio
    played = [(r[0], r[1]) for r in rows if float(r[1] or 0) >= 20]
    if len(played) < 4:
        return 1.0

    last3_avg  = sum(p[0] for p in played[:3]) / 3
    last10_avg = sum(p[0] for p in played) / len(played)

    if last10_avg <= 0:
        return 1.0

    ratio = last3_avg / last10_avg
    return round(min(1.45, max(0.70, ratio)), 3)


def _player_history(player_id: str) -> dict:
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(_DB_PATH)
        # Only include games the player actually played (min > 0).
        # DNP/missed games have 0 stats and would pull every rolling average down
        # artificially — skip them and use the real played games immediately before.
        rows = conn.execute(
            """
            SELECT pts, ast, reb, stl, blk, fg3m, tov, min, fg_pct, fg3_pct
            FROM player_game_logs
            WHERE player_id = ? AND min > 0
            ORDER BY game_date DESC
            LIMIT 10
            """,
            (player_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    if not rows:
        return {}
    cols = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct"]
    return {c: [r[i] for r in rows] for i, c in enumerate(cols)}


def _opponent_def_stats(opponent_id: str) -> dict:
    defaults = {"opp_pts_per_game": 114.0, "opp_fg_pct": 0.46, "opp_fg3_pct": 0.36}
    if not _DB_PATH.exists():
        return defaults
    try:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute(
            """
            SELECT opp_pts_per_game, opp_fg_pct, opp_fg3_pct
            FROM team_defensive_stats
            WHERE team_abbreviation = ? AND season = '2024-25' AND season_type = 'Regular Season'
            """,
            (opponent_id.upper(),),
        ).fetchone()
        conn.close()
        if row:
            return {"opp_pts_per_game": row[0], "opp_fg_pct": row[1], "opp_fg3_pct": row[2]}
    except Exception:
        pass
    return defaults


def _rolling(values: list[float], n: int) -> float:
    subset = values[:n]
    return float(np.mean(subset)) if subset else 0.0


def _build_features(player: PlayerGameState, history: dict, opp_def: dict, is_home: bool) -> dict:
    row: dict[str, float] = {}
    for stat in ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct"]:
        vals = history.get(stat, [])
        row[f"{stat}_last5"]      = _rolling(vals, 5)
        row[f"{stat}_last10"]     = _rolling(vals, 10)
        row[f"{stat}_season_avg"] = float(np.mean(vals)) if vals else 0.0
    row["opp_pts_per_game"] = opp_def.get("opp_pts_per_game", 114.0)
    row["opp_fg_pct"]       = opp_def.get("opp_fg_pct", 0.46)
    row["opp_fg3_pct"]      = opp_def.get("opp_fg3_pct", 0.36)
    row["is_home"]          = float(is_home)
    row["rest_days"]        = 2.0
    return row


_NOISE_SCALES: dict[str, float] = {
    # Rolling scoring stats — higher variance in last-5 than last-10
    "pts_last5": 3.0,   "pts_last10": 1.8,   "pts_season_avg": 1.0,
    "ast_last5": 1.0,   "ast_last10": 0.6,   "ast_season_avg": 0.3,
    "reb_last5": 1.5,   "reb_last10": 0.9,   "reb_season_avg": 0.5,
    "stl_last5": 0.4,   "stl_last10": 0.25,  "stl_season_avg": 0.15,
    "blk_last5": 0.5,   "blk_last10": 0.3,   "blk_season_avg": 0.2,
    "fg3m_last5": 0.8,  "fg3m_last10": 0.5,  "fg3m_season_avg": 0.3,
    "tov_last5": 0.5,   "tov_last10": 0.3,   "tov_season_avg": 0.2,
    "min_last5": 2.5,   "min_last10": 1.5,   "min_season_avg": 1.0,
    # Shooting percentages
    "fg_pct_last5": 0.030,  "fg_pct_last10": 0.018,  "fg_pct_season_avg": 0.010,
    "fg3_pct_last5": 0.040, "fg3_pct_last10": 0.025, "fg3_pct_season_avg": 0.015,
    # Opponent defense varies game-to-game
    "opp_pts_per_game": 2.5,
    "opp_fg_pct": 0.020,
    "opp_fg3_pct": 0.025,
    # Rest days uncertainty (we default to 2.0)
    "rest_days": 0.8,
}

_N_RUNS = 200  # number of perturbed runs per prediction


def _xgb_predict(player: PlayerGameState, opponent_id: str, is_home: bool) -> dict[str, dict] | None:
    """
    Run each XGBoost model _N_RUNS times with perturbed features and return
    the mean and std of predictions. Adding noise to rolling stats and opponent
    defense captures real game-to-game variance and gives data-driven CI.
    """
    if _MODELS is None:
        return None
    history  = _player_history(player.player_id)
    opp_def  = _opponent_def_stats(opponent_id)
    feat_row = _build_features(player, history, opp_def, is_home)
    feature_cols = _MODELS["_features"]

    base_X = np.array([feat_row.get(c, 0.0) for c in feature_cols])

    # Build noise matrix: shape (N_RUNS, n_features)
    noise = np.zeros((_N_RUNS, len(feature_cols)))
    for i, col in enumerate(feature_cols):
        scale = _NOISE_SCALES.get(col, 0.0)
        if scale > 0:
            noise[:, i] = np.random.normal(0, scale, _N_RUNS)

    X_batch = np.clip(np.tile(base_X, (_N_RUNS, 1)) + noise, 0, None)

    results: dict[str, dict] = {}
    for t in _TARGETS:
        preds = np.clip(_MODELS[t].predict(X_batch), 0, None)
        results[t] = {
            "mean": float(np.mean(preds)),
            "std":  float(np.std(preds)),
        }
    return results


class PredictionEngine:

    def project_player(
        self,
        context: GameContext,
        offense: TeamGameState,
        defense: TeamGameState,
        player: PlayerGameState,
    ) -> PlayerProjection:
        zero_line = StatLine()

        if player.availability_status == "dnp":
            return PlayerProjection(
                player_id=player.player_id,
                player_name=player.player_name,
                team_id=player.team_id,
                quarter=context.quarter,
                rotation_role=player.rotation_role,
                availability_status="dnp",
                dnp_reason=player.dnp_reason,
                live_stats=zero_line,
                projected_stats=ConfidenceBand(low=zero_line, mean=zero_line, high=zero_line),
                momentum_score=0.5,
                fatigue_index=0.0,
                defensive_pressure=0.0,
                adjustments=[],
            )

        adjustments = coaching_engine.build_player_counters(context, offense, defense, player)
        pressure = min(1.0, player.matchup_difficulty + player.fatigue_index + len(adjustments) * 0.08)
        is_home  = offense.team_id == context.home_team.team_id

        # Hot factor: ratio of last-3-game scoring vs last-10-game average.
        # Nudges the mean projection and significantly widens the ceiling for hot players.
        hot = _hot_factor(player.player_id)

        preds = _xgb_predict(player, defense.team_id, is_home)

        if preds is not None:
            # Use ensemble mean — more robust than a single run.
            proj_pts  = round(preds["pts"]["mean"],  1)
            proj_ast  = round(preds["ast"]["mean"],  1)
            proj_reb  = round(preds["reb"]["mean"],  1)
            proj_stl  = round(preds["stl"]["mean"],  1)
            proj_blk  = round(preds["blk"]["mean"],  1)
            proj_tov  = round(preds["tov"]["mean"],  1)
            proj_fg3m = round(preds["fg3m"]["mean"], 1)

            # Confidence band driven by prediction std — no manual multipliers needed.
            pts_std = preds["pts"]["std"]
            ast_std = preds["ast"]["std"]
            reb_std = preds["reb"]["std"]
            tov_std = preds["tov"]["std"]
            spread  = pts_std  # kept for hot_factor ceiling calculation
        else:
            # XGBoost unavailable — season average is the full-game prediction.
            proj_pts  = round(player.pts_avg,  1) if player.pts_avg  > 0 else 0.0
            proj_ast  = round(player.ast_avg,  1) if player.ast_avg  > 0 else 0.0
            proj_reb  = round(player.reb_avg,  1) if player.reb_avg  > 0 else 0.0
            proj_stl  = round(player.stl_avg,  1) if player.stl_avg  > 0 else 0.0
            proj_blk  = round(player.blk_avg,  1) if player.blk_avg  > 0 else 0.0
            proj_tov  = round(player.tov_avg,  1) if player.tov_avg  > 0 else 0.0
            proj_fg3m = round(player.fg3m_avg, 1) if player.fg3m_avg > 0 else 0.0
            spread = 1.2 + pressure * 2.0

        mean_line = StatLine(
            points=proj_pts, assists=proj_ast, rebounds=proj_reb,
            steals=proj_stl, blocks=proj_blk, turnovers=proj_tov,
            **{"3pm": proj_fg3m},
            usage_rate=round(max(0.10, min(0.42, player.usage_rate)), 3),
            field_goal_pct=round(max(0.33, min(0.68, player.field_goal_pct)), 3),
            three_point_pct=round(max(0.25, min(0.55, player.three_point_pct)), 3),
        )
        # Floor/ceiling from ensemble std — data-driven, no manual multipliers.
        # Hot players widen the ceiling further; cold players widen the floor.
        ceiling_mult = 1.0 + (hot - 1.0) * 1.8
        floor_mult   = 1.0 - (hot - 1.0) * 0.4

        if preds is not None:
            low_line = mean_line.model_copy(update={
                "points":    round(max(0, proj_pts - pts_std * 1.5 * floor_mult), 1),
                "assists":   round(max(0, proj_ast - ast_std * 1.5 * floor_mult), 1),
                "rebounds":  round(max(0, proj_reb - reb_std * 1.5 * floor_mult), 1),
                "turnovers": round(max(0, proj_tov - tov_std * 1.0), 1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(proj_pts + pts_std * 2.0 * ceiling_mult, 1),
                "assists":   round(proj_ast + ast_std * 2.0 * ceiling_mult, 1),
                "rebounds":  round(proj_reb + reb_std * 2.0 * ceiling_mult, 1),
                "turnovers": round(proj_tov + tov_std * 1.0, 1),
            })
        else:
            # Fallback: manual band when XGBoost unavailable
            low_line = mean_line.model_copy(update={
                "points":    round(max(0, proj_pts  - spread * 0.25), 1),
                "assists":   round(max(0, proj_ast  - spread * 0.15), 1),
                "rebounds":  round(max(0, proj_reb  - spread * 0.18), 1),
                "turnovers": round(max(0, proj_tov  - 0.4), 1),
            })
            high_line = mean_line.model_copy(update={
                "points":    round(proj_pts  + spread * 0.35 * ceiling_mult, 1),
                "assists":   round(proj_ast  + spread * 0.20 * ceiling_mult, 1),
                "rebounds":  round(proj_reb  + spread * 0.22 * ceiling_mult, 1),
                "turnovers": round(proj_tov  + 0.6, 1),
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
            hot_factor=hot,
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
        final_mean = player_score_sum if player_score_sum > 0 else team.score
        spread = max(4, int(final_mean * 0.10))

        home_edge = (
            context.home_team.offensive_rating - context.away_team.defensive_rating * 0.08 + context.home_advantage
        ) - (
            context.away_team.offensive_rating - context.home_team.defensive_rating * 0.08
        )
        win_prob = 1 / (1 + math.exp(-(home_edge / 8.0 + context.score_margin * 0.22)))
        team_win_prob = win_prob if is_home else 1 - win_prob

        # Build per-quarter score breakdown.
        q = context.quarter
        if q == 0:
            # Pre-game: distribute projected total evenly across 4 quarters.
            q_base = final_mean // 4
            projected_score = (q_base, q_base, q_base, final_mean - q_base * 3)
        else:
            # Live/final: approximate past quarters from actual cumulative score,
            # project future quarters from the remaining expected points.
            remaining_q = max(0, 4 - q)
            actual_per_q = round(team.score / q) if q > 0 else 0
            future_per_q = round((final_mean - team.score) / remaining_q) if remaining_q > 0 else 0
            quarters = [actual_per_q] * min(q, 4) + [future_per_q] * remaining_q
            projected_score = tuple(quarters[:4])  # type: ignore[assignment]

        return TeamProjection(
            team_id=team.team_id,
            team_name=team.team_name,
            quarter=context.quarter,
            score=team.score,
            projected_score=projected_score,
            final_score_mean=final_mean,
            final_score_ci=(max(0, final_mean - spread), final_mean + spread),
            pace=round(team.pace, 1),
            offensive_rating=round(team.offensive_rating, 1),
            defensive_rating=round(opponent.defensive_rating, 1),
            win_probability=round(team_win_prob, 3),
        )


prediction_engine = PredictionEngine()
