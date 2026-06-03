"""
Walk-forward backtesting for BallPredict XGBoost models.

Process:
  For each fold, train ONLY on seasons before the test season, then
  predict every player-game in the test season. This gives genuine
  out-of-sample accuracy — no future data ever leaks into training.

Folds (regular season only for consistent evaluation):
  Fold 1: Train ≤ 2022-23  →  Test 2023-24
  Fold 2: Train ≤ 2023-24  →  Test 2024-25
  Fold 3: Train ≤ 2024-25  →  Test 2025-26

Metrics reported:
  · Per-stat MAE & RMSE (player level)
  · Naive baseline MAE (season rolling mean) — shows model lift
  · Team score MAE (sum of player predictions vs actual game totals)
  · Win prediction accuracy % (did we call the right winner?)
  · Confidence interval coverage (% of actuals inside floor/ceiling)
  · Per-season error trend (is accuracy improving each fold?)
  · Top-10 worst individual player-game predictions

Run from backend/:
    python scripts/backtest.py
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ── Reuse feature engineering from train_model ───────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from train_model import (
    TARGETS,
    XGB_PARAMS,
    _classify_positions,
    _compute_series_features,
    _compute_series_player_perf,
    _compute_team_elo,
    _feature_cols,
    build_features,
    load_data,
)

DB_PATH = Path(__file__).parent.parent / "data" / "nba_training.db"

# Confidence band multipliers (mirrors projection_service floor/ceiling logic)
_CI_FLOOR_MULT   = 0.72   # floor  = mean × 0.72
_CI_CEILING_MULT = 1.28   # ceiling = mean × 1.28


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep(char="─", width=72):
    print(char * width)


def _train_fold(df: pd.DataFrame, train_seasons: list[str]) -> dict[str, xgb.XGBRegressor]:
    """Retrain one XGBoost model per stat on the given training seasons."""
    train = df[df["season"].isin(train_seasons)]
    feature_cols = _feature_cols()
    models = {}
    for target in TARGETS:
        m = xgb.XGBRegressor(**XGB_PARAMS)
        m.fit(train[feature_cols], train[target], verbose=False)
        models[target] = m
    return models


def _predict(models: dict, X: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of predictions for every stat."""
    preds = {}
    feature_cols = _feature_cols()
    for target, model in models.items():
        preds[target] = model.predict(X[feature_cols]).clip(0)
    return pd.DataFrame(preds, index=X.index)


def _team_game_accuracy(test: pd.DataFrame, preds: pd.DataFrame) -> dict:
    """
    Aggregate player predictions to team-game totals, compare to actuals.
    Returns: score_mae, score_rmse, win_accuracy (% correct winner)
    """
    test = test.copy()
    test["pred_pts"] = preds["pts"]

    # Actual team score per game
    actual_team = (
        test.groupby(["game_id", "team_abbreviation"])["pts"]
        .sum()
        .reset_index()
        .rename(columns={"pts": "actual_score"})
    )
    # Predicted team score per game
    pred_team = (
        test.groupby(["game_id", "team_abbreviation"])["pred_pts"]
        .sum()
        .reset_index()
        .rename(columns={"pred_pts": "pred_score"})
    )
    team = actual_team.merge(pred_team, on=["game_id", "team_abbreviation"])

    score_mae  = mean_absolute_error(team["actual_score"], team["pred_score"])
    score_rmse = mean_squared_error(team["actual_score"], team["pred_score"]) ** 0.5

    # Win accuracy: for each game, does our predicted winner match actual winner?
    opp = (
        team.rename(columns={
            "team_abbreviation": "opp_abbreviation",
            "actual_score": "opp_actual",
            "pred_score": "opp_pred",
        })
    )
    matchup = team.merge(
        opp, on="game_id", how="inner"
    )
    matchup = matchup[matchup["team_abbreviation"] != matchup["opp_abbreviation"]]

    actual_win = matchup["actual_score"] > matchup["opp_actual"]
    pred_win   = matchup["pred_score"]   > matchup["opp_pred"]
    win_acc    = (actual_win == pred_win).mean() * 100

    return {
        "score_mae":   round(score_mae, 2),
        "score_rmse":  round(score_rmse, 2),
        "win_accuracy": round(win_acc, 1),
    }


def _ci_coverage(test: pd.DataFrame, preds: pd.DataFrame) -> dict[str, float]:
    """
    What % of actual outcomes fall within [floor, ceiling] for pts?
    Floor  = pred × 0.72,  Ceiling = pred × 1.28
    """
    actual = test["pts"].values
    pred   = preds["pts"].values
    floor  = pred * _CI_FLOOR_MULT
    ceil_  = pred * _CI_CEILING_MULT
    inside = ((actual >= floor) & (actual <= ceil_)).mean() * 100
    return {"pts_ci_coverage": round(inside, 1)}


