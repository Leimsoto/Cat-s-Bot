"""
api/routes/public_stats.py
──────────────────────────
Endpoint público de estadísticas globales — usado por la landing page
para mostrar números reales del bot (sin auth).

GET /api/public/stats → totales agregados (servidores, miembros, módulos, comandos)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from api.deps import get_bot, get_db

logger = logging.getLogger("API.public_stats")

router = APIRouter(prefix="/api/public", tags=["public"])

# Lista canónica de módulos expuesta en la landing.
# Mantener sincronizada con cogs/* y dashboard sidebar.
MODULES = [
    {"key": "ia", "name": "Inteligencia Artificial", "icon": "fa-microchip"},
    {"key": "moderation", "name": "Moderación", "icon": "fa-gavel"},
    {"key": "tickets", "name": "Tickets", "icon": "fa-ticket"},
    {"key": "radio", "name": "Radio / Música", "icon": "fa-music"},
    {"key": "levels", "name": "Niveles & XP", "icon": "fa-chart-line"},
    {"key": "welcome", "name": "Bienvenidas", "icon": "fa-door-open"},
    {"key": "autoroles", "name": "Autoroles", "icon": "fa-user-tag"},
    {"key": "giveaways", "name": "Sorteos", "icon": "fa-gift"},
    {"key": "embeds", "name": "Creador de Embeds", "icon": "fa-code"},
    {"key": "tags", "name": "Tags", "icon": "fa-tag"},
    {"key": "reports", "name": "Reportes", "icon": "fa-flag"},
    {"key": "schedules", "name": "Mensajes Programados", "icon": "fa-clock"},
    {"key": "voice-gen", "name": "Canales de Voz Auto", "icon": "fa-headset"},
    {"key": "logs", "name": "Registros", "icon": "fa-file-lines"},
    {"key": "suggestions", "name": "Sugerencias", "icon": "fa-lightbulb"},
    {"key": "invites", "name": "Invitaciones", "icon": "fa-link"},
]


@router.get("/stats")
async def public_stats(request: Request):
    """Estadísticas globales del bot — sin auth.

    Devuelve servidores, miembros aproximados, latencia, uptime, módulos.
    Nunca lanza error — si el bot no está conectado, devuelve ceros y `online: false`.
    """
    bot = getattr(request.app.state, "bot", None)
    db = getattr(request.app.state, "db", None)

    server_count = 0
    member_count = 0
    channel_count = 0
    online = False
    latency_ms = 0
    uptime_seconds = 0

    if bot is not None:
        try:
            guilds = list(bot.guilds)
            server_count = len(guilds)
            member_count = sum((g.member_count or 0) for g in guilds)
            channel_count = sum(len(g.channels) for g in guilds)
            online = bot.is_ready() if hasattr(bot, "is_ready") else True
            latency_ms = round((bot.latency or 0) * 1000)
            started_at = getattr(request.app.state, "started_at", None)
            if started_at is not None:
                uptime_seconds = int(
                    (datetime.now(timezone.utc) - started_at).total_seconds()
                )
        except Exception as e:
            logger.debug(f"public_stats parcial: {e}")

    total_commands = 0
    if db is not None:
        try:
            row = db._fetchone("SELECT COUNT(*) AS c FROM mod_actions")
            total_commands = int(row["c"]) if row and "c" in row else 0
        except Exception:
            total_commands = 0

    return {
        "online": online,
        "server_count": server_count,
        "member_count": member_count,
        "channel_count": channel_count,
        "module_count": len(MODULES),
        "modules": MODULES,
        "latency_ms": latency_ms,
        "uptime_seconds": uptime_seconds,
        "total_actions_logged": total_commands,
    }
