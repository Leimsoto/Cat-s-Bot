"""
api/routes/emojis.py
────────────────────
Endpoints de emojis disponibles para el dashboard.

GET /api/guilds/{guild_id}/emojis  → emojis del servidor + de la app (Cat's Bot)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_bot, require_guild_admin

logger = logging.getLogger("API.emojis")
router = APIRouter(prefix="/api/guilds", tags=["emojis"])


@router.get("/{guild_id}/emojis")
async def list_emojis(
    guild_id: int,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Devuelve los emojis disponibles agrupados.

    Forma del payload:

    .. code-block:: json

        {
          "guild": [{"id": "...", "name": "...", "animated": false, "url": "...", "tag": "<:name:id>"}],
          "bot":   [{"id": "...", "name": "...", "animated": false, "url": "...", "tag": "<:name:id>"}]
        }

    El cliente añade la lista de emojis Unicode genéricos del lado del navegador.
    """
    if bot is None:
        raise HTTPException(503, "Bot no conectado")

    guild = bot.get_guild(guild_id)
    guild_emojis = []
    if guild:
        for e in guild.emojis:
            guild_emojis.append({
                "id": str(e.id),
                "name": e.name,
                "animated": e.animated,
                "url": str(e.url),
                "tag": str(e),
            })

    bot_emojis = []
    catbot = getattr(bot, "catbot", {}) or {}
    if catbot:
        try:
            app_emojis = await bot.fetch_application_emojis()
        except Exception as exc:
            logger.debug("fetch_application_emojis falló: %s", exc)
            app_emojis = []
        for e in app_emojis:
            bot_emojis.append({
                "id": str(e.id),
                "name": e.name,
                "animated": e.animated,
                "url": str(e.url),
                "tag": str(e),
            })

    return {"guild": guild_emojis, "bot": bot_emojis}
