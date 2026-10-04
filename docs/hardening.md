# Correções encontradas por testes adversos

## Busca: números, candidatos e rejeições

Embeddings podem aproximar `MEM-023/2026` de `MEM-024/2026`. A aplicação agora exige
referências alfanuméricas explícitas e anos entre 1900 e 2099 na página de origem, no
contexto ou no nome do arquivo. Normalizamos acentos e separadores de códigos para tolerar
`MEM 023/2026` reconhecido pelo OCR. O filtro vem antes da deduplicação: duas fontes com
o mesmo texto não podem fazer o documento correto desaparecer. O texto completo da página
é usado internamente e não é incluído nos resultados da API. O número zero voltou à
tokenização lexical. Esses filtros não resolvem toda quantidade, data ou identificador.

O RRF favorece passagens presentes nas duas listas. Com mais de 30 candidatos, uma
paráfrase em segundo lugar somente no NLP podia ficar fora da janela do verificador.
Reservamos os três primeiros candidatos de cada origem e completamos as demais vagas pelo
RRF, preservando o limite de 30 passagens e uma chamada ao verificador. Isso não altera
texto, página ou caixas das passagens.

A recuperação alternativa aceitava cosseno ≥0,6 com palavras em comum mesmo quando o
verificador rejeitava fortemente a relação. Agora exige também logit ≥-8. Esse limite é
uma escolha conservadora de implementação, não um valor universal: preserva a paráfrase
já diagnosticada “A internet cai toda hora”, cujo trecho correto recebeu aproximadamente
-6,71. O teste de regressão reproduz a rejeição forte com logit -9. Os limiares principais
continuam os mesmos; não os reduzimos para aumentar a taxa de respostas artificialmente.

## Interface: quem pode aplicar uma resposta

Uma resposta antiga podia vencer uma busca nova, restaurar destaques após uma busca sem
resultados ou trocar o documento escolhido enquanto a busca estava em andamento.
Cada busca e cada seleção de prévia recebem uma versão. Somente a versão atual pode
atualizar a tela. Nova consulta cancela a requisição anterior com `AbortController`; editar
a consulta ou enviá-la vazia também cancela. O contador continua necessário, pois cancelar
HTTP não garante que todas as respostas já em trânsito desaparecerão.

Trocar uma página invalida a prévia anterior. O bloco `finally` de uma busca velha não pode
reativar controles de outra busca ainda em andamento. Oito testes executam o JavaScript
real com um DOM mínimo e respostas controladas; até respostas que ignoram o cancelamento
são testadas. Texto reconhecido é inserido como texto, sem interpretar HTML do documento.
Um nono teste posterior verifica o aviso de consulta ajustada, também como texto literal.

## Imagens, PDF e processamento

Remover o canal alfa de PNGs diretamente podia criar um fundo preto. Compor transparência
sobre branco preserva texto preto sobre papel; testamos RGBA, escala de cinza com alfa e
paleta. A operação segue a [documentação do Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.alpha_composite).
PNGs animados são rejeitados com mensagem clara, pois ler somente o primeiro quadro
perderia conteúdo silenciosamente. A orientação EXIF de JPEG foi verificada.

O bloqueio de upload agora ocorre antes de decodificar imagens ou abrir PDFs. Um segundo
upload recebe 409 sem gastar trabalho de renderização. Também há um mutex global em torno
das chamadas ao PDFium: a biblioteca exige serialização inclusive entre documentos
diferentes, conforme a [documentação oficial](https://pypdfium2.readthedocs.io/en/stable/python_api.html#threading).
O teste usa objetos simulados e detecta sobreposição entre threads, sem provocar uma corrida
insegura na biblioteca nativa. A aplicação continua limitada a uma instância/worker local.

Uma falha na segunda página não pode deixar um documento pela metade: arquivos parciais
são removidos, o banco permanece íntegro e o bloqueio é liberado para o próximo upload.

## API e saídas dos modelos

Surrogates Unicode isolados, caracteres invisíveis, JSON incompleto, UTF-8 inválido e
`NaN`/`Infinity` em `top_k` foram testados. O erro padrão de validação podia tentar devolver
a própria entrada inválida e falhar na serialização, produzindo 500. Agora retorna mensagem
em português e detalhes de validação sem reproduzir a entrada. `top_k` exige inteiro entre
1 e 10; booleanos, textos e frações são rejeitados. Caracteres de controle são rejeitados;
marcas de formatação invisíveis são removidas antes de validar uma consulta vazia.

Vetores com NaN, infinito, zero, formato ou dimensão incompatível não são persistidos nem
usados para ordenar. A verificação de relevância também exige saída finita e uma pontuação
para cada candidato; antes, uma saída curta poderia descartar candidatos silenciosamente.
Essas falhas retornam 503, preservando os documentos existentes.

Frases terminadas dentro de aspas ou parênteses voltam a gerar passagens curtas. Blocos
misturando linhas com e sem geometria não quebram a detecção de títulos. O índice v4 refaz
as passagens a partir do OCR salvo, com backup: não repete o OCR nem altera as imagens.

Resultados e casos ainda falhos: [reports/hardening.md](../reports/hardening.md).
Três desses casos foram corrigidos na rodada seguinte; os dois restantes não têm resposta
explícita na fonte. Veja [query-recovery.md](query-recovery.md).
