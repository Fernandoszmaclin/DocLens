"""Prepara modelos nas revisões fixadas e verifica os hashes autorizados do OCR."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from doclens.config import MODEL_NAME, RERANKER_NAME, ROOT, Settings
from doclens.errors import ModelUnavailable
from doclens.models import OCR_FILES, LocalModels, verify_ocr_weights


def prepare_ocr_weights(settings: Settings):
    """Baixa sem desserializar e verifica os hashes autorizados pelo manifesto."""
    expected = settings.ocr_weights_sha256 or {}
    if any(not re.fullmatch(r"[0-9a-f]{64}", expected.get(name, "")) for name in OCR_FILES):
        raise ModelUnavailable()
    from easyocr.config import detection_models, recognition_models
    from easyocr.utils import download_and_unzip

    directory = settings.model_dir / "ocr"
    directory.mkdir(parents=True, exist_ok=True)
    sources = [detection_models["craft"], recognition_models["gen2"]["latin_g2"]]
    for source in sources:
        filename = source["filename"]
        digest = expected[filename]
        target = directory / filename
        if target.is_file():
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == digest:
                    continue
        # Um download incorreto não substitui o cache nem autoriza um novo hash.
        with tempfile.TemporaryDirectory(prefix="download-", dir=directory) as temporary:
            download_and_unzip(source["url"], filename, temporary, False)
            downloaded = Path(temporary) / filename
            with downloaded.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ModelUnavailable()
            downloaded.replace(target)
    verify_ocr_weights(settings)


def main():
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    import truststore

    truststore.inject_into_ssl()
    from huggingface_hub import model_info

    config = ROOT / "config"
    config.mkdir(exist_ok=True)
    manifest_path = config / "models.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        revision = previous["revision"]
    else:
        revision = model_info(MODEL_NAME).sha
    reranker_revision = (
        previous.get("reranker_revision") if manifest_path.exists() else None
    ) or model_info(RERANKER_NAME).sha
    settings = Settings(model_revision=revision, reranker_revision=reranker_revision)
    # A preparação pode reparar um download parcial; a aplicação usa o snapshot local.
    models = LocalModels(settings, force_remote=True)
    print("Preparando EasyOCR (português/inglês, CPU)...", flush=True)
    prepare_ocr_weights(settings)
    _ = models.reader
    print("Preparando embeddings multilíngues (CPU)...", flush=True)
    vectors = models.embed(["Manutenção dos equipamentos de informática."])
    print("Preparando verificação de relevância multilíngue (CPU)...", flush=True)
    _ = models.rerank("Problemas nos computadores", ["Os notebooks estão com defeito."])
    manifest = {
        "model": MODEL_NAME,
        "revision": revision,
        "embedding_dimensions": int(vectors.shape[1]),
        "reranker": RERANKER_NAME,
        "reranker_revision": reranker_revision,
        "ocr_languages": ["pt", "en"],
        "ocr_weights_sha256": dict(settings.ocr_weights_sha256 or {}),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Modelos prontos. Revisão e hashes: config/models.json", flush=True)


if __name__ == "__main__":
    main()
