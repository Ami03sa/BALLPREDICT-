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

ROLL_STATS = ["pts", "ast", "reb", "stl", "blk", "fg3m", "tov", "min", "fg_pct", "fg3_pct", "usg_pct"]

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

def _classify_positions(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Assign each player a position archetype (G/F/C) from per-36-minute career stats.
    Per-36 avoids the low-scorer bias of ratio-to-points metrics.

    Thresholds (per 36 minutes):
      C: (reb + blk) per 36 > 6.5    ← rim presence / rebounding
      G: (ast + fg3m) per 36 > 4.5   ← playmaking + perimeter shooting
      F: everyone else
    """
    career = (
        logs[logs["min"] >= 8]
        .groupby("player_id")[["reb", "blk", "ast", "fg3m", "min"]]
        .mean()
        .reset_index()
    )
    # Avoid division by zero for players with very low minutes
    career["min36"] = career["min"].clip(lower=1)
    career["big_per36"]   = (career["reb"] + career["blk"])  / career["min36"] * 36
    career["guard_per36"] = (career["ast"] + career["fg3m"]) / career["min36"] * 36

    def _pos(row):
        if row["big_per36"] > 6.5:
            return "C"
        if row["guard_per36"] > 4.5:
            return "G"
        return "F"

    career["position"] = career.apply(_pos, axis=1)
    return career[["player_id", "position"]]


def _compute_series_player_perf(logs: pd.DataFrame) -> pd.DataFrame:
    """
    For each playoff player-game, compute player's series performance stats
    from games played BEFORE that game (no lookahead).

    New columns:
      series_games     — games played in this series before this game (0 for Game 1)
      series_pts_avg   — player's pts avg in series so far (0 if no prior games)
      series_ast_avg   — same for ast
      series_reb_avg   — same for reb
      series_fg3m_avg  — same for fg3m
      team_series_tov  — team's avg TOV per game in series before this game
    """
    playoff = logs[logs["season_type"] == "Playoffs"].copy()
    empty_cols = ["player_id", "game_id", "series_games",
                  "series_pts_avg", "series_ast_avg", "series_reb_avg",
                  "series_fg3m_avg", "team_series_tov"]
    if playoff.empty:
        return pd.DataFrame(columns=empty_cols)

    # Canonical series key for each player: (player, season, sorted team pair)
    playoff["_ps_key"] = (
        playoff["player_id"].astype(str) + "__" + playoff["season"] + "__" +
        playoff[["team_abbreviation", "opponent_abbreviation"]].apply(
            lambda r: "_".join(sorted([r["team_abbreviation"], r["opponent_abbreviation"]])), axis=1
        )
    )
    playoff = playoff.sort_values(["_ps_key", "game_date"]).copy()
    g = playoff.groupby("_ps_key")

    # Shift(1) excludes the current game → pure look-back, no data leakage
    playoff["series_games"] = (
        g["pts"].transform(lambda x: x.shift(1).expanding().count()).fillna(0).astype(int)
    )
    for stat in ["pts", "ast", "reb", "fg3m"]:
        playoff[f"series_{stat}_avg"] = (
            g[stat].transform(lambda x: x.shift(1).expanding().mean()).fillna(0.0)
        )

    # Team-level TOV: sum all players' TOV per game, then rolling avg before this game
    team_tov_pg = (
        playoff.groupby(["game_id", "team_abbreviation"])["tov"]
        .sum().reset_index().rename(columns={"tov": "_game_tov"})
    )
    team_tov_pg = team_tov_pg.merge(
        playoff[["game_id", "team_abbreviation", "opponent_abbreviation", "season", "game_date"]]
        .drop_duplicates(["game_id", "team_abbreviation"]),
        on=["game_id", "team_abbreviation"], how="left",
    )
    team_tov_pg["_ts_key"] = (
        team_tov_pg["team_abbreviation"] + "__" + team_tov_pg["season"] + "__" +
        team_tov_pg[["team_abbreviation", "opponent_abbreviation"]].apply(
            lambda r: "_".join(sorted([r["team_abbreviation"], r["opponent_abbreviation"]])), axis=1
        )
    )
    team_tov_pg = team_tov_pg.sort_values(["_ts_key", "game_date"])
    team_tov_pg["team_series_tov"] = (
        team_tov_pg.groupby("_ts_key")["_game_tov"]
        .transform(lambda x: x.shift(1).expanding().mean())
        .fillna(14.0)
    )

    playoff = playoff.merge(
        team_tov_pg[["game_id", "team_abbreviation", "team_series_tov"]].drop_duplicates(),
        on=["game_id", "team_abbreviation"], how="left",
    )
    playoff["team_series_tov"] = playoff["team_series_tov"].fillna(14.0)

    return playoff[empty_cols].drop_duplicates(["player_id", "game_id"])


def _compute_series_features(game_results: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    """
    For each playoff player-game, compute:
      series_game_num   – which game in this series (1-7)
      team_series_wins  – team wins in this series before this game
      opp_series_wins   – opponent wins before this game
      series_advantage  – +1 if team leads, -1 if trails, 0 if tied

    Returns DataFrame with (game_id, team_abbreviation) → context columns.
    Merged into logs via (game_id, team_abbreviation).
    """
    # Work only on playoff games
    playoff_results = game_results[game_results["game_id"].isin(
        logs[logs["season_type"] == "Playoffs"]["game_id"].unique()
    )].copy()

    if playoff_results.empty:
        return pd.DataFrame(columns=["game_id", "team", "series_game_num",
                                     "team_series_wins", "opp_series_wins", "series_advantage"])

    # Canonical series key: season encoded in game_id prefix + sorted team pair
    playoff_results = playoff_results.merge(
        logs[["game_id", "season"]].drop_duplicates(), on="game_id", how="left"
    )
    playoff_results["series_key"] = (
        playoff_results["season"] + "_" +
        playoff_results[["team", "opp"]].apply(
            lambda r: "_".join(sorted([r["team"], r["opp"]])), axis=1
        )
    )

    playoff_results = playoff_results.sort_values("game_date")
    records = []
    for key, grp in playoff_results.groupby("series_key"):
        # Unique game dates in this series (one per game, two team rows each)
        game_dates = sorted(grp["game_date"].unique())
        for _, row in grp.iterrows():
            game_idx = game_dates.index(row["game_date"])  # 0-based
            prior = grp[grp["game_date"] < row["game_date"]]
            team_wins = int((prior[prior["team"] == row["team"]]["team_score"] >
                             prior[prior["team"] == row["team"]]["opp_score"]).sum())
            opp_wins = int((prior[prior["team"] == row["opp"]]["team_score"] >
                            prior[prior["team"] == row["opp"]]["opp_score"]).sum())
            adv = 1 if team_wins > opp_wins else (-1 if team_wins < opp_wins else 0)
            records.append({
                "game_id": row["game_id"],
                "team": row["team"],
                "series_game_num": game_idx + 1,
                "team_series_wins": team_wins,
                "opp_series_wins": opp_wins,
                "series_advantage": adv,
            })
    return pd.DataFrame(records)


def _compute_team_elo(game_results: pd.DataFrame, k: float = 20.0, init: float = 1500.0) -> pd.DataFrame:
    """
    Compute ELO ratings for every team before each game they played.
    game_results must have columns: game_date, game_id, team, opp, team_score, opp_score.
    Returns a DataFrame with (game_id, team) → elo_before columns.
    """
    elo: dict[str, float] = {}
    records = []

    for _, row in game_results.sort_values("game_date").iterrows():
        t, o = row["team"], row["opp"]
        t_elo = elo.get(t, init)
        o_elo = elo.get(o, init)

        expected_t = 1.0 / (1.0 + 10 ** ((o_elo - t_elo) / 400.0))
        actual_t   = 1.0 if row["team_score"] > row["opp_score"] else 0.5 if row["team_score"] == row["opp_score"] else 0.0

        records.append({"game_id": row["game_id"], "team": t, "team_elo": t_elo, "opp_elo": o_elo})

        elo[t] = t_elo + k * (actual_t - expected_t)
        elo[o] = o_elo + k * ((1 - actual_t) - (1 - expected_t))

    return pd.DataFrame(records)


def load_data() -> tuple:
    conn = sqlite3.connect(DB_PATH)

    logs = pd.read_sql_query("""
        SELECT player_id, player_name, team_abbreviation, opponent_abbreviation,
               game_id, game_date, season, season_type, home_away,
               min, pts, ast, reb, stl, blk, tov, fg3m, fg_pct, fg3_pct, usg_pct
        FROM player_game_logs
        WHERE min >= 5
        ORDER BY player_id, game_date
    """, conn)

    # Team-level opponent defensive profile (all players combined)
    def_stats = pd.read_sql_query("""
        SELECT opponent_abbreviation AS team_abbreviation,
               season,
               season_type,
               AVG(pts)    AS opp_pts_per_game,
               AVG(fg_pct) AS opp_fg_pct,
               AVG(fg3_pct) AS opp_fg3_pct,
               AVG(ast)    AS opp_ast_pg,
               AVG(reb)    AS opp_reb_pg,
               AVG(fg3m)   AS opp_fg3m_pg,
               AVG(blk)    AS opp_blk_pg,
               AVG(stl)    AS opp_stl_pg
        FROM player_game_logs
        WHERE min >= 5
        GROUP BY opponent_abbreviation, season, season_type
    """, conn)

    # Team-level scores per game — needed to compute ELO
    game_scores = pd.read_sql_query("""
        SELECT game_id, game_date, team_abbreviation AS team,
               opponent_abbreviation AS opp,
               SUM(pts) AS team_score
        FROM player_game_logs
        WHERE min >= 5
        GROUP BY game_id, team_abbreviation, opponent_abbreviation, game_date
    """, conn)

    conn.close()
    logs["game_date"] = pd.to_datetime(logs["game_date"])
    game_scores["game_date"] = pd.to_datetime(game_scores["game_date"])

    # Derive opponent score by joining on flipped team/opp
    opp_scores = game_scores.rename(columns={"team": "opp", "opp": "team", "team_score": "opp_score"})[
        ["game_id", "team", "opp_score"]
    ]
    game_results = game_scores.merge(opp_scores, on=["game_id", "team"], how="inner")

    # Compute ELO per game (rating before that game)
    print("  Computing team ELO ratings...")
    elo_df = _compute_team_elo(game_results)

    # Compute playoff series context per game
    print("  Computing series context features...")
    series_df = _compute_series_features(game_results, logs)

    # Compute player-level series performance features (new)
    print("  Computing player series performance features...")
    series_perf_df = _compute_series_player_perf(logs)
    print(f"  Series perf rows: {len(series_perf_df):,}")

    # Classify each player into G/F/C by career play style
    positions = _classify_positions(logs)
    pos_counts = positions["position"].value_counts().to_dict()
    print(f"  Position split — G:{pos_counts.get('G',0)}  F:{pos_counts.get('F',0)}  C:{pos_counts.get('C',0)}")

    return logs, def_stats, positions, elo_df, series_df, series_perf_df


# ── Feature engineering ───────────────────────────────────────────────────────

def build_features(logs: pd.DataFrame, def_stats: pd.DataFrame, positions: pd.DataFrame, elo_df: pd.DataFrame, series_df: pd.DataFrame | None = None, series_perf_df: pd.DataFrame | None = None) -> pd.DataFrame:
    print("Engineering features...")

    logs = logs.sort_values(["player_id", "game_date"]).reset_index(drop=True)
    grp  = logs.groupby("player_id")

    for stat in ROLL_STATS:
        shifted = grp[stat].shift(1)
        logs[f"{stat}_last5"]      = shifted.groupby(logs["player_id"]).transform(lambda x: x.rolling(5,  min_periods=1).mean())
        logs[f"{stat}_last10"]     = shifted.groupby(logs["player_id"]).transform(lambda x: x.rolling(10, min_periods=1).mean())
        logs[f"{stat}_season_avg"] = grp[stat].transform(lambda x: x.shift(1).expanding().mean())

    # Last-3 recent form for key stats
    for stat in ["pts", "ast", "reb", "fg3m"]:
        shifted = grp[stat].shift(1)
        logs[f"{stat}_last3"] = shifted.groupby(logs["player_id"]).transform(lambda x: x.rolling(3, min_periods=1).mean())

    # Minutes consistency — std of last 10 games
    logs["min_std_last10"] = (
        grp["min"].transform(lambda x: x.shift(1).rolling(10, min_periods=3).std()).fillna(5.0)
    )

    # Rest days
    logs["rest_days"] = (
        grp["game_date"].transform(lambda x: x.diff().dt.days).fillna(3).clip(1, 14)
    )

    # Flags
    logs["is_home"]     = (logs["home_away"] == "H").astype(int)
    logs["is_playoffs"] = (logs["season_type"] == "Playoffs").astype(int)

    # Home/away career scoring splits (all games up to but not including current)
    print("  Computing home/away splits...")
    for loc, col in [("H", "home_pts_avg"), ("A", "away_pts_avg")]:
        tmp = logs.copy()
        tmp["_pts_loc"] = tmp["pts"].where(tmp["home_away"] == loc)
        tmp[col] = tmp.groupby("player_id")["_pts_loc"].transform(lambda x: x.shift(1).expanding().mean())
        logs[col] = tmp[col].fillna(logs["pts_season_avg"])

    # Join opponent defensive stats (all per-player-game averages allowed)
    logs = logs.merge(
        def_stats.rename(columns={"team_abbreviation": "opponent_abbreviation"}),
        on=["opponent_abbreviation", "season", "season_type"],
        how="left",
    )
    logs["opp_pts_per_game"] = logs["opp_pts_per_game"].fillna(12.0)
    logs["opp_fg_pct"]       = logs["opp_fg_pct"].fillna(0.46)
    logs["opp_fg3_pct"]      = logs["opp_fg3_pct"].fillna(0.36)
    logs["opp_ast_pg"]       = logs["opp_ast_pg"].fillna(2.8)
    logs["opp_reb_pg"]       = logs["opp_reb_pg"].fillna(4.6)
    logs["opp_fg3m_pg"]      = logs["opp_fg3m_pg"].fillna(1.4)
    logs["opp_blk_pg"]       = logs["opp_blk_pg"].fillna(0.55)
    logs["opp_stl_pg"]       = logs["opp_stl_pg"].fillna(0.85)

    # Position-specific matchup vulnerability.
    # Join player position archetype, then compute per-(opponent, position) defense.
    # This tells the model: "how many pts does this team allow to GUARDS specifically"
    # vs the generic team-level average.
    print("  Computing position-specific matchup features...")
    logs = logs.merge(positions, on="player_id", how="left")
    logs["position"] = logs["position"].fillna("F")  # default unknown → forward

    pos_def = (
        logs[logs["min"] >= 5]
        .groupby(["opponent_abbreviation", "season", "season_type", "position"])[
            ["pts", "ast", "reb", "fg3m", "blk", "stl"]
        ]
        .mean()
        .reset_index()
        .rename(columns={
            "pts": "opp_pos_pts", "ast": "opp_pos_ast", "reb": "opp_pos_reb",
            "fg3m": "opp_pos_fg3m", "blk": "opp_pos_blk", "stl": "opp_pos_stl",
        })
    )
    logs = logs.merge(
        pos_def,
        on=["opponent_abbreviation", "season", "season_type", "position"],
        how="left",
    )
    # Fall back to team-level average when position bucket has too few games
    logs["opp_pos_pts"]  = logs["opp_pos_pts"].fillna(logs["opp_pts_per_game"])
    logs["opp_pos_ast"]  = logs["opp_pos_ast"].fillna(logs["opp_ast_pg"])
    logs["opp_pos_reb"]  = logs["opp_pos_reb"].fillna(logs["opp_reb_pg"])
    logs["opp_pos_fg3m"] = logs["opp_pos_fg3m"].fillna(logs["opp_fg3m_pg"])
    logs["opp_pos_blk"]  = logs["opp_pos_blk"].fillna(logs["opp_blk_pg"])
    logs["opp_pos_stl"]  = logs["opp_pos_stl"].fillna(logs["opp_stl_pg"])

    # Team ELO — join on (game_id, team_abbreviation)
    print("  Joining ELO features...")
    elo_team = elo_df.rename(columns={"team": "team_abbreviation", "team_elo": "team_elo", "opp_elo": "opp_elo"})
    logs = logs.merge(elo_team[["game_id", "team_abbreviation", "team_elo", "opp_elo"]],
                      on=["game_id", "team_abbreviation"], how="left")
    logs["team_elo"] = logs["team_elo"].fillna(1500.0)
    logs["opp_elo"]  = logs["opp_elo"].fillna(1500.0)
    logs["elo_diff"] = logs["team_elo"] - logs["opp_elo"]

    # Head-to-head history: rolling stats vs each specific opponent.
    # Sort per (player, opponent, date) so shift(1) excludes the current game.
    print("  Computing head-to-head features...")
    h2h_cols = []
    tmp = logs.sort_values(["player_id", "opponent_abbreviation", "game_date"]).copy()
    for stat in ["pts", "ast", "reb"]:
        g = tmp.groupby(["player_id", "opponent_abbreviation"])[stat]
        tmp[f"{stat}_vs_opp_last3"] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
        tmp[f"{stat}_vs_opp_avg"]   = g.transform(lambda x: x.shift(1).expanding().mean())
        h2h_cols += [f"{stat}_vs_opp_last3", f"{stat}_vs_opp_avg"]

    logs = logs.merge(
        tmp[["player_id", "game_id"] + h2h_cols].drop_duplicates(["player_id", "game_id"]),
        on=["player_id", "game_id"],
        how="left",
    )
    # Fall back to season average when no prior H2H games exist
    for stat in ["pts", "ast", "reb"]:
        logs[f"{stat}_vs_opp_last3"] = logs[f"{stat}_vs_opp_last3"].fillna(logs[f"{stat}_season_avg"])
        logs[f"{stat}_vs_opp_avg"]   = logs[f"{stat}_vs_opp_avg"].fillna(logs[f"{stat}_season_avg"])

    # Playoff series context — game number and series record going into each game.
    # Non-playoff rows get neutral defaults (game 1, 0-0).
    if series_df is not None and not series_df.empty:
        print("  Merging series context features...")
        logs = logs.merge(
            series_df.rename(columns={"team": "team_abbreviation"}),
            on=["game_id", "team_abbreviation"],
            how="left",
        )
    logs["series_game_num"]   = logs.get("series_game_num",   pd.Series(1, index=logs.index)).fillna(1).astype(int)
    logs["team_series_wins"]  = logs.get("team_series_wins",  pd.Series(0, index=logs.index)).fillna(0).astype(int)
    logs["opp_series_wins"]   = logs.get("opp_series_wins",   pd.Series(0, index=logs.index)).fillna(0).astype(int)
    logs["series_advantage"]  = logs.get("series_advantage",  pd.Series(0, index=logs.index)).fillna(0).astype(int)

    # Player-level series performance — how the player has actually performed in this series.
    # Non-playoff rows get all-zero defaults (series_games=0 acts as the "not in series" flag).
    if series_perf_df is not None and not series_perf_df.empty:
        print("  Merging player series performance features...")
        logs = logs.merge(series_perf_df, on=["player_id", "game_id"], how="left")
    logs["series_games"]     = logs.get("series_games",     pd.Series(0, index=logs.index)).fillna(0).astype(int)
    logs["series_pts_avg"]   = logs.get("series_pts_avg",   pd.Series(0.0, index=logs.index)).fillna(0.0)
    logs["series_ast_avg"]   = logs.get("series_ast_avg",   pd.Series(0.0, index=logs.index)).fillna(0.0)
    logs["series_reb_avg"]   = logs.get("series_reb_avg",   pd.Series(0.0, index=logs.index)).fillna(0.0)
    logs["series_fg3m_avg"]  = logs.get("series_fg3m_avg",  pd.Series(0.0, index=logs.index)).fillna(0.0)
    logs["team_series_tov"]  = logs.get("team_series_tov",  pd.Series(0.0, index=logs.index)).fillna(0.0)

    feature_cols = _feature_cols()
    logs = logs.dropna(subset=feature_cols + TARGETS)

    print(f"  {len(logs):,} rows after feature engineering")
    return logs


def _feature_cols() -> list[str]:
    cols = []
    for stat in ROLL_STATS:
        cols += [f"{stat}_last5", f"{stat}_last10", f"{stat}_season_avg"]
    for stat in ["pts", "ast", "reb", "fg3m"]:
        cols += [f"{stat}_last3"]
    cols += ["opp_pts_per_game", "opp_fg_pct", "opp_fg3_pct",
             "opp_ast_pg", "opp_reb_pg", "opp_fg3m_pg", "opp_blk_pg", "opp_stl_pg",
             "is_home", "rest_days"]
    cols += ["is_playoffs", "min_std_last10", "home_pts_avg", "away_pts_avg"]
    cols += ["opp_pos_pts", "opp_pos_ast", "opp_pos_reb", "opp_pos_fg3m", "opp_pos_blk", "opp_pos_stl"]
    for stat in ["pts", "ast", "reb"]:
        cols += [f"{stat}_vs_opp_last3", f"{stat}_vs_opp_avg"]
    cols += ["team_elo", "opp_elo", "elo_diff"]
    cols += ["series_game_num", "team_series_wins", "opp_series_wins", "series_advantage"]
    # Player-level series performance — zero for regular season / Game 1
    cols += ["series_games", "series_pts_avg", "series_ast_avg",
             "series_reb_avg", "series_fg3m_avg", "team_series_tov"]
    return cols


# ── Train / evaluate ──────────────────────────────────────────────────────────

def train_models(df: pd.DataFrame) -> dict:
    # Train on all seasons except last; test on most recent regular season
    seasons = sorted(df["season"].unique())
    test_season = seasons[-1]
    train = df[df["season"] != test_season]
    test  = df[(df["season"] == test_season) & (df["season_type"] == "Regular Season")]

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
    logs, def_stats, positions, elo_df, series_df, series_perf_df = load_data()
    print(f"Loaded {len(logs):,} player-game rows")

    df = build_features(logs, def_stats, positions, elo_df, series_df, series_perf_df)

    print("\nTraining XGBoost models...")
    models, metrics = train_models(df)

    save_models(models, metrics)

    print("\n══ Metrics (2024-25 Regular Season test set) ══")
    for stat, m in metrics.items():
        print(f"  {stat:>5}  MAE={m['mae']}  RMSE={m['rmse']}")


if __name__ == "__main__":
    main()
