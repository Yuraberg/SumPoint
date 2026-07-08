"""Guard against the AVAILABLE_MODELS / cron-preset duplication regressing.

These constants used to be copy-pasted in two model modules; the models now
re-export them from app.constants. If someone reintroduces a literal, these
identity checks fail.
"""
from app import constants
from app.models import digest_schedule as digest_model
from app.models import schedule as schedule_model


def test_available_models_shared():
    assert schedule_model.AVAILABLE_MODELS is constants.AVAILABLE_MODELS
    assert digest_model.AVAILABLE_MODELS is constants.AVAILABLE_MODELS


def test_default_model_is_in_available():
    assert constants.DEFAULT_MODEL in constants.AVAILABLE_MODELS


def test_cron_presets_shared():
    assert schedule_model.CRON_PRESETS is constants.CRON_PRESETS


def test_valid_hours_shared():
    assert digest_model.VALID_HOURS is constants.VALID_DIGEST_HOURS


def test_model_labels_cover_available_models():
    for m in constants.AVAILABLE_MODELS:
        assert m in constants.MODEL_LABELS
