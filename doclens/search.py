"""Busca nas mesmas passagens, com normalização lexical e filtro de relevância."""

import json
import re
from functools import lru_cache

import numpy as np
import snowballstemmer
from sklearn.feature_extraction.text import TfidfVectorizer

from doclens.config import ROOT
from doclens.contracts import ModelProvider, SearchChunk
from doclens.errors import ModelOutputError
from doclens.models import validate_embeddings, validate_relevance
from doclens.passages import make_chunks  # noqa: F401 — contrato usado pela avaliação
from doclens.query import QueryInterpretation, folded, interpret_query

# Lista explícita, sem download de corpus. Negações (não/sem) continuam sendo conteúdo.
STOP_WORDS = set(
    """
a ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de dela delas dele
dele deles do dos e ela elas ele eles em entre era eram essa essas esse esses esta estas
este estes eu foi fomos for foram ha isso isto ja lhe lhes mais mas me mesmo meu meus
minha minhas muito na nas nem no nos nossa nossas nosso nossos o os ou para pela pelas
pelo pelos por qual quais quando que quem se seja sejam seu seus sua suas tambem te tem
temos ter teve ti tu tua tuas um uma umas uns voce voces sao ser sera serao so sobre
onde quanto quantos pode podem posso preciso quero conseguir fazer estar estamos
""".split()
)
CANDIDATE_LIMIT = 30


@lru_cache(maxsize=8192)
def lexical_tokens(text: str) -> tuple[str, ...]:
    # Cada chamada usa uma instância própria: o stemmer mantém estado interno mutável.
    stemmer = snowballstemmer.stemmer("portuguese")
    words = re.findall(r"[^\W_]+", folded(text))
    return tuple(
        stemmer.stemWord(word)
        for word in words
        if word not in STOP_WORDS and (len(word) > 1 or word.isdigit())
    )


def identifier_patterns(query: str) -> list[re.Pattern]:
    """Códigos e anos explícitos devem existir na fonte; semântica confunde números."""
    codes = re.findall(
        r"\b[a-z]{2,}(?=[a-z0-9_/-]*\d)[a-z0-9]*(?:[-_/][a-z0-9]+)*\b", folded(query)
    )
    patterns = [
        re.compile(r"(?<!\w)" + r"[\s_/.-]*".join(re.findall(r"[a-z]+|\d+", code)) + r"(?!\w)")
        for code in codes
    ]
    years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", query)
    return patterns + [re.compile(r"(?<!\d)" + year + r"(?!\d)") for year in years]


def matches_identifiers(chunk: dict, patterns: list[re.Pattern]) -> bool:
    source = folded(
        "\n".join(chunk.get(key, "") for key in ("source_text", "filename", "context_text", "text"))
    )
    return all(pattern.search(source) for pattern in patterns)


def search_policy() -> dict:
    defaults = {
        "semantic": {
            "min_score": 0.2,
            "relative_ratio": 0.85,
            "min_relevance": -3.25,
            "fallback_min_relevance": -8.0,
            "min_unanchored_score": 0.5,
        },
        "tfidf": {"min_score": 0.02, "relative_ratio": 0.6, "min_relevance": -2.25},
        "hybrid": {
            "rank_constant": 60,
            "relative_ratio": 0.6,
            "min_relevance": -2.25,
            "relevance_bonus": 0.002,
            "fallback_min_relevance": -8.0,
            "origin_head_size": 3,
            "min_unanchored_score": 0.5,
        },
    }
    path = ROOT / "config" / "search.json"
    if path.exists():
        for method, values in json.loads(path.read_text(encoding="utf-8"))["methods"].items():
            defaults[method] = {**defaults.get(method, {}), **values}
    return defaults


