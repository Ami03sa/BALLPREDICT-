"""
Bayesian hyperparameter optimisation for BallPredict XGBoost models.

Uses Optuna (TPE sampler) to find the best XGBoost params for predicting
player pts — the primary stat and proxy for all others. The winning params
are then used to retrain ALL stat models.

Walk-forward evaluation (same methodology as backtest.py):
  Train ≤ 2023-24  →  Validate 2024-25  (fold 1)
  Train ≤ 2024-25  →  Validate 2025-26  (fold 2)
  Objective: minimise mean pts MAE across both folds.

This prevents hyperparams that overfit to a single season from winning.

Search space:
  n_estimators      100 – 800
  max_depth         3 – 8
  learning_rate     0.005 – 0.20   (log scale)
  subsample         0.50 – 1.00
  colsample_bytree  0.50 – 1.00
  min_child_weight  1 – 12
  gamma             0.0 – 1.0
  reg_alpha         0.0 – 3.0
  reg_lambda        0.0 – 3.0

Run from backend/:
    python scripts/tune_hyperparams.py           # default 80 trials
    python scripts/tune_hyperparams.py --trials 150
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import optuna
import xgboost as xgb
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).parent))
from train_model import (
    _feature_cols,
    build_features,
    load_data,
)

BEST_PARAMS_PATH = Path(__file__).parent.parent / "data" / "models" / "best_params.json"
optuna.logging.set_verbosity(optuna.logging.WARNING)   # quiet per-trial spam


def _build_folds(df):
    """
    Return walk-forward folds as (train_df, val_df) pairs.
    Only Regular Season rows — consistent game volume across seasons.
    """
    rs = df[df["season_type"] == "Regular Season"].copy()
    seasons = sorted(rs["season"].unique())
    # Need at least 2 training seasons before validating
    folds = []
    for i in range(2, len(seasons)):
        train_seasons = seasons[:i]
        val_season    = seasons[i]
        folds.append((
            rs[rs["season"].isin(train_seasons)],
            rs[rs["season"] == val_season],
        ))
    return folds


def objective(trial, folds, feature_cols):
    params = dict(
        n_estimators      = trial.suggest_int  ("n_estimators",      100, 800),
        max_depth         = trial.suggest_int  ("max_depth",         3,   8),
        learning_rate     = trial.suggest_float("learning_rate",     0.005, 0.20, log=True),
        subsample         = trial.suggest_float("subsample",         0.50, 1.00),
        colsample_bytree  = trial.suggest_float("colsample_bytree",  0.50, 1.00),
        min_child_weight  = trial.suggest_int  ("min_child_weight",  1,   12),
        gamma             = trial.suggest_float("gamma",             0.0,  1.0),
        reg_alpha         = trial.suggest_float("reg_alpha",         0.0,  3.0),
        reg_lambda        = trial.suggest_float("reg_lambda",        0.0,  3.0),
        objective         = "reg:squarederror",
        random_state      = 42,
        n_jobs            = -1,
    )

    fold_maes = []
    for train_df, val_df in folds:
        model = xgb.XGBRegressor(**params)
        model.fit(train_df[feature_cols], train_df["pts"], verbose=False)
        preds = model.predict(val_df[feature_cols]).clip(0)
        fold_maes.append(mean_absolute_error(val_df["pts"], preds))

    return float(np.mean(fold_maes))


def run_tuning(n_trials: int = 80):
    print("\n" + "═" * 72)
    print("  BALLPREDICT — BAYESIAN HYPERPARAMETER OPTIMISATION (Optuna TPE)")
    print("═" * 72)

    print("\nLoading data and engineering features…")
    logs, def_stats, positions, elo_df, series_df, series_perf_df = load_data()
    df = build_features(logs, def_stats, positions, elo_df, series_df, series_perf_df)

    folds = _build_folds(df)
    feature_cols = _feature_cols()

    print(f"Walk-forward folds : {len(folds)}")
    for train_df, val_df in folds:
        seasons = sorted(train_df["season"].unique())
        val_s   = val_df["season"].iloc[0]
        print(f"  Train {seasons[0]}–{seasons[-1]}  →  Validate {val_s}  "
              f"({len(train_df):,} / {len(val_df):,} rows)")

    print(f"\nRunning {n_trials} Optuna trials (TPE sampler)…\n")

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(
        lambda trial: objective(trial, folds, feature_cols),
        n_trials=n_trials,
        show_progress_bar=True,
    )

    best = study.best_trial
    best_params = best.params
    best_params["objective"]    = "reg:squarederror"
    best_params["random_state"] = 42
    best_params["n_jobs"]       = -1

    print(f"\n{'─' * 72}")
    print(f"  Best pts MAE (avg across folds): {best.value:.4f}")
    print(f"{'─' * 72}")
    print("  Best hyperparameters:")
    for k, v in best_params.items():
        if k not in ("objective", "random_state", "n_jobs"):
            print(f"    {k:<22} = {v}")

    # ── Improvement vs current defaults ──────────────────────────────────────
    from train_model import XGB_PARAMS
    print("\n  Comparing against current defaults…")
    baseline_maes = []
    for train_df, val_df in folds:
        m = xgb.XGBRegressor(**XGB_PARAMS)
        m.fit(train_df[feature_cols], train_df["pts"], verbose=False)
        p = m.predict(val_df[feature_cols]).clip(0)
        baseline_maes.append(mean_absolute_error(val_df["pts"], p))
    baseline_avg = float(np.mean(baseline_maes))
    improvement  = (baseline_avg - best.value) / baseline_avg * 100

    print(f"  Baseline pts MAE  : {baseline_avg:.4f}")
    print(f"  Tuned   pts MAE  : {best.value:.4f}")
    print(f"  Improvement      : {improvement:+.1f}%  "
          f"({'✓ better' if improvement > 0 else '✗ worse'})")

    # ── Save ─────────────────────────────────────────────────────────────────
    BEST_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BEST_PARAMS_PATH, "w") as f:
        json.dump(best_params, f, indent=2)
    print(f"\n  Best params saved → {BEST_PARAMS_PATH}")
    print("  Run  python scripts/train_model.py  to retrain with these params.\n")
    print("═" * 72)

    return best_params


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=80,
                        help="Number of Optuna trials (default: 80)")
    args = parser.parse_args()
    run_tuning(n_trials=args.trials)
