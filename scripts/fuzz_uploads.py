"""Muta fixtures fictícias e verifica respostas e atomicidade dos uploads."""

import json
import random
import tempfile
from pathlib import Path

from doclens.api import create_app
from doclens.config import ROOT, Settings
from tests.support import FakeModels, image_bytes, pdf_bytes
from tests.support import LocalTestClient as TestClient


def main():
    seed = 20261003
    rng = random.Random(seed)
    cases = []
    for ext, original in (
        ("png", image_bytes()),
        ("jpg", image_bytes("JPEG")),
        ("pdf", pdf_bytes()),
    ):
        for index in range(40):
            changed = bytearray(original)
            if index < 20:
                changed = changed[: rng.randrange(len(changed))]
            else:
                for _ in range(rng.randrange(1, 12)):
                    position = rng.randrange(len(changed))
                    changed[position] ^= rng.randrange(1, 256)
            cases.append((f"mutated-{index}.{ext}", bytes(changed)))
    results, failures = {}, []
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=artifacts) as directory:
        settings = Settings(data_dir=Path(directory) / "data", preprocess=False, max_side=512)
        with TestClient(
            create_app(settings, FakeModels()), raise_server_exceptions=False
        ) as client:
            for name, content in cases:
                before = len(client.get("/documents").json())
                result = client.post("/documents", files={"file": (name, content)})
                after = len(client.get("/documents").json())
                results[result.status_code] = results.get(result.status_code, 0) + 1
                if result.status_code >= 500 or after != before + (result.status_code == 201):
                    (artifacts / name).write_bytes(content)
                    failures.append(
                        {"file": name, "status": result.status_code, "detail": result.text}
                    )
    report = {
        "seed": seed,
        "cases": len(cases),
        "status_counts": results,
        "failures": failures,
        "scope": "Bytes truncados ou alterados de fixtures fictícias; "
        "OCR simulado; banco temporário.",
    }
    (ROOT / "reports/upload-fuzz.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
