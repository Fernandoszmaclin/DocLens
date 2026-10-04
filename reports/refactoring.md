# Refatoração do DocLens

Refatoração interna concluída. API, pontuações, textos, coordenadas, interface e relatórios mantêm os mesmos resultados nas comparações realizadas.

## Mudanças

- Persistência reutiliza blocos e mapa de identificadores por página durante uma leitura. Caixas antigas continuam independentes entre passagens; nenhuma estrutura da biblioteca é mantida entre consultas.
- Busca divide filtros, verificação, cortes relativos e montagem da resposta. TF-IDF mantém termos ausentes da consulta e o corpus já filtrado; RRF, limiares e desempates permanecem iguais.
- Interpretação separa preferências, vocabulário e correção; palavras repetidas são normalizadas uma vez por chamada.
- Serviço compartilha preparação de páginas e atribuição validada de embeddings. Modelos compartilham resolução de snapshots e configuração de threads; Settings lê o manifesto uma vez.
- Rota de imagem consulta somente page_count; não carrega OCR ou páginas completas.
- Frontend separa renderização de resumo, estado vazio e cartões, preservando versões de requisição e cancelamento. CSS não foi modificado.
- Comandos de avaliação compartilham corpus, métricas, cache e calibração; execução e escrita de relatórios ficam separadas. Doubles de teste não dependem de pytest ou da API.
- Contratos internos usam TypedDict e Protocol, sem conversão ou validação extra em execução. Nenhuma dependência nova ou alteração de esquema SQLite.

## Validação

- 145 testes Python passaram, incluindo OCR, PDF e modelos reais; 9 testes frontend passaram; Ruff limpo.
- Comparação exata de OpenAPI, campos/vetores/ordem/caixas da biblioteca e resultados sobre reference, clean e degraded.
- Nove snapshots do DOM iguais nos três modos, com respostas vazias e seleção manual.
- Sete execuções de diagnóstico comparadas antes/depois em diretórios isolados: evaluate, evaluate_search com/sem calibração, evaluate_hybrid com/sem calibração, evaluate_stress e fuzz_uploads.
- JSON, Markdown e configurações calibradas iguais, desconsiderando timestamps e tempos de execução. Essa comparação reutiliza OCR salvo como entrada fixa; OCR real foi validado nos testes de integração.
- Sete novas regressões cobrem reutilização por página, atualização entre leituras, independência de vetores/caixas antigas, rota de imagem sem hidratação e revisões explícitas do manifesto.
- Hashes de 75 arquivos originais confirmam corpus, configurações, documentação histórica, relatórios históricos, CSS e baseline de busca preservados.

## Desempenho medido

Biblioteca local de 13 documentos e 150 passagens; modelos locais em CPU, aquecidos; uma consulta fixa; sem cache de consultas ou reranking.

Três aquecimentos por operação. Mediana de 60 leituras e 30 buscas por método, em processos separados para referência e versão refatorada. Consulta: “Problemas nos computadores”.

| Operação | Antes (ms) | Depois (ms) | Redução | Pico Python antes (KiB) | Pico Python depois (KiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Leitura da biblioteca | 13.74 | 7.55 | 45.1% | 944.2 | 1068.1 |
| Busca híbrida | 586.91 | 554.50 | 5.5% | 1197.4 | 1188.4 |
| Busca semântica | 616.60 | 559.51 | 9.3% | 1197.1 | 1188.2 |
| Busca TF-IDF | 46.25 | 37.04 | 19.9% | 944.2 | 1068.1 |

A reutilização de geometria aumenta o pico temporário da leitura em aproximadamente 124 KiB nesta biblioteca; essas estruturas são liberadas ao concluir a chamada. O pico das buscas híbrida e semântica ficou praticamente igual. tracemalloc mede alocações Python, não memória nativa dos modelos.

Modelos continuam dominando a latência da busca completa. Os percentuais descrevem esta consulta e esta máquina.

Dados completos: [refactoring.json](refactoring.json). Scripts, cópia da referência e comparações detalhadas estão em artifacts/refactor_*.py, artifacts/refactor_baseline e artifacts/refactor.patch (ignorados pelo Git).

## Reproduzir testes

```powershell
uv run pytest -m "not models" -q
node --test tests/frontend.test.cjs
uv run ruff check doclens scripts tests
$env:DOCLENS_RUN_MODELS = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
uv run pytest -m models -q
```
