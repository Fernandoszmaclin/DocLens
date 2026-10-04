"""Versão anterior congelada para avaliação antes/depois; não usada pela aplicação."""

import uuid

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


def make_chunks(blocks: list[dict], models) -> list[dict]:
    """Agrupa blocos contíguos por página; divide blocos maiores que o limite."""
    pieces = []
    for block in blocks:
        words = block["text"].split()
        current = []
        for word in words:
            candidate = " ".join([*current, word])
            if models.token_length(candidate) > models.token_budget:
                if current:
                    pieces.append((" ".join(current), block["id"]))
                    current = []
                # Palavras isoladas excessivamente longas não devem ser truncadas silenciosamente.
                remaining = word
                while models.token_length(remaining) > models.token_budget:
                    size = max(1, len(remaining) // 2)
                    while models.token_length(remaining[:size]) > models.token_budget:
                        size = max(1, size // 2)
                    pieces.append((remaining[:size], block["id"]))
                    remaining = remaining[size:]
                current.append(remaining)
            else:
                current.append(word)
        if current:
            pieces.append((" ".join(current), block["id"]))

    chunks, texts, ids = [], [], []
    for text, block_id in pieces:
        if texts and models.token_length(" ".join([*texts, text])) > models.token_budget:
            chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": " ".join(texts),
                    "block_ids": list(dict.fromkeys(ids)),
                }
            )
            texts, ids = [], []
        texts.append(text)
        ids.append(block_id)
    if texts:
        chunks.append(
            {
                "id": str(uuid.uuid4()),
                "text": " ".join(texts),
                "block_ids": list(dict.fromkeys(ids)),
            }
        )
    return chunks


def rank_chunks(chunks: list[dict], query: str, method: str, models, top_k: int) -> list[dict]:
    if not chunks:
        return []
    if method == "semantic":
        matrix = np.vstack([item["embedding"] for item in chunks])
        vector = models.embed([query])[0]
        # Ambos estão normalizados: produto escalar equivale à similaridade de cosseno.
        scores = np.clip(matrix @ vector, -1, 1)
    else:
        vectorizer = TfidfVectorizer(strip_accents="unicode", ngram_range=(1, 2))
        try:
            matrix = vectorizer.fit_transform([item["text"] for item in chunks])
            scores = (matrix @ vectorizer.transform([query]).T).toarray().ravel()
        except ValueError:  # Corpus sem palavras com dois ou mais caracteres.
            return []
    order = np.argsort(-scores, kind="stable")[:top_k]
    return [
        {
            **{key: value for key, value in chunks[int(index)].items() if key != "embedding"},
            "score": float(scores[index]),
        }
        for index in order
        if method == "semantic" or scores[index] > 0
    ]
