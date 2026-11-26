"""FastAPI application factory."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import (
    auth,
    chats,
    documents,
    health,
    invitations,
    llm_providers,
    logs,
    operations,
    password_reset,
    platform,
    setup,
    tenants,
    users,
)
from app.core.config import get_settings

# State-changing requests must carry this header. Browsers do not send it cross-site
# without a CORS preflight, which this API never allows, so it blocks CSRF.
CSRF_HEADER = "x-mentis-request"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The interactive API docs reveal every endpoint: off unless MENTIS_API_DOCS=true (development).
    docs = get_settings().api_docs
    app = FastAPI(title="Mentis API", version=__version__, docs_url="/api/docs" if docs else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if docs else None)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse(status_code=403, content={"detail": "Missing request header."})
        return await call_next(request)

    for module in (health, setup, auth, password_reset, tenants, users, invitations, platform, documents, llm_providers, chats, logs, operations):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
