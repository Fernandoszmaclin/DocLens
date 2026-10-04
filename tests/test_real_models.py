import os

import pytest

from doclens.api import create_app
from doclens.config import ROOT, Settings
from doclens.models import LocalModels
from doclens.search import make_chunks, rank_chunks
from tests.support import LocalTestClient as TestClient


@pytest.mark.models
@pytest.mark.skipif(os.getenv("DOCLENS_RUN_MODELS") != "1", reason="Use DOCLENS_RUN_MODELS=1")
def test_real_ocr_embeddings_and_pdf(tmp_path):
    settings = Settings(data_dir=tmp_path / "real-data")
    models = LocalModels(settings)
    with TestClient(create_app(settings, models)) as client:
        for extension, directory in (("png", "clean"), ("pdf", "pdf")):
            path = ROOT / "data" / "fixtures" / directory / f"manutencao_01.{extension}"
            response = client.post("/documents", files={"file": (path.name, path.read_bytes())})
            assert response.status_code == 201, response.text
            assert "notebooks" in response.json()["pages"][0]["text"].lower()
        for method in (None, "semantic", "tfidf"):
            payload = {"query": "Problemas nos computadores"}
            if method is not None:
                payload["method"] = method
            response = client.post("/search", json=payload)
            assert response.status_code == 200
            hits = response.json()["results"]
            if method == "tfidf":
                assert not hits  # A paráfrase não tem sobreposição lexical suficiente.
                continue
            assert response.json()["method"] == (method or "hybrid")
            assert hits and hits[0]["boxes"] and hits[0]["page"] == 1
            assert "notebooks" in hits[0]["text"].lower()
            assert 0 < hits[0]["score"] <= (2 / 61 + 0.008 if method is None else 1)


@pytest.mark.models
@pytest.mark.skipif(os.getenv("DOCLENS_RUN_MODELS") != "1", reason="Use DOCLENS_RUN_MODELS=1")
def test_specific_questions_match_when_the_source_actually_contains_the_information():
    models = LocalModels(Settings())
    examples = [
        (
            "computador",
            "O computador não liga",
            "Quando o computador não ligar, registre um chamado no suporte técnico.",
        ),
        (
            "certificado",
            "Onde entregar o certificado depois do curso?",
            "Após concluir o curso, entregue o certificado no setor de recursos humanos.",
        ),
        (
            "saude",
            "Inscrição no plano de saúde dos funcionários",
            "A inscrição no plano de saúde dos funcionários deve ser solicitada "
            "ao setor de recursos humanos.",
        ),
    ]
    chunks = []
    for document, _, text in examples:
        chunks.extend(
            {**chunk, "document_id": document}
            for chunk in make_chunks([{"id": 0, "text": text}], models)
        )
    for chunk, embedding in zip(
        chunks, models.embed([item["text"] for item in chunks]), strict=True
    ):
        chunk["embedding"] = embedding
    for expected, query, _ in examples:
        for method in ("hybrid", "semantic", "tfidf"):
            hits = rank_chunks(chunks, query, method, models, 3)
            assert hits and hits[0]["document_id"] == expected
