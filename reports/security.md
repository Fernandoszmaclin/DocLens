# Segurança do DocLens — 4 de outubro de 2026

Correções aplicadas para uso local por uma pessoa, com um worker e sem autenticação.

## Falhas reproduzidas e corrigidas

| Entrada | Antes | Depois |
| --- | --- | --- |
| Host arbitrário | API respondia 200 | 400, antes de ler o corpo |
| Upload com origem externa ou `null` | Documento criado, 201 | 403, sem processamento ou persistência |
| Cliente fora de loopback com Host local | API respondia 200 | 403 |
| Multipart arbitrariamente grande | Parser gravava arquivo completo antes do 413 | Corpo contado durante recebimento; 413 no limite |
| JSON grande com campo ignorado | Consulta aceita | 413 acima de 64 KiB |
| Arquivos ou campos multipart adicionais | Parser os recebia e ignorava | 400, temporários fechados |

O upload mantém seu limite de arquivo de 10 MiB e admite até 64 KiB de overhead multipart.
O prazo total para receber o corpo é 30 segundos; timeout retorna 408. Uma vaga de upload
e duas de busca limitam trabalho simultâneo; excedentes retornam 409. Em cancelamentos,
workers já iniciados mantêm suas vagas até terminar. CLI local sem Origin continua aceito.

Host e origem são controles contra requisições indevidas ao servidor local. A viabilidade
de ataques por páginas externas também depende das proteções e permissões do navegador;
as reproduções de origem usaram clientes HTTP controlados em bancos temporários.

## Endurecimento adicional

- CSP, `nosniff`, `DENY`, `no-referrer`, proteção de recursos entre origens e `no-store`
  para documentos, consultas, prévias e páginas com nonce.
- Swagger JS 5.33.1, CSS 5.33.0 e Redoc 2.5.4 fixados com SHA-384/SRI; scripts da
  documentação exigem nonce. Nenhum `unsafe-inline` ou `unsafe-eval` para scripts.
- SHA-256 dos dois pesos OCR verificado antes da carga. Preparação baixa em diretório
  temporário, verifica antes de substituir o cache e preserva hashes autorizados.
- Execução normal exige snapshots locais, desabilita downloads e código remoto de modelos.
  Cache ausente, incompleto ou pesos OCR inválidos retornam 503.
- Pillow usa somente os decodificadores PNG/JPEG; dimensões PDF não finitas são rejeitadas.
- Pisos de FastAPI, Starlette, Pillow e python-multipart elevados. Versões existentes do
  lock preservadas; Starlette passou a ser dependência direta, sem novo pacote instalado.
- GitHub Actions fixadas por SHA, `contents: read`, sem credenciais persistidas pelo checkout.
  `.env.*` ignorado, com exceção de `.env.example`.

## Validação

- **192 testes Python passaram**, incluindo OCR, embeddings, reranker e PDF com modelos reais.
  Desses, 46 cobrem as proteções de segurança adicionadas.
- **9 testes frontend passaram; Ruff limpo.**
- OpenAPI comparado com o baseline: idêntico. Arquivos de `static/` e `config/`, incluindo
  limiares, revisões e hashes autorizados, permaneceram idênticos.
- Comparação antes/depois de PNG, PDF de duas páginas e 12 consultas nos três métodos:
  respostas idênticas, incluindo IDs, textos, scores, ordem, correções e coordenadas.
  Somente datas de criação e tempos de processamento foram excluídos da comparação.
- Navegador real: upload do exemplo fictício, busca, seleção e destaque; Swagger e Redoc
  renderizados, sem erros ou avisos de CSP/SRI no console. Essa verificação de interface usou
  OCR simulado e banco separado; os testes Python acima usaram também os modelos reais.
- Consulta à OSV de **74 dependências Python do lock: nenhum alerta retornado**. Os três
  assets fixados da documentação também não retornaram alertas por pacote/versão.
- Varredura inicial de padrões de credenciais nos fontes: nenhum achado. Esses resultados
  descrevem as verificações executadas, sem garantir ausência de toda vulnerabilidade.

Os testes cobrem IPv4/IPv6, origens válidas e inválidas, cliente externo, tamanho omitido
ou incorreto, limite exato, partes extras, fechamento de temporários, timeout total,
cancelamento, capacidade após falha e rejeição de pesos adulterados antes da carga.

Não foram adicionados autenticação, exposição pela rede ou isolamento dos decodificadores
nativos em outro processo. O perfil continua estritamente local. Inicie com
`--host 127.0.0.1 --no-proxy-headers`, como documentado no README.

## Fontes

- [OWASP: validação de origem e Fetch Metadata](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
- [Starlette: limites de multipart e corpo](https://www.starlette.io/requests/).
- [GitHub: uso seguro de Actions](https://docs.github.com/en/actions/reference/security/secure-use).
- [OSV: consulta de vulnerabilidades por pacote e versão](https://google.github.io/osv.dev/post-v1-querybatch/).

Evidências locais ignoradas pelo Git: `artifacts/security_baseline/`, `artifacts/security.patch`,
`artifacts/security-osv.json`, `artifacts/security-before.json`, `artifacts/security-after.json`
e `artifacts/security-browser.jpg`.
