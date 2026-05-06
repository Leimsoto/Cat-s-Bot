"""
api/app.py
──────────
Aplicación FastAPI principal — Bot ES.

Novedades v2:
  • Sirve el nuevo dashboard React desde new-dashboard/dist/
  • Registra /api/guilds (router nuevo del dashboard)
  • Fallback SPA: cualquier ruta bajo /panel/* → index.html
"""

import logging
import os
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("API")

BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = BASE_DIR / "dashboard" / "dist"


def create_app(db=None, bot=None) -> FastAPI:
    app = FastAPI(
        title="Bot ES API",
        description="Backend REST para el panel web del Bot ES",
        version="2.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:8080")
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8080")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            {
                dashboard_url,
                api_base_url,
                "http://localhost:3000",
                "http://localhost:5173",
                "http://localhost:8080",
            }
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Inyectar DB y Bot ─────────────────────────────────────────────────────
    if db is not None:
        app.state.db = db
    if bot is not None:
        app.state.bot = bot

    # ── Registrar routers API ─────────────────────────────────────────────────
    from api.auth import router as auth_router
    from api.routes import (
        autoroles,
        channels,
        embeds,
        giveaways,
        levels,
        moderation,
        radio,
        reports,
        schedules,
        tags,
        tickets,
        voice_gen,
    )
    from api.routes.embeds import _send_router as embeds_send_router
    from api.routes.guild import router as guilds_router
    from api.routes.guild import router_legacy

    app.include_router(auth_router)
    app.include_router(guilds_router)  # /api/guilds — nuevo dashboard
    app.include_router(router_legacy)  # /api/guild/{id} — compatibilidad
    app.include_router(embeds_send_router)  # /api/guilds/{id}/embeds/send
    app.include_router(moderation.router)
    app.include_router(tickets.router)
    app.include_router(tags.router)
    app.include_router(levels.router)
    app.include_router(reports.router)
    app.include_router(schedules.router)
    app.include_router(giveaways.router)
    app.include_router(autoroles.router)
    app.include_router(radio.router)
    app.include_router(embeds.router)
    app.include_router(channels.router)
    app.include_router(voice_gen.router)

    from api.routes.invites_route import router as invites_router
    from api.routes.suggestions_route import router as suggestions_router
    from api.routes.welcome import router as welcome_router

    app.include_router(welcome_router)
    app.include_router(suggestions_router)
    app.include_router(invites_router)

    # ── Health-check ──────────────────────────────────────────────────────────
    @app.get("/", tags=["health"])
    async def health():
        return {"status": "online", "bot": "Bot ES", "api": "v2.0.0"}

    @app.get("/api/health", tags=["health"])
    async def api_health():
        return {"status": "ok"}

    # ── Servir nuevo Dashboard React (SPA) ────────────────────────────────────
    if DASHBOARD_DIR.is_dir():
        # Montar assets estáticos de Vite (JS, CSS, imágenes)
        assets_dir = DASHBOARD_DIR / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/panel/assets",
                StaticFiles(directory=str(assets_dir)),
                name="panel-assets",
            )

        @app.get("/panel/{full_path:path}", tags=["panel"], include_in_schema=False)
        async def serve_panel(full_path: str, request: Request):
            """SPA fallback — devuelve index.html para cualquier ruta /panel/*"""
            index = DASHBOARD_DIR / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            return {
                "error": "Panel no compilado. Ejecuta: cd dashboard && npm run build"
            }

        logger.info("✅ Panel React disponible en /panel/")
    else:
        logger.warning(
            "⚠️  dashboard/dist/ no encontrado. Ejecuta: cd dashboard && npm run build"
        )

    return app


def iniciar_api(db=None, bot=None, host: str = "0.0.0.0", port: int = 8080) -> None:
    """Arranca el servidor FastAPI en un hilo daemon."""
    import uvicorn

    app = create_app(db=db, bot=bot)

    def _run():
        uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)

    t = Thread(target=_run, daemon=True)
    t.start()
    logger.info(f"API FastAPI iniciada en http://{host}:{port}")
    logger.info(f"Panel disponible en http://{host}:{port}/panel/")
