"""Corpus, métricas, cache e calibração compartilhados pelos comandos de avaliação."""

import hashlib
import json
import re
import time
from difflib import SequenceMatcher

import numpy as np

from doclens.config import ROOT, Settings
from doclens.models import LocalModels
from doclens.passages import make_chunks, passage_boxes, sentence_ranges
from doclens.query import interpret_query
from doclens.search import folded, rank_chunks
from scripts import search_baseline


def words(text):
    return re.findall(r"[^\W_]+", folded(text))


def passage_quality(hit, item, documents, references):
    if hit["document_id"] not in item.get("relevant", []):
        return 0.0, False
    document = documents[hit["document_id"]]
    targets = []
    for paragraph, sentence in item["targets"]:
        text = document["title"] if paragraph == -1 else document["paragraphs"][paragraph]
        a, b = sentence_ranges(text)[sentence]
        targets.append(words(text[a:b]))
    truth = words(references[document["id"]])
    labels, target_positions = set(), []
    for target in targets:
        for i in range(len(truth) - len(target) + 1):
            if truth[i : i + len(target)] == target:
                positions = set(range(i, i + len(target)))
                labels.update(positions)
                target_positions.append(positions)
                break
    predicted = words(hit["text"])
    matching = SequenceMatcher(None, truth, predicted, autojunk=False).get_matching_blocks()
    relevant = sum(
        sum(i in labels for i in range(match.a, match.a + match.size)) for match in matching
    )
    precision = relevant / max(1, len(predicted))
    # Cobertura impede que uma palavra isolada seja contada como resposta.
    matched = {i for match in matching for i in range(match.a, match.a + match.size)}
    covered = any(
        len(matched & positions) >= len(positions) * 0.5 for positions in target_positions
    )
    return precision, precision >= 0.5 and covered


class CachedModels:
    def __init__(self, settings):
        self.models = LocalModels(settings)
        self.revision = settings.reranker_revision
        self.directory = ROOT / "artifacts" / "search_cache"
        self.directory.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name):
        return getattr(self.models, name)

    def rerank(self, query, texts):
        key = hashlib.sha256(
            json.dumps([self.revision, query, texts], ensure_ascii=False).encode()
        ).hexdigest()
        path = self.directory / f"{key}.json"
        if path.exists():
            return np.array(json.loads(path.read_text(encoding="utf-8")), dtype=np.float32)
        scores = self.models.rerank(query, texts)
        path.write_text(json.dumps(scores.tolist()), encoding="utf-8")
        return scores


def build_chunks(source, references, variant, models, legacy=False):
    chunks = []
    builder = search_baseline.make_chunks if legacy else make_chunks
    for document in source["documents"]:
        if variant == "reference":
            if legacy:
                blocks = [
                    {"id": i, "text": text}
                    for i, text in enumerate(references[document["id"]].splitlines())
                ]
            else:
                lines = references[document["id"]].splitlines()
                texts = [*lines[:4], document["title"], *document["paragraphs"], *lines[-2:]]
                blocks = [
                    {"id": i, "text": text, "role": "title" if i == 4 else "body"}
                    for i, text in enumerate(texts)
                ]
        else:
            selected = int(Settings().preprocess)
            path = (
                ROOT
                / "artifacts"
                / "evaluation_cache"
                / f"{document['id']}_{variant}_{selected}.json"
            )
            if not path.exists():
                raise SystemExit("Execute python -m scripts.evaluate para gerar o cache de OCR.")
            blocks = json.loads(path.read_text(encoding="utf-8"))["blocks"]
        for chunk in builder(blocks, models):
            boxes = (
                passage_boxes(blocks, chunk["spans"])
                if not legacy
                else [b["box"] for b in blocks if b["id"] in chunk["block_ids"] and b.get("box")]
            )
            chunks.append(
                {
                    **chunk,
                    "document_id": document["id"],
                    "boxes": boxes,
                    "source_text": "\n".join(block["text"] for block in blocks),
                }
            )
    for chunk, embedding in zip(chunks, models.embed([c["text"] for c in chunks]), strict=True):
        chunk["embedding"] = embedding
    return chunks


