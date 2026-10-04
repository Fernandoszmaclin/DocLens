"""Antes/depois por documento, passagem e consultas sem resposta; somente fixtures."""

import argparse
import json
from datetime import UTC, datetime

from doclens.config import ROOT, Settings
from doclens.search import search_policy
from scripts.evaluation_support import (
    CachedModels,
    build_chunks,
    calibrate_method,
    load_benchmark,
    measure,
    summary,
)
from scripts.evaluation_support import passage_quality as passage_quality
from scripts.evaluation_support import words as words


def _evaluate_variants(source, references, documents, queries, models, clean, policy):
    results = {}
    for variant in ("reference", "clean", "degraded"):
        results[variant] = {}
        for revision in ("before", "after"):
            legacy = revision == "before"
            chunks = (
                clean
                if variant == "clean" and not legacy
                else build_chunks(source, references, variant, models, legacy)
            )
            results[variant][revision] = {}
            for method in ("semantic", "tfidf"):
                rows = measure(
                    chunks, queries, method, models, documents, references, legacy, policy
                )
                results[variant][revision][method] = {
                    "all": summary(rows),
                    "evaluation": summary([r for r in rows if r["split"] == "evaluation"]),
                    "queries": rows,
                }
                print(variant, revision, method, json.dumps(summary(rows)), flush=True)
    return results


def _make_report(results, settings, policy):
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": policy,
        "reranker_revision": settings.reranker_revision,
        "embedding_revision": settings.model_revision,
        "ocr_preprocess": settings.preprocess,
        "definition": "Passagem focada: pelo menos 50% das palavras na frase anotada, "
        "e cobertura de pelo menos metade de uma frase-alvo. "
        "Alinhamento por SequenceMatcher normalizado, tolerando erros OCR.",
        "limitations": [
            "Corpus sintético pequeno já inspecionado; diagnóstico/regressão, "
            "não avaliação independente.",
            "Precisão de palavras é um indicador aproximado; não avaliação humana cega.",
            "TF-IDF agora usa verificação de relevância por modelo; comparação entre pipelines, "
            "não TF-IDF puro vs NLP puro.",
            "Tempo da avaliação inclui cache de reranking; não é latência de produção.",
        ],
        "results": results,
    }


def _write_report(report):
    results = report["results"]
    (ROOT / "reports" / "search-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Melhoria da busca — comparação medida",
        "",
        "12 documentos fictícios, 20 consultas com resposta e 10 sem resposta. "
        "Mesmas consultas e OCR nas duas versões.",
        "",
        "Os limiares foram escolhidos nas sete consultas positivas e cinco negativas "
        "de development. "
        "O conjunto já foi inspecionado: estes números servem para diagnóstico/regressão.",
        "",
        "## OCR limpo — todas as consultas",
        "",
        "| Método / versão | Documento em top 3 | Passagem focada em top 1 | "
        "Passagem focada em top 3 | Rejeição sem resposta | Palavras no primeiro trecho |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for revision in ("before", "after"):
        for method in ("semantic", "tfidf"):
            stats = results["clean"][revision][method]["all"]
            lines.append(
                f"| {method} / {revision} | {stats['document_recall_at_3']:.0%} | "
                f"{stats['focused_at_1']:.0%} | {stats['focused_at_3']:.0%} | "
                f"{stats['negative_rejection_rate']:.0%} | {stats['mean_top1_words']:.1f} |"
            )
    lines += [
        "",
        report["definition"],
        "",
        "A métrica de foco exige uma passagem curta que contenha a informação anotada. "
        "Encontrar o documento correto, sozinho, não garante um destaque útil.",
        "",
        "## Limitações",
        "",
    ] + [f"- {item}" for item in report["limitations"]]
    lines += [
        "",
        "Dados, trechos e subdivisões reference/clean/degraded: "
        "[search-comparison.json](search-comparison.json).",
        "",
        "Reproduzir: `uv run python -m scripts.evaluate_search`. "
        "Recalibrar somente em development: acrescentar `--calibrate`.",
    ]
    (ROOT / "reports" / "search-comparison.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Seleciona limiar apenas nas consultas development, sobre OCR limpo.",
    )
    args = parser.parse_args()
    source, references, documents, queries = load_benchmark()
    settings = Settings()
    models = CachedModels(settings)
    clean = build_chunks(source, references, "clean", models)
    policy = search_policy()
    calibration = {}
    if args.calibrate:
        for method in ("semantic", "tfidf"):
            calibration[method] = calibrate_method(
                clean, queries, method, models, documents, references, policy
            )
            policy[method]["min_relevance"] = calibration[method]["selected"]["threshold"]
        (ROOT / "config" / "search.json").write_text(
            json.dumps(
                {
                    "selected_on": "development clean",
                    "methods": policy,
                    "candidate_limit": 30,
                    "calibration": calibration,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    results = _evaluate_variants(source, references, documents, queries, models, clean, policy)
    _write_report(_make_report(results, settings, policy))


if __name__ == "__main__":
    main()