def score_chunks(
    chunks: list[SearchChunk], query: str, method: str, models: ModelProvider
) -> np.ndarray:
    if not chunks or not lexical_tokens(query):
        return np.zeros(len(chunks))
    if method == "semantic":
        try:
            matrix = validate_embeddings([item["embedding"] for item in chunks], len(chunks))
        except (TypeError, ValueError) as exc:
            raise ModelOutputError() from exc
        vector = validate_embeddings(models.embed([query]), 1)[0]
        if matrix.shape[1] != len(vector):
            raise ModelOutputError()
        return np.clip(matrix @ vector, -1, 1)
    if method != "tfidf":
        raise ValueError(f"Método de pontuação individual desconhecido: {method}")
    vectorizer = TfidfVectorizer(
        tokenizer=lexical_tokens,
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    texts = [item["text"] for item in chunks]
    analyzer = vectorizer.build_analyzer()
    # Termos ausentes também entram no vetor da consulta. Descartá-los faria uma
    # pergunta específica parecer idêntica a uma única palavra genérica conhecida.
    vocabulary = sorted({term for text in [*texts, query] for term in analyzer(text)})
    if not vocabulary:
        return np.zeros(len(chunks))
    vectorizer.set_params(vocabulary=vocabulary)
    matrix = vectorizer.fit_transform(texts)
    return (matrix @ vectorizer.transform([query]).T).toarray().ravel()


def passage_identity(chunk: dict) -> tuple[str, str]:
    return (folded(chunk.get("context_text", "")), folded(chunk["text"]).strip())


def retrieve_candidates(chunks: list[dict], query: str, method: str, models, policy: dict):
    scores = score_chunks(chunks, query, method, models)
    candidates, seen = [], set()
    for index in np.argsort(-scores, kind="stable"):
        score = float(scores[index])
        if score <= 0 or score < policy[method]["min_score"]:
            break
        chunk = chunks[int(index)]
        identity = passage_identity(chunk)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append({**chunk, "score": score})
        if len(candidates) == CANDIDATE_LIMIT:
            break
    return candidates


def hybrid_candidates(chunks: list[dict], query: str, models, policy: dict) -> list[dict]:
    """RRF com pesos iguais: cada lista contribui 1/(constante + posição).

    A união conserva paráfrases sem palavras em comum. A fusão mantém o texto,
    os intervalos e as caixas de uma passagem; nunca agrupa destaques diferentes.
    """
    fused, origin_heads = {}, set()
    constant = policy["hybrid"]["rank_constant"]
    for method in ("semantic", "tfidf"):
        candidates = retrieve_candidates(chunks, query, method, models, policy)
        for position, chunk in enumerate(candidates, 1):
            identity = passage_identity(chunk)
            if position <= policy["hybrid"]["origin_head_size"]:
                origin_heads.add(identity)
            if identity not in fused:
                fused[identity] = {
                    **chunk,
                    "score": 0.0,
                    "semantic_score": 0.0,
                    "tfidf_score": 0.0,
                }
            fused[identity]["score"] += 1 / (constant + position)
            fused[identity][f"{method}_score"] = chunk["score"]
    # RRF favorece concordância. Reservar os três primeiros de cada origem evita
    # perder uma paráfrase forte que só o NLP encontrou antes de verificá-la.
    ordered = sorted(fused.values(), key=lambda item: item["score"], reverse=True)
    chosen = [item for item in ordered if passage_identity(item) in origin_heads]
    remaining = CANDIDATE_LIMIT - len(chosen)
    chosen.extend(
        [item for item in ordered if passage_identity(item) not in origin_heads][:remaining]
    )
    return sorted(chosen, key=lambda item: item["score"], reverse=True)


def candidate_is_relevant(chunk, value, method, policy, query_tokens):
    selected = policy[method]
    semantic = chunk.get("semantic_score", 0) if method == "hybrid" else chunk["score"]
    anchored = bool(
        query_tokens
        & set(
            lexical_tokens(
                f"{chunk.get('context_text', '')} {chunk['text']} {chunk.get('source_text', '')}"
            )
        )
    )
    if method == "hybrid":
        # Concordar nas posições não torna um texto relevante. Candidatos sem
        # evidência semântica precisam passar pelo critério lexical ou ter logit positivo.
        verified = value >= selected["min_relevance"] and (
            semantic >= 0.4
            or value >= 0
            or chunk["tfidf_score"] > 0
            and value >= policy["tfidf"]["min_relevance"]
        )
    else:
        verified = value >= selected["min_relevance"] and (
            method != "semantic" or semantic >= 0.4 or value >= 0
        )
    if method in ("hybrid", "semantic") and not anchored and value < 0:
        verified = verified and semantic >= selected["min_unanchored_score"]
    # Mesma recuperação de paráfrases do NLP: o verificador também pode errar.
    strong_agreement = (
        method in ("semantic", "hybrid")
        and value >= selected["fallback_min_relevance"]
        and semantic >= 0.6
        and bool(query_tokens & set(lexical_tokens(chunk["text"])))
    )
    return verified or strong_agreement


def ranking_score(item, method, selected):
    if method == "semantic":
        return float(item["score"] + 0.02 * np.clip(item["relevance_score"], -4, 4))
    if method == "hybrid":
        # Um sinal positivo pode promover a frase que responde à consulta em vez
        # de um título genérico. O ajuste limitado conserva o sinal da fusão.
        return float(
            item["score"] + selected["relevance_bonus"] * np.clip(item["relevance_score"], 0, 4)
        )
    return item["score"]


def _filter_chunks(
    chunks: list[SearchChunk], excluded_terms: list[str], identifiers: list[re.Pattern]
) -> list[SearchChunk]:
    for excluded in excluded_terms:
        excluded_tokens = set(lexical_tokens(excluded))
        excluded_identifiers = identifier_patterns(excluded)
        if excluded_tokens:
            chunks = [
                chunk
                for chunk in chunks
                if not excluded_tokens.issubset(
                    lexical_tokens(f"{chunk.get('context_text', '')} {chunk['text']}")
                )
                and not (excluded_identifiers and matches_identifiers(chunk, excluded_identifiers))
            ]
    if identifiers:
        chunks = [chunk for chunk in chunks if matches_identifiers(chunk, identifiers)]
    return chunks


def _verify_candidates(
    candidates: list[SearchChunk],
    query: str,
    method: str,
    models: ModelProvider,
    policy: dict,
    query_tokens: set[str],
) -> list[SearchChunk]:
    relevance = validate_relevance(
        models.rerank(
            query,
            [
                f"{chunk.get('context_text', '')} — {chunk['text']}".strip(" —")
                for chunk in candidates
            ],
        ),
        len(candidates),
    )
    accepted = [
        {**chunk, "relevance_score": float(value)}
        for chunk, value in zip(candidates, relevance, strict=True)
        if candidate_is_relevant(chunk, float(value), method, policy, query_tokens)
    ]
    return accepted


def _filter_hybrid_neighbors(accepted: list[SearchChunk], policy: dict) -> list[SearchChunk]:
    if accepted:
        semantic_floor = (
            max(item["semantic_score"] for item in accepted) * policy["semantic"]["relative_ratio"]
        )
        lexical_floor = (
            max(item["tfidf_score"] for item in accepted) * policy["tfidf"]["relative_ratio"]
        )
        # RRF aproxima pontuações de vizinhos distantes. Os cortes de cada origem
        # evitam ampliar a lista com um tema apenas próximo do melhor resultado.
        accepted = [
            item
            for item in accepted
            if item["relevance_score"] >= 0
            or item["semantic_score"] > 0
            and item["semantic_score"] >= semantic_floor
            or (
                item["tfidf_score"] > 0
                and item["tfidf_score"] >= lexical_floor
                and item["relevance_score"] >= policy["tfidf"]["min_relevance"]
            )
        ]
    return accepted


def _finish_ranking(
    accepted: list[SearchChunk], method: str, selected: dict, top_k: int
) -> list[dict]:
    # NLP combina cosseno com um ajuste limitado da avaliação conjunta. TF-IDF
    # mantém a ordem lexical; o verificador rejeita correspondências fora do assunto.
    accepted.sort(
        key=lambda item: (
            ranking_score(item, method, selected),
            item["score"],
        ),
        reverse=True,
    )
    if accepted:
        floor = accepted[0]["score"] * selected["relative_ratio"]
        accepted = [
            item
            for item in accepted
            if item["score"] >= floor
            or method in ("semantic", "hybrid")
            and item["relevance_score"] >= 0
        ]
    if method == "hybrid":
        accepted = [
            {**item, "rrf_score": item["score"], "score": ranking_score(item, method, selected)}
            for item in accepted
        ]
    return [
        {key: value for key, value in chunk.items() if key not in {"embedding", "source_text"}}
        for chunk in accepted[:top_k]
    ]


def rank_chunks(
    chunks: list[SearchChunk],
    query: str,
    method: str,
    models: ModelProvider,
    top_k: int,
    *,
    policy: dict | None = None,
    interpretation: QueryInterpretation | None = None,
) -> list[dict]:
    interpretation = interpretation or interpret_query(chunks, query)
    query = interpretation.query
    query_tokens = set(lexical_tokens(query))
    if not chunks or not query_tokens:
        return []
    policy = policy or search_policy()
    identifiers = identifier_patterns(query)
    chunks = _filter_chunks(chunks, interpretation.excluded_terms, identifiers)
    if identifiers and not chunks:
        return []
    selected = policy[method]
    candidates = (
        hybrid_candidates(chunks, query, models, policy)
        if method == "hybrid"
        else retrieve_candidates(chunks, query, method, models, policy)
    )
    if not candidates:
        return []
    accepted = _verify_candidates(candidates, query, method, models, policy, query_tokens)
    if method == "hybrid":
        accepted = _filter_hybrid_neighbors(accepted, policy)
    return _finish_ranking(accepted, method, selected, top_k)
