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
            "SELECT pts, min FROM player_game_logs WHERE player_id = ? ORDER BY game_date DESC LIMIT 10",
            (player_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return 1.0

    # Require 20+ minutes so foul-trouble / injury games don't skew the ratio
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
        rows = conn.execute(
            """
            SELECT pts, ast, reb, stl, blk, fg3m, tov, min, fg_pct, fg3_pct
            FROM player_game_logs
            WHERE player_id = ?
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


def _xgb_predict(player: PlayerGameState, opponent_id: str, is_home: bool) -> dict[str, float] | None:
    if _MODELS is None:
        return None
    history  = _player_history(player.player_id)
    opp_def  = _opponent_def_stats(opponent_id)
    feat_row = _build_features(player, history, opp_def, is_home)
    X = np.array([[feat_row.get(c, 0.0) for c in _MODELS["_features"]]])
    return {t: float(max(0.0, _MODELS[t].predict(X)[0])) for t in _TARGETS}


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
            # XGBoost full-game prediction adjusted for quarters already played.
            # hot_factor is NOT applied to the mean — XGBoost already captures recent
            # form through rolling averages. hot_factor only widens/tightens the band.
            remaining_frac = max(0.0, (4 - context.quarter) / 4.0)
            proj_pts  = round(player.points  + max(0.0, preds["pts"]  - player.points)  * remaining_frac, 1)
            proj_ast  = round(player.assists + max(0.0, preds["ast"]  - player.assists) * remaining_frac, 1)
            proj_reb  = round(player.rebounds + max(0.0, preds["reb"] - player.rebounds) * remaining_frac, 1)
            proj_stl  = round(player.steals  + max(0.0, preds["stl"]  - player.steals)  * remaining_frac, 1)
            proj_blk  = round(player.blocks  + max(0.0, preds["blk"]  - player.blocks)  * remaining_frac, 1)
            proj_tov  = round(player.turnovers + max(0.0, preds["tov"] - player.turnovers) * remaining_frac, 1)
            proj_fg3m = round(player.threes_made + max(0.0, preds["fg3m"] - player.threes_made) * remaining_frac, 1)

            spread = 1.0 + pressure * 1.8
        else:
            # XGBoost unavailable — use season averages directly.
            remaining_q = max(0, 4 - context.quarter)
            proj_pts  = round(player.points  + (player.pts_avg  / 4.0) * remaining_q, 1) if player.pts_avg  > 0 else round(player.points,  1)
            proj_ast  = round(player.assists + (player.ast_avg  / 4.0) * remaining_q, 1) if player.ast_avg  > 0 else round(player.assists, 1)
            proj_reb  = round(player.rebounds + (player.reb_avg / 4.0) * remaining_q, 1) if player.reb_avg  > 0 else round(player.rebounds, 1)
            proj_stl  = round(player.steals  + (player.stl_avg  / 4.0) * remaining_q, 1) if player.stl_avg  > 0 else round(player.steals,  1)
            proj_blk  = round(player.blocks  + (player.blk_avg  / 4.0) * remaining_q, 1) if player.blk_avg  > 0 else round(player.blocks,  1)
            proj_tov  = round(player.turnovers + (player.tov_avg / 4.0) * remaining_q, 1) if player.tov_avg > 0 else round(player.turnovers, 1)
            proj_fg3m = round(player.threes_made + (player.fg3m_avg / 4.0) * remaining_q, 1) if player.fg3m_avg > 0 else round(player.threes_made, 1)
            spread = 1.2 + pressure * 2.0

        mean_line = StatLine(
            points=proj_pts, assists=proj_ast, rebounds=proj_reb,
            steals=proj_stl, blocks=proj_blk, turnovers=proj_tov,
            **{"3pm": proj_fg3m},
            usage_rate=round(max(0.10, min(0.42, player.usage_rate)), 3),
            field_goal_pct=round(max(0.33, min(0.68, player.field_goal_pct)), 3),
            three_point_pct=round(max(0.25, min(0.55, player.three_point_pct)), 3),
        )
        # Hot players get a tighter floor (harder to have a bad game mid-streak)
        # and a much higher ceiling (takeover potential is real).
        # Cold players get a wider floor (regression likely) and lower ceiling.
        floor_mult   = 1.0 - (hot - 1.0) * 0.4   # hot=1.45 → floor_mult=0.82 (tighter)
        ceiling_mult = 1.0 + (hot - 1.0) * 1.8    # hot=1.45 → ceiling_mult=1.81 (way higher)

        low_line = mean_line.model_copy(update={
            "points":    round(max(0, proj_pts  - spread * 2.2 * floor_mult), 1),
            "assists":   round(max(0, proj_ast  - spread * 0.8 * floor_mult), 1),
            "rebounds":  round(max(0, proj_reb  - spread * 0.7 * floor_mult), 1),
            "turnovers": round(max(0, proj_tov  - 0.4), 1),
        })
        high_line = mean_line.model_copy(update={
            "points":    round(proj_pts  + spread * 2.5 * ceiling_mult, 1),
            "assists":   round(proj_ast  + spread * 1.0 * ceiling_mult, 1),
            "rebounds":  round(proj_reb  + spread * 0.9 * ceiling_mult, 1),
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
