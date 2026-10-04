# Como a busca foi melhorada

Este documento registra a melhoria anterior de NLP e TF-IDF. A opção híbrida agora é o padrão;
sua implementação, comparação e limitações estão em [hybrid-search.md](hybrid-search.md).

## O problema observado

A primeira versão agrupava linhas até completar o limite de tokens. Um vetor podia misturar
instituição, data, título, defeitos de notebooks e instruções sobre arquivos. Ao selecionar
esse resultado, o destaque abrangia todo o agrupamento. Recall@3 por documento não detectava
esse problema: encontrar o arquivo certo não significa apontar a resposta certa.

Além disso, a busca semântica sempre devolvia vizinhos, inclusive em perguntas sem resposta.
O TF-IDF considerava preposições e ignorava palavras desconhecidas da consulta; “problemas nos
computadores” podia corresponder apenas a “problemas”, em um texto sobre materiais de proteção.

## Decisões e motivos

1. **Uma frase por passagem, respeitando parágrafos e páginas.** O espaçamento das caixas separa
   parágrafos; a pontuação separa frases, preservando abreviações e decimais. Frases longas
   continuam sendo divididas pelo tokenizer. Isso mantém o resultado curto e focado.
2. **Intervalos de caracteres ligados ao OCR.** Cada passagem registra bloco, início e fim.
   Quando duas frases dividem uma linha, o destaque recorta somente a parte correspondente.
   Esse recorte é proporcional aos caracteres: é aproximado, pois o OCR fornece caixas de
   linhas, e não de cada palavra. Não foi repetido o OCR para obter novos resultados.
3. **Normalização lexical em português.** Remover palavras funcionais, normalizar acentos e
   aplicar Snowball reduz ruído e aproxima algumas flexões. “Não” e “sem” são preservados.
   Stemming não entende sinônimos nem resolve todas as flexões. Os termos ausentes também
   entram no vetor da consulta para evitar supervalorizar uma única palavra conhecida.
4. **Verificação conjunta de pergunta e trecho.** O modelo local
   `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` avalia até 30 candidatos. O título, quando
   identificado pela altura das letras, oferece contexto sem ampliar o texto destacado.
   Essa etapa pode rejeitar relações fracas, como transporte vs reembolso de viagem.
5. **Combinar evidências.** O novo modelo também comete erros. Na busca semântica, o cosseno
   permanece a principal evidência, com ajuste limitado de relevância (`0,02 × logit`, limitado
   a ±0,08). Uma correspondência semântica forte com termos em comum pode preservar uma
   paráfrase rejeitada pelo verificador. No TF-IDF, a ordem lexical é mantida e o modelo apenas
   filtra candidatos. Portanto, a comparação atual é entre dois pipelines com verificação
   compartilhada; a implementação anterior preserva a referência TF-IDF pura.
6. **Não preencher a lista à força.** Limiares de relevância foram selecionados em development:
   sete consultas positivas e cinco sem resposta, sobre OCR limpo. Resultados semânticos
   fracos abaixo de 85% do melhor cosseno são removidos, exceto quando o verificador fornece
   evidência positiva. No TF-IDF, o corte relativo é 60%. `top_k` é um máximo.
7. **Reindexação segura.** Uma versão do índice identifica mudanças de passagens/modelo.
   A primeira busca ou upload atualiza índices antigos a partir dos blocos salvos, com backup
   SQLite e substituição em uma transação. Falhas preservam o índice anterior. Documentos,
   identificadores, imagens e texto reconhecido permanecem intactos.
8. **Apagar destaques obsoletos.** Uma consulta sem resultados limpa o destaque da consulta
   anterior. A interface explica a ausência e sugere termos alternativos ou busca por significado.

## Como a melhoria foi verificada

As mesmas 20 consultas originais receberam anotações de frases relevantes; foram acrescentadas
10 consultas sem resposta. A avaliação verifica documento em top 3, foco da passagem em top 1
e top 3, rejeição de consultas sem resposta e tamanho do trecho. O foco exige pelo menos 50%
das palavras na informação anotada e cobertura de metade de uma frase-alvo. O alinhamento
normalizado é um indicador aproximado, não um julgamento humano cego.

Os valores medidos estão em [search-comparison.md](../reports/search-comparison.md), com
consultas e trechos em [search-comparison.json](../reports/search-comparison.json).
Use `uv run python -m scripts.evaluate_search` para reproduzir. A opção `--calibrate`
refaz a seleção do limiar somente em development. O cache inclui revisão, pergunta e textos.

O conjunto sintético já foi inspecionado durante o diagnóstico. A subdivisão evaluation ajuda
a acompanhar regressões, mas não equivale a um teste independente com documentos novos.
Rejeitar resultados fracos pode deixar uma consulta válida sem resposta, especialmente no
TF-IDF quando a pergunta usa paráfrases. O modelo adicional também acrescenta download,
uso de memória e latência em CPU; os modelos continuam locais e sem serviços pagos.

Na execução registrada sobre OCR limpo, os filtros semânticos rejeitaram nove das dez perguntas
sem resposta. “Inscrição no plano de saúde dos funcionários” ainda produziu um trecho indevido.
No TF-IDF, as três consultas válidas sem resultado foram “problemas nos computadores”,
“o auditório está quente e barulhento” e “preciso de um carro e motorista para uma visita”.
Esses casos permanecem no relatório; não foram retirados para melhorar os números.

## Referências

- [Snowball para português](https://snowballstem.org/algorithms/portuguese/stemmer.html).
- [TF-IDF no scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html).
- [Ficha do verificador multilíngue](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1).
- [Recuperação e reordenação](https://www.sbert.net/examples/cross_encoder/applications/README.html).
