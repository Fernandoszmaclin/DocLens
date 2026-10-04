# Aprenda a explicar e modificar o projeto

## Etapa 1: Ambiente e dados

Comece por `pyproject.toml`, `uv.lock` e `data/corpus.json`. A `.venv` isola bibliotecas; o lock
registra versões exatas. Os textos são próprios e vêm com consultas e documentos relevantes.

**Exercício:** escreva um comunicado fictício adicional e uma consulta com palavras diferentes.
Antes de alterar o corpus de avaliação, copie-o para um experimento separado e registre a versão.

**Você deve conseguir explicar:** por que dados anotados são necessários e por que quatro
documentos de desenvolvimento não são usados como evidência independente de desempenho.

## Etapa 2: Visão computacional

Leia `load_pages`, `preprocess_image` e `recognize` em `doclens/vision.py`. O OCR possui duas
tarefas: localizar regiões de texto e reconhecer caracteres. OpenCV modifica os pixels antes
dessas tarefas; EasyOCR retorna texto e quadriláteros.

**Exercício:** abra a versão limpa e degradada do mesmo documento. Observe inclinação,
contraste e ruído. Compare a transcrição correta com os erros presentes no OCR.

**Você deve conseguir explicar:** o que é CER; por que menor é melhor; por que realçar contraste
pode ajudar em uma imagem e piorar outra; por que a prévia usa a imagem processada.

## Etapa 3: NLP e avaliação

Leia `make_chunks` em `doclens/passages.py` e `rank_chunks` em `doclens/search.py`.
Um embedding representa uma sequência
de texto como um vetor. Vetores próximos podem expressar conceitos próximos, sem palavras iguais.
TF-IDF valoriza termos presentes no trecho e menos comuns no conjunto.

**Exercício:** teste “problemas nos computadores” e compare os métodos. Depois use uma consulta
sobre um tema ausente do corpus. Observe quando os filtros rejeitam os candidatos e quando
um trecho indevido ainda passa. Compare os três modos; a opção híbrida é o padrão.

**Você deve conseguir explicar:** tokens versus palavras; limite de entrada; similaridade de
cosseno; por que score não é probabilidade; como calcular Recall@3 a partir dos documentos anotados.

Leia `hybrid_candidates` e [hybrid-search.md](hybrid-search.md). RRF combina posições, e não
os cossenos diretamente. **Exercício:** calcule a contribuição de uma passagem em primeiro
lugar no NLP e terceiro no TF-IDF. Explique por que a união preserva paráfrases sem palavras
em comum e por que fusão ainda precisa de filtros e verificação de relevância.

Leia `reports/metrics.json`: um resultado em transcrição correta que piora com OCR revela uma
perda causada pelo reconhecimento. Um erro que já ocorre em `reference` merece investigar NLP
ou a anotação da consulta. Não conclua superioridade universal a partir de vinte consultas.

## Etapa 4: Backend e persistência

Leia `DocumentService` e `Store`. O serviço coordena as etapas, mas não conhece botões nem HTTP.
Uma transação evita salvar apenas metade dos dados. Cada chamada abre sua própria conexão SQLite,
permitindo trabalhar com a thread usada pelo FastAPI.

**Exercício:** envie um documento, pare o servidor e inicie novamente. Procure o mesmo assunto.
Não houve OCR novo: texto e embeddings foram recuperados do banco.

**Você deve conseguir explicar:** responsabilidade de cada camada; upload multipart; códigos
HTTP; por que nomes de arquivos externos não devem controlar caminhos de armazenamento.

## Etapa 5: Frontend e fonte visual

Leia `static/app.js`. `fetch` conecta a interface à API. Texto vindo de documentos é inserido
com `textContent`, para ser exibido como texto. O estado guarda documento, página e caixas do
resultado selecionado. A geometria do SVG vem diretamente do backend.

**Exercício:** selecione outro resultado, mude a página e redimensione a janela. Observe que
caixas e imagem compartilham o mesmo espaço de coordenadas.

**Você deve conseguir explicar:** estado da interface; chamada assíncrona; diferença entre texto
e HTML; por que uma resposta antiga não deve substituir a seleção mais recente.

## Como apresentar na seleção

Uma descrição fiel: “Implementei uma aplicação de OCR e recuperação de informação, integrando
modelos pré-treinados com uma API Python e uma interface web. Preservei evidências visuais e
comparei TF-IDF e embeddings em um conjunto anotado. Medi o efeito do pré-processamento no OCR.”

Mostre um acerto e uma limitação. Explique a métrica e o tamanho da amostra. Escolha uma melhoria
futura com base em um erro observado: correção de perspectiva, mais exemplos reais autorizados,
reordenação de layouts complexos ou calibração de relevância.