def measure(chunks, queries, method, models, documents, references, legacy=False, policy=None):
    rows = []
    for item in queries:
        start = time.perf_counter()
        interpretation = None if legacy else interpret_query(chunks, item["query"])
        hits = (
            search_baseline.rank_chunks(chunks, item["query"], method, models, 3)
            if legacy
            else rank_chunks(
                chunks,
                item["query"],
                method,
                models,
                3,
                policy=policy,
                interpretation=interpretation,
            )
        )
        elapsed = time.perf_counter() - start
        qualities = [passage_quality(hit, item, documents, references) for hit in hits]
        relevant = set(item.get("relevant", []))
        rows.append(
            {
                **item,
                "interpreted_query": interpretation.query if interpretation else item["query"],
                "corrections": interpretation.corrections if interpretation else [],
                "excluded_terms": interpretation.excluded_terms if interpretation else [],
                "document_recall_at_3": bool(relevant & {h["document_id"] for h in hits}),
                "focused_at_1": bool(qualities and qualities[0][1]),
                "focused_at_3": any(q[1] for q in qualities),
                "top1_precision": qualities[0][0] if qualities else 0,
                "rejected": not hits,
                "seconds": elapsed,
                "hits": [
                    {
                        "document": h["document_id"],
                        "text": h["text"],
                        "score": h["score"],
                        **{
                            name: h[name]
                            for name in (
                                "semantic_score",
                                "tfidf_score",
                                "rrf_score",
                                "relevance_score",
                            )
                            if name in h
                        },
                        "boxes": len(h["boxes"]),
                        "precision": q[0],
                        "focused": q[1],
                    }
                    for h, q in zip(hits, qualities, strict=True)
                ],
            }
        )
    return rows


def summary(rows):
    positives = [r for r in rows if r.get("relevant")]
    negatives = [r for r in rows if not r.get("relevant")]
    returned = [r for r in positives if r["hits"]]
    hits = [hit for row in positives for hit in row["hits"]]
    return {
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "document_recall_at_3": sum(r["document_recall_at_3"] for r in positives) / len(positives),
        "focused_at_1": sum(r["focused_at_1"] for r in positives) / len(positives),
        "focused_at_3": sum(r["focused_at_3"] for r in positives) / len(positives),
        "focused_result_rate": sum(hit["focused"] for hit in hits) / max(1, len(hits)),
        "mean_results_per_positive_query": len(hits) / len(positives),
        "top1_precision_when_returned": sum(r["top1_precision"] for r in returned)
        / max(1, len(returned)),
        "answer_rate": len(returned) / len(positives),
        "negative_rejection_rate": sum(r["rejected"] for r in negatives) / max(1, len(negatives)),
        "mean_top1_words": sum(len(words(r["hits"][0]["text"])) for r in returned)
        / max(1, len(returned)),
        "mean_top1_boxes": sum(r["hits"][0]["boxes"] for r in returned) / max(1, len(returned)),
        "mean_seconds": sum(r["seconds"] for r in rows) / len(rows),
    }


def load_corpus():
    source = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    references = json.loads(
        (ROOT / "data" / "fixtures" / "references.json").read_text(encoding="utf-8")
    )
    documents = {document["id"]: document for document in source["documents"]}
    return source, references, documents


def load_benchmark():
    source, references, documents = load_corpus()
    labels = json.loads((ROOT / "data" / "search_benchmark.json").read_text(encoding="utf-8"))
    queries = [
        {**item, "targets": target, "split": documents[item["relevant"][0]]["split"]}
        for item, target in zip(source["queries"], labels["positive_targets"], strict=True)
    ] + labels["negative_queries"]
    return source, references, documents, queries


def calibrate_method(chunks, queries, method, models, documents, references, policy):
    development = [query for query in queries if query["split"] == "development"]
    scores = []
    for threshold in np.arange(-6, 0.1, 0.25):
        candidate = {name: dict(values) for name, values in policy.items()}
        candidate[method]["min_relevance"] = float(threshold)
        rows = measure(chunks, development, method, models, documents, references, policy=candidate)
        tp = sum(row["focused_at_1"] for row in rows)
        fp = sum(bool(row["hits"]) and not row["focused_at_1"] for row in rows)
        fn = sum(bool(row.get("relevant")) and not row["focused_at_1"] for row in rows)
        scores.append(
            {
                "threshold": float(threshold),
                "f1": 2 * tp / max(1, 2 * tp + fp + fn),
                "tp": tp,
                "fp": fp,
                "fn": fn,
            }
        )
    best = max(scores, key=lambda row: (row["f1"], -row["fp"], row["threshold"]))
    return {"selected": best, "grid": scores}
