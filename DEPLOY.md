# Publicar o DocLens gratuitamente

A interface pública usa **Streamlit Community Cloud**, com OCR, busca híbrida/NLP/TF-IDF
e destaques nas imagens. O código está em `streamlit_app.py`; o processamento reutiliza
as camadas existentes do DocLens.

**Aplicação pública:** https://doclens-fernando.streamlit.app/

Deploy validado em 10/10/2026 com OCR de PNG e PDF e busca híbrida na nuvem.
O acesso público está habilitado nas configurações de compartilhamento.

## Publicação

1. Abra [Streamlit Community Cloud](https://share.streamlit.io/) e entre com GitHub.
2. Conecte a conta que administra `Fernandoszmaclin/DocLens`.
3. Clique em **Create app** e escolha **Yup, I have an app**.
4. Preencha:

   | Campo | Valor |
   | --- | --- |
   | Repository | `Fernandoszmaclin/DocLens` |
   | Branch | `codex/streamlit-deploy` (ou `main` após integrar o PR) |
   | Main file path | `streamlit_app.py` |
   | Python, em Advanced settings | **3.12** |
   | App URL | escolha um subdomínio disponível, como `doclens-fernando` |

5. Não há chaves de API ou serviços pagos necessários. Clique em **Deploy**.
6. Aguarde a instalação das dependências do `uv.lock`. Na primeira operação, aguarde
   também o download dos modelos nas revisões fixadas em `config/models.json`.
7. Clique em **Testar com um exemplo**, busque **problemas nos computadores** e abra
   o destaque. Repita com um PNG/JPEG e um PDF de teste. Confirme o funcionamento
   em uma janela anônima antes de divulgar.
8. Confira nas configurações que a aplicação é pública. Copie a URL realmente
   atribuída pelo serviço; o subdomínio sugerido acima pode estar ocupado.

O login, a aceitação dos termos e eventual autorização do GitHub precisam ser
concluídos pelo titular da conta. Não envie senhas ou tokens no chat.

## Funcionamento da demonstração

- Os modelos são compartilhados entre visitantes; bancos e imagens são separados por sessão.
- Uma tarefa pesada é executada por vez. Outros visitantes recebem uma mensagem para tentar novamente.
- Limites: 10 MB por arquivo, cinco páginas por PDF e dez documentos por sessão.
- Páginas são reduzidas a no máximo 1200 pixels no maior lado para limitar memória.
  Documentos com letras muito pequenas podem ter OCR pior que na versão local.
- OCR e verificador de relevância são descarregados alternadamente para reduzir o consumo.
- A biblioteca é temporária. O recurso de sessão limpa o diretório ao desconectar;
  também há o botão **Limpar minha biblioteca**. Reinícios podem apagar todos os arquivos.
- Os pesos de OCR mantêm a verificação SHA-256. Embeddings e verificador usam revisões fixadas.
- A aplicação FastAPI continua disponível para uso local pelos comandos do README.

## Limites do plano gratuito

O [Community Cloud é gratuito](https://docs.streamlit.io/get-started/tutorials/create-an-app).
A [documentação de recursos](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
publica memória aproximada entre 690 MB e 2,7 GB; esses limites podem mudar e não são
uma reserva garantida. Aplicações sem tráfego por 12 horas hibernam e podem ser reativadas
pelo visitante. O primeiro processamento após reiniciar pode ser demorado.

Esta hospedagem precisa de validação real após o deploy: um teste local de memória não
garante a mesma capacidade no Linux do serviço. Se aparecer erro de recursos, consulte
os logs antes de divulgar. A alternativa com mais memória é a VM ARM Always Free da
Oracle, com [até 2 OCPUs e 12 GB na cota atual](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
mas ela exige administração de servidor e cadastro com verificação de cartão.

## Testar localmente

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

Os modelos são preparados na primeira operação, sem precisar executar manualmente
`scripts.prepare_models`. Os testes rápidos continuam sem baixar pesos:

```powershell
uv run pytest -m "not models" -q
uv run ruff check doclens scripts tests streamlit_app.py
```

## Divulgar

Depois de validar a URL pública, adicione-a ao campo **Website** em **About** do repositório
GitHub e ao início do README. No LinkedIn, inclua-a como link em **Destaques**.

Sugestão de texto, substituindo o marcador pela URL verificada:

> Publiquei o DocLens: OCR e busca híbrida em documentos em português, com destaque
> do trecho na página original. O projeto integra visão computacional, NLP, Python
> e uma interface web. Experimente com um documento fictício: https://doclens-fernando.streamlit.app/
> Código e avaliação: https://github.com/Fernandoszmaclin/DocLens

Pesquisa de planos realizada em 10/10/2026. Revise as condições do serviço antes de
escolher qualquer recurso pago.
