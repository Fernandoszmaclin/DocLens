"""Recursos limitados e bibliotecas privadas para a demonstração pública."""

import gc
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from doclens.config import MODEL_NAME, RERANKER_NAME, Settings
from doclens.errors import DocumentError, ModelUnavailable
from doclens.models import LocalModels
from doclens.service import DocumentService


class CloudModels(LocalModels):
    """Evita manter OCR e verificador carregados ao mesmo tempo."""

    @staticmethod
    def _configure_threads():
        import torch

        torch.set_num_threads(1)

    @property
    def reader(self):
        with self._lock:
            if self._reranker is not None:
                self._reranker = None
                gc.collect()
            return super().reader

    @property
    def encoder(self):
        with self._lock:
            if self._reader is not None:
                self._reader = None
                gc.collect()
            return super().encoder


class CloudRuntime:
    """Modelos compartilhados; somente uma operação pesada em execução."""

    def __init__(self, models=None):
        self.settings = Settings(max_side=1200)
        self.models = models or CloudModels(self.settings)
        self.gate = threading.BoundedSemaphore(1)
        self.prepared = models is not None

    def prepare(self):
        if self.prepared:
            return
        from huggingface_hub import snapshot_download

        from scripts.prepare_models import prepare_ocr_weights

        try:
            prepare_ocr_weights(self.settings)
            for name, directory, revision in (
                (MODEL_NAME, "nlp", self.settings.model_revision),
                (RERANKER_NAME, "reranker", self.settings.reranker_revision),
            ):
                if not revision:
                    raise ModelUnavailable()
                snapshot_download(
                    name,
                    revision=revision,
                    cache_dir=str(self.settings.model_dir / directory),
                    allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "*.bin"],
                )
            self.prepared = True
        except Exception as exc:
            raise ModelUnavailable() from exc

    def run(self, function, *args):
        if not self.gate.acquire(blocking=False):
            raise DocumentError(
                "A demonstração está processando outra tarefa. Aguarde e tente novamente.", 409
            )
        try:
            self.prepare()
            return function(*args)
        finally:
            gc.collect()
            self.gate.release()


class CloudSession:
    """Cada visitante recebe um banco e imagens em diretório temporário próprio."""

    def __init__(self, runtime: CloudRuntime):
        self.directory = TemporaryDirectory(prefix="doclens-session-")
        self.runtime = runtime
        self.settings = Settings(data_dir=Path(self.directory.name), max_side=1200)
        self.service = DocumentService(self.settings, runtime.models)

    def ingest(self, content: bytes, filename: str):
        if len(self.service.store.list_documents()) >= 10:
            raise DocumentError(
                "Limite de 10 documentos por sessão. Limpe a biblioteca para continuar."
            )
        return self.runtime.run(self.service.ingest, content, filename)

    def search(self, query: str, method: str, top_k: int):
        return self.runtime.run(self.service.search_response, query, method, top_k)

    def close(self):
        self.directory.cleanup()
