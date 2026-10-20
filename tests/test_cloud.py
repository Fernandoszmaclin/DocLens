"""Isolamento de visitantes e limites do processamento público, sem rede."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from doclens.cloud import CloudRuntime, CloudSession
from doclens.config import ROOT
from doclens.errors import DocumentError
from tests.support import FakeModels, image_bytes


def test_visitors_have_private_libraries_and_cleanup():
    runtime = CloudRuntime(FakeModels())
    first, second = CloudSession(runtime), CloudSession(runtime)
    try:
        document = first.ingest(image_bytes(), "teste.png")
        assert first.service.store.document(document["id"]) is not None
        assert second.service.store.document(document["id"]) is None
        assert second.service.store.list_documents() == []
        assert first.settings.data_dir != second.settings.data_dir
        first.close()
        assert not first.settings.data_dir.exists()
        assert second.settings.data_dir.exists()
    finally:
        first.close()
        second.close()


def test_only_one_heavy_task_and_failure_releases_capacity():
    runtime = CloudRuntime(FakeModels())
    with runtime.gate, pytest.raises(DocumentError) as busy:
        runtime.run(lambda: None)
    assert busy.value.status_code == 409

    def fail():
        raise ValueError("falha de processamento")

    with pytest.raises(ValueError):
        runtime.run(fail)
    assert runtime.run(lambda: "disponível") == "disponível"


def test_streamlit_example_search_and_clear():
    runtime = CloudRuntime(FakeModels())
    with patch("doclens.cloud.CloudRuntime", return_value=runtime):
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
        assert not app.exception
        assert app.title[0].value == "DocLens"
        assert next(
            button for button in app.button if button.label == "Buscar nos documentos"
        ).disabled
        next(
            button for button in app.button if button.label == "Testar com um exemplo"
        ).click().run()
        assert not app.exception
        assert app.success
        app.text_input[0].set_value("Manutenção dos computadores da equipe")
        next(
            button for button in app.button if button.label == "Buscar nos documentos"
        ).click().run()
        assert not app.exception
        assert app.expander[0].label == "Ver trecho destacado na página"
        next(
            button for button in app.button if button.label == "Limpar minha biblioteca"
        ).click().run()
        assert not app.exception
        assert next(
            button for button in app.button if button.label == "Buscar nos documentos"
        ).disabled
