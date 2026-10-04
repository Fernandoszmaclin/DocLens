# Validação da entrega

Execução local no Windows, com Python 3.12.13 e as dependências do `uv.lock`.

## Verificações executadas

- `ruff check doclens scripts tests`: aprovado.
- `ruff format --check doclens scripts tests`: aprovado.
- `node --check static/app.js`: aprovado.
- **38 testes rápidos e um teste de modelos reais passaram** (39 no total), incluindo OCR,
  embeddings e verificação de relevância em PNG/PDF. Modelos reais executados offline.
- Reindexação dos 13 documentos da biblioteca local: arquivos e metadados preservados,
  150 passagens, backup SQLite e nenhuma nova execução de OCR.
- Avaliação de 48 combinações de imagem/política de OCR e 20 consultas, com separação entre
  desenvolvimento e avaliação. Resultados em `metrics.json` e `results.md`.
- Navegador: busca vazia, consulta semântica, alternância para TF-IDF e abertura da fonte.
- Destaques: imagem carregada, um polígono da frase sobre notebooks, `viewBox` correspondente
  à página e diferenças de largura/altura entre imagem e overlay iguais a zero.
- Layout de três colunas e layout em tela estreita: sem rolagem horizontal.
- Nenhum ajuste novo de viewport. Captura dos resultados e da fonte em
  `../docs/search-improvement.jpg`.
- Busca atual: 20 consultas positivas e 10 sem resposta nas versões reference, clean e degraded,
  comparadas com a implementação anterior congelada. Resultados em `search-comparison.md`.
- Navegador confirmou resultado lexical de reposição de materiais, ausência de correspondência
  lexical adequada para computadores e ausência de resposta para cardápio nos dois métodos.
  Uma busca vazia de resultados remove os polígonos anteriores.
- Testes adicionais verificam intervalos de caracteres, parágrafos, palavras longas, stopwords,
  termos ausentes, reindexação sem OCR, falha de inferência e rollback da troca de índice.

## Limites da validação

Os testes rápidos usam doubles para isolar contratos, erros e persistência. O teste de modelos
reais e a avaliação executam as redes pré-treinadas. Há avisos de depreciação/CPU de bibliotecas;
os testes finais não falharam. O workflow de GitHub Actions foi preparado,
mas ainda não executado no GitHub. As métricas medem um corpus sintético pequeno.

Os tempos HTTP registrados em `search-runtime.json` usam cinco consultas originais e a
biblioteca local de 13 documentos. Médias com modelos aquecidos: aproximadamente 0,60 s
para significado e 0,16 s para palavras. Havia outro processo de avaliação ativo: esse ensaio
não é um benchmark isolado e não inclui o carregamento inicial. Tempos do relatório de
qualidade podem usar cache de reranking e não representam latência de produção.
