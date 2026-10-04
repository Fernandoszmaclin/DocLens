import sqlite3
import uuid

import numpy as np
import pytest

from doclens.errors import ModelUnavailable
from doclens.service import DocumentService
from doclens.storage import Store
from tests.conftest import FakeModels, image_bytes


def legacy_library(settings):
    store = Store(settings.data_dir)
    identifier = str(uuid.uuid4())
    text = "Computadores com defeito. Guarde os arquivos."
    block = {
        "id": 0,
        "text": text,
        "box": [[0, 0], [250, 0], [250, 20], [0, 20]],
        "confidence": 0.9,
    }
    document = {
        "id": identifier,
        "filename": "memo.png",
        "created_at": "2026-10-03T00:00:00+00:00",
        "duration_seconds": 5.0,
        "preprocess": False,
    }
    store.save(
        document,
        [{"number": 1, "width": 250, "height": 300, "text": text, "blocks": [block]}],
        [
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "page": 1,
                "block_ids": [0],
                "spans": [],
                "embedding": np.array([1, 0, 0], dtype=np.float32),
            }
        ],
    )
    with store.connect() as connection:
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('index', 'legacy')")
    directory = settings.data_dir / identifier
    directory.mkdir()
    image = directory / "1.png"
    image.write_bytes(image_bytes())
    return identifier, image


def test_old_index_is_rebuilt_once_without_ocr_or_changed_documents(settings):
    identifier, image = legacy_library(settings)
    original = image.read_bytes()

    class Models(FakeModels):
        calls = 0

        @property
        def reader(self):
            raise AssertionError("Reindexação não deve repetir OCR")

        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)

    models = Models()
    service = DocumentService(settings, models)
    before = service.store.document(identifier)
    service.ensure_index()
    hits = service.search("computadores", "tfidf", 5)
    assert hits[0]["text"] == "Computadores com defeito."
    assert hits[0]["boxes"][0][1][0] < 250
    assert service.store.document(identifier) == before
    assert image.read_bytes() == original
    assert models.calls == 1
    assert len(list((settings.data_dir / "backups").glob("*.sqlite3"))) == 1


def test_reindex_failure_keeps_old_index_and_source(settings):
    identifier, image = legacy_library(settings)

    class Models(FakeModels):
        def embed(self, texts):
            raise ModelUnavailable()

    service = DocumentService(settings, Models())
    previous = service.store.chunks()[0]["text"]
    with pytest.raises(ModelUnavailable):
        service.ensure_index()
    assert service.store.index_key() == "legacy"
    assert service.store.chunks()[0]["text"] == previous
    assert service.store.document(identifier)
    assert image.exists()
    assert not service.lock.locked()


def test_index_replacement_rolls_back_if_a_chunk_cannot_be_saved(settings):
    legacy_library(settings)
    store = Store(settings.data_dir)
    previous = store.chunks()
    bad = {
        "id": str(uuid.uuid4()),
        "document_id": "unknown",
        "page": 1,
        "text": "Teste",
        "block_ids": [0],
        "spans": [],
        "embedding": np.array([1, 0, 0], dtype=np.float32),
    }
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_index([bad], "new")
    assert store.chunks()[0]["id"] == previous[0]["id"]
    assert store.index_key() == "legacy"
