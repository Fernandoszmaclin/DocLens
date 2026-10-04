"""Limites e isolamento HTTP para uma aplicação de uso exclusivamente local."""

import asyncio
import ipaddress
import secrets
import threading
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from doclens.config import Settings
from doclens.errors import DocumentError

JSON_MAX_BYTES = 64 * 1024
MULTIPART_OVERHEAD = 64 * 1024
BODY_TIMEOUT_SECONDS = 30
DOC_NONCE_KEY = "doclens.docs_nonce"
LEASE_KEY = "doclens.request_lease"
DOC_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}


def response_headers(scope) -> dict[str, str]:
    path = scope["path"].rstrip("/") or "/"
    directives = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
    if path in DOC_PATHS and DOC_NONCE_KEY in scope:
        # Swagger/Redoc usam estilos dinâmicos; somente scripts com nonce podem executar.
        directives[1] = f"script-src 'nonce-{scope[DOC_NONCE_KEY]}'"
        directives[2] = (
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com"
        )
        directives[3] += " https://fastapi.tiangolo.com"
        directives[4] += " https://fonts.gstatic.com"
        directives.append("worker-src blob:")
    headers = {
        "Content-Security-Policy": "; ".join(directives),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if path == "/" or path in DOC_PATHS or path == "/search" or path.startswith("/documents"):
        headers["Cache-Control"] = "no-store"
    return headers


class RequestLease:
    """Uma requisição cancelada mantém sua vaga enquanto o worker ainda executa."""

    def __init__(self, slots: threading.BoundedSemaphore):
        self.slots = slots
        self.lock = threading.Lock()
        self.working = False
        self.release_requested = False
        self.released = False

    def _release(self):
        if not self.released:
            self.released = True
            self.slots.release()

    def release(self):
        with self.lock:
            self.release_requested = True
            if not self.working:
                self._release()

    def call(self, function, *args):
        with self.lock:
            if self.released:
                raise DocumentError("A requisição foi encerrada.", 409)
            self.working = True
        try:
            return function(*args)
        finally:
            with self.lock:
                self.working = False
                if self.release_requested:
                    self._release()


async def run_protected(request: Request, function, *args):
    lease = request.scope[LEASE_KEY]
    return await run_in_threadpool(lease.call, function, *args)


class UploadRoute(APIRoute):
    """Restringe o formulário antes de FastAPI resolver File(), mantendo seu schema."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def upload_handler(request: Request):
            async with request.form(max_files=1, max_fields=0):
                return await handler(request)

        return upload_handler


def _origin(value: str):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not value.isascii()
            or any(ord(char) < 33 for char in value)
        ):
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


class LocalSecurityMiddleware:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.slots = {
            "/documents": threading.BoundedSemaphore(1),
            "/search": threading.BoundedSemaphore(2),
        }
        self.trusted_host = TrustedHostMiddleware(
            self._dispatch, allowed_hosts=["localhost", "127.0.0.1", "[::1]"], www_redirect=False
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"].rstrip("/") in DOC_PATHS:
            scope[DOC_NONCE_KEY] = secrets.token_urlsafe(24)

        async def secured_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in response_headers(scope).items():
                    headers[key] = value
            await send(message)

        if len(Headers(scope=scope).getlist("host")) != 1:
            return await self._reject(scope, receive, secured_send, 400, "Host inválido.")
        await self.trusted_host(scope, receive, secured_send)

    @staticmethod
    async def _reject(scope, receive, send, status: int, detail: str):
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

    async def _dispatch(self, scope, receive, send):
        try:
            peer = scope.get("client")
            local = peer is not None and ipaddress.ip_address(peer[0]).is_loopback
        except ValueError:
            local = False
        if not local:
            return await self._reject(
                scope, receive, send, 403, "Acesso permitido somente localmente."
            )
        headers = Headers(scope=scope)
        origins = headers.getlist("origin")
        target = _origin(f"{scope['scheme']}://{headers['host']}")
        if origins and (len(origins) != 1 or _origin(origins[0]) != target):
            return await self._reject(
                scope, receive, send, 403, "Origem da requisição não permitida."
            )
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            fetch_sites = headers.getlist("sec-fetch-site")
            if fetch_sites and fetch_sites != ["same-origin"]:
                return await self._reject(
                    scope, receive, send, 403, "Origem da requisição não permitida."
                )

        path = scope["path"].rstrip("/")
        limit = (
            self.settings.max_bytes + MULTIPART_OVERHEAD
            if path == "/documents" and scope["method"] == "POST"
            else JSON_MAX_BYTES
        )
        lengths = headers.getlist("content-length")
        if lengths:
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
                return await self._reject(
                    scope, receive, send, 400, "Tamanho da requisição inválido."
                )
            # Comparar dígitos antes de int() também limita cabeçalhos com milhares de dígitos.
            declared = lengths[0].lstrip("0") or "0"
            if len(declared) > len(str(limit)) or int(declared) > limit:
                return await self._reject(
                    scope, receive, send, 413, "A requisição excede o limite permitido."
                )

        lease = None
        if scope["method"] == "POST" and path in self.slots:
            slots = self.slots[path]
            if not slots.acquire(blocking=False):
                detail = (
                    "Outro documento está sendo processado. Aguarde e tente novamente."
                    if path == "/documents"
                    else "Há consultas em andamento. Aguarde e tente novamente."
                )
                return await self._reject(scope, receive, send, 409, detail)
            lease = RequestLease(slots)
            scope[LEASE_KEY] = lease

        total = 0
        complete = False
        deadline = asyncio.get_running_loop().time() + BODY_TIMEOUT_SECONDS

        async def limited_receive():
            nonlocal total, complete
            if complete:
                return await receive()
            try:
                async with asyncio.timeout_at(deadline):
                    message = await receive()
            except TimeoutError as exc:
                raise HTTPException(408, "O tempo para enviar a requisição foi excedido.") from exc
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(413, "A requisição excede o limite permitido.")
                complete = not message.get("more_body", False)
            return message

        try:
            await self.app(scope, limited_receive, send)
        finally:
            if lease is not None:
                lease.release()
