# Por que a busca híbrida virou o padrão

## Problema e alternativas

TF-IDF favorece palavras exatas, nomes e códigos, mas pode deixar paráfrases sem resposta.
Embeddings aproximam significados, mas podem selecionar um título genérico ou devolver
vizinhos para um assunto ausente. A busca híbrida reúne esses sinais; os modos individuais
continuam disponíveis para observar suas diferenças.

Somar os cossenos diretamente exigiria calibrar distribuições diferentes. Exigir que uma
passagem aparecesse nas duas listas perderia consultas sem sobreposição lexical. Escolhemos
a união dos candidatos e Reciprocal Rank Fusion (RRF), que combina posições nas listas.

## Fluxo e decisões

1. **Recuperar até 30 passagens por método**, usando os filtros de pontuação já existentes.
   TF-IDF usa a mesma normalização em português; NLP usa os embeddings persistidos.
2. **Combinar passagens iguais com pesos iguais.** Cada lista contribui `1 / (60 + posição)`,
   com posições começando em 1. Ausência em uma lista contribui zero. A identidade normaliza
   o contexto e o texto, seguindo a deduplicação dos modos anteriores. Mantemos uma fonte
   representativa, com texto, página, intervalos e caixas originais.
3. **Verificar até 30 candidatos da fusão**, reservando os três primeiros de cada origem
   antes de completar a janela pela pontuação RRF. Isso protege paráfrases fortes que
   aparecem apenas no NLP. A verificação usa uma única chamada ao cross-encoder
   já instalado. A fusão não repete OCR nem exige um modelo adicional. As pontuações de cada
   método permanecem disponíveis internamente para avaliar a evidência; o cosseno não é
   confundido com a pontuação RRF.
4. **Filtrar relações fracas.** Um candidato sem evidência semântica suficiente precisa passar
   pelo critério lexical ou obter um sinal positivo do verificador. O limiar híbrido de logit
   foi selecionado em development e ficou em -3,25. Também preservamos a regra do NLP que
   recupera correspondências com cosseno ≥0,6, palavras em comum e logit ≥-8, pois o verificador pode
   rejeitar uma paráfrase correta. Essa exceção também pode aceitar um trecho indevido.
5. **Promover respostas específicas com bônus limitado.** A pontuação final é
   `RRF + 0,002 × clip(logit, 0, 4)`. O bônus chega a 0,008 e é aplicado somente a sinais
   positivos; sinais negativos filtram, mas não penalizam novamente uma paráfrase recuperada
   pela regra anterior. Isso ajuda uma frase sobre comprovantes a superar o título de uma
   solicitação de capacitação. Constante, pesos e bônus são escolhas de implementação,
   verificadas neste diagnóstico; não foram otimizados em um conjunto independente.
6. **Retornar até top_k passagens.** Preservamos os cortes relativos de cada origem: 85% do
   melhor cosseno semântico aceito ou 60% do melhor TF-IDF aceito, com critério lexical de
   relevância. Sinais positivos do verificador podem preservar uma passagem abaixo desses
   cortes. Isso evita acrescentar um trecho sobre internet a uma resposta sobre notebooks
   apenas porque sua posição RRF ficou próxima. Aplicamos também corte de 60% do RRF do
   primeiro resultado, com exceção para sinais positivos. Textos e destaques não são
   concatenados. A interface exibe “Pontuação” com quatro casas decimais; os modos
   individuais continuam exibindo seus cossenos como “Similaridade”.

`hybrid` é o padrão da API quando `method` não é enviado e a opção inicialmente selecionada
na interface. `semantic` e `tfidf` continuam aceitos explicitamente. O índice e o banco
existentes são reutilizados. Correções na divisão de frases atualizaram o índice para v4;
a primeira busca refaz passagens e vetores a partir do OCR salvo, com backup do banco.

## O que os testes mostraram

O primeiro experimento, com RRF e apenas um limiar de relevância, obteve foco no primeiro
trecho em 17/20 consultas sobre OCR limpo e rejeitou somente 5/10 perguntas sem resposta.
A concordância de posições podia favorecer assuntos próximos, como limpeza de filtros
quando a pergunta tratava de equipamentos de proteção para quem faz a limpeza. Essa versão
motivou os filtros de evidência e o bônus positivo limitado.

Na versão final, o foco em top 1 sobre OCR limpo foi 20/20 na híbrida, 19/20 em NLP e 15/20
em TF-IDF. Na híbrida, o primeiro trecho teve em média 14,2 palavras e 2,15 caixas de linhas;
NLP teve 12,4 palavras e 1,95 caixas. Após os ajustes de interpretação e evidência, os três
modos rejeitaram 10/10 perguntas sem resposta.
Entre todos os trechos retornados para consultas positivas, 86,7% passaram pelo critério
automático de foco na híbrida, 82,8% no NLP e 90% no TF-IDF. A última métrica deve ser lida
junto com a taxa de consultas respondidas: TF-IDF deixou três consultas válidas sem resposta.
O falso positivo de “Inscrição no plano de saúde dos funcionários” foi corrigido exigindo
mais evidência para correspondências sem palavras em comum. Sobre OCR degradado, a híbrida
obteve foco em top 1 em 19/20 consultas.

O limiar foi calibrado somente com sete consultas positivas e cinco negativas de development.
As 13 positivas e cinco negativas restantes são reportadas separadamente. O corpus sintético
já foi inspecionado durante o desenvolvimento: estes resultados servem para diagnóstico e
regressão. O foco usa alinhamento automático aproximado, não avaliação humana cega. Tempos
da avaliação incluem cache de reranking e não representam latência da interface.

Consulte [o relatório completo](../reports/hybrid-search.md),
[as consultas e pontuações](../reports/hybrid-search.json) e
[o registro do primeiro experimento](../reports/hybrid-experiments.json).

Para reproduzir: `uv run python -m scripts.evaluate_hybrid`.
Para selecionar novamente o limiar apenas em development: acrescentar `--calibrate`.

Testes posteriores encontraram limitações adicionais e motivaram a reserva dos candidatos,
o limite da recuperação alternativa e filtros literais para códigos/anos. Veja
[as decisões de robustez](hardening.md) e [os resultados adicionais](../reports/hardening.md).
Uma rodada posterior recuperou consultas com digitação incorreta e preferências negativas:
[query-recovery.md](query-recovery.md).

## Referências

- [RRF e ordenação híbrida: Microsoft](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking).
- [Reciprocal Rank Fusion: Elastic](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).

Os serviços citados documentam o algoritmo; o DocLens implementa a fusão localmente em Python,
sem contratar esses serviços.
