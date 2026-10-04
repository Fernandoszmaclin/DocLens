# Demonstração em aproximadamente dois minutos

Grave a interface e sua voz. Use somente os documentos fictícios incluídos. Execute
`uv run python -m scripts.load_demo` antes da gravação para evitar esperar pelo OCR de todos os exemplos.

| Tempo     | Mostrar                                              | Explicar                                                                                                                                |
| --------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 0:00 a 0:15 | Tela inicial e biblioteca                            | “DocLens transforma memorandos e comunicados em documentos pesquisáveis, combinando Python, visão computacional, NLP e web.”            |
| 0:15 a 0:35 | Upload de um PDF fictício; corte o período de espera | “O PDF vira uma imagem. O OCR identifica texto e coordenadas. O tratamento da imagem foi escolhido com base na taxa de erro.”           |
| 0:35 a 1:00 | Buscar “problemas nos computadores” na opção híbrida | “A busca padrão combina significado e palavras. Ela encontra a informação mesmo quando a consulta usa palavras diferentes.”              |
| 1:00 a 1:15 | Clicar no resultado e abrir texto reconhecido        | “Cada resultado leva à página de origem. Os blocos usados na busca aparecem destacados para conferência.”                               |
| 1:15 a 1:35 | Alternar para NLP e TF-IDF; consultar o relatório    | “Mantive os três modos para comparar suas decisões. Avaliei os mesmos trechos com vinte consultas anotadas e dez perguntas sem resposta.” |
| 1:35 a 1:50 | Mostrar README, arquitetura e testes                 | “A API valida uploads; SQLite preserva texto e vetores. Os testes cobrem PDF, persistência e falhas.”                                   |
| 1:50 a 2:00 | Voltar à interface                                   | “Similaridade não é certeza. O próximo passo é avaliar documentos reais autorizados e mais tipos de layout.”                            |

Ao narrar números de busca, leia `reports/hybrid-search.md`; para OCR, leia
`reports/results.md`. Diga o conjunto correspondente. Não transforme
Recall@3 em “precisão do sistema”. Acrescente a URL real do seu repositório somente após publicá-lo.

Explique a melhoria: as passagens passaram a respeitar frases e parágrafos, e um verificador
local filtra relações fracas. Mostre uma consulta sem resposta e o destaque anterior sendo
removido. Os três modos usam o verificador local. A híbrida combina posições das listas e
aplica um bônus limitado de relevância, preservando destaques de passagens específicas.
