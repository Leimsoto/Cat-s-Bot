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

import asyncio
import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.deps import get_bot, get_db, require_guild_admin
from radio_url_policy import (
    RadioURLPolicyError,
    redact_url_for_log,
    validate_public_http_url,
)

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


def _serialize_radio_config(cfg: dict) -> dict:
    """Devuelve config segura para JS.

    Los snowflakes de Discord superan Number.MAX_SAFE_INTEGER; si salen como
    número JSON el navegador los redondea y luego guarda un channel_id inválido.
    """
    data = dict(cfg or {})
    if data.get("channel_id") not in (None, ""):
        data["channel_id"] = str(data["channel_id"])
    return data


def _is_voice_channel(channel) -> bool:
    try:
        import discord
        return isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
    except Exception:
        return False


def _repair_rounded_channel_id(bot, guild_id: int, channel_id: int | None) -> int | None:
    """Intenta reparar un snowflake redondeado por JS.

    Si el ID no existe pero hay exactamente un canal de voz/stage muy cercano,
    lo usamos. El redondeo de doubles en IDs ~1e18 suele estar en centenas.
    """
    if bot is None or not hasattr(bot, "get_guild") or channel_id is None:
        return channel_id
    guild = bot.get_guild(guild_id)
    if guild is None:
        return channel_id
    direct = guild.get_channel(channel_id)
    if _is_voice_channel(direct):
        return channel_id

    candidates = [
        ch.id
        for ch in getattr(guild, "channels", [])
        if _is_voice_channel(ch) and abs(int(ch.id) - int(channel_id)) <= 4096
    ]
    if len(candidates) == 1:
        fixed = int(candidates[0])
        logger.warning(
            "[radio] channel_id redondeado reparado para guild %s: %s -> %s",
            guild_id,
            channel_id,
            fixed,
        )
        return fixed
    return channel_id


def _validate_radio_channel_id(bot, guild_id: int, channel_id: int | None) -> None:
    if bot is None or not hasattr(bot, "get_guild") or channel_id is None:
        return
    guild = bot.get_guild(guild_id)
    if guild is None:
        return
    if not _is_voice_channel(guild.get_channel(channel_id)):
        raise HTTPException(
            400,
            {
                "message": "El canal configurado para radio no existe o no es un canal de voz.",
                "channel_id": str(channel_id),
            },
        )


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
    return {"guild_id": str(guild_id), "radio_config": _serialize_radio_config(cfg)}


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
    if "channel_id" in payload:
        payload["channel_id"] = _repair_rounded_channel_id(bot, guild_id, payload["channel_id"])
        _validate_radio_channel_id(bot, guild_id, payload["channel_id"])
    if "stream_url" in payload:
        raw_stream_url = str(payload["stream_url"] or "").strip()
        if not raw_stream_url:
            payload["stream_url"] = None
        else:
            try:
                payload["stream_url"] = await asyncio.to_thread(
                    validate_public_http_url,
                    raw_stream_url,
                )
            except RadioURLPolicyError as exc:
                raise HTTPException(400, str(exc)) from exc
    if payload:
        db.set_lofi_config(guild_id, **payload)
    saved = db.get_lofi_config(guild_id)

    # Forzar reconexión inmediata: reiniciar el task radio_manager del cog
    # para que no haya que esperar el próximo tick de 60 s.
    restart_result = await _trigger_radio_reconnect(bot, guild_id)
    logger.info(
        "[radio] PATCH config guild=%s updated=%s channel_id=%s station=%r stream=%r restart=%s",
        guild_id,
        sorted(payload.keys()),
        saved.get("channel_id"),
        saved.get("station_name"),
        redact_url_for_log(saved.get("stream_url")),
        restart_result,
    )

    return {
        "status": "ok",
        "updated": list(payload.keys()),
        "radio_config": _serialize_radio_config(saved),
        "radio_restart": restart_result,
    }


@router.post("/restart")
async def restart_radio(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Reinicia explícitamente la radio con la configuración ya guardada."""
    saved = db.get_lofi_config(guild_id)
    restart_result = await _trigger_radio_reconnect(bot, guild_id)
    logger.info(
        "[radio] POST restart guild=%s channel_id=%s station=%r stream=%r restart=%s",
        guild_id,
        saved.get("channel_id"),
        saved.get("station_name"),
        redact_url_for_log(saved.get("stream_url")),
        restart_result,
    )
    return {
        "status": "ok",
        "radio_config": _serialize_radio_config(saved),
        "radio_restart": restart_result,
    }


async def _trigger_radio_reconnect(bot, guild_id: int) -> dict:
    """Dispara la conexión de radio para el guild usando el event loop del bot.

    Usa run_coroutine_threadsafe para cruzar correctamente del hilo de uvicorn
    al event loop del bot de Discord, evitando problemas de thread-safety.
    """
    if bot is None:
        return {"triggered": False, "completed": False, "reason": "bot_not_available"}
    try:
        radio_cog = bot.cogs.get("Radio")
        if radio_cog is None:
            logger.warning("Cog Radio no encontrado — no se puede forzar reconexión")
            return {"triggered": False, "completed": False, "reason": "radio_cog_not_found"}

        from api.discord_bridge import DiscordBridgeTimeout, run_on_bot_loop
        try:
            await run_on_bot_loop(
                bot,
                lambda: (
                    radio_cog.restart_guild(guild_id)
                    if hasattr(radio_cog, "restart_guild")
                    else radio_cog.connect_guild(guild_id, restart_stream=True)
                ),
                timeout=15,
            )
        except DiscordBridgeTimeout:
            logger.warning("[radio] restart_guild(%s) disparado pero no confirmó antes del timeout", guild_id)
            return {"triggered": True, "completed": False, "reason": "timeout"}
        except Exception as exc:
            logger.exception("Error durante restart_guild(%s)", guild_id)
            return {"triggered": True, "completed": False, "reason": str(exc)[:200]}

        logger.info(f"[radio] restart_guild ejecutado para guild {guild_id}")
        return {"triggered": True, "completed": True}
    except Exception:
        logger.exception("Error al disparar reconexión de radio")
        return {"triggered": False, "completed": False, "reason": "trigger_error"}


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
