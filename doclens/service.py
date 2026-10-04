"""Orquestração mantém OCR, NLP e persistência separados da camada HTTP."""

import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from doclens.config import MODEL_NAME, Settings
from doclens.contracts import ModelProvider, ProcessedPage, SearchChunk
from doclens.errors import DocumentError
from doclens.models import validate_embeddings
from doclens.passages import INDEX_VERSION
from doclens.query import interpret_query
from doclens.search import make_chunks, rank_chunks
from doclens.storage import Store
from doclens.vision import load_pages, preprocess_image, recognize


class DocumentService:
    def __init__(self, settings: Settings, models: ModelProvider):
        self.settings, self.models = settings, models
        self.store = Store(settings.data_dir)
        self.lock = threading.Lock()

    @property
    def index_key(self):
        return f"{INDEX_VERSION}:{MODEL_NAME}:{self.settings.model_revision}"

    def _attach_embeddings(self, chunks: list[SearchChunk]) -> None:
        vectors = validate_embeddings(
            self.models.embed([chunk["text"] for chunk in chunks]), len(chunks)
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk["embedding"] = vector

    def _process_page(
        self, original: np.ndarray, number: int, directory: Path
    ) -> tuple[ProcessedPage, list[SearchChunk]]:
        image = preprocess_image(original) if self.settings.preprocess else original
        blocks = recognize(image, self.models.reader)
        Image.fromarray(image).save(directory / f"{number}.png")
        page = {
            "number": number,
            "width": image.shape[1],
            "height": image.shape[0],
            "text": "\n".join(block["text"] for block in blocks),
            "blocks": blocks,
        }
        chunks = [{**chunk, "page": number} for chunk in make_chunks(blocks, self.models)]
        return page, chunks

    def _ensure_index_locked(self):
        if self.store.index_key() == self.index_key:
            return
        pages = self.store.pages_for_index()
        chunks = []
        for page in pages:
            chunks.extend(
                {**chunk, "document_id": page["document_id"], "page": page["number"]}
                for chunk in make_chunks(page["blocks"], self.models)
            )
        if chunks:
            self._attach_embeddings(chunks)
        if pages:
            self.store.backup_index()
        self.store.replace_index(chunks, self.index_key)

    def ensure_index(self):
        if self.store.index_key() == self.index_key:
            return
        if not self.lock.acquire(blocking=False):
            raise DocumentError("O índice está sendo atualizado. Aguarde e tente novamente.", 409)
        try:
            self._ensure_index_locked()
        finally:
            self.lock.release()

    def ingest(self, content: bytes, filename: str) -> dict:
        if not self.lock.acquire(blocking=False):
            raise DocumentError(
                "Outro documento está sendo processado. Aguarde e tente novamente.", 409
            )
        document_id = str(uuid.uuid4())
        directory = self.settings.data_dir / document_id
        start = time.perf_counter()
        try:
            images = load_pages(content, filename, self.settings)
            self._ensure_index_locked()
            directory.mkdir()
            pages, chunks = [], []
            for number, original in enumerate(images, 1):
                page, page_chunks = self._process_page(original, number, directory)
                pages.append(page)
                chunks.extend(page_chunks)
            if not chunks:
                raise DocumentError(
                    "Nenhum texto foi reconhecido. "
                    "Use um documento impresso, legível e bem iluminado."
                )
            self._attach_embeddings(chunks)
            # Normaliza nomes recebidos de clientes Windows ou Unix; nunca vira caminho em disco.
            safe_name = Path(filename.replace("\\", "/")).name[:200]
            document = {
                "id": document_id,
                "filename": safe_name,
                "created_at": datetime.now(UTC).isoformat(),
                "duration_seconds": time.perf_counter() - start,
                "preprocess": self.settings.preprocess,
            }
            self.store.save(document, pages, chunks)
            return self.store.document(document_id)
        except Exception:
            # O alvo calculado precisa continuar dentro do diretório de dados configurado.
            if directory.resolve().parent == self.settings.data_dir.resolve():
                shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            self.lock.release()

    def search(self, query: str, method: str, top_k: int) -> list[dict]:
        return self.search_response(query, method, top_k)["results"]

    def search_response(self, query: str, method: str, top_k: int) -> dict:
        self.ensure_index()
        chunks = self.store.chunks()
        response = {
            "query": query,
            "method": method,
            "interpreted_query": query,
            "corrections": [],
            "excluded_terms": [],
            "results": [],
        }
        if not chunks:
            return response
        if self.models.token_length(query) > self.models.token_budget:
            raise DocumentError("A consulta é muito longa para o modelo. Use uma frase mais curta.")
        interpretation = interpret_query(chunks, query)
        if self.models.token_length(interpretation.query) > self.models.token_budget:
            raise DocumentError("A consulta é muito longa para o modelo. Use uma frase mais curta.")
        return {
            **response,
            "interpreted_query": interpretation.query,
            "corrections": interpretation.corrections,
            "excluded_terms": interpretation.excluded_terms,
            "results": rank_chunks(
                chunks, query, method, self.models, top_k, interpretation=interpretation
            ),
        }
