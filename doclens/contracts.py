"""Tipos internos: documentam os dicionários sem mudar seus dados em execução."""

from typing import Any, NotRequired, Protocol, TypedDict

import numpy as np

type Box = list[list[float]]


class OCRBlock(TypedDict):
    id: int
    text: str
    confidence: NotRequired[float]
    box: NotRequired[Box]
    role: NotRequired[str]


class Span(TypedDict):
    block_id: int
    start: int
    end: int


class Passage(TypedDict):
    id: str
    text: str
    block_ids: list[int]
    spans: list[Span]
    context_text: str


class SearchChunk(TypedDict, total=False):
    id: str
    text: str
    block_ids: list[int]
    spans: list[Span]
    context_text: str
    document_id: str
    page: int
    filename: str
    source_text: str
    embedding: np.ndarray
    boxes: list[Box]
    score: float
    semantic_score: float
    tfidf_score: float
    relevance_score: float
    rrf_score: float


class ProcessedPage(TypedDict):
    number: int
    width: int
    height: int
    text: str
    blocks: list[OCRBlock]


class OCRReader(Protocol):
    def readtext(self, image: np.ndarray, **kwargs: Any) -> list: ...


class ModelProvider(Protocol):
    @property
    def reader(self) -> OCRReader: ...

    @property
    def token_budget(self) -> int: ...

    def token_length(self, text: str) -> int: ...

    def embed(self, texts: list[str]) -> np.ndarray: ...

    def rerank(self, query: str, texts: list[str]) -> np.ndarray: ...
