# Busca híbrida: comparação dos três modos

O conjunto contém 12 documentos fictícios, 20 consultas com resposta e 10 sem resposta. Todos os modos usam as mesmas passagens, consultas e OCR.

O RRF usa pesos iguais, posições numeradas a partir de 1 e constante 60. São recuperados até 30 candidatos por método e verificadas até 30 passagens após a fusão. A janela reserva os três primeiros candidatos de cada origem antes do corte. A ordem final inclui um bônus de relevância de 0,002 × clip(logit, 0, 4), limitado a 0,008. A pontuação publicada inclui esse ajuste.

## clean / all

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 100.0% | 100.0% | 100.0% | 86.7% | 14.2 |
| semantic | 100.0% | 95.0% | 100.0% | 100.0% | 82.8% | 12.4 |
| tfidf | 85.0% | 75.0% | 80.0% | 100.0% | 90.0% | 13.3 |

## clean / evaluation

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 100.0% | 100.0% | 100.0% | 89.5% | 16.7 |
| semantic | 100.0% | 92.3% | 100.0% | 100.0% | 88.9% | 13.9 |
| tfidf | 92.3% | 76.9% | 84.6% | 100.0% | 86.7% | 15.5 |

## degraded / all

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 95.0% | 95.0% | 100.0% | 83.3% | 16.1 |
| semantic | 100.0% | 90.0% | 95.0% | 100.0% | 76.7% | 14.1 |
| tfidf | 85.0% | 70.0% | 75.0% | 100.0% | 84.2% | 14.4 |

## degraded / evaluation

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 92.3% | 92.3% | 100.0% | 84.2% | 19.2 |
| semantic | 100.0% | 84.6% | 92.3% | 100.0% | 78.9% | 16.2 |
| tfidf | 92.3% | 69.2% | 76.9% | 100.0% | 78.6% | 16.8 |

## reference / all

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 95.0% | 100.0% | 100.0% | 79.4% | 13.7 |
| semantic | 100.0% | 90.0% | 100.0% | 100.0% | 75.8% | 12.1 |
| tfidf | 80.0% | 70.0% | 75.0% | 100.0% | 90.0% | 12.9 |

## reference / evaluation

| Método | Documento em top 3 | Foco em top 1 | Foco em top 3 | Rejeição sem resposta | Foco entre os trechos retornados | Palavras no primeiro trecho |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 100.0% | 92.3% | 100.0% | 100.0% | 78.3% | 15.5 |
| semantic | 100.0% | 84.6% | 100.0% | 100.0% | 77.3% | 13.1 |
| tfidf | 84.6% | 69.2% | 76.9% | 100.0% | 86.7% | 14.8 |

Foco: pelo menos 50% das palavras na frase anotada e cobertura de metade de uma frase-alvo, com alinhamento normalizado por SequenceMatcher.

## Limitações

- 12 documentos fictícios e conjunto já inspecionado: diagnóstico/regressão, não teste independente em documentos novos.
- Limiar híbrido escolhido somente em 7 consultas positivas e 5 negativas de development sobre OCR limpo. evaluation: 13 positivas e 5 negativas.
- Foco é um indicador automático aproximado, não julgamento humano cego.
- Os três modos usam o mesmo verificador local de relevância.
- Tempos incluem cache de reranking; não representam latência de produção.
- Pontuação RRF não é similaridade de cosseno nem probabilidade de acerto.

Consultas, trechos e métricas completas: [hybrid-search.json](hybrid-search.json).

Reproduzir: `uv run python -m scripts.evaluate_hybrid`. Recalibrar apenas em development: acrescentar `--calibrate`.
