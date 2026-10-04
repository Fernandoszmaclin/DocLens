"""Interpretação conservadora de consultas, sem reescrever sintomas ou referências."""

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from spellchecker import SpellChecker

from doclens.contracts import SearchChunk


def folded(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )


@dataclass
class QueryInterpretation:
    query: str
    corrections: list[dict[str, str]] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def spelling_dictionary():
    # Apenas leitura após inicialização: consultas concorrentes não mudam o dicionário.
    spell = SpellChecker(language="pt", distance=1)
    known = frozenset(folded(word) for word in spell.word_frequency.keys())
    return spell, known


def _split_preference(query: str) -> tuple[str, list[str]]:
    focused, excluded = query, []
    # Somente uma preferência explícita seguida de um pedido positivo. Nunca
    # remover "não" de sintomas (não liga) ou de restrições (sem motorista).
    preference = re.match(
        r"^\s*n[aã]o\s+(?:quero|procuro|busco|preciso\s+de)\s+(.+?)"
        r"\s*(?::|;|,?\s+mas\s+|,?\s+e\s+sim\s+)\s*(.+)$",
        query,
        re.IGNORECASE,
    )
    if preference and not re.match(r"n[aã]o\b", preference[2], re.IGNORECASE):
        focused, excluded = preference[2].strip(), [preference[1].strip()]
    return focused, excluded


def _library_vocabulary(chunks: list[SearchChunk]) -> set[str]:
    words = {
        word
        for chunk in chunks
        for key in ("text", "context_text", "filename")
        for word in re.findall(r"[^\W\d_]+", chunk.get(key, ""))
    }
    # Contextos e nomes aparecem em muitas passagens: normalizar cada palavra uma vez.
    return {folded(word) for word in words}


def _correct_spelling(query: str, vocabulary: set[str]) -> tuple[str, list[dict[str, str]]]:
    spell, known = spelling_dictionary()
    corrections = []

    def correct(match):
        word = match[0]
        normalized = folded(word)
        # Nomes presentes na biblioteca, palavras válidas sem acento, códigos,
        # siglas e palavras curtas permanecem exatamente como foram escritos.
        if (
            not word.isalpha()
            or not 5 <= len(word) <= 20
            or word.isupper()
            or normalized in vocabulary
            or normalized in known
        ):
            return word
        candidates = {
            folded(candidate): candidate for candidate in (spell.candidates(word.casefold()) or [])
        }
        for candidate in spell.edit_distance_1(normalized) & vocabulary:
            candidates.setdefault(candidate, candidate)
        # Havendo ambiguidade, não escolher pela frequência: preservar a intenção.
        if len(candidates) != 1:
            return word
        replacement = next(iter(candidates.values()))
        if word[0].isupper():
            replacement = replacement.capitalize()
        corrections.append({"original": word, "replacement": replacement})
        return replacement

    corrected = re.sub(r"[^\W_]+(?:[-_/][^\W_]+)*", correct, query)
    return corrected, corrections


def interpret_query(chunks: list[SearchChunk], query: str) -> QueryInterpretation:
    focused, excluded = _split_preference(query)
    corrected, corrections = _correct_spelling(focused, _library_vocabulary(chunks))
    return QueryInterpretation(corrected, corrections, excluded)
