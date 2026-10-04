# Melhoria da busca: comparação medida

Foram usados 12 documentos fictícios, 20 consultas com resposta e 10 sem resposta. As duas versões receberam as mesmas consultas e imagens de OCR.

Os limiares foram escolhidos nas sete consultas positivas e cinco negativas de development. O conjunto já foi inspecionado: estes números servem para diagnóstico/regressão.

## OCR limpo: todas as consultas

| Método / versão | Documento em top 3 | Passagem focada em top 1 | Passagem focada em top 3 | Rejeição sem resposta | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic / before | 85% | 0% | 0% | 0% | 71.8 |
| tfidf / before | 95% | 0% | 5% | 0% | 71.5 |
| semantic / after | 100% | 95% | 100% | 90% | 12.4 |
| tfidf / after | 85% | 75% | 80% | 100% | 13.3 |

Uma passagem é considerada focada quando contém pelo menos 50% das palavras da frase anotada e cobre pelo menos metade de uma frase-alvo. O alinhamento usa SequenceMatcher normalizado e tolera erros de OCR.

A métrica de foco exige uma passagem curta que contenha a informação anotada. Encontrar o documento correto, sozinho, não garante um destaque útil.

## Limitações

- Corpus sintético pequeno já inspecionado; diagnóstico/regressão, não avaliação independente.
- Precisão de palavras é um indicador aproximado; não avaliação humana cega.
- TF-IDF agora usa verificação de relevância por modelo; comparação entre pipelines, não TF-IDF puro vs NLP puro.
- Tempo da avaliação inclui cache de reranking; não é latência de produção.

Dados, trechos e subdivisões reference/clean/degraded: [search-comparison.json](search-comparison.json).

Reproduzir: `uv run python -m scripts.evaluate_search`. Recalibrar somente em development: acrescentar `--calibrate`.
