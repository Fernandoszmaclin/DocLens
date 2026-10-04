"""Nenhum teste de integridade baixa modelos ou desserializa pesos adulterados."""

import hashlib
import sys
import types
from pathlib import Path

import pytest

from doclens import vision
from doclens.config import MODEL_NAME, RERANKER_NAME
from doclens.errors import DocumentError, ModelUnavailable
from doclens.models import OCR_FILES, LocalModels
from scripts.prepare_models import prepare_ocr_weights
from tests.support import image_bytes


def authorized_ocr(settings):
    directory = settings.model_dir / "ocr"
    directory.mkdir(parents=True)
    content = b"authorized synthetic weights"
    digest = hashlib.sha256(content).hexdigest()
    settings.ocr_weights_sha256 = dict.fromkeys(OCR_FILES, digest)
    for filename in OCR_FILES:
        (directory / filename).write_bytes(content)
    return content


@pytest.mark.parametrize("condition", ["tampered", "missing", "unauthorized"])
def test_untrusted_ocr_is_rejected_before_reader_construction(settings, monkeypatch, condition):
    authorized_ocr(settings)
    path = settings.model_dir / "ocr" / OCR_FILES[0]
    if condition == "tampered":
        path.write_bytes(b"untrusted payload")
    elif condition == "missing":
        path.unlink()
    else:
        settings.ocr_weights_sha256 = {}

    def forbidden(*args, **kwargs):
        raise AssertionError("Pesos não verificados chegaram ao Reader")

    monkeypatch.setitem(sys.modules, "easyocr", types.SimpleNamespace(Reader=forbidden))
    with pytest.raises(ModelUnavailable):
        _ = LocalModels(settings).reader


def test_verified_ocr_disables_downloads_and_loads_once(settings, monkeypatch):
    authorized_ocr(settings)
    calls = []

    def reader(*args, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "easyocr", types.SimpleNamespace(Reader=reader))
    monkeypatch.setattr(LocalModels, "_configure_threads", lambda self: None)
    models = LocalModels(settings)
    assert models.reader is models.reader
    assert len(calls) == 1 and calls[0]["download_enabled"] is False


@pytest.mark.parametrize(
    "property_name,name,directory,revision_name,constructor",
    [
        ("encoder", MODEL_NAME, "nlp", "model_revision", "SentenceTransformer"),
        ("reranker", RERANKER_NAME, "reranker", "reranker_revision", "CrossEncoder"),
    ],
)
def test_nlp_requires_pinned_local_snapshot(
    settings, monkeypatch, property_name, name, directory, revision_name, constructor
):
    calls = []
    instance = object()

    def construct(*args, **kwargs):
        calls.append((args, kwargs))
        return instance

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(**{constructor: construct})
    )
    monkeypatch.setattr(LocalModels, "_configure_threads", lambda self: None)
    models = LocalModels(settings)
    with pytest.raises(ModelUnavailable):
        getattr(models, property_name)
    assert not calls
    snapshot = (
        settings.model_dir
        / directory
        / f"models--{name.replace('/', '--')}"
        / "snapshots"
        / getattr(settings, revision_name)
    )
    snapshot.mkdir(parents=True)
    assert getattr(models, property_name) is instance
    assert calls[0][0] == (str(snapshot),)
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["trust_remote_code"] is False
    assert getattr(models, property_name) is instance and len(calls) == 1


@pytest.mark.parametrize("valid", [True, False])
def test_provisioning_verifies_download_before_replacing_cache(settings, monkeypatch, valid):
    allowed = authorized_ocr(settings)
    target = settings.model_dir / "ocr" / OCR_FILES[0]
    target.write_bytes(b"old corrupt file")
    before = dict(settings.ocr_weights_sha256)
    downloads = []

    def download(url, filename, directory, verbose):
        downloads.append(filename)
        (Path(directory) / filename).write_bytes(allowed if valid else b"untrusted download")

    descriptors = [
        {"filename": name, "url": f"https://example.invalid/{name}"} for name in OCR_FILES
    ]
    monkeypatch.setitem(
        sys.modules,
        "easyocr.config",
        types.SimpleNamespace(
            detection_models={"craft": descriptors[0]},
            recognition_models={"gen2": {"latin_g2": descriptors[1]}},
        ),
    )
    monkeypatch.setitem(
        sys.modules, "easyocr.utils", types.SimpleNamespace(download_and_unzip=download)
    )
    if valid:
        prepare_ocr_weights(settings)
        assert target.read_bytes() == allowed
    else:
        with pytest.raises(ModelUnavailable):
            prepare_ocr_weights(settings)
        assert target.read_bytes() == b"old corrupt file"
    assert downloads == [OCR_FILES[0]]
    assert settings.ocr_weights_sha256 == before
    assert not list(target.parent.glob("download-*"))


def test_provisioning_without_authorized_hashes_fails_before_downloading(settings):
    settings.ocr_weights_sha256 = {}
    with pytest.raises(ModelUnavailable):
        prepare_ocr_weights(settings)
    assert not settings.model_dir.exists()


def test_only_png_and_jpeg_decoders_are_enabled(settings, monkeypatch):
    calls = []
    original = vision.Image.open

    def open_image(*args, **kwargs):
        calls.append(kwargs["formats"])
        return original(*args, **kwargs)

    monkeypatch.setattr(vision.Image, "open", open_image)
    assert vision.load_pages(image_bytes(), "a.png", settings)[0].shape == (320, 240, 3)
    assert calls == [["PNG", "JPEG"]]


@pytest.mark.parametrize("dimensions", [(float("nan"), 72), (72, float("inf")), (-1, 72), (0, 72)])
def test_invalid_pdf_dimensions_are_rejected_before_rendering(settings, monkeypatch, dimensions):
    class Page:
        def get_size(self):
            return dimensions

        def render(self, **kwargs):
            raise AssertionError("Dimensões inválidas chegaram ao renderizador")

        def close(self):
            pass

    class PDF:
        def __init__(self, content):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return Page()

    monkeypatch.setattr(vision.pdfium, "PdfDocument", PDF)
    with pytest.raises(DocumentError, match="dimensões inválidas"):
        vision.load_pages(b"%PDF-test", "a.pdf", settings)
