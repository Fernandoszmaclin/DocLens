"""OCR e busca original (baseline). Nova busca: scripts.evaluate_search."""

import argparse
import hashlib
import json
import platform
import re
import time
import unicodedata
from datetime import UTC, datetime
from importlib.metadata import version

from doclens.config import MODEL_NAME, ROOT, Settings
from doclens.models import LocalModels
from doclens.vision import load_pages, preprocess_image, recognize
from scripts.search_baseline import make_chunks, rank_chunks


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def summarize_ocr(rows: list[dict], split: str, variant: str, preprocess: bool) -> dict:
    subset = [
        row
        for row in rows
        if row["split"] == split and row["variant"] == variant and row["preprocess"] == preprocess
    ]
    return {
        "pages": len(subset),
        "cer": sum(row["edits"] for row in subset) / sum(row["characters"] for row in subset),
        "mean_seconds": sum(row["seconds"] for row in subset) / len(subset),
    }


def _collect_ocr(source, references, settings, models, refresh):
    fixtures = ROOT / "data" / "fixtures"
    cache = ROOT / "artifacts" / "evaluation_cache"
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    pipeline = (ROOT / "doclens" / "vision.py").read_bytes()
    pipeline += json.dumps(
        {
            "max_side": settings.max_side,
            "easyocr": version("easyocr"),
            "torch": version("torch"),
            "opencv": version("opencv-python-headless"),
        },
        sort_keys=True,
    ).encode()
    for doc in source["documents"]:
        for variant in ("clean", "degraded"):
            path = fixtures / variant / f"{doc['id']}.png"
            content = path.read_bytes()
            image = load_pages(content, path.name, settings)[0]
            fingerprint = hashlib.sha256(
                pipeline + content + references[doc["id"]].encode("utf-8")
            ).hexdigest()
            for processed in (False, True):
                cache_path = cache / f"{doc['id']}_{variant}_{int(processed)}.json"
                row = None
                if cache_path.exists() and not refresh:
                    row = json.loads(cache_path.read_text(encoding="utf-8"))
                if row is None or row.get("fingerprint") != fingerprint:
                    start = time.perf_counter()
                    candidate = preprocess_image(image) if processed else image
                    blocks = recognize(candidate, models.reader)
                    seconds = time.perf_counter() - start
                    prediction = normalized("\n".join(block["text"] for block in blocks))
                    truth = normalized(references[doc["id"]])
                    row = {
                        "document": doc["id"],
                        "fingerprint": fingerprint,
                        "split": doc["split"],
                        "variant": variant,
                        "preprocess": processed,
                        "seconds": seconds,
                        "edits": edit_distance(truth, prediction),
                        "characters": len(truth),
                        "blocks": blocks,
                        "prediction": prediction,
                    }
                    cache_path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
                rows.append(row)
                print(
                    f"OCR {doc['id']} / {variant} / preprocess={processed}: "
                    f"CER={row['edits'] / row['characters']:.4f}, {row['seconds']:.1f}s",
                    flush=True,
                )

    return rows


def _select_policy(rows, source):
    development = {
        str(value).lower(): sum(
            row["edits"]
            for row in rows
            if row["split"] == "development" and row["preprocess"] == value
        )
        / sum(
            row["characters"]
            for row in rows
            if row["split"] == "development" and row["preprocess"] == value
        )
        for value in (False, True)
    }
    selected = development["true"] < development["false"]
    policy = {
        "preprocess": selected,
        "selected_on": "development",
        "weighted_cer": development,
        "document_ids": [doc["id"] for doc in source["documents"] if doc["split"] == "development"],
    }
    config = ROOT / "config"
    config.mkdir(exist_ok=True)
    (config / "ocr.json").write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    print(f"Pré-processamento escolhido somente no desenvolvimento: {selected}", flush=True)

    return policy


