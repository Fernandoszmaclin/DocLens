# Resultados medidos

O conjunto contém 12 documentos fictícios: 4 de desenvolvimento e 8 de avaliação, além de 20 consultas anotadas.

Pré-processamento escolhido durante o desenvolvimento: **sim**.

## OCR: oito documentos de avaliação

| Imagem | Sem tratamento: CER | Com tratamento: CER |
| --- | ---: | ---: |
| clean | 1.81% | 1.76% |
| degraded | 11.11% | 1.20% |

CER menor é melhor. Normalização: NFC, caixa baixa e espaços uniformes.

## Busca: consultas de avaliação

| Texto usado | TF-IDF: Recall@3 | Semântica: Recall@3 |
| --- | ---: | ---: |
| reference | 100.0% | 92.3% |
| clean | 100.0% | 84.6% |
| degraded | 100.0% | 84.6% |

Cada consulta tem um documento relevante. Recall@3 indica se esse documento aparece entre os três primeiros trechos; o ranking pode repetir documentos.

A comparação entre `reference`, `clean` e `degraded` ajuda a separar erros de NLP e de OCR.

## Limitações

- Corpus sintético pequeno; métricas não representam documentos reais.
- Recall medido por documento relevante entre os três primeiros trechos.
- Tempos não incluem download nem carregamento inicial dos modelos.
- Consultas anotadas manualmente pelo autor; não houve ajuste do modelo NLP.

Tempos individuais, consultas, revisão do modelo e versões: [metrics.json](metrics.json).

Reprodução: `uv run python -m scripts.evaluate --refresh`.
