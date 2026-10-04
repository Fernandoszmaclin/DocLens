import numpy as np
import pytest

from doclens.passages import passage_boxes, sentence_ranges
from doclens.search import (
    hybrid_candidates,
    lexical_tokens,
    make_chunks,
    rank_chunks,
    score_chunks,
    search_policy,
)
from scripts.evaluate import edit_distance, normalized
from tests.conftest import FakeModels


def test_chunks_keep_origin_and_respect_token_limit():
    models = FakeModels()
    blocks = [
        {"id": 10, "text": " ".join(["palavra"] * 30)},
        {"id": 20, "text": "Outro bloco do mesmo documento"},
    ]
    chunks = make_chunks(blocks, models)
    assert len(chunks) >= 3
    assert all(models.token_length(chunk["text"]) <= models.token_budget for chunk in chunks)
    assert " ".join(chunk["text"] for chunk in chunks) == " ".join(b["text"] for b in blocks)
    assert chunks[0]["block_ids"] == [10]
    assert 20 in chunks[-1]["block_ids"]


def test_cer_counts_insertions_deletions_and_accent_errors():
    assert edit_distance("casa", "casas") == 1
    assert edit_distance("casa", "cas") == 1
    assert edit_distance("café", "cafe") == 1
    assert normalized("  AÇÃO\n  teste ") == "ação teste"


def test_sentences_join_wrapped_lines_but_keep_paragraphs_separate():
    blocks = [
        {
            "id": 0,
            "text": "Manutenção de computadores",
            "box": [[0, 0], [250, 0], [250, 30], [0, 30]],
        },
        {
            "id": 1,
            "text": "Os notebooks apresentam",
            "box": [[0, 60], [250, 60], [250, 80], [0, 80]],
        },
        {
            "id": 2,
            "text": "lentidão. A revisão será amanhã.",
            "box": [[0, 82], [250, 82], [250, 102], [0, 102]],
        },
        {
            "id": 3,
            "text": "Salve seus arquivos.",
            "box": [[0, 130], [250, 130], [250, 150], [0, 150]],
        },
    ]
    chunks = make_chunks(blocks, FakeModels())
    assert [c["text"] for c in chunks] == [
        "Manutenção de computadores",
        "Os notebooks apresentam lentidão.",
        "A revisão será amanhã.",
        "Salve seus arquivos.",
    ]
    assert chunks[1]["block_ids"] == [1, 2]
    assert all(c["context_text"] == blocks[0]["text"] for c in chunks)
    boxes = passage_boxes(blocks, chunks[1]["spans"])
    assert len(boxes) == 2
    assert boxes[0] == blocks[1]["box"]
    assert boxes[1][1][0] < blocks[2]["box"][1][0]
    assert chunks[2]["spans"][0]["start"] == len("lentidão. ")


def test_lowercase_ocr_and_abbreviations_do_not_break_sentences():
    text = "O Sr. Silva revisou o item 2.5. equipe fará testes amanhã."
    assert [text[a:b] for a, b in sentence_ranges(text)] == [
        "O Sr. Silva revisou o item 2.5.",
        "equipe fará testes amanhã.",
    ]


def test_single_large_word_is_split_without_losing_characters():
    class CharacterModels(FakeModels):
        token_budget = 5

        def token_length(self, text):
            return len(text)

    chunks = make_chunks([{"id": 0, "text": "abcdefghijklmnop"}], CharacterModels())
    assert "".join(c["text"] for c in chunks) == "abcdefghijklmnop"
    assert all(len(c["text"]) <= 5 for c in chunks)


def test_portuguese_flexions_accents_stopwords_and_negation():
    assert lexical_tokens("equipamentos") == lexical_tokens("equipamento")
    assert lexical_tokens("MANUTENÇÃO") == lexical_tokens("manutencao")
    assert lexical_tokens("de nos para com") == ()
    assert lexical_tokens("não sem")


@pytest.mark.parametrize("method", ["hybrid", "semantic", "tfidf"])
def test_stopword_query_does_not_produce_highlights(method):
    chunks = [
        {
            "id": "1",
            "document_id": "a",
            "text": "Computadores da equipe",
            "embedding": np.array([1, 0, 0]),
        }
    ]
    assert rank_chunks(chunks, "de nos para", method, FakeModels(), 5) == []


def test_missing_query_terms_reduce_lexical_score():
    chunks = [{"text": "Revisão dos computadores"}]
    assert (
        score_chunks(chunks, "computadores", "tfidf", FakeModels())[0]
        > score_chunks(chunks, "computadores quânticos extraterrestres", "tfidf", FakeModels())[0]
    )


def test_unrelated_candidate_is_rejected_instead_of_filling_top_k():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.array([4 if "notebooks" in t.casefold() else -9 for t in texts])

    chunks = [
        {"document_id": "a", "text": "Notebooks com defeito", "embedding": np.array([0.8, 0.6, 0])},
        {
            "document_id": "b",
            "text": "Computadores na sala de treinamento",
            "embedding": np.array([0.7, 0, 0]),
        },
    ]
    hits = rank_chunks(chunks, "máquinas defeituosas", "semantic", Models(), 5)
    assert len(hits) == 1
    assert hits[0]["document_id"] == "a"


