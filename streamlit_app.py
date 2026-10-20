"""Interface pública: streamlit run streamlit_app.py."""

import logging

import streamlit as st
from PIL import Image, ImageDraw

from doclens.cloud import CloudRuntime, CloudSession
from doclens.config import ROOT
from doclens.errors import DocumentError, ModelUnavailable

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="DocLens · Busca em documentos",
    page_icon=ROOT / "static" / "favicon.png",
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def shared_runtime():
    return CloudRuntime()


@st.cache_resource(scope="session", on_release=lambda session: session.close(), show_spinner=False)
def private_session():
    return CloudSession(shared_runtime())


def report_error(error):
    if isinstance(error, ModelUnavailable):
        logger.error("Modelos indisponíveis na demonstração", exc_info=error)
        st.error("Não foi possível preparar os modelos. Aguarde um pouco e tente novamente.")
    else:
        st.error(str(error))


def process_upload(session, content, filename):
    try:
        with st.spinner("Lendo o documento... Iniciando modelos."):
            document = session.ingest(content, filename)
        st.session_state.pop("search_response", None)
        st.success(f"{document['filename']} indexado. Faça uma busca para encontrar os trechos.")
    except DocumentError as exc:
        report_error(exc)
    except Exception:
        logger.exception("Falha no upload da demonstração")
        st.error("Não foi possível processar o documento. Tente novamente.")


def highlighted_page(session, hit):
    path = session.settings.data_dir / hit["document_id"] / f"{hit['page']}.png"
    with Image.open(path) as source:
        image = source.convert("RGBA")
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    for box in hit["boxes"]:
        points = [(float(x), float(y)) for x, y in box]
        draw.polygon(points, fill=(255, 198, 48, 90), outline=(207, 135, 0, 230), width=2)
    return Image.alpha_composite(image, overlay).convert("RGB")


def main():
    session = private_session()
    st.title("DocLens", anchor=False)
    st.subheader("Ache o que precisa sem reler tudo.", anchor=False)
    st.write(
        "Envie um PDF ou uma imagem e diga o que está procurando. "
        "O DocLens encontra os trechos e mostra onde eles aparecem no documento."
    )
    st.caption(
        "Demonstração gratuita de portfólio · OCR em português e inglês · "
        "Biblioteca individual e temporária"
    )

    with st.sidebar:
        st.subheader("Sua biblioteca")
        st.caption("PNG, JPEG ou PDF · até 10 MB e 5 páginas · até 10 documentos")
        uploaded = st.file_uploader(
            "Escolha um documento",
            type=["png", "jpg", "jpeg", "pdf"],
            key=f"upload_{st.session_state.get('upload_generation', 0)}",
            max_upload_size=10,
        )
        if st.button("Processar documento", type="primary", disabled=uploaded is None):
            process_upload(session, uploaded.getvalue(), uploaded.name)
        if st.button("Testar com um exemplo", width="stretch"):
            example = ROOT / "data" / "fixtures" / "clean" / "manutencao_01.png"
            process_upload(session, example.read_bytes(), example.name)

        documents = session.service.store.list_documents()
        if documents:
            st.divider()
            for document in documents:
                st.text(f"{document['filename']} · {document['page_count']} pág.")
            if st.button("Limpar minha biblioteca"):
                private_session.clear()
                st.session_state.pop("search_response", None)
                st.session_state["upload_generation"] = (
                    st.session_state.get("upload_generation", 0) + 1
                )
                st.rerun()
        st.divider()
        st.info(
            "Use documentos de teste. A biblioteca pertence à sua sessão e pode ser apagada "
            "ao desconectar, recarregar ou reiniciar a aplicação."
        )
        st.link_button(
            "Código e avaliação no GitHub", "https://github.com/Fernandoszmaclin/DocLens"
        )

    with st.form("search"):
        query = st.text_input(
            "O que você procura?", placeholder="Problemas nos computadores", max_chars=500
        )
        options = {
            "Híbrida (recomendada)": "hybrid",
            "Semântica (NLP)": "semantic",
            "Palavras (TF-IDF)": "tfidf",
        }
        left, right = st.columns([3, 1])
        method = left.selectbox("Método de busca", options)
        top_k = right.selectbox("Máximo de trechos", [3, 5, 10], index=1)
        submitted = st.form_submit_button(
            "Buscar nos documentos", type="primary", disabled=not documents
        )

    if submitted:
        if not query.strip():
            st.warning("Digite uma consulta com texto.")
        else:
            try:
                with st.spinner("Buscando os trechos mais relevantes…"):
                    st.session_state["search_response"] = session.search(
                        query.strip(), options[method], top_k
                    )
            except DocumentError as exc:
                st.session_state.pop("search_response", None)
                report_error(exc)
            except Exception:
                st.session_state.pop("search_response", None)
                logger.exception("Falha na busca da demonstração")
                st.error("Não foi possível concluir a busca. Tente novamente.")

    response = st.session_state.get("search_response")
    if response:
        if response["interpreted_query"] != response["query"]:
            st.info(f"Consulta interpretada: {response['interpreted_query']}")
        if response["excluded_terms"]:
            st.caption("Termos excluídos: " + ", ".join(response["excluded_terms"]))
        if not response["results"]:
            st.info("Nenhum trecho suficientemente relevante. Tente reformular a consulta.")
        for index, hit in enumerate(response["results"], 1):
            with st.container(border=True):
                st.subheader(f"{index}. {hit['filename']} · página {hit['page']}")
                st.write(hit["text"])
                st.caption(
                    f"Pontuação do método: {hit['score']:.4f} · "
                    "não representa probabilidade de acerto"
                )
                with st.expander("Ver trecho destacado na página", expanded=index == 1):
                    st.image(highlighted_page(session, hit), width="stretch")
    elif not documents:
        st.info(
            "Comece pelo botão **Testar com um exemplo**. "
            "Depois busque **problemas nos computadores**."
        )

    st.caption("Projeto demonstrativo com modelos pré-treinados. Confira sempre o trecho na fonte.")


if __name__ == "__main__":
    main()