def _evaluate_retrieval(rows, source, references, models, selected):
    retrieval = {}
    queries = []
    for item in source["queries"]:
        splits = {doc["split"] for doc in source["documents"] if doc["id"] in item["relevant"]}
        queries.append(
            {**item, "split": "evaluation" if splits == {"evaluation"} else "development"}
        )
    for variant in ("reference", "clean", "degraded"):
        chunks = []
        for doc in source["documents"]:
            if variant == "reference":
                blocks = [
                    {"id": i, "text": text}
                    for i, text in enumerate(references[doc["id"]].splitlines())
                ]
            else:
                blocks = next(
                    row["blocks"]
                    for row in rows
                    if row["document"] == doc["id"]
                    and row["variant"] == variant
                    and row["preprocess"] == selected
                )
            chunks.extend(
                [{**chunk, "document_id": doc["id"]} for chunk in make_chunks(blocks, models)]
            )
        vectors = models.embed([chunk["text"] for chunk in chunks])
        for chunk, embedding in zip(chunks, vectors, strict=True):
            chunk["embedding"] = embedding
        retrieval[variant] = {}
        for method in ("tfidf", "semantic"):
            per_query = []
            for item in queries:
                start = time.perf_counter()
                hits = rank_chunks(chunks, item["query"], method, models, 3)
                elapsed = time.perf_counter() - start
                retrieved = [hit["document_id"] for hit in hits]
                recall = len(set(retrieved) & set(item["relevant"])) / len(item["relevant"])
                per_query.append(
                    {
                        **item,
                        "retrieved_documents": retrieved,
                        "recall_at_3": recall,
                        "seconds": elapsed,
                    }
                )
            final = [item for item in per_query if item["split"] == "evaluation"]
            retrieval[variant][method] = {
                "recall_at_3_all": sum(item["recall_at_3"] for item in per_query) / len(per_query),
                "recall_at_3_evaluation": sum(item["recall_at_3"] for item in final) / len(final),
                "evaluation_queries": len(final),
                "total_queries": len(per_query),
                "mean_seconds": sum(item["seconds"] for item in per_query) / len(per_query),
                "queries": per_query,
            }
            print(
                f"Busca {variant} / {method}: Recall@3 (evaluation)="
                f"{retrieval[variant][method]['recall_at_3_evaluation']:.3f}",
                flush=True,
            )

    return retrieval


def _make_report(rows, retrieval, settings, policy):
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "processor": platform.processor(),
            "device": "cpu",
            "torch_threads": 4,
            "versions": {
                name: version(name)
                for name in ("easyocr", "torch", "sentence-transformers", "opencv-python-headless")
            },
        },
        "model": MODEL_NAME,
        "revision": settings.model_revision,
        "policy": policy,
        "cer_normalization": "Unicode NFC, casefold, whitespace collapse",
        "ocr": {
            split: {
                variant: {
                    str(value).lower(): summarize_ocr(rows, split, variant, value)
                    for value in (False, True)
                }
                for variant in ("clean", "degraded")
            }
            for split in ("development", "evaluation")
        },
        "retrieval": retrieval,
        "limitations": [
            "Corpus sintético pequeno; métricas não representam documentos reais.",
            "Recall medido por documento relevante entre os três primeiros trechos.",
            "Tempos não incluem download nem carregamento inicial dos modelos.",
            "Consultas anotadas manualmente pelo autor; não houve ajuste do modelo NLP.",
        ],
    }


def _write_report(report):
    selected = report["policy"]["preprocess"]
    retrieval = report["retrieval"]
    output = ROOT / "reports"
    output.mkdir(exist_ok=True)
    (output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = [
        "# Resultados medidos",
        "",
        "Conjunto: 12 documentos fictícios; 4 de desenvolvimento "
        "e 8 de avaliação. 20 consultas anotadas.",
        "",
        f"Pré-processamento escolhido em development: **{selected}**.",
        "",
        "## OCR — oito documentos de avaliação",
        "",
        "| Imagem | Sem tratamento: CER | Com tratamento: CER |",
        "| --- | ---: | ---: |",
    ]
    for variant in ("clean", "degraded"):
        stats = report["ocr"]["evaluation"][variant]
        markdown.append(f"| {variant} | {stats['false']['cer']:.2%} | {stats['true']['cer']:.2%} |")
    markdown += [
        "",
        "CER menor é melhor. Normalização: NFC, caixa baixa e espaços uniformes.",
        "",
        "## Busca — consultas de avaliação",
        "",
        "| Texto usado | TF-IDF: Recall@3 | Semântica: Recall@3 |",
        "| --- | ---: | ---: |",
    ]
    for variant, methods in retrieval.items():
        markdown.append(
            f"| {variant} | {methods['tfidf']['recall_at_3_evaluation']:.1%} | "
            f"{methods['semantic']['recall_at_3_evaluation']:.1%} |"
        )
    markdown += [
        "",
        "Cada consulta tem um documento relevante. Recall@3 indica se esse documento "
        "aparece entre os três primeiros trechos; o ranking pode repetir documentos.",
        "",
        "Comparar reference com clean/degraded ajuda a separar erros de NLP e OCR.",
        "",
        "## Limitações",
        "",
    ] + [f"- {item}" for item in report["limitations"]]
    markdown += [
        "",
        "Tempos individuais, consultas, revisão do modelo e versões: [metrics.json](metrics.json).",
        "",
        "Reprodução: `uv run python -m scripts.evaluate --refresh`.",
    ]
    (output / "results.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Ignora cache das inferências OCR.")
    args = parser.parse_args()
    settings = Settings()
    models = LocalModels(settings)
    _ = models.reader
    _ = models.encoder
    source = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    fixtures = ROOT / "data" / "fixtures"
    references = json.loads((fixtures / "references.json").read_text(encoding="utf-8"))
    rows = _collect_ocr(source, references, settings, models, args.refresh)
    policy = _select_policy(rows, source)
    retrieval = _evaluate_retrieval(rows, source, references, models, policy["preprocess"])
    _write_report(_make_report(rows, retrieval, settings, policy))


if __name__ == "__main__":
    main()
