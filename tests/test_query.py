import numpy as np
import pytest

from doclens.query import interpret_query
from doclens.search import rank_chunks
from tests.conftest import FakeModels


def test_one_edit_typos_are_corrected_without_using_benchmark_words():
    interpreted = interpret_query([], "probelmas nos computdores")
    assert interpreted.query == "problemas nos computadores"
    assert len(interpreted.corrections) == 2


@pytest.mark.parametrize(
    "query",
    [
        "MEM-023/2026",
        "MANUTENCAO_99",
        "Wi-Fi",
        "0",
        "NASA",
        "recepcao reuniao",
        "O computador não liga",
        "Sem motorista",
        "Não quero luvas",
        "Inscrição no plano de saúde",
    ],
)
def test_valid_terms_numbers_and_symptom_negation_are_preserved(query):
    interpreted = interpret_query([], query)
    assert interpreted.query == query
    assert interpreted.excluded_terms == []


def test_names_from_the_library_and_ambiguous_typos_are_preserved():
    assert interpret_query([{"text": "Mylena"}], "Mylena").query == "Mylena"
    # Nomes sintéticos, ambos a uma edição: não assumir qual o usuário quis mencionar.
    assert interpret_query([{"text": "zxqab zxqac"}], "zxqaa").query == "zxqaa"


@pytest.mark.parametrize("separator", [":", ";", " mas ", ", mas ", " e sim "])
def test_preference_exclusion_preserves_positive_request(separator):
    result = interpret_query(
        [], f"Não quero ar-condicionado{separator} preciso de luvas para limpeza"
    )
    assert result.query == "preciso de luvas para limpeza"
    assert result.excluded_terms == ["ar-condicionado"]


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
def test_excluded_topic_cannot_return_as_a_highlight(method):
    chunks = [
        {"text": "Limpeza do ar-condicionado", "embedding": np.array([1, 0, 0])},
        {"text": "Luvas para limpeza", "embedding": np.array([0.8, 0, 0])},
    ]
    hits = rank_chunks(
        chunks, "Não quero ar-condicionado: preciso de luvas para limpeza", method, FakeModels(), 5
    )
    assert hits and all("ar-condicionado" not in hit["text"] for hit in hits)


@pytest.mark.parametrize("method", ["hybrid", "semantic"])
def test_generic_unanchored_passage_does_not_answer_a_specific_missing_topic(method):
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -3.18)

    chunks = [
        {
            "text": "A equipe avaliará a disponibilidade dos materiais.",
            "embedding": np.array([0.449, 0, 0]),
        }
    ]
    assert (
        rank_chunks(chunks, "Inscrição no plano de saúde dos funcionários", method, Models(), 3)
        == []
    )


@pytest.mark.parametrize("method", ["hybrid", "semantic"])
def test_related_sentence_can_use_topic_evidence_elsewhere_on_the_same_page(method):
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -1)

    chunks = [
        {
            "text": "Solicite transporte para atividades externas.",
            "source_text": "Solicite transporte para atividades externas. "
            "Veículo e motorista disponíveis.",
            "embedding": np.array([0.45, 0, 0]),
        }
    ]
    hits = rank_chunks(chunks, "Carro e motorista para uma visita", method, Models(), 3)
    assert hits and hits[0]["text"] == chunks[0]["text"]
    assert "source_text" not in hits[0]
