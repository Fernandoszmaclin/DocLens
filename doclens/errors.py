class DocumentError(Exception):
    """Erro esperado que pode ser exibido em português na interface."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class ModelUnavailable(DocumentError):
    def __init__(self):
        super().__init__(
            "Não foi possível carregar os modelos. Execute python -m scripts.prepare_models "
            "com acesso à internet e tente novamente.",
            503,
        )


class ModelOutputError(DocumentError):
    def __init__(self):
        super().__init__(
            "O modelo retornou dados inválidos. Reinicie a aplicação e tente novamente.", 503
        )