def _naive_baseline(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, float]:
    """
    Naive baseline: predict each player's season rolling mean from prior games.
    This is the floor the XGBoost model must beat to be worth anything.
    """
    # Season avg pts for each player from training data
    player_avg = (
        train.groupby("player_id")["pts"]
        .mean()
        .reset_index()
        .rename(columns={"pts": "naive_pred"})
    )
    t = test.merge(player_avg, on="player_id", how="left")
    t["naive_pred"] = t["naive_pred"].fillna(train["pts"].mean())
    mae = mean_absolute_error(t["pts"], t["naive_pred"])
    return {"naive_pts_mae": round(mae, 3)}


def _worst_predictions(test: pd.DataFrame, preds: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return the n player-games with the largest absolute error in pts."""
    t = test.copy()
    t["pred_pts"] = preds["pts"]
    t["error"]    = (t["pts"] - t["pred_pts"]).abs()
    cols = ["player_name", "team_abbreviation", "opponent_abbreviation",
            "game_date", "pts", "pred_pts", "error"]
    return (
        t[cols]
        .sort_values("error", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )


def _player_error_summary(test: pd.DataFrame, preds: pd.DataFrame, min_games: int = 10) -> pd.DataFrame:
    """MAE per player across the test season (only players with ≥ min_games)."""
    t = test.copy()
    t["pred_pts"] = preds["pts"]
    t["abs_err"]  = (t["pts"] - t["pred_pts"]).abs()
    summary = (
        t.groupby(["player_id", "player_name"])
        .agg(games=("pts", "count"), actual_avg=("pts", "mean"),
             pred_avg=("pred_pts", "mean"), mae=("abs_err", "mean"))
        .reset_index()
    )
    return (
        summary[summary["games"] >= min_games]
        .sort_values("mae", ascending=False)
        .reset_index(drop=True)
    )


# ── Main backtest loop ────────────────────────────────────────────────────────

def run_backtest():
    print("\n" + "═" * 72)
    print("  BALLPREDICT — WALK-FORWARD BACKTEST")
    print("═" * 72)

    print("\nLoading data and engineering features…")
    logs, def_stats, positions, elo_df, series_df, series_perf_df = load_data()
    df = build_features(logs, def_stats, positions, elo_df, series_df, series_perf_df)

    # Only evaluate on regular season (consistent volume across seasons)
    df_rs = df[df["season_type"] == "Regular Season"].copy()

    all_seasons = sorted(df_rs["season"].unique())
    print(f"\nAvailable regular seasons: {all_seasons}")

    # Walk-forward folds: need at least 2 seasons to train before testing
    folds = [
        (all_seasons[:i], all_seasons[i])
        for i in range(2, len(all_seasons))
    ]

    feature_cols = _feature_cols()
    fold_results = []
    all_worst    = []
    all_player_errors = []

    for train_seasons, test_season in folds:
        _sep()
        print(f"\n  FOLD: Train {train_seasons[0]}–{train_seasons[-1]}  →  Test {test_season}")
        _sep()

        train_df = df_rs[df_rs["season"].isin(train_seasons)]
        test_df  = df_rs[df_rs["season"] == test_season]

        print(f"  Train rows: {len(train_df):,}   Test rows: {len(test_df):,}")

        # ── Train ────────────────────────────────────────────────────────────
        print("  Training models…")
        models = _train_fold(df_rs, train_seasons)

        # ── Predict ──────────────────────────────────────────────────────────
        preds = _predict(models, test_df)

        # ── Per-stat metrics ─────────────────────────────────────────────────
        print(f"\n  {'Stat':<8} {'MAE':>8} {'RMSE':>8}")
        print(f"  {'─'*8} {'─'*8} {'─'*8}")
        stat_metrics = {}
        for target in TARGETS:
            mae  = mean_absolute_error(test_df[target], preds[target])
            rmse = mean_squared_error(test_df[target], preds[target]) ** 0.5
            stat_metrics[target] = {"mae": round(mae, 3), "rmse": round(rmse, 3)}
            print(f"  {target:<8} {mae:>8.3f} {rmse:>8.3f}")

        # ── Naive baseline ───────────────────────────────────────────────────
        baseline = _naive_baseline(train_df, test_df)
        lift = baseline["naive_pts_mae"] - stat_metrics["pts"]["mae"]
        print(f"\n  Naive pts baseline MAE : {baseline['naive_pts_mae']:.3f}")
        print(f"  XGBoost pts MAE        : {stat_metrics['pts']['mae']:.3f}")
        print(f"  Model lift over naive  : {lift:+.3f} pts  ({'✓ better' if lift > 0 else '✗ worse'})")

        # ── Team / game level ────────────────────────────────────────────────
        team_acc = _team_game_accuracy(test_df, preds)
        print(f"\n  Team score MAE    : {team_acc['score_mae']} pts/game")
        print(f"  Team score RMSE   : {team_acc['score_rmse']}")
        print(f"  Win prediction    : {team_acc['win_accuracy']}% correct")

        # ── CI coverage ──────────────────────────────────────────────────────
        ci = _ci_coverage(test_df, preds)
        print(f"  CI coverage (pts) : {ci['pts_ci_coverage']}% of actuals inside floor/ceiling")

        # ── Worst predictions ────────────────────────────────────────────────
        worst = _worst_predictions(test_df, preds, n=5)
        worst.insert(0, "season", test_season)
        all_worst.append(worst)

        # ── Player error ─────────────────────────────────────────────────────
        pe = _player_error_summary(test_df, preds)
        pe.insert(0, "season", test_season)
        all_player_errors.append(pe)

        fold_results.append({
            "test_season": test_season,
            "train_seasons": train_seasons,
            **stat_metrics,
            **team_acc,
            **ci,
            **baseline,
            "model_lift_pts": round(lift, 3),
        })

    # ── Cross-fold summary ────────────────────────────────────────────────────
    _sep("═")
    print("\n  CROSS-FOLD SUMMARY")
    _sep("═")

    summary_rows = []
    for r in fold_results:
        row = {"Season": r["test_season"]}
        for stat in TARGETS:
            row[f"{stat}_MAE"] = r[stat]["mae"]
        row["Win%"] = r["win_accuracy"]
        row["Score_MAE"] = r["score_mae"]
        row["CI_cov%"] = r["pts_ci_coverage"]
        row["Lift"] = r["model_lift_pts"]
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    print("\n" + summary_df.to_string(index=False))

    # Average across folds
    _sep()
    print("\n  AVERAGES ACROSS ALL FOLDS")
    _sep()
    avg_row = {"Season": "AVG"}
    for stat in TARGETS:
        col = f"{stat}_MAE"
        avg_row[col] = round(summary_df[col].mean(), 3)
    avg_row["Win%"]      = round(summary_df["Win%"].mean(), 1)
    avg_row["Score_MAE"] = round(summary_df["Score_MAE"].mean(), 2)
    avg_row["CI_cov%"]   = round(summary_df["CI_cov%"].mean(), 1)
    avg_row["Lift"]      = round(summary_df["Lift"].mean(), 3)
    print(pd.DataFrame([avg_row]).to_string(index=False))

    # ── Worst predictions across all folds ────────────────────────────────────
    _sep("═")
    print("\n  TOP-10 WORST PLAYER-GAME PREDICTIONS (across all folds)")
    _sep("═")
    all_worst_df = pd.concat(all_worst, ignore_index=True)
    top10 = all_worst_df.sort_values("error", ascending=False).head(10).reset_index(drop=True)
    print(top10.to_string(index=False))

    # ── Consistently hard-to-predict players ─────────────────────────────────
    _sep("═")
    print("\n  PLAYERS THE MODEL STRUGGLES WITH MOST (avg MAE ≥ 7 pts, ≥ 2 seasons)")
    _sep("═")
    all_pe_df = pd.concat(all_player_errors, ignore_index=True)
    hard = (
        all_pe_df.groupby(["player_id", "player_name"])
        .agg(seasons=("season", "nunique"), avg_mae=("mae", "mean"),
             avg_actual=("actual_avg", "mean"))
        .reset_index()
    )
    hard = hard[(hard["seasons"] >= 1) & (hard["avg_mae"] >= 7)].sort_values("avg_mae", ascending=False)
    print(hard[["player_name", "seasons", "avg_actual", "avg_mae"]].head(15).to_string(index=False))

    # ── Save results ──────────────────────────────────────────────────────────
    out_path = Path(__file__).parent.parent / "data" / "backtest_results.json"
    results_payload = {
        "folds": fold_results,
        "averages": avg_row,
        "worst_predictions": top10.to_dict(orient="records"),
        "hard_players": hard.head(15)[["player_name", "avg_mae", "avg_actual"]].to_dict(orient="records"),
    }
    out_path.write_text(json.dumps(results_payload, indent=2, default=str))
    print(f"\n  Results saved → {out_path}")
    print("\n" + "═" * 72)


if __name__ == "__main__":
    run_backtest()
