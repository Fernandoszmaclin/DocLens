"""Indexa os 12 exemplos limpos usando OCR e NLP reais; evita duplicar nomes."""

import argparse
import json

from doclens.config import ROOT, Settings
from doclens.models import LocalModels
from doclens.service import DocumentService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    settings = Settings()
    service = DocumentService(settings, LocalModels(settings))
    existing = {item["filename"] for item in service.store.list_documents()}
    corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    for doc in corpus["documents"][: args.limit]:
        path = ROOT / "data" / "fixtures" / "clean" / f"{doc['id']}.png"
        if path.name in existing:
            print(f"Já indexado: {path.name}", flush=True)
            continue
        result = service.ingest(path.read_bytes(), path.name)
        print(f"Indexado: {path.name} ({result['duration_seconds']:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
