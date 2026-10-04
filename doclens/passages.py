"""Passagens curtas, com intervalos de caracteres rastreáveis até o OCR."""

import re
import uuid

import numpy as np

from doclens.contracts import Box, ModelProvider, OCRBlock, Passage, Span

INDEX_VERSION = "sentences-spans-context-v4"
ABBREVIATIONS = {"sr", "sra", "dr", "dra", "prof", "profa", "art", "av", "ex", "pag"}


def _paragraphs(blocks: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    heights = [
        max(p[1] for p in b["box"]) - min(p[1] for p in b["box"]) for b in blocks if b.get("box")
    ]
    height = float(np.median(heights)) if heights else 1
    bottom = None
    for block in blocks:
        if not block["text"].strip():
            bottom = None
            continue
        box = block.get("box")
        # Sem geometria (transcrições de referência), cada bloco já é um parágrafo.
        new_group = not groups or bottom is None or not box
        if box and bottom is not None:
            top = min(p[1] for p in box)
            new_group = top - bottom > height * 0.55
        if new_group:
            groups.append([])
        groups[-1].append(block)
        if box:
            bottom = max(max(p[1] for p in box), bottom if not new_group else 0)
        else:
            bottom = None
    return groups


def sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Pontuação final, preservando abreviações e números decimais."""
    start, ranges = 0, []
    for match in re.finditer(r"([.!?]+)[\"'”’»)\]]*(?=\s+\S|\s*$)", text):
        prefix = text[: match.start()]
        last_word = re.search(r"([\w]+)$", prefix)
        if match[1] == "." and last_word and last_word[1].casefold() in ABBREVIATIONS:
            continue
        ranges.append((start, match.end()))
        start = match.end()
    if start < len(text):
        ranges.append((start, len(text)))
    return [
        (a + len(text[a:b]) - len(text[a:b].lstrip()), b - len(text[a:b]) + len(text[a:b].rstrip()))
        for a, b in ranges
        if text[a:b].strip()
    ]


def _bounded_ranges(text: str, start: int, end: int, models):
    """Divide apenas frases excessivas; nunca trunca tokens silenciosamente."""
    current = start
    for word in re.finditer(r"\S+", text[start:end]):
        word_start, word_end = start + word.start(), start + word.end()
        if models.token_length(text[current:word_end]) > models.token_budget:
            if word_start > current:
                yield current, word_start - 1
            current = word_start
            while models.token_length(text[current:word_end]) > models.token_budget:
                size = max(1, (word_end - current) // 2)
                while models.token_length(text[current : current + size]) > models.token_budget:
                    size = max(1, size // 2)
                yield current, current + size
                current += size
    if current < end:
        yield current, end


def make_chunks(blocks: list[OCRBlock], models: ModelProvider) -> list[Passage]:
    chunks = []
    paragraphs = _paragraphs(blocks)
    title = next((b["text"] for b in blocks if b.get("role") == "title"), "")
    heights = [
        max(p[1] for p in b["box"]) - min(p[1] for p in b["box"]) for b in blocks if b.get("box")
    ]
    if heights and not title:
        typical = float(np.median(heights))
        headings = []
        for paragraph in paragraphs:
            text = " ".join(b["text"] for b in paragraph)
            if len(text.split()) > 20 or text.isupper():
                continue
            height = max(
                (
                    max(p[1] for p in b["box"]) - min(p[1] for p in b["box"])
                    for b in paragraph
                    if b.get("box")
                ),
                default=0,
            )
            if height >= typical * 1.12:
                headings.append((height, text))
        if headings:
            title = max(headings, key=lambda item: item[0])[1]
    for paragraph in paragraphs:
        text, origins = "", []
        for block in paragraph:
            if text:
                text += " "
            start = len(text)
            text += block["text"]
            origins.append((block, start, len(text)))
        for a, b in sentence_ranges(text):
            for start, end in _bounded_ranges(text, a, b, models):
                spans = [
                    {
                        "block_id": block["id"],
                        "start": max(start, left) - left,
                        "end": min(end, right) - left,
                    }
                    for block, left, right in origins
                    if start < right and end > left
                ]
                chunks.append(
                    {
                        "id": str(uuid.uuid4()),
                        "text": text[start:end].strip(),
                        "block_ids": list(dict.fromkeys(span["block_id"] for span in spans)),
                        "spans": spans,
                        "context_text": title,
                    }
                )
    return chunks


def passage_boxes(
    blocks: list[OCRBlock],
    spans: list[Span],
    *,
    blocks_by_id: dict[int, OCRBlock] | None = None,
) -> list[Box]:
    """Recorta caixas de linha por proporção de caracteres; posição é aproximada."""
    by_id = blocks_by_id if blocks_by_id is not None else {block["id"]: block for block in blocks}
    boxes = []
    for span in spans:
        block = by_id[span["block_id"]]
        if not block.get("box"):
            continue
        box = np.asarray(block["box"], dtype=float)
        length = max(1, len(block["text"]))
        left, right = span["start"] / length, span["end"] / length
        top = box[1] - box[0]
        bottom = box[2] - box[3]
        boxes.append(
            [
                (box[0] + left * top).tolist(),
                (box[0] + right * top).tolist(),
                (box[3] + right * bottom).tolist(),
                (box[3] + left * bottom).tolist(),
            ]
        )
    return boxes
