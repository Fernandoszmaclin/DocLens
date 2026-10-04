"""Documentação padrão FastAPI com scripts autorizados e assets imutáveis."""

import re

from fastapi import Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse

from doclens.security import DOC_NONCE_KEY

SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/swagger-ui-bundle.js"
SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.0/swagger-ui.css"
REDOC_JS = "https://cdn.jsdelivr.net/npm/redoc@2.5.4/bundles/redoc.standalone.js"
ASSET_INTEGRITY = {
    SWAGGER_JS: "sha384-ZPehFMQommnnuaZ4rpxgkgTT2DKFVp4hZC/7pLit+9Lek9T1YGSo23eHFbvNkXkw",
    SWAGGER_CSS: "sha384-Ov4/wv3j2bmct8cDc5X4ngJZohVPzEmc6uDPH8WeljUxO5vtoykvMEfbu9Vh6RaW",
    REDOC_JS: "sha384-w447zOpYfw/1Tv/5AK9NfHTlQIqE3RVR6KY62jCyy9zNDgO64cMwGGP1Fj0zJVf5",
}


def _secure_html(response: HTMLResponse, nonce: str) -> HTMLResponse:
    html = response.body.decode("utf-8")
    html = re.sub(r"<script\b", f'<script nonce="{nonce}"', html)
    for url, integrity in ASSET_INTEGRITY.items():
        for attribute in ("src", "href"):
            html = html.replace(
                f'{attribute}="{url}"',
                f'{attribute}="{url}" integrity="{integrity}" crossorigin="anonymous"',
            )
    return HTMLResponse(html)


def register_documentation(app):
    @app.get("/docs", include_in_schema=False)
    def swagger(request: Request):
        root = request.scope.get("root_path", "").rstrip("/")
        response = get_swagger_ui_html(
            openapi_url=root + app.openapi_url,
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=root + "/docs/oauth2-redirect",
            swagger_js_url=SWAGGER_JS,
            swagger_css_url=SWAGGER_CSS,
        )
        return _secure_html(response, request.scope[DOC_NONCE_KEY])

    @app.get("/redoc", include_in_schema=False)
    def redoc(request: Request):
        root = request.scope.get("root_path", "").rstrip("/")
        response = get_redoc_html(
            openapi_url=root + app.openapi_url,
            title=app.title + " - ReDoc",
            redoc_js_url=REDOC_JS,
        )
        return _secure_html(response, request.scope[DOC_NONCE_KEY])

    @app.get("/docs/oauth2-redirect", include_in_schema=False)
    def oauth_redirect(request: Request):
        return _secure_html(get_swagger_ui_oauth2_redirect_html(), request.scope[DOC_NONCE_KEY])
