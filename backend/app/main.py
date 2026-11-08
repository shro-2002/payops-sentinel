import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import router
from app.api.studio import router as studio_router
from app.config import get_settings
from app.db.session import engine

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')


def create_app() -> FastAPI:
    app = FastAPI(title="PayOps Sentinel API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    app.include_router(router)
    app.include_router(studio_router)

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                             "Referrer-Policy": "no-referrer"})
        return resp

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/ready")
    def ready():
        with engine.connect() as c:
            c.execute(text("select 1"))
        c = get_settings()
        return {"status": "ready", "checks": {"db": "ok", "paypal_credentials": bool(c.paypal_client_id),
                                              "llm_key": bool(c.gemini_api_key)}}

    return app


app = create_app()
