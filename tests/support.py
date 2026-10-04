"""Modelos e arquivos sintéticos, reutilizáveis sem pytest ou inicialização da API."""

import io

import numpy as np
from PIL import Image


class FakeReader:
    def readtext(self, image, **kwargs):
        if image.mean() > 254:
            return []
        return [
            (
                [[10, 10], [180, 10], [180, 30], [10, 30]],
                "Manutenção dos computadores da equipe",
                0.9,
            )
        ]


class FakeModels:
    reader = FakeReader()
    token_budget = 12

    def token_length(self, text):
        return len(text.split())

    def embed(self, texts):
        return np.tile(np.array([[1, 0, 0]], dtype=np.float32), (len(texts), 1))

    def rerank(self, query, texts):
        return np.full(len(texts), 8, dtype=np.float32)


def image_bytes(format="PNG", color="#dddddd"):
    buffer = io.BytesIO()
    Image.new("RGB", (240, 320), color).save(buffer, format=format)
    return buffer.getvalue()


def pdf_bytes(pages=1):
    buffer = io.BytesIO()
    images = [Image.new("RGB", (240, 320), "#dddddd") for _ in range(pages)]
    images[0].save(buffer, "PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def LocalTestClient(app, **kwargs):
    """Clientes de teste usam o mesmo endereço local exigido pela aplicação."""
    from fastapi.testclient import TestClient

    kwargs.setdefault("base_url", "http://127.0.0.1:8000")
    kwargs.setdefault("client", ("127.0.0.1", 50000))
    return TestClient(app, **kwargs)
