"""Fixtures HTTP; doubles compartilhados continuam disponíveis por compatibilidade."""

import pytest

from doclens.api import create_app
from doclens.config import Settings
from tests.support import FakeModels as FakeModels
from tests.support import FakeReader as FakeReader
from tests.support import LocalTestClient as TestClient
from tests.support import image_bytes as image_bytes
from tests.support import pdf_bytes as pdf_bytes


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", model_dir=tmp_path / "models", preprocess=False)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, FakeModels())) as current:
        yield current
