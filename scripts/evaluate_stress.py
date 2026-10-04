"""Diagnóstico de consultas adicionais; erros remanescentes são publicados integralmente."""

import json
from datetime import UTC, datetime

from doclens.config import ROOT, Settings
from doclens.search import rank_chunks, search_policy
from scripts.evaluation_support import CachedModels, build_chunks, load_corpus, measure, summary


def _evaluate_cases(chunks, cases, models, documents, references):
    results = {}
    for method in ("hybrid", "semantic", "tfidf"):
        rows = measure(
            chunks,
            [item for item in cases["queries"] if item["kind"] != "identifier"],
            method,
            models,
            documents,
            references,
        )
        identifiers = []
        for item in cases["queries"]:
            if item["kind"] != "identifier":
                continue
            hits = rank_chunks(chunks, item["query"], method, models, 3)
            relevant = set(item["relevant"])
            passed = (
                bool(hits) and all(hit["document_id"] in relevant for hit in hits)
                if relevant
                else not hits
            )
            identifiers.append(
                {
                    **item,
                    "passed": passed,
                    "hits": [{"document": hit["document_id"], "text": hit["text"]} for hit in hits],
                }
            )
        results[method] = {"summary": summary(rows), "queries": rows, "identifiers": identifiers}
        print(
            method,
            json.dumps(summary(rows)),
            "identifiers",
            sum(i["passed"] for i in identifiers),
            flush=True,
        )
        for row in rows:
            if (row["relevant"] and not row["focused_at_1"]) or (
                not row["relevant"] and not row["rejected"]
            ):
                print(
                    "CASE",
                    row["query"],
                    [(h["document"], h["text"]) for h in row["hits"]],
                    flush=True,
                )
    return results


def _write_report(results, cases):
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "description": cases["description"],
        "policy": search_policy(),
        "scope": "OCR limpo, modelos reais locais; tempos incluem cache.",
        "results": results,
    }
    (ROOT / "reports/search-stress.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    source, references, documents = load_corpus()
    cases = json.loads((ROOT / "data/search-stress.json").read_text(encoding="utf-8"))
    models = CachedModels(Settings())
    chunks = build_chunks(source, references, "clean", models)
    results = _evaluate_cases(chunks, cases, models, documents, references)
    _write_report(results, cases)


if __name__ == "__main__":
    main()
