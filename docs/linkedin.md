# Texto para revisar e publicar no LinkedIn

Desenvolvi o **DocLens**, uma aplicação para pesquisar memorandos e comunicados pelo significado
do conteúdo e conferir os resultados na página original.

A ideia é simples: buscar “problemas nos computadores” e encontrar um comunicado sobre
“manutenção dos equipamentos de informática”, mesmo com palavras diferentes.

O projeto combina quatro áreas:

- **Python:** processamento, API com FastAPI e persistência em SQLite.
- **Visão computacional:** tratamento de imagens com OpenCV e reconhecimento de texto com EasyOCR.
- **NLP:** embeddings multilíngues, TF-IDF e busca híbrida com RRF e verificação de relevância.
- **Web:** interface com upload, busca e destaque dos trechos na fonte.

Além da aplicação, preparei um conjunto de 12 documentos fictícios e 20 consultas anotadas.
Comparei o OCR com e sem tratamento de imagem e avaliei se os documentos relevantes apareciam
entre os primeiros três trechos. As métricas e as limitações estão documentadas no repositório.

Uma lição do projeto: encontrar o documento certo não basta; o trecho precisa conter a informação
buscada. Após identificar destaques amplos, passei a separar frases, preservar seus intervalos
no OCR e verificar a relevância da consulta completa com um segundo modelo local. Também
acrescentei perguntas sem resposta à avaliação. Similaridade continua sendo proximidade,
sem representar probabilidade de acerto.

A busca híbrida virou o padrão, mantendo os métodos individuais disponíveis. No conjunto
fictício com OCR limpo, a híbrida encontrou um primeiro trecho focado em 20/20 consultas,
contra 19/20 do NLP e 15/20 do TF-IDF. Ela rejeitou 10/10 perguntas sem resposta. Esses números
são um diagnóstico do conjunto utilizado e não garantem desempenho em documentos reais.

Usei modelos pré-treinados e desenvolvi a integração, o fluxo de processamento e a avaliação.
O próximo passo é ampliar os testes com documentos reais autorizados e layouts variados.

**Antes de publicar:** adicione o link real do GitHub, anexe o vídeo e confira os resultados em
`reports/results.md` para OCR e `reports/hybrid-search.md` para busca. Ajuste o texto para
descrever apenas experiências que você consegue explicar.

#Python #VisaoComputacional #NLP #FastAPI #Portfolio
