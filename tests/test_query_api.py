from doclens.api import create_app
from tests.conftest import FakeModels, image_bytes
from tests.support import LocalTestClient as TestClient


def test_api_explains_spelling_changes_without_replacing_original_query(client):
    client.post("/documents", files={"file": ("memo.png", image_bytes())})
    data = client.post("/search", json={"query": "probelmas nos computdores"}).json()
    assert data["query"] == "probelmas nos computdores"
    assert data["interpreted_query"] == "problemas nos computadores"
    assert len(data["corrections"]) == 2
    assert data["excluded_terms"] == []
    assert data["results"]


def test_api_explains_preferences_and_keeps_symptom_negation(client):
    client.post("/documents", files={"file": ("memo.png", image_bytes())})
    original = "Não quero luvas: preciso de computadores"
    data = client.post("/search", json={"query": original}).json()
    assert data["query"] == original
    assert data["interpreted_query"] == "preciso de computadores"
    assert data["excluded_terms"] == ["luvas"]
    symptom = "O computador não liga"
    data = client.post("/search", json={"query": symptom}).json()
    assert data["interpreted_query"] == symptom
    assert data["excluded_terms"] == []


def test_corrected_query_must_still_fit_the_model_budget(settings):
    class Models(FakeModels):
        def token_length(self, text):
            return 13 if "computadores" in text else super().token_length(text)

    with TestClient(create_app(settings, Models())) as client:
        # Upload precisa de um orçamento que caiba o texto reconhecido.
        Models.token_budget = 20
        client.post("/documents", files={"file": ("memo.png", image_bytes())})
        Models.token_budget = 12
        response = client.post("/search", json={"query": "probelmas nos computdores"})
        assert response.status_code == 422
        assert "longa" in response.json()["detail"]
