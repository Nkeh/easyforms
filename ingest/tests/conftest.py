import pytest

from spam import scoring


@pytest.fixture(autouse=True)
def _reset_spam_scorer_singleton():
    _reset()
    yield
    _reset()


def _reset():
    scorer = scoring._default_scorer
    scorer._pipeline = None
    scorer._model_version = None
    scorer._last_checked = None
    scorer._failure_logged = False
