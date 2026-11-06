"""
api/routes/channels.py
──────────────────────
Endpoints para configurar el filtro multimedia y las autorreacciones de canales.

GET /api/guild/{guild_id}/channels              → Configs especiales de todos los canales
PUT /api/guild/{guild_id}/channels/{channel_id} → Actualizar la config de un canal
"""

import json
import discord
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_bot, get_db, require_guild_admin
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.snowflakes import stringify_rows
from cogs.channels import validate_auto_reactions
from pydantic import BaseModel, ConfigDict, StrictBool
from typing import Optional

router = APIRouter(prefix="/api/guild/{guild_id}/channels", tags=["channels"])

class ChannelConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_only: Optional[bool] = None
    media_config: Optional[str] = None
    auto_react: Optional[str] = None
    auto_react_enabled: Optional[StrictBool] = None

@router.get("")
async def get_all_channel_configs(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Obtiene una lista de todos los canales que tienen configuración especial guardada."""
    channels = db.get_all_channel_configs(guild_id)
    return {
        "guild_id": str(guild_id),
        "channels": stringify_rows(channels, ("guild_id", "channel_id"))
    }

@router.put("/{channel_id}")
async def update_channel_config(
    guild_id: int,
    channel_id: str,
    body: ChannelConfigUpdate,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
    bot=Depends(get_bot),
):
    """Actualiza las opciones que consumen los listeners de canales."""
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "Sin campos para actualizar")
    for field in ("media_config", "auto_react"):
        if field not in update_data:
            continue
        try:
            value = json.loads(update_data[field])
        except (ValueError, TypeError):
            raise HTTPException(400, f"{field} debe contener JSON válido")
        if field == "media_config":
            types = value.get("allowed_types") if isinstance(value, dict) else None
            if not isinstance(types, list) or not types or any(item not in ("image", "video", "audio", "application") for item in types):
                raise HTTPException(400, "allowed_types debe contener tipos multimedia válidos")
        elif not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise HTTPException(400, "auto_react debe ser una lista de emojis")
    if not channel_id.isascii() or not channel_id.isdecimal() or not 0 < int(channel_id) < 2**63:
        raise HTTPException(400, "channel_id inválido")
    ident = int(channel_id)
    previous = db.get_channel_config(ident)
    if previous.get("guild_id") not in (None, guild_id):
        raise HTTPException(400, "El canal no pertenece a este servidor.")
    # Permitir pausar/quitar una config propia aunque su canal ya no exista.
    disabling_existing = (
        previous.get("guild_id") == guild_id
        and set(update_data) <= {"auto_react", "auto_react_enabled"}
        and update_data.get("auto_react_enabled") is False
        and ("auto_react" not in update_data or json.loads(update_data["auto_react"]) == [])
    )

    async def validate_channel():
        guild = bot.get_guild(guild_id)
        if guild is None:
            raise HTTPException(409, "El bot no está conectado a este servidor.")
        channel = guild.get_channel(ident)
        if channel is None:
            try:
                channel = await guild.fetch_channel(ident)
            except (discord.NotFound, discord.Forbidden):
                raise HTTPException(400, "Canal no disponible en este servidor.")
        if getattr(getattr(channel, "guild", None), "id", None) != guild_id or channel.type not in (
            discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.public_thread,
            discord.ChannelType.private_thread, discord.ChannelType.news_thread,
        ):
            raise HTTPException(400, "Elige un canal de texto o un hilo de este servidor.")
        if "auto_react" in update_data or update_data.get("auto_react_enabled"):
            try:
                emojis = json.loads(update_data.get("auto_react", previous.get("auto_react")) or "[]")
                await validate_auto_reactions(bot, guild, channel, emojis,
                                              enabled=update_data.get("auto_react_enabled", previous.get("auto_react_enabled", 1)))
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc))

    try:
        if not disabling_existing:
            await run_on_bot_loop(bot, validate_channel)
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    except discord.HTTPException:
        raise HTTPException(502, "No pude comprobar el canal o los emojis con Discord.")
    db.set_channel_config(ident, guild_id, **update_data)
    return {"status": "ok", "message": "Configuración de canal actualizada.",
            "channel": stringify_rows([db.get_channel_config(ident)], ("guild_id", "channel_id"))[0]}
