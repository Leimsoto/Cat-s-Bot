"""
api/routes/radio.py
───────────────────
Endpoints para configuración de la radio Lofi 24/7.

GET   /api/guilds/{guild_id}/radio/config   → obtiene config
PATCH /api/guilds/{guild_id}/radio/config   → actualiza config y reconecta inmediatamente

Fix: tras guardar la config se fuerza un restart del radio_manager del cog
para que la conexión al canal sea inmediata y no espere hasta el próximo
tick del loop de 60 s.
"""

import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator

from api.deps import get_bot, get_db, require_guild_admin

logger = logging.getLogger("API.radio")

router = APIRouter(prefix="/api/guilds/{guild_id}/radio", tags=["radio"])

# Columnas válidas de lofi_config. Mantener sincronizado con database/manager.py.
_LOFI_KEYS = {
    "channel_id",
    "volume",
    "enabled",
    "stream_url",
    "station_name",
    "auto_reconnect",
    "pause_on_empty",
}


class RadioConfigUpdate(BaseModel):
    enabled: Optional[int] = None
    # channel_id se acepta como str o int para evitar pérdida de precisión en JS
    # (los Snowflakes de Discord superan Number.MAX_SAFE_INTEGER).
    channel_id: Optional[Union[str, int]] = None
    stream_url: Optional[str] = None
    station_name: Optional[str] = None
    volume: Optional[int] = None
    auto_reconnect: Optional[int] = None
    pause_on_empty: Optional[int] = None

    @field_validator("channel_id", mode="before")
    @classmethod
    def coerce_channel_id(cls, v):
        """Convierte a int server-side; None o '' → None."""
        if v is None or v == "" or v == 0:
            return None
        return int(v)


@router.get("/config")
async def get_radio_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    cfg = db.get_lofi_config(guild_id)
    return {"guild_id": guild_id, "radio_config": cfg}


@router.patch("/config")
async def patch_radio_config(
    guild_id: int,
    body: RadioConfigUpdate,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Actualiza solo los campos enviados y reconecta el bot inmediatamente."""
    payload = {
        k: v
        for k, v in body.model_dump().items()
        if v is not None and k in _LOFI_KEYS
    }
    if payload:
        db.set_lofi_config(guild_id, **payload)

    # Forzar reconexión inmediata: reiniciar el task radio_manager del cog
    # para que no haya que esperar el próximo tick de 60 s.
    _trigger_radio_reconnect(bot, guild_id)

    return {"status": "ok", "updated": list(payload.keys())}


def _trigger_radio_reconnect(bot, guild_id: int) -> None:
    """Dispara la conexión de radio para el guild usando el event loop del bot.

    Usa run_coroutine_threadsafe para cruzar correctamente del hilo de uvicorn
    al event loop del bot de Discord, evitando problemas de thread-safety.
    """
    if bot is None:
        return
    try:
        radio_cog = bot.cogs.get("Radio")
        if radio_cog is None:
            logger.warning("Cog Radio no encontrado — no se puede forzar reconexión")
            return

        import asyncio
        future = asyncio.run_coroutine_threadsafe(
            radio_cog.connect_guild(guild_id),
            bot.loop,
        )
        # Esperamos hasta 10 s para que la conexión arranque (no bloqueamos más)
        try:
            future.result(timeout=10)
        except Exception:
            logger.exception(f"Error durante connect_guild({guild_id})")
        else:
            logger.info(f"[radio] connect_guild ejecutado para guild {guild_id}")
    except Exception:
        logger.exception("Error al disparar reconexión de radio")


# Mantenemos PUT como alias por compat (algún cliente externo podría usarlo).
@router.put("/config")
async def put_radio_config(
    guild_id: int,
    body: RadioConfigUpdate,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    return await patch_radio_config(guild_id, body, request, db, bot, user)
