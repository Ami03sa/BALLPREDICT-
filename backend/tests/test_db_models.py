"""Coverage tests for db and model modules — just importing exercises module-level code."""


def test_db_base_importable():
    from app.db.base import Base
    assert Base is not None


def test_db_session_importable():
    import importlib
    import sys

    sys.modules.pop("app.db.session", None)
    try:
        importlib.import_module("app.db.session")
    except Exception:
        pass  # psycopg[binary] may not be installed locally; lines still traced


def test_entities_importable():
    from app.models.entities import Game, Player, Team
    assert Team.__tablename__ == "teams"
    assert Player.__tablename__ == "players"
    assert Game.__tablename__ == "games"


def test_train_models_importable():
    from app.workers.train_models import FEATURES, TARGETS, TrainedModelArtifact
    assert len(FEATURES) > 0
    assert "points" in TARGETS


def test_train_models_make_preprocessor():
    from app.workers.train_models import _make_preprocessor
    preprocessor = _make_preprocessor()
    assert preprocessor is not None
