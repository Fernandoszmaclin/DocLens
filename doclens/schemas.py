"""Contratos de resposta publicados na documentação OpenAPI."""

from uuid import UUID

from pydantic import BaseModel


class Block(BaseModel):
    id: int
    text: str
    confidence: float
    box: list[tuple[float, float]]


class Page(BaseModel):
    number: int
    width: int
    height: int
    text: str
    blocks: list[Block]
    image_url: str


class DocumentSummary(BaseModel):
    id: UUID
    filename: str
    created_at: str
    page_count: int
    duration_seconds: float
    preprocess: bool


class Document(DocumentSummary):
    pages: list[Page]


class SearchHit(BaseModel):
    id: UUID
    document_id: UUID
    filename: str
    page: int
    text: str
    score: float
    boxes: list[list[tuple[float, float]]]


class SearchResponse(BaseModel):
    method: str
    query: str
    interpreted_query: str
    corrections: list[dict[str, str]]
    excluded_terms: list[str]
    results: list[SearchHit]
