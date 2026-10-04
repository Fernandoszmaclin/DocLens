"""SQLite guarda texto, geometria e vetores float32; imagens ficam em disco."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from doclens.contracts import OCRBlock, SearchChunk
from doclens.passages import passage_boxes


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "doclens.sqlite3"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, created_at TEXT NOT NULL,
                    page_count INTEGER NOT NULL, duration_seconds REAL NOT NULL,
                    preprocess INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pages (
                    document_id TEXT NOT NULL REFERENCES documents(id), number INTEGER NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, text TEXT NOT NULL,
                    blocks TEXT NOT NULL, PRIMARY KEY(document_id, number)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    page INTEGER NOT NULL, text TEXT NOT NULL, block_ids TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            if "spans" not in {
                row["name"] for row in connection.execute("PRAGMA table_info(chunks)")
            }:
                connection.execute("ALTER TABLE chunks ADD COLUMN spans TEXT NOT NULL DEFAULT '[]'")
            if "context_text" not in {
                row["name"] for row in connection.execute("PRAGMA table_info(chunks)")
            }:
                connection.execute(
                    "ALTER TABLE chunks ADD COLUMN context_text TEXT NOT NULL DEFAULT ''"
                )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, document: dict, pages: list[dict], chunks: list[dict]):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
                (
                    document["id"],
                    document["filename"],
                    document["created_at"],
                    len(pages),
                    document["duration_seconds"],
                    document["preprocess"],
                ),
            )
            for page in pages:
                connection.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        document["id"],
                        page["number"],
                        page["width"],
                        page["height"],
                        page["text"],
                        json.dumps(page["blocks"], ensure_ascii=False),
                    ),
                )
            for chunk in chunks:
                self._insert_chunk(connection, {**chunk, "document_id": document["id"]})

    @staticmethod
    def _insert_chunk(connection, chunk):
        connection.execute(
            "INSERT INTO chunks "
            "(id, document_id, page, text, block_ids, embedding, spans, context_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk["id"],
                chunk["document_id"],
                chunk["page"],
                chunk["text"],
                json.dumps(chunk["block_ids"]),
                chunk["embedding"].astype("<f4").tobytes(),
                json.dumps(chunk["spans"]),
                chunk.get("context_text", ""),
            ),
        )

    def index_key(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='index'").fetchone()
            return row["value"] if row else None

    def pages_for_index(self) -> list[dict]:
        with self.connect() as connection:
            return [
                {**dict(row), "blocks": json.loads(row["blocks"])}
                for row in connection.execute("SELECT * FROM pages ORDER BY document_id, number")
            ]

    def backup_index(self) -> Path:
        directory = self.directory / "backups"
        directory.mkdir(exist_ok=True)
        target = directory / f"index-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.sqlite3"
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        return target

    def replace_index(self, chunks: list[dict], key: str):
        # Tudo em uma transação: falha de inferência ou escrita não remove o índice anterior.
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks")
            for chunk in chunks:
                self._insert_chunk(connection, chunk)
            connection.execute("INSERT OR REPLACE INTO metadata VALUES ('index', ?)", (key,))

    def list_documents(self) -> list[dict]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM documents ORDER BY created_at DESC, id"
                )
            ]

    def document(self, document_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            if row is None:
                return None
            pages = []
            for page in connection.execute(
                "SELECT * FROM pages WHERE document_id=? ORDER BY number", (document_id,)
            ):
                item = dict(page)
                item["blocks"] = json.loads(item["blocks"])
                item["image_url"] = f"/documents/{document_id}/pages/{item['number']}/image"
                pages.append(item)
            return {**dict(row), "pages": pages}

    def page_count(self, document_id: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT page_count FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            return row["page_count"] if row is not None else None

    def chunks(self) -> list[SearchChunk]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT c.*, d.filename, p.blocks, p.text AS source_text FROM chunks c
                JOIN documents d ON d.id=c.document_id
                JOIN pages p ON p.document_id=c.document_id AND p.number=c.page
                ORDER BY d.created_at, c.page, c.id
            """)
            result = []
            # Apenas esta leitura reutiliza geometria. A próxima consulta vê novos dados.
            pages: dict[tuple[str, int], tuple[list[OCRBlock], dict[int, OCRBlock]]] = {}
            for row in rows:
                item = dict(row)
                ids = json.loads(item.pop("block_ids"))
                serialized_blocks = item.pop("blocks")
                page_key = (item["document_id"], item["page"])
                if page_key not in pages:
                    blocks = json.loads(serialized_blocks)
                    pages[page_key] = (blocks, {block["id"]: block for block in blocks})
                blocks, blocks_by_id = pages[page_key]
                spans = json.loads(item.pop("spans"))
                item["boxes"] = (
                    passage_boxes(blocks, spans, blocks_by_id=blocks_by_id)
                    if spans
                    else [
                        [point.copy() for point in block["box"]]
                        for block in blocks
                        if block["id"] in ids
                    ]
                )
                item["embedding"] = np.frombuffer(item["embedding"], dtype="<f4").copy()
                result.append(item)
            return result
