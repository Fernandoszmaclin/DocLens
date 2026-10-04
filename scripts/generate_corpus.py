"""Desenha 12 documentos próprios. PNG/PDF limpos e PNG degradados, semente fixa."""

import json
import platform
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from doclens.config import ROOT


def find_font() -> Path:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Instale uma fonte Arial ou DejaVu Sans para gerar os exemplos.")


def wrap(text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_document(doc: dict, font_path: Path) -> tuple[Image.Image, str]:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    body_font = ImageFont.truetype(str(font_path), 25)
    heading_font = ImageFont.truetype(str(font_path), 33)
    small_font = ImageFont.truetype(str(font_path), 21)
    reference = []

    def line(text: str, y: int, font, color="#202820"):
        draw.text((100, y), text, font=font, fill=color)
        reference.append(text)

    line("INSTITUTO HORIZONTE", 90, heading_font)
    line("DOCUMENTO FICTÍCIO PARA DEMONSTRAÇÃO", 142, small_font)
    draw.line((100, 195, 1140, 195), fill="#8d9b88", width=2)
    line(f"Referência: {doc['id'].upper()}", 229, small_font)
    line("Data: 03 de outubro de 2026", 267, small_font)
    y = 335
    for text in wrap(doc["title"], heading_font, 1040):
        line(text, y, heading_font)
        y += 46
    y += 42
    for paragraph in doc["paragraphs"]:
        for text in wrap(paragraph, body_font, 1040):
            line(text, y, body_font)
            y += 39
        y += 28
    line("Coordenação Administrativa", y + 42, body_font)
    line("Exemplo sintético. Sem dados pessoais reais.", 1610, small_font)
    return image, "\n".join(reference)


def degrade(image: Image.Image, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    array = np.array(image).astype(np.float32)
    array = array * 0.65 + 48
    array += rng.normal(0, 6, array.shape[:2])[..., None]
    array = cv2.GaussianBlur(np.clip(array, 0, 255).astype(np.uint8), (3, 3), 0.7)
    h, w = array.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), 1.7, 1)
    array = cv2.warpAffine(array, matrix, (w, h), borderValue=(214, 214, 214))
    return Image.fromarray(array)


def main():
    source = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    directory = ROOT / "data" / "fixtures"
    for variant in ("clean", "degraded", "pdf"):
        (directory / variant).mkdir(parents=True, exist_ok=True)
    font = find_font()
    references = {}
    for index, doc in enumerate(source["documents"]):
        image, reference = render_document(doc, font)
        references[doc["id"]] = reference
        image.save(directory / "clean" / f"{doc['id']}.png", optimize=True)
        image.save(directory / "pdf" / f"{doc['id']}.pdf", resolution=150)
        degrade(image, 2026 + index).save(
            directory / "degraded" / f"{doc['id']}.png", optimize=True
        )
    (directory / "references.json").write_text(
        json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "generation.json").write_text(
        json.dumps(
            {
                "seed": 2026,
                "font": font.name,
                "platform": platform.system(),
                "dimensions": [1240, 1754],
                "degradation": "contrast=0.65, noise=6, blur=0.7, rotation=1.7",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("12 documentos, 24 imagens e 12 PDFs gerados em data/fixtures.")


if __name__ == "__main__":
    main()
