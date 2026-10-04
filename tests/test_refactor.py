"""Regressões de geometria, leitura local e acesso às imagens sem hidratar OCR."""

import json
import uuid
from pathlib import Path

import numpy as np
import pytest

from doclens import config, storage
from doclens.config import Settings
from doclens.passages import passage_boxes
from doclens.storage import Store
from tests.support import image_bytes


def library(settings):
    store = Store(settings.data_dir)
    identifier = str(uuid.uuid4())
    blocks = [
        {"id": 9, "text": "Primeira frase.", "box": [[0, 0], [140, 0], [140, 20], [0, 20]]},
        {"id": 2, "text": "Segunda frase.", "box": [[0, 30], [140, 30], [140, 50], [0, 50]]},
    ]
    pages = [
        {"number": number, "width": 200, "height": 300, "text": "Texto", "blocks": blocks}
        for number in (1, 2)
    ]
    chunks = [
        {
            "id": f"chunk-{number}-{part}",
            "page": number,
            "text": block["text"],
            "block_ids": [block["id"]],
            "spans": [{"block_id": block["id"], "start": 1, "end": 5}],
            "embedding": np.array([1, 0, 0], dtype=np.float32),
        }
        for number in (1, 2)
        for part, block in enumerate(blocks)
    ]
    chunks[-1]["block_ids"] = [2, 9]
    chunks[-1]["spans"] = []
    store.save(
        {
            "id": identifier,
            "filename": "memo.png",
            "created_at": "2026-10-03T00:00:00+00:00",
            "duration_seconds": 1.0,
            "preprocess": False,
        },
        pages,
        chunks,
    )
    return store, identifier, blocks


def test_page_geometry_is_reused_only_within_each_read(settings, monkeypatch):
    store, identifier, blocks = library(settings)
    original_loads = json.loads
    original_boxes = passage_boxes
    decoded_pages = []
    geometry_maps = []

    def loads(value):
        result = original_loads(value)
        if result and isinstance(result[0], dict) and "box" in result[0]:
            decoded_pages.append(result)
        return result

    def boxes(blocks, spans, *, blocks_by_id=None):
        geometry_maps.append(blocks_by_id)
        return original_boxes(blocks, spans, blocks_by_id=blocks_by_id)

    monkeypatch.setattr(storage.json, "loads", loads)
    monkeypatch.setattr(storage, "passage_boxes", boxes)
    chunks = store.chunks()
    assert len(decoded_pages) == 2
    assert geometry_maps[0] is geometry_maps[1]
    assert geometry_maps[1] is not geometry_maps[2]
    assert [chunk["id"] for chunk in chunks] == ["chunk-1-0", "chunk-1-1", "chunk-2-0", "chunk-2-1"]
    assert chunks[0]["boxes"] == original_boxes(blocks, [{"block_id": 9, "start": 1, "end": 5}])
    # Índices antigos preservam a ordem dos blocos, mesmo com IDs em outra ordem.
    assert chunks[-1]["boxes"] == [block["box"] for block in blocks]
    assert chunks[0]["embedding"].dtype == np.float32
    chunks[0]["embedding"][0] = 99

    changed = [dict(block, box=[[1, 1], [141, 1], [141, 21], [1, 21]]) for block in blocks]
    with store.connect() as connection:
        connection.execute(
            "UPDATE pages SET blocks=?, text=? WHERE document_id=? AND number=1",
            (json.dumps(changed), "Texto atualizado", identifier),
        )
    next_chunks = store.chunks()
    assert len(decoded_pages) == 4
    assert geometry_maps[0] is not geometry_maps[3]
    assert next_chunks[0]["boxes"] != chunks[0]["boxes"]
    assert next_chunks[0]["source_text"] == "Texto atualizado"
    np.testing.assert_array_equal(next_chunks[0]["embedding"], [1, 0, 0])


def test_legacy_highlights_remain_independent_between_passages(settings):
    store, _, blocks = library(settings)
    with store.connect() as connection:
        connection.execute("UPDATE chunks SET spans='[]', block_ids='[2, 9]' WHERE page=2")
    chunks = store.chunks()
    original = [block["box"] for block in blocks]
    assert chunks[2]["boxes"] == chunks[3]["boxes"] == original
    chunks[2]["boxes"][0][0][0] = 99
    assert chunks[3]["boxes"] == original
    assert store.chunks()[2]["boxes"] == original


def test_image_route_reads_metadata_without_loading_document(client, monkeypatch):
    document = client.post("/documents", files={"file": ("memo.png", image_bytes())}).json()

    def forbidden(_):
        raise AssertionError("A rota de imagem não deve carregar páginas ou blocos OCR")

    monkeypatch.setattr(client.app.state.service.store, "document", forbidden)
    image = client.get(document["pages"][0]["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    for number in (0, -1, 2):
        response = client.get(f"/documents/{document['id']}/pages/{number}/image")
        assert response.status_code == 404
        assert response.json() == {"detail": "Página não encontrada."}
    response = client.get(f"/documents/{uuid.uuid4()}/pages/1/image")
    assert response.status_code == 404
    assert response.json() == {"detail": "Página não encontrada."}


@pytest.mark.parametrize(
    "overrides, expected, reads",
    [
        ({}, ("encoder", "reranker"), 1),
        ({"model_revision": "fixed"}, ("fixed", "reranker"), 1),
        ({"reranker_revision": "fixed"}, ("encoder", "fixed"), 1),
        ({"model_revision": "one", "reranker_revision": "two"}, ("one", "two"), 1),
        (
            {"model_revision": "one", "reranker_revision": "two", "ocr_weights_sha256": {}},
            ("one", "two"),
            0,
        ),
    ],
)
def test_manifest_is_read_once_and_explicit_revisions_win(
    tmp_path, monkeypatch, overrides, expected, reads
):
    manifest = tmp_path / "config" / "models.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"revision": "encoder", "reranker_revision": "reranker"}))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    original = Path.read_text
    calls = []

    def read(path, *args, **kwargs):
        if path == manifest:
            calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    settings = Settings(preprocess=False, **overrides)
    assert (settings.model_revision, settings.reranker_revision) == expected
    assert len(calls) == reads
