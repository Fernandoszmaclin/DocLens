# Cinco consultas: o que corrigir e o que a fonte permite afirmar

## Diagnóstico

“probelmas nos computdores” chegava ao modelo com duas palavras incorretas. O candidato
correto era encontrado, mas recebia uma verificação fraca e era rejeitado. A pergunta sobre
luvas continha também um tema explicitamente indesejado, ar-condicionado, que confundia a
consulta completa. No falso positivo sobre plano de saúde, a passagem genérica de
disponibilidade de materiais tinha cosseno aproximado de 0,449 e logit -3,188: sinais
fracos, mas suficientes para atravessar os filtros anteriores.

As outras duas perguntas exigiam informações ausentes. O comunicado sobre notebooks
descreve lentidão e desligamentos inesperados; não descreve falha ao ligar. O documento de
capacitação pede um comprovante de conclusão; não informa onde entregar o certificado.
As anotações anteriores indicavam documentos do mesmo tema, mas isso não garante que a
pergunta tenha uma resposta explícita. As 15 anotações foram mantidas para preservar a
comparação e mostrar esse limite, sem transformar a ausência de informação em resposta.

## Interpretação da consulta

Usamos `pyspellchecker==0.9.0`, com dicionário de português incluído no pacote, somente
uma edição e nenhuma chamada de rede. A biblioteca considera inserção, remoção,
substituição e transposição, conforme a [documentação oficial](https://pyspellchecker.readthedocs.io/en/latest/).
Cada correção exige um único candidato. Palavras válidas sem acento, números, referências,
siglas e termos existentes na biblioteca ficam preservados. O vocabulário local também
ajuda a reconhecer palavras estrangeiras dos próprios documentos. Não escolhemos uma
alternativa ambígua somente porque ela é mais frequente.

Preferências explícitas no início, seguidas de dois-pontos, ponto e vírgula, “mas” ou
“e sim”, são separadas em pedido positivo e tema excluído. Por exemplo:
“Não quero ar-condicionado: preciso de luvas para limpeza” passa a buscar o pedido de
luvas e excluir passagens do tema anterior. A regra é deliberadamente limitada: não é
uma análise gramatical geral. “O computador não liga” e “sem motorista” são preservados.
Uma formulação fora dessas estruturas pode continuar difícil para o modelo.

A API mantém a consulta original e devolve a consulta interpretada, correções e exclusões.
A interface mostra o ajuste para que o usuário confira o sentido. Todo conteúdo é texto
literal. O orçamento de tokens também é verificado após a interpretação. As imagens,
frases reconhecidas e coordenadas dos resultados continuam vindo da fonte original.

## Relevância: evidência em vez de palavras proibidas

No NLP e na híbrida, uma passagem com verificação negativa e sem palavra em comum com a
consulta na própria passagem, título ou página precisa de cosseno ≥0,5. Os critérios
anteriores continuam valendo. Uma verificação positiva pode aceitar uma paráfrase sem
sobreposição lexical. O filtro não proíbe o assunto “plano de saúde”: um teste com modelo
real verifica que um documento sobre inscrição nesse plano é encontrado normalmente.

O contexto da página é necessário: a frase de solicitação de transporte pode não conter
“motorista”, embora a frase seguinte contenha. Ignorar essa evidência perdeu uma consulta
válida no primeiro experimento. A regra final usa também o OCR da mesma página, preserva
o destaque apenas da passagem escolhida e não devolve o texto completo em `/search`.

O limiar de 0,5 é uma escolha de implementação verificada nestes diagnósticos, não um
limiar universal ou uma probabilidade. Não foi otimizado em uma avaliação independente.
Uma palavra em comum também não garante relevância; a verificação e os demais cortes
continuam necessários. A busca ainda pode errar em documentos novos.

## Testes e interpretação dos números

Testes rápidos verificam correção única, ambiguidade, termos válidos sem acento, nomes do
corpus, códigos, negação de sintomas, exclusão de preferências, transparência da API,
limite de tokens e rejeição de passagens genéricas. Testes com modelos reais verificam
que as duas perguntas específicas retornam resultado quando um texto contém a informação
explicitamente. Esses exemplos ficam somente no teste; a biblioteca local e os documentos
do benchmark original continuam preservados.

Os resultados antes/depois, trechos e comandos estão em
[reports/query-recovery.md](../reports/query-recovery.md).
