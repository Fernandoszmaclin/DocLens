"""Modelos carregados uma vez, sob demanda, e sempre em CPU."""

import hashlib
import os
import threading
from pathlib import Path

import numpy as np

from doclens.config import MODEL_NAME, RERANKER_NAME, Settings
from doclens.errors import ModelOutputError, ModelUnavailable

OCR_FILES = ("craft_mlt_25k.pth", "latin_g2.pth")


def verify_ocr_weights(settings: Settings) -> None:
    """Verifica os pesos autorizados antes de EasyOCR desserializar qualquer arquivo."""
    expected = settings.ocr_weights_sha256 or {}
    for filename in OCR_FILES:
        digest = expected.get(filename, "")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ModelUnavailable()
        try:
            with (settings.model_dir / "ocr" / filename).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ModelUnavailable()
        except OSError as exc:
            raise ModelUnavailable() from exc


def validate_embeddings(vectors, rows: int) -> np.ndarray:
    try:
        result = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModelOutputError() from exc
    if (
        result.ndim != 2
        or result.shape[0] != rows
        or result.shape[1] == 0
        or not np.isfinite(result).all()
        or np.any(np.linalg.norm(result, axis=1) == 0)
    ):
        raise ModelOutputError()
    return result


def validate_relevance(values, rows: int) -> np.ndarray:
    try:
        result = np.asarray(values, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModelOutputError() from exc
    if result.shape != (rows,) or not np.isfinite(result).all():
        raise ModelOutputError()
    return result


class LocalModels:
    def __init__(self, settings: Settings, force_remote: bool = False):
        import truststore

        truststore.inject_into_ssl()
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        self.settings = settings
        self.force_remote = force_remote
        self._reader = None
        self._encoder = None
        self._reranker = None
        self._lock = threading.RLock()

    @staticmethod
    def _configure_threads():
        import torch

        torch.set_num_threads(min(4, os.cpu_count() or 1))

    def _model_source(self, name: str, directory: str, revision: str | None) -> str:
        if self.force_remote:
            return name
        snapshot: Path = (
            self.settings.model_dir
            / directory
            / f"models--{name.replace('/', '--')}"
            / "snapshots"
            / (revision or "missing")
        )
        if not revision or not snapshot.is_dir():
            raise ModelUnavailable()
        return str(snapshot)

    @property
    def reader(self):
        with self._lock:
            if self._reader is None:
                try:
                    verify_ocr_weights(self.settings)
                    import easyocr

                    self._configure_threads()
                    directory = self.settings.model_dir / "ocr"
                    directory.mkdir(parents=True, exist_ok=True)
                    self._reader = easyocr.Reader(
                        ["pt", "en"],
                        gpu=False,
                        model_storage_directory=str(directory),
                        user_network_directory=str(directory / "user_network"),
                        download_enabled=False,
                        verbose=False,
                    )
                except Exception as exc:
                    raise ModelUnavailable() from exc
            return self._reader

    @property
    def encoder(self):
        with self._lock:
            if self._encoder is None:
                try:
                    source = self._model_source(MODEL_NAME, "nlp", self.settings.model_revision)
                    from sentence_transformers import SentenceTransformer

                    self._configure_threads()
                    self._encoder = SentenceTransformer(
                        source,
                        device="cpu",
                        cache_folder=str(self.settings.model_dir / "nlp"),
                        revision=self.settings.model_revision,
                        local_files_only=not self.force_remote,
                        trust_remote_code=False,
                    )
                except Exception as exc:
                    raise ModelUnavailable() from exc
            return self._encoder

    def token_length(self, text: str) -> int:
        with self._lock:
            return len(
                self.encoder.tokenizer(
                    text, add_special_tokens=False, truncation=False, verbose=False
                )["input_ids"]
            )

    @property
    def token_budget(self) -> int:
        return self.encoder.max_seq_length - 2

    def embed(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            return self.encoder.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).astype(np.float32)

    @property
    def reranker(self):
        with self._lock:
            if self._reranker is None:
                try:
                    source = self._model_source(
                        RERANKER_NAME, "reranker", self.settings.reranker_revision
                    )
                    from sentence_transformers import CrossEncoder

                    self._configure_threads()
                    self._reranker = CrossEncoder(
                        source,
                        device="cpu",
                        max_length=512,
                        cache_folder=str(self.settings.model_dir / "reranker"),
                        revision=self.settings.reranker_revision,
                        local_files_only=not self.force_remote,
                        trust_remote_code=False,
                    )
                except Exception as exc:
                    raise ModelUnavailable() from exc
            return self._reranker

    def rerank(self, query: str, texts: list[str]) -> np.ndarray:
        import torch

        with self._lock:
            return np.asarray(
                self.reranker.predict(
                    [(query, text) for text in texts],
                    batch_size=16,
                    activation_fn=torch.nn.Identity(),
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            ).reshape(-1)
