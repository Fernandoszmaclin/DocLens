"""Atualiza passagens/vetores a partir do OCR salvo; preserva documentos e imagens."""

import time

from doclens.config import Settings
from doclens.models import LocalModels
from doclens.service import DocumentService


def main():
    settings = Settings()
    service = DocumentService(settings, LocalModels(settings))
    start = time.perf_counter()
    documents = service.store.list_documents()
    service.ensure_index()
    assert service.store.list_documents() == documents
    print(f"{len(documents)} documentos preservados; {len(service.store.chunks())} passagens.")
    print(f"Índice: {service.store.index_key()}. Tempo: {time.perf_counter() - start:.1f}s.")
    print("Backups de migração: .data/backups (ou diretório DOCLENS_DATA_DIR/backups).")


if __name__ == "__main__":
    main()
