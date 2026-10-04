"""Compara os três modos atuais nas mesmas fixtures, sem modificar a referência histórica."""

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

METHODS = ("hybrid", "semantic", "tfidf")


def _evaluate_variants(source, references, documents, queries, models, clean, policy):
    results = {}
    for variant in ("reference", "clean", "degraded"):
        chunks = clean if variant == "clean" else build_chunks(source, references, variant, models)
        results[variant] = {}
        for method in METHODS:
            rows = measure(chunks, queries, method, models, documents, references, policy=policy)
            results[variant][method] = {
                "all": summary(rows),
                "evaluation": summary([row for row in rows if row["split"] == "evaluation"]),
                "queries": rows,
            }
            print(variant, method, json.dumps(summary(rows)), flush=True)
    return results


def _make_report(results, settings, policy):
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": policy,
        "embedding_revision": settings.model_revision,
        "reranker_revision": settings.reranker_revision,
        "ocr_preprocess": settings.preprocess,
        "fusion": "RRF com pesos iguais, posições iniciadas em 1 e constante 60. "
        "Até 30 candidatos por método, até 30 passagens verificadas depois da fusão. "
        "A janela reserva os três primeiros candidatos de cada origem antes do corte. "
        "A ordem final inclui bônus de relevância 0,002 × clip(logit, 0, 4), "
        "limitado a 0,008. A pontuação publicada inclui esse ajuste.",
        "definition": "Foco: pelo menos 50% das palavras na frase anotada e cobertura "
        "de metade de uma frase-alvo, com alinhamento normalizado por SequenceMatcher.",
        "limitations": [
            "12 documentos fictícios e conjunto já inspecionado: diagnóstico/regressão, "
            "não teste independente em documentos novos.",
            "Limiar híbrido escolhido somente em 7 consultas positivas e 5 negativas "
            "de development sobre OCR limpo. evaluation: 13 positivas e 5 negativas.",
            "Foco é um indicador automático aproximado, não julgamento humano cego.",
            "Os três modos usam o mesmo verificador local de relevância.",
            "Tempos incluem cache de reranking; não representam latência de produção.",
            "Pontuação RRF não é similaridade de cosseno nem probabilidade de acerto.",
        ],
        "results": results,
    }


def _write_report(report):
    results = report["results"]
    (ROOT / "reports" / "hybrid-search.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Busca híbrida — comparação dos três modos",
        "",
        "12 documentos fictícios, 20 consultas com resposta e 10 sem resposta. "
        "Todos os modos usam as mesmas passagens, consultas e OCR.",
        "",
        report["fusion"],
    ]
    for variant in ("clean", "degraded", "reference"):
        for split in ("all", "evaluation"):
            lines += [
                "",
                f"## {variant} / {split}",
                "",
                "| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | "
                "Rejeição sem resposta | Foco entre os trechos retornados | "
                "Palavras no primeiro trecho |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
            for method in METHODS:
                stats = results[variant][method][split]
                lines.append(
                    f"| {method} | {stats['document_recall_at_3']:.1%} | "
                    f"{stats['focused_at_1']:.1%} | {stats['focused_at_3']:.1%} | "
                    f"{stats['negative_rejection_rate']:.1%} | "
                    f"{stats['focused_result_rate']:.1%} | {stats['mean_top1_words']:.1f} |"
                )
    lines += ["", report["definition"], "", "## Limitações", ""]
    lines += [f"- {limitation}" for limitation in report["limitations"]]
    lines += [
        "",
        "Consultas, trechos e métricas completas: [hybrid-search.json](hybrid-search.json).",
        "",
        "Reproduzir: `uv run python -m scripts.evaluate_hybrid`. "
        "Recalibrar apenas em development: acrescentar `--calibrate`.",
    ]
    (ROOT / "reports" / "hybrid-search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calibrate", action="store_true", help="Calibra somente o limiar híbrido em development."
    )
    args = parser.parse_args()
    source, references, documents, queries = load_benchmark()
    settings = Settings()
    models = CachedModels(settings)
    clean = build_chunks(source, references, "clean", models)
    policy = search_policy()
    if args.calibrate:
        calibration = calibrate_method(
            clean, queries, "hybrid", models, documents, references, policy
        )
        best = calibration["selected"]
        policy["hybrid"]["min_relevance"] = best["threshold"]
        path = ROOT / "config" / "search.json"
        config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        config["methods"] = policy
        config.setdefault("calibration", {})["hybrid"] = calibration
        config["hybrid_selected_on"] = "development clean"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("hybrid calibration", json.dumps(best), flush=True)
    results = _evaluate_variants(source, references, documents, queries, models, clean, policy)
    _write_report(_make_report(results, settings, policy))


if __name__ == "__main__":
    main()
