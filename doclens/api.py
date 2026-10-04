"""API local. Use --host 127.0.0.1 --no-proxy-headers ao iniciar o Uvicorn."""

import logging
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException

from doclens.config import ROOT, Settings
from doclens.contracts import ModelProvider
from doclens.documentation import register_documentation
from doclens.errors import DocumentError
from doclens.models import LocalModels
from doclens.schemas import Document, DocumentSummary, SearchResponse
from doclens.security import LocalSecurityMiddleware, UploadRoute, response_headers, run_protected
from doclens.service import DocumentService

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    method: Literal["hybrid", "semantic", "tfidf"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        if any(unicodedata.category(c) == "Cc" and c not in "\t\n\r" for c in value):
            raise ValueError("Use texto legível, sem caracteres de controle.")
        value = "".join(c for c in value if unicodedata.category(c) != "Cf").strip()
        if not value:
            raise ValueError("Digite uma consulta com texto.")
        return value


def create_app(settings: Settings | None = None, models: ModelProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    service = DocumentService(settings, models or LocalModels(settings))
    app = FastAPI(
        title="DocLens",
        version="0.1.0",
        description="OCR e busca em português",
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = service
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    register_documentation(app)
    upload_router = APIRouter(route_class=UploadRoute)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc: RequestValidationError):
        # Não devolver a entrada inválida: um surrogate Unicode isolado também
        # quebraria a serialização do erro padrão e transformaria um 422 em 500.
        errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"detail": "Confira a consulta e os campos enviados.", "errors": errors},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        detail = (
            "Não foi possível ler os dados enviados. Confira o arquivo ou JSON."
            if exc.status_code == 400
            else exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
        )

    @app.exception_handler(DocumentError)
    async def document_error(_, exc: DocumentError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Falha inesperada no DocLens", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "O processamento falhou. Consulte o terminal e tente novamente."},
            headers=response_headers(request.scope),
        )

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/example", include_in_schema=False)
    def example():
        path = ROOT / "data" / "fixtures" / "clean" / "manutencao_01.png"
        if not path.exists():
            raise DocumentError("Gere os exemplos com python -m scripts.generate_corpus.", 404)
        return FileResponse(path, media_type="image/png")

    @app.get("/health")
    def health():
        return {"status": "ok", "preprocess": settings.preprocess}

    @upload_router.post("/documents", status_code=201, response_model=Document)
    async def upload(file: Annotated[UploadFile, File()], request: Request):
        try:
            # Lê somente limite+1; não carrega um upload arbitrariamente grande na memória.
            content = await file.read(settings.max_bytes + 1)
            return await run_protected(request, service.ingest, content, file.filename or "arquivo")
        finally:
            await file.close()

    app.include_router(upload_router)

    @app.get("/documents", response_model=list[DocumentSummary])
    def documents():
        return service.store.list_documents()

    @app.get("/documents/{document_id}", response_model=Document)
    def document(document_id: UUID):
        found = service.store.document(str(document_id))
        if found is None:
            raise DocumentError("Documento não encontrado.", 404)
        return found

    @app.get("/documents/{document_id}/pages/{number}/image", include_in_schema=False)
    def page_image(document_id: UUID, number: int):
        page_count = service.store.page_count(str(document_id))
        if page_count is None or not 1 <= number <= page_count:
            raise DocumentError("Página não encontrada.", 404)
        return FileResponse(settings.data_dir / str(document_id) / f"{number}.png")

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest, http_request: Request):
        return await run_protected(
            http_request, service.search_response, request.query, request.method, request.top_k
        )

    return app


app = create_app()
