"""Entrada validada → páginas RGB → pré-processamento opcional → blocos OCR."""

import io
import math
import threading
import warnings
from contextlib import closing
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from doclens.config import Settings
from doclens.errors import DocumentError

# PDFium exige serialização de todas as chamadas, inclusive entre serviços distintos.
PDF_LOCK = threading.Lock()


def load_pages(content: bytes, filename: str, settings: Settings) -> list[np.ndarray]:
    extension = Path(filename).suffix.lower()
    if not content:
        raise DocumentError("O arquivo está vazio.")
    if len(content) > settings.max_bytes:
        raise DocumentError("O arquivo excede o limite de 10 MB.", 413)
    if extension not in {".png", ".jpg", ".jpeg", ".pdf"}:
        raise DocumentError("Envie um arquivo PNG, JPEG ou PDF.", 415)

    if extension == ".pdf":
        if not content.lstrip().startswith(b"%PDF-"):
            raise DocumentError("O conteúdo do arquivo não é um PDF válido.")
        try:
            with PDF_LOCK, pdfium.PdfDocument(content) as document:
                if not 1 <= len(document) <= settings.max_pages:
                    raise DocumentError("O PDF deve ter entre uma e cinco páginas.")
                pages = []
                for index in range(len(document)):
                    with closing(document[index]) as page:
                        width, height = page.get_size()
                        if not (
                            math.isfinite(width)
                            and math.isfinite(height)
                            and width > 0
                            and height > 0
                        ):
                            raise DocumentError("O PDF contém uma página com dimensões inválidas.")
                        scale = min(200 / 72, settings.max_side / max(width, height))
                        with closing(page.render(scale=scale)) as bitmap:
                            pages.append(np.array(bitmap.to_pil().convert("RGB")))
                return pages
        except pdfium.PdfiumError as exc:
            raise DocumentError(
                "Não foi possível ler o PDF. Verifique se está corrompido ou protegido por senha."
            ) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=["PNG", "JPEG"]) as image:
                expected = "PNG" if extension == ".png" else "JPEG"
                if image.format != expected:
                    raise DocumentError("A extensão não corresponde ao conteúdo da imagem.")
                if image.width * image.height > settings.max_pixels:
                    raise DocumentError("A imagem excede o limite de 25 megapixels.", 413)
                if getattr(image, "n_frames", 1) > 1:
                    raise DocumentError("Imagens animadas não são aceitas. Envie um PNG estático.")
                image = ImageOps.exif_transpose(image)
                if "A" in image.getbands() or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    image = Image.alpha_composite(
                        Image.new("RGBA", rgba.size, "white"), rgba
                    ).convert("RGB")
                else:
                    image = image.convert("RGB")
                image.thumbnail((settings.max_side, settings.max_side))
                return [np.array(image)]
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DocumentError(
            "Não foi possível ler a imagem. Verifique se o arquivo é válido."
        ) from exc


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """Contraste local e deskew por linhas. A prévia usa ESTE espaço de coordenadas."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(enhanced, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=max(50, image.shape[1] // 8),
        maxLineGap=20,
    )
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if abs(angle) <= 10:
                angles.append(angle)
    angle = float(np.median(angles)) if angles else 0
    if abs(angle) >= 0.3:
        height, width = gray.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
        enhanced = cv2.warpAffine(
            enhanced,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)


def recognize(image: np.ndarray, reader) -> list[dict]:
    raw = reader.readtext(image, detail=1, paragraph=False, workers=0, batch_size=1)

    # Letras e caixas da mesma linha podem começar em alturas diferentes. Ordenar somente
    # por y inverteria fragmentos de uma linha. Primeiro agrupamos pelo centro vertical.
    def center(item):
        return float(np.mean([point[1] for point in item[0]]))

    def height(item):
        return max(point[1] for point in item[0]) - min(point[1] for point in item[0])

    rows = []
    for item in sorted(raw, key=center):
        if rows and abs(center(item) - np.mean([center(part) for part in rows[-1]])) <= (
            0.55 * max(height(item), np.median([height(part) for part in rows[-1]]))
        ):
            rows[-1].append(item)
        else:
            rows.append([item])
    raw = [item for row in rows for item in sorted(row, key=lambda x: min(p[0] for p in x[0]))]
    return [
        {
            "id": index,
            "text": text.strip(),
            "confidence": float(confidence),
            "box": [[float(x), float(y)] for x, y in box],
        }
        for index, (box, text, confidence) in enumerate(raw)
        if text.strip()
    ]
