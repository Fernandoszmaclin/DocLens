"""Casos extremos reproduzidos: entradas, geometria, concorrência e busca literal."""

import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image

from doclens.api import create_app
from doclens.errors import ModelUnavailable
from doclens.passages import make_chunks, sentence_ranges
from doclens.search import rank_chunks
from doclens.vision import load_pages
from tests.conftest import FakeModels, FakeReader, image_bytes, pdf_bytes
from tests.support import LocalTestClient as TestClient


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_transparency_becomes_white_paper(settings, mode):
    if mode == "P":
        image = Image.new(mode, (20, 20), 0)
        image.putpalette([0, 0, 0] * 256)
        image.info["transparency"] = 0
        image.putpixel((10, 10), 1)
    else:
        image = Image.new(mode, (20, 20), (0, 0, 0, 0) if mode == "RGBA" else (0, 0))
        image.putpixel((10, 10), (0, 0, 0, 255) if mode == "RGBA" else (0, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    page = load_pages(buffer.getvalue(), "memo.png", settings)[0]
    assert page[0, 0].tolist() == [255, 255, 255]
    assert page[10, 10].tolist() == [0, 0, 0]


def test_animated_png_is_rejected_without_silently_losing_frames(client):
    buffer = io.BytesIO()
    image = Image.new("RGB", (20, 20), "white")
    image.save(buffer, "PNG", save_all=True, append_images=[Image.new("RGB", (20, 20), "black")])
    response = client.post("/documents", files={"file": ("animated.png", buffer.getvalue())})
    assert response.status_code == 422
    assert "animadas" in response.json()["detail"]
    assert client.get("/documents").json() == []


def test_jpeg_orientation_matches_processed_dimensions(settings):
    buffer = io.BytesIO()
    image = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[274] = 6
    image.save(buffer, "JPEG", exif=exif)
    page = load_pages(buffer.getvalue(), "memo.jpeg", settings)[0]
    assert page.shape == (40, 20, 3)


def test_busy_upload_does_not_decode_another_file(client, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Um upload ocupado não deve abrir PDF nem decodificar imagem")

    monkeypatch.setattr("doclens.service.load_pages", forbidden)
    lock = client.app.state.service.lock
    lock.acquire()
    try:
        response = client.post("/documents", files={"file": ("memo.pdf", b"%PDF-test")})
        assert response.status_code == 409
    finally:
        lock.release()


@pytest.mark.parametrize(
    "body,status",
    [
        (b'{"query":"\\ud800"}', 422),
        (b'{"query":"\\udfff"}', 422),
        (b'{"query":"\\u200b"}', 422),
        (b'{"query":"\\ufeff"}', 422),
        (b'{"query":"\\u0000"}', 422),
        (b'{"query":"x", "top_k":NaN}', 422),
        (b'{"query":"x", "top_k":Infinity}', 422),
        (b'{"query":"x", "top_k":true}', 422),
        (b'{"query":"x", "top_k":"3"}', 422),
        (b'{"query":"x", "top_k":1.5}', 422),
        (b'{"query":null}', 422),
        (b'{"query":[]}', 422),
        (b'{"method":"\\ud800", "query":"x"}', 422),
        (b'{"query":', 422),
        (b'{"query":"\xff"}', 400),
    ],
)
def test_malformed_input_is_a_client_error_instead_of_500(settings, body, status):
    with TestClient(create_app(settings, FakeModels()), raise_server_exceptions=False) as client:
        response = client.post(
            "/search", content=body, headers={"content-type": "application/json"}
        )
        assert response.status_code == status, response.text
        assert isinstance(response.json()["detail"], str)
        assert "input" not in json.dumps(response.json())


def test_failure_on_second_page_rolls_back_files_and_releases_processor(settings):
    class Reader(FakeReader):
        calls = 0

        def readtext(self, image, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise ModelUnavailable()
            return super().readtext(image, **kwargs)

    models = FakeModels()
    models.reader = Reader()
    with TestClient(create_app(settings, models)) as client:
        response = client.post("/documents", files={"file": ("memo.pdf", pdf_bytes(2))})
        assert response.status_code == 503
        assert client.get("/documents").json() == []
        assert not list(settings.data_dir.glob("*/[1-5].png"))
        assert not client.app.state.service.lock.locked()
        assert (
            client.post("/documents", files={"file": ("memo.png", image_bytes())}).status_code
            == 201
        )


@pytest.mark.parametrize("value", [np.nan, np.inf, 0.0])
def test_invalid_embeddings_are_not_persisted(settings, value):
    class Models(FakeModels):
        def embed(self, texts):
            return np.full((len(texts), 3), value, dtype=np.float32)

    with TestClient(create_app(settings, Models()), raise_server_exceptions=False) as client:
        response = client.post("/documents", files={"file": ("memo.png", image_bytes())})
        assert response.status_code == 503
        assert client.get("/documents").json() == []
        assert not list(settings.data_dir.glob("*/[1-5].png"))


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
@pytest.mark.parametrize("output", [[np.nan], [], [8, 8]])
def test_invalid_reranking_is_a_clear_error_and_preserves_documents(settings, method, output):
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.array(output)

    with TestClient(create_app(settings, Models()), raise_server_exceptions=False) as client:
        assert (
            client.post("/documents", files={"file": ("memo.png", image_bytes())}).status_code
            == 201
        )
        response = client.post("/search", json={"query": "computadores", "method": method})
        assert response.status_code == 503
        assert "dados inválidos" in response.json()["detail"]
        assert len(client.get("/documents").json()) == 1


@pytest.mark.parametrize("method", ["hybrid", "semantic"])
@pytest.mark.parametrize("output", [[[np.nan, 0, 0]], [[1, 0]], [[0, 0, 0]]])
def test_invalid_query_vectors_are_not_used_to_rank(settings, method, output):
    models = FakeModels()
    with TestClient(create_app(settings, models), raise_server_exceptions=False) as client:
        assert (
            client.post("/documents", files={"file": ("memo.png", image_bytes())}).status_code
            == 201
        )
        models.embed = lambda texts: np.array(output)
        response = client.post("/search", json={"query": "computadores", "method": method})
        assert response.status_code == 503
        assert "dados inválidos" in response.json()["detail"]


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
def test_wrong_document_number_is_not_a_semantic_match(method):
    chunks = [{"text": "Memorando MEM-024/2026: manutenção.", "embedding": np.array([1, 0, 0])}]
    assert rank_chunks(chunks, "MEM-023/2026", method, FakeModels(), 5) == []


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
def test_identifier_filter_runs_before_duplicate_passages_are_removed(method):
    chunks = [
        {
            "document_id": str(number),
            "text": "Computadores com defeito.",
            "source_text": f"Referência: MEM {number:03d}/2026. Computadores com defeito.",
            "embedding": np.array([1, 0, 0]),
        }
        for number in (24, 23)
    ]
    hits = rank_chunks(chunks, "Computadores MEM-023/2026", method, FakeModels(), 5)
    assert hits and all(hit["document_id"] == "23" for hit in hits)
    assert "source_text" not in hits[0]


def test_zero_remains_a_searchable_number():
    hits = rank_chunks([{"text": "Saldo 0"}], "0", "tfidf", FakeModels(), 3)
    assert hits and hits[0]["text"] == "Saldo 0"


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
def test_requested_year_must_be_present_in_the_source(method):
    chunks = [
        {
            "text": "Entrega de equipamentos de proteção.",
            "source_text": "Comunicado 2026. Entrega de equipamentos de proteção.",
            "embedding": np.array([1, 0, 0]),
        }
    ]
    assert rank_chunks(chunks, "Entrega de equipamentos em 2030", method, FakeModels(), 3) == []
    assert rank_chunks(chunks, "Entrega de equipamentos em 2026", method, FakeModels(), 3)


def test_fallback_does_not_override_a_very_strong_relevance_rejection():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -9)

    chunks = [{"text": "Treinamento com computadores", "embedding": np.array([0.9, 0, 0])}]
    for method in ("semantic", "hybrid"):
        assert rank_chunks(chunks, "Computadores avariados", method, Models(), 5) == []


def test_hybrid_window_preserves_a_top_semantic_only_candidate():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.array([8 if "Notebooks lentos" in text else -9 for text in texts])

    chunks = [
        {"text": "Máquinas disponíveis", "embedding": np.array([0.52, 0, 0])},
        {"text": "Notebooks lentos", "embedding": np.array([0.51, 0, 0])},
        *[
            {"text": f"Computadores treinamento {i}", "embedding": np.array([0.5, 0, 0])}
            for i in range(30)
        ],
        {"text": "Computadores", "embedding": np.array([0.1, 0, 0])},
    ]
    hits = rank_chunks(chunks, "computadores", "hybrid", Models(), 3)
    assert len(hits) == 1 and hits[0]["text"] == "Notebooks lentos"


@pytest.mark.parametrize("closing", ['"', "”", "')", ")."])
def test_sentence_ending_inside_quotes_or_parentheses_keeps_short_passages(closing):
    text = f"Informe: suporte concluído.{closing} Depois aguarde."
    ranges = sentence_ranges(text)
    assert len(ranges) == 2
    assert text[ranges[0][0] : ranges[0][1]] == f"Informe: suporte concluído.{closing}"
    assert text[ranges[1][0] : ranges[1][1]] == "Depois aguarde."


def test_mixed_blocks_with_and_without_geometry_do_not_break_title_detection():
    blocks = [
        {"id": 0, "text": "Texto sem caixa."},
        {"id": 1, "text": "Título", "box": [[0, 0], [200, 0], [200, 20], [0, 20]]},
    ]
    assert len(make_chunks(blocks, FakeModels())) == 2


def test_pdfium_is_serialized_across_threads(settings, monkeypatch):
    activity = {"current": 0, "maximum": 0}
    tracker = threading.Lock()

    class Bitmap:
        def to_pil(self):
            return Image.new("RGB", (20, 20), "white")

        def close(self):
            pass

    class Page:
        def get_size(self):
            return 72, 72

        def render(self, **kwargs):
            return Bitmap()

        def close(self):
            pass

    class Document:
        def __init__(self, content):
            pass

        def __enter__(self):
            with tracker:
                activity["current"] += 1
                activity["maximum"] = max(activity["maximum"], activity["current"])
            time.sleep(0.02)  # Permite sobreposição do segundo thread sem chamar PDFium real.
            return self

        def __exit__(self, *args):
            with tracker:
                activity["current"] -= 1

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return Page()

    monkeypatch.setattr("doclens.vision.pdfium.PdfDocument", Document)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(load_pages, b"%PDF-test", "memo.pdf", settings) for _ in range(2)
        ]
        assert all(future.result(timeout=3)[0].shape == (20, 20, 3) for future in futures)
    assert activity["maximum"] == 1