def test_lexical_mode_keeps_lexical_order_after_relevance_filter():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.array([0 if t == "computadores" else 9 for t in texts])

    chunks = [
        {"text": "computadores", "document_id": "a"},
        {"text": "Computadores para atendimento diário da equipe", "document_id": "b"},
    ]
    hits = rank_chunks(chunks, "computadores", "tfidf", Models(), 5)
    assert hits[0]["document_id"] == "a"


def test_hybrid_consensus_uses_positions_and_preserves_one_source_passage():
    boxes = [[[10, 20], [100, 20], [100, 40], [10, 40]]]
    chunks = [
        {"id": "a", "text": "Máquinas avariadas", "embedding": np.array([0.9, 0, 0])},
        {
            "id": "b",
            "text": "computadores",
            "embedding": np.array([0.8, 0, 0]),
            "boxes": boxes,
            "spans": [{"block_id": 3, "start": 0, "end": 12}],
        },
        {"id": "c", "text": "Astronomia", "embedding": np.array([0.1, 0, 0])},
    ]
    hits = rank_chunks(chunks, "computadores", "hybrid", FakeModels(), 5)
    assert [hit["id"] for hit in hits] == ["b", "a"]
    assert hits[0]["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert hits[0]["boxes"] == boxes
    assert hits[0]["spans"] == chunks[1]["spans"]
    assert "embedding" not in hits[0]


def test_hybrid_keeps_semantic_only_paraphrase_without_lexical_overlap():
    chunks = [
        {
            "text": "Notebooks apresentam lentidão.",
            "embedding": np.array([0.8, 0, 0]),
        }
    ]
    assert rank_chunks(chunks, "Problemas nos computadores", "tfidf", FakeModels(), 5) == []
    hits = rank_chunks(chunks, "Problemas nos computadores", "hybrid", FakeModels(), 5)
    assert hits[0]["text"] == chunks[0]["text"]
    assert hits[0]["rrf_score"] == pytest.approx(1 / 61)


def test_hybrid_keeps_exact_match_with_weak_semantic_score():
    chunks = [{"text": "MEM-023/2026", "embedding": np.array([0.1, 0, 0])}]
    hits = rank_chunks(chunks, "MEM-023/2026", "hybrid", FakeModels(), 5)
    assert hits[0]["text"] == "MEM-023/2026"
    assert hits[0]["semantic_score"] == 0
    assert hits[0]["tfidf_score"] == pytest.approx(1)


def test_hybrid_rejects_irrelevance_even_when_both_methods_agree():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -9)

    chunks = [{"text": "computadores", "embedding": np.array([0.5, 0, 0])}]
    assert rank_chunks(chunks, "computadores", "hybrid", Models(), 5) == []


def test_hybrid_promotes_specific_answer_over_generic_title():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.array([5 if "entregar" in text else -1 for text in texts])

    chunks = [
        {"text": "capacitação comprovante", "embedding": np.array([0.9, 0, 0])},
        {
            "text": "Após o curso, entregar o comprovante ao setor.",
            "embedding": np.array([0.4, 0, 0]),
        },
    ]
    hits = rank_chunks(chunks, "capacitação comprovante", "hybrid", Models(), 2)
    assert hits[0]["text"] == chunks[1]["text"]
    assert hits[0]["score"] > hits[1]["score"]


def test_hybrid_rejects_weak_semantic_only_match_with_negative_verification():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -1)

    chunks = [{"text": "Expediente amanhã", "embedding": np.array([0.3, 0, 0])}]
    assert rank_chunks(chunks, "Previsão do tempo", "hybrid", Models(), 5) == []


def test_hybrid_does_not_add_distant_semantic_neighbors_as_extra_highlights():
    class Models(FakeModels):
        def rerank(self, query, texts):
            return np.full(len(texts), -1)

    chunks = [
        {"text": "Notebooks apresentam lentidão.", "embedding": np.array([0.8, 0, 0])},
        {"text": "A rede de internet oscila.", "embedding": np.array([0.5, 0, 0])},
    ]
    hits = rank_chunks(chunks, "Problemas nos computadores", "hybrid", Models(), 5)
    assert [hit["text"] for hit in hits] == [chunks[0]["text"]]


def test_hybrid_deduplicates_and_limits_one_verification_batch():
    class Models(FakeModels):
        calls = []

        def rerank(self, query, texts):
            self.calls.append(texts)
            return super().rerank(query, texts)

    models = Models()
    chunks = [
        {"text": f"computadores equipe {i}", "embedding": np.array([0.8, 0, 0])} for i in range(60)
    ]
    chunks.append({**chunks[0], "id": "duplicate"})
    candidates = hybrid_candidates(chunks, "computadores", models, search_policy())
    assert len(candidates) == 30
    assert len({hit["text"] for hit in candidates}) == 30
    hits = rank_chunks(chunks, "computadores", "hybrid", models, 3)
    assert len(models.calls) == 1 and len(models.calls[0]) == 30
    assert len(hits) == 3


def test_passage_metric_requires_one_target_sentence_not_scattered_words():
    from scripts.evaluate_search import passage_quality

    documents = {
        "a": {
            "id": "a",
            "title": "Teste",
            "paragraphs": ["Um dois três quatro. Cinco seis sete oito."],
        }
    }
    item = {"relevant": ["a"], "targets": [[0, 0], [0, 1]]}
    references = {"a": "Teste Um dois três quatro. Cinco seis sete oito."}
    precision, focused = passage_quality(
        {"document_id": "a", "text": "Um cinco"}, item, documents, references
    )
    assert precision == 1
    assert not focused
