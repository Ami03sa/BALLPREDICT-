"""
Train XGBoost per-stat prediction models on historical NBA game logs.

Features per player-game:
  - Rolling averages (last 5 / last 10 games) for every stat
  - Season average up to that game
  - Opponent season defensive stats
  - Home/away flag
  - Rest days since last game

One model is trained per target stat: pts, ast, reb, stl, blk, fg3m, tov

Train set : 2023-24 (Regular Season + Playoffs)
Test  set : 2024-25 Regular Season
Models saved to: data/models/model_{stat}.json

Run from backend/:
    python scripts/train_model.py
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

DB_PATH   = Path(__file__).parent.parent / "data" / "nba_training.db"
MODEL_DIR = Path(__file__).parent.parent / "data" / "models"

TARGETS = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov"]

ROLL_STATS = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct"]

XGB_PARAMS = dict(
    n_estimators=300,
    max_depth=5,
    learning_rate=0.04,
    subsample=0.8,
    colsample_bytree=0.75,
    min_child_weight=3,
    gamma=0.1,
    reg_alpha=0.05,
    reg_lambda=1.0,
    objective="reg:squarederror",
    random_state=42,
    n_jobs=-1,
)


# ── Load data ─────────────────────────────────────────────────────────────────

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(DB_PATH)

    logs = pd.read_sql_query("""
        SELECT player_id, player_name, team_abbreviation, opponent_abbreviation,
               game_id, game_date, season, season_type, home_away,
               min, pts, ast, reb, stl, blk, tov, fg3m, fg_pct, fg3_pct
        FROM player_game_logs
        WHERE min >= 5
        ORDER BY player_id, game_date
    """, conn)

    def_stats = pd.read_sql_query("""
        SELECT team_abbreviation, season, season_type,
               opp_pts_per_game, opp_fg_pct, opp_fg3_pct
        FROM team_defensive_stats
    """, conn)

    conn.close()
    logs["game_date"] = pd.to_datetime(logs["game_date"])
    return logs, def_stats


# ── Feature engineering ───────────────────────────────────────────────────────

def build_features(logs: pd.DataFrame, def_stats: pd.DataFrame) -> pd.DataFrame:
    print("Engineering features...")

    # Sort per player chronologically
    logs = logs.sort_values(["player_id", "game_date"]).reset_index(drop=True)

    # Rolling averages: shift(1) so the current game is excluded
    grp = logs.groupby("player_id")

    for stat in ROLL_STATS:
        shifted = grp[stat].shift(1)
        logs[f"{stat}_last5"]  = (
            shifted.groupby(logs["player_id"]).transform(lambda x: x.rolling(5, min_periods=1).mean())
        )
        logs[f"{stat}_last10"] = (
            shifted.groupby(logs["player_id"]).transform(lambda x: x.rolling(10, min_periods=1).mean())
        )
        # Expanding (season-to-date) average — reset on each new season
        logs[f"{stat}_season_avg"] = (
            grp[stat]
            .transform(lambda x: x.shift(1).expanding().mean())
        )

    # Rest days
    logs["rest_days"] = (
        grp["game_date"]
        .transform(lambda x: x.diff().dt.days)
        .fillna(3)
        .clip(1, 14)
    )

    # Home flag
    logs["is_home"] = (logs["home_away"] == "H").astype(int)

    # Join opponent defensive stats
    # Opponent's defensive profile for that season/season_type
    logs = logs.merge(
        def_stats.rename(columns={
            "team_abbreviation": "opponent_abbreviation",
            "opp_pts_per_game": "opp_pts_per_game",
            "opp_fg_pct":       "opp_fg_pct",
            "opp_fg3_pct":      "opp_fg3_pct",
        }),
        on=["opponent_abbreviation", "season", "season_type"],
        how="left",
    )

    # Fill missing opponent stats with league average
    logs["opp_pts_per_game"] = logs["opp_pts_per_game"].fillna(114.0)
    logs["opp_fg_pct"]       = logs["opp_fg_pct"].fillna(0.46)
    logs["opp_fg3_pct"]      = logs["opp_fg3_pct"].fillna(0.36)

    # Drop rows where we don't have enough history (first game of career)
    feature_cols = _feature_cols()
    logs = logs.dropna(subset=feature_cols + TARGETS)

    print(f"  {len(logs):,} rows after feature engineering")
    return logs


def _feature_cols() -> list[str]:
    cols = []
    for stat in ROLL_STATS:
        cols += [f"{stat}_last5", f"{stat}_last10", f"{stat}_season_avg"]
    cols += ["opp_pts_per_game", "opp_fg_pct", "opp_fg3_pct", "is_home", "rest_days"]
    return cols


# ── Train / evaluate ──────────────────────────────────────────────────────────

def train_models(df: pd.DataFrame) -> dict:
    train = df[df["season"] == "2023-24"]
    test  = df[(df["season"] == "2024-25") & (df["season_type"] == "Regular Season")]

    print(f"\nTrain: {len(train):,} rows  |  Test: {len(test):,} rows")

    feature_cols = _feature_cols()
    X_train = train[feature_cols]
    X_test  = test[feature_cols]

    metrics: dict[str, dict] = {}
    models:  dict[str, xgb.XGBRegressor] = {}

    for target in TARGETS:
        y_train = train[target]
        y_test  = test[target]

        model = xgb.XGBRegressor(**XGB_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        preds = model.predict(X_test).clip(0)
        mae   = mean_absolute_error(y_test, preds)
        rmse  = mean_squared_error(y_test, preds) ** 0.5

        print(f"  {target:>5}  MAE={mae:.2f}  RMSE={rmse:.2f}")
        metrics[target] = {"mae": round(mae, 3), "rmse": round(rmse, 3)}
        models[target] = model

    return models, metrics


# ── Save ──────────────────────────────────────────────────────────────────────

def save_models(models: dict, metrics: dict) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for target, model in models.items():
        model.save_model(str(MODEL_DIR / f"model_{target}.json"))

    with open(MODEL_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    feature_cols = _feature_cols()
    with open(MODEL_DIR / "features.json", "w") as f:
        json.dump(feature_cols, f, indent=2)

    print(f"\nModels saved to {MODEL_DIR}/")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logs, def_stats = load_data()
    print(f"Loaded {len(logs):,} player-game rows")

    df = build_features(logs, def_stats)

    print("\nTraining XGBoost models...")
    models, metrics = train_models(df)

    save_models(models, metrics)

    print("\n══ Metrics (2024-25 Regular Season test set) ══")
    for stat, m in metrics.items():
        print(f"  {stat:>5}  MAE={m['mae']}  RMSE={m['rmse']}")


if __name__ == "__main__":
    main()
