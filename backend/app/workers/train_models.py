from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from lightgbm import LGBMRegressor
except ImportError:  # pragma: no cover
    LGBMRegressor = None

try:
    from xgboost import XGBRegressor
except ImportError:  # pragma: no cover
    XGBRegressor = None


FEATURES = [
    "player_id",
    "team_id",
    "opponent_team_id",
    "is_home",
    "days_rest",
    "back_to_back",
    "rolling_points_5",
    "rolling_assists_5",
    "rolling_usage_5",
    "season_usage",
    "opponent_def_rating",
    "opponent_pace",
    "lineup_synergy",
    "touch_time",
    "paint_touches",
    "drive_frequency",
    "double_team_rate_allowed",
    "coach_adjustment_index",
]

TARGETS = ["points", "assists", "rebounds", "turnovers", "three_pointers_made"]


@dataclass
class TrainedModelArtifact:
    target: str
    model_name: str
    mae: float


def _make_preprocessor() -> ColumnTransformer:
    numeric_features = [
        "days_rest",
        "rolling_points_5",
        "rolling_assists_5",
        "rolling_usage_5",
        "season_usage",
        "opponent_def_rating",
        "opponent_pace",
        "lineup_synergy",
        "touch_time",
        "paint_touches",
        "drive_frequency",
        "double_team_rate_allowed",
        "coach_adjustment_index",
    ]
    categorical_features = ["player_id", "team_id", "opponent_team_id", "is_home", "back_to_back"]
    return ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
        ]
    )


def train_box_score_models(dataset_path: str = "data/training/player_games.parquet") -> list[TrainedModelArtifact]:
    dataset = pd.read_parquet(Path(dataset_path))
    X = dataset[FEATURES]
    artifacts: list[TrainedModelArtifact] = []

    model_factories = []
    if XGBRegressor is not None:
        model_factories.append(("xgboost", XGBRegressor(n_estimators=250, max_depth=6, learning_rate=0.05)))
    if LGBMRegressor is not None:
        model_factories.append(("lightgbm", LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31)))

    if not model_factories:
        raise RuntimeError("Install xgboost or lightgbm to train BallPredict models.")

    for target in TARGETS:
        y = dataset[target]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        for model_name, regressor in model_factories:
            pipeline = Pipeline(
                steps=[
                    ("preprocessor", _make_preprocessor()),
                    ("model", regressor),
                ]
            )
            pipeline.fit(X_train, y_train)
            predictions = pipeline.predict(X_test)
            artifacts.append(
                TrainedModelArtifact(
                    target=target,
                    model_name=model_name,
                    mae=round(mean_absolute_error(y_test, predictions), 3),
                )
            )
    return artifacts


if __name__ == "__main__":
    for artifact in train_box_score_models():
        print(f"{artifact.model_name} {artifact.target}: MAE={artifact.mae}")

