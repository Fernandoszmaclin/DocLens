import io

import pytest
from pypdf import PdfReader, PdfWriter

from doclens.api import create_app
from doclens.errors import ModelUnavailable
from tests.conftest import FakeModels, image_bytes, pdf_bytes
from tests.support import LocalTestClient as TestClient


@pytest.mark.parametrize(
    "filename,content",
    [
        ("memo.png", image_bytes()),
        ("memo.jpg", image_bytes("JPEG")),
        ("memo.pdf", pdf_bytes()),
    ],
    ids=["png", "jpeg", "pdf"],
)
def test_upload_search_and_restart(client, settings, filename, content):
    response = client.post("/documents", files={"file": (filename, content)})
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["page_count"] == 1
    assert "Manutenção" in document["pages"][0]["text"]
    assert client.get(document["pages"][0]["image_url"]).headers["content-type"] == "image/png"
    query = {"query": "computadores", "method": "tfidf"}
    before = client.post("/search", json=query).json()["results"]
    assert before[0]["document_id"] == document["id"]
    assert before[0]["boxes"] == [document["pages"][0]["blocks"][0]["box"]]
    # Nova instância usa SQLite e vetores já armazenados.
    with TestClient(create_app(settings, FakeModels())) as restarted:
        assert restarted.get("/documents").json()[0]["id"] == document["id"]
        assert restarted.post("/search", json=query).json()["results"] == before
        semantic = restarted.post("/search", json={"query": "máquinas", "method": "semantic"})
        assert semantic.json()["results"][0]["score"] == pytest.approx(1)


@pytest.mark.parametrize(
    "filename,content,status,fragment",
    [
        ("memo.exe", b"text", 415, "PNG"),
        ("memo.png", b"invalid", 422, "imagem"),
        ("memo.pdf", b"%PDF-1.7\nbroken", 422, "PDF"),
        ("memo.png", b"", 422, "vazio"),
        ("memo.jpg", image_bytes(), 422, "extensão"),
        ("memo.png", image_bytes(color="white"), 422, "Nenhum texto"),
        ("memo.pdf", pdf_bytes(6), 422, "cinco"),
    ],
    ids=["unsupported", "bad-image", "bad-pdf", "empty", "wrong-extension", "blank", "six-pages"],
)
def test_invalid_uploads_leave_no_documents(client, settings, filename, content, status, fragment):
    response = client.post("/documents", files={"file": (filename, content)})
    assert response.status_code == status, response.text
    assert fragment in response.json()["detail"]
    assert client.get("/documents").json() == []
    assert not list(settings.data_dir.glob("*/[1-5].png"))


def test_protected_pdf(client):
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes())))
    writer.encrypt("senha-exemplo")
    buffer = io.BytesIO()
    writer.write(buffer)
    response = client.post("/documents", files={"file": ("protegido.pdf", buffer.getvalue())})
    assert response.status_code == 422
    assert "senha" in response.json()["detail"]


def test_upload_limit(client):
    response = client.post(
        "/documents", files={"file": ("large.png", b"x" * (10 * 1024 * 1024 + 1))}
    )
    assert response.status_code == 413


def test_multipage_coordinates_follow_rendered_page(client):
    document = client.post("/documents", files={"file": ("memo.pdf", pdf_bytes(2))}).json()
    assert document["page_count"] == 2
    for page in document["pages"]:
        assert client.get(page["image_url"]).status_code == 200
        assert all(
            0 <= x <= page["width"] and 0 <= y <= page["height"]
            for block in page["blocks"]
            for x, y in block["box"]
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "test", "method": "invalid"},
        {"query": "test", "top_k": 0},
        {"query": "x" * 501},
    ],
)
def test_bad_search_request(client, payload):
    assert client.post("/search", json=payload).status_code == 422


def test_empty_library_and_tfidf_no_overlap(client):
    assert client.post("/search", json={"query": "qualquer"}).json()["results"] == []
    client.post("/documents", files={"file": ("memo.png", image_bytes())})
    assert (
        client.post("/search", json={"query": "astronomia", "method": "tfidf"}).json()["results"]
        == []
    )


@pytest.mark.parametrize("method", [None, "hybrid", "semantic", "tfidf"])
def test_search_default_is_hybrid_and_other_modes_keep_source_boxes(client, method):
    document = client.post("/documents", files={"file": ("memo.png", image_bytes())}).json()
    payload = {"query": "computadores"}
    if method is not None:
        payload["method"] = method
    response = client.post("/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == (method or "hybrid")
    assert len(data["results"]) == 1
    hit = data["results"][0]
    assert hit["document_id"] == document["id"]
    assert hit["boxes"] == [document["pages"][0]["blocks"][0]["box"]]
    assert 0 < hit["score"] <= (2 / 61 + 0.008 if data["method"] == "hybrid" else 1)


def test_names_are_not_used_as_paths(client, settings):
    document = client.post("/documents", files={"file": ("../../memo.png", image_bytes())}).json()
    assert document["filename"] == "memo.png"
    assert (settings.data_dir / document["id"] / "1.png").exists()
    assert client.get("/documents/not-a-uuid").status_code == 422
    assert client.get(f"/documents/{document['id']}/pages/999/image").status_code == 404


def test_busy_processor(client):
    lock = client.app.state.service.lock
    lock.acquire()
    try:
        assert (
            client.post("/documents", files={"file": ("memo.png", image_bytes())}).status_code
            == 409
        )
    finally:
        lock.release()


def test_model_failure_removes_partial_upload(settings):
    class UnavailableModels:
        @property
        def reader(self):
            raise ModelUnavailable()

    with TestClient(create_app(settings, UnavailableModels())) as client:
        result = client.post("/documents", files={"file": ("memo.png", image_bytes())})
        assert result.status_code == 503
        assert "prepare_models" in result.json()["detail"]
        assert client.get("/documents").json() == []
    assert not list(settings.data_dir.glob("*/[1-5].png"))


def test_home_and_docs(client):
    assert 'lang="pt-BR"' in client.get("/").text
    assert client.get("/docs").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
