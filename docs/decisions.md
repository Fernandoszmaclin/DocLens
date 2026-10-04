# Por que o DocLens foi construído assim

A evolução da busca está em [search-improvements.md](search-improvements.md): frases menores,
recorte dos destaques, normalização lexical e verificação local de relevância. As seções 3 e 4
abaixo registram a primeira versão, preservada como baseline na comparação antes/depois.

## 1. Modelos pré-treinados, execução local e CPU

**Problema:** entregar uma aplicação reproduzível em duas semanas, demonstrando visão e NLP.

**Escolha:** EasyOCR para detectar/reconhecer texto e MiniLM multilíngue para representações
de trechos. Modelos carregados uma vez, sob demanda, em CPU. Versões de bibliotecas ficam
no `uv.lock`; revisão e hashes dos pesos em `config/models.json`.

**Alternativas:** treinamento do zero demandaria muito mais dados e recursos. Uma API externa
reduziria a instalação local, mas criaria dependência de credenciais, disponibilidade e cobrança.

**Consequência:** o projeto demonstra integração e avaliação de modelos pré-treinados.
O primeiro download é grande; OCR em CPU tem latência perceptível. Não é correto apresentar
esse trabalho como treinamento de um modelo próprio.

## 2. Pré-processamento escolhido por medição

**Problema:** pouca iluminação e inclinação afetam OCR; filtros também podem destruir detalhes.

**Escolha:** comparar a imagem original com contraste local (CLAHE) e correção de inclinação
estimada por linhas (Hough). Aceitar apenas ângulos de até dez graus; manter o tamanho da página.
Usar somente os quatro documentos de desenvolvimento para escolher a política global.

**Alternativas:** binarização agressiva pode eliminar acentos e linhas finas; aplicar filtros
indiscriminadamente não garante melhora. Correção de perspectiva exige detecção dos cantos,
fora do recorte inicial.

**Consequência:** `config/ocr.json` registra a decisão e sua evidência. Oito documentos separados
medem a generalização dentro do corpus sintético. A política não é ajustada por consulta.
Os resultados efetivos estão em `reports/results.md`.

Um erro identificado nos exemplos de desenvolvimento estava na ordem das caixas: pequenas
diferenças de altura faziam fragmentos da mesma linha saírem invertidos. A implementação passou
a agrupar caixas por linha antes de ordenar da esquerda para a direita. A avaliação foi refeita
após essa correção; caches registram um hash do código, da imagem e da referência para evitar
reutilizar inferências de uma versão anterior do pipeline.

## 3. Primeira divisão de trechos: baseline

**Problema:** o modelo tem um limite de tokens e truncaria entradas longas. Além disso, um
resultado útil precisa indicar exatamente onde a informação foi encontrada.

**Escolha:** agrupar blocos de OCR contíguos dentro de uma página, contando tokens com o
tokenizer do próprio modelo. Dividir blocos grandes; preservar os identificadores das caixas.
O orçamento desconta os tokens especiais. Não há mistura de páginas.

**Alternativas:** cortar por um número fixo de caracteres não respeita o tokenizer. Colocar o
documento inteiro em um vetor perde detalhes. Sobreposição poderia melhorar passagens entre
trechos, mas aumentaria duplicação e complexidade; não foi usada nesta versão.

**Consequência:** um trecho pode começar no meio de um parágrafo. Ao dividir uma linha muito
longa, o destaque mostra a caixa do bloco completo, e não coordenadas inventadas para palavras.

## 4. Busca inicial com TF-IDF e cosseno: baseline

**Problema:** demonstrar de maneira verificável se interpretar significado traz benefícios.

**Escolha:** TF-IDF usa termos e pares de termos, com normalização de acentos. A busca semântica
normaliza vetores; o produto escalar passa a ser a similaridade de cosseno. Os dois métodos
recebem exatamente os mesmos trechos.

**Alternativas:** busca literal é mais restritiva; um chatbot generativo acrescentaria avaliação
de respostas e possíveis afirmações sem suporte. Um banco vetorial não é necessário para
algumas dezenas de documentos.

**Consequência:** busca semântica pode encontrar paráfrases, mas também retornar conteúdo pouco
relevante. Não há limiar calibrado para declarar ausência de resposta. A interface mostra
similaridade numérica, sem apresentá-la como confiança. TF-IDF retorna vazio sem sobreposição.

Recall@3 é medido por documento relevante entre os primeiros três **trechos**. Documentos
podem se repetir no ranking; não alteramos o ranking para inflar a métrica.

Na avaliação entregue, TF-IDF obteve 100% nas 13 consultas de avaliação sobre OCR, e a busca
semântica 84,6%. Já a paráfrase de desenvolvimento “problemas nos computadores” localiza o
comunicado de informática por significado, enquanto TF-IDF retorna outros assuntos. A análise
agregada e os exemplos individuais mostram aspectos diferentes; um exemplo escolhido para a
demonstração não prova superioridade geral.

## 5. FastAPI, interface própria e SQLite

**Problema:** demonstrar web sem consumir o prazo com múltiplos serviços e builds.

**Escolha:** FastAPI serve API e arquivos estáticos; HTML/CSS/JavaScript implementam upload,
estados, busca e prévia. SQLite grava documento, páginas, blocos e vetores float32 numa
transação. Imagens usam diretórios UUID; o nome enviado nunca vira caminho de armazenamento.

**Alternativas:** React é útil em interfaces maiores, mas acrescentaria ferramentas de build.
Streamlit aceleraria um painel Python, mas reduziria a prática de frontend. PostgreSQL e uma
fila distribuída exigiriam serviços adicionais.

**Consequência:** uma aplicação local e um worker. OCR é executado fora do loop assíncrono;
um lock impede uploads simultâneos. Falhas removem arquivos parciais e não deixam registros
incompletos. A chamada aguarda o processamento, com feedback na interface.

## 6. Coordenadas da página processada

**Problema:** corrigir a rotação muda a localização do texto; usar caixas corrigidas sobre a
imagem original produziria destaques incorretos.

**Escolha:** salvar e mostrar a mesma página usada pelo OCR. O SVG usa `viewBox` com largura
e altura da página; imagem e polígonos redimensionam juntos.

**Consequência:** o destaque continua alinhado ao mudar a largura da interface. A prévia indica
se a imagem é original ou tratada; nenhuma transformação inversa é necessária.
