"""Configuração explícita; os modelos e uploads não entram no Git."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def selected_preprocessing() -> bool:
    policy = ROOT / "config" / "ocr.json"
    return (
        json.loads(policy.read_text(encoding="utf-8"))["preprocess"] if policy.exists() else False
    )


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DOCLENS_DATA_DIR", ROOT / ".data"))
    )
    model_dir: Path = field(default_factory=lambda: ROOT / ".cache" / "models")
    preprocess: bool = field(default_factory=selected_preprocessing)
    max_bytes: int = 10 * 1024 * 1024
    max_pages: int = 5
    max_pixels: int = 25_000_000
    max_side: int = 2000
    model_revision: str | None = None
    reranker_revision: str | None = None
    ocr_weights_sha256: dict[str, str] | None = None

    def __post_init__(self):
        manifest = ROOT / "config" / "models.json"
        if (
            self.model_revision is None
            or self.reranker_revision is None
            or self.ocr_weights_sha256 is None
        ) and manifest.exists():
            values = json.loads(manifest.read_text(encoding="utf-8"))
            if self.model_revision is None:
                self.model_revision = values["revision"]
            if self.reranker_revision is None:
                self.reranker_revision = values.get("reranker_revision")
            if self.ocr_weights_sha256 is None:
                self.ocr_weights_sha256 = values.get("ocr_weights_sha256", {})
