"""
api/routes/voice_gen.py
───────────────────────
Endpoints REST para el módulo Generador de VCs (Join To Create).

GET   /api/guilds/{guild_id}/voice-gen/config         → obtiene config
PATCH /api/guilds/{guild_id}/voice-gen/config         → actualiza config (parcial)
PUT   /api/guilds/{guild_id}/voice-gen/config         → alias compat
GET   /api/guilds/{guild_id}/voice-gen/channels       → lista VCs activos
POST  /api/guilds/{guild_id}/voice-gen/resend-panel   → publica/actualiza el panel permanente

Antes:
  • El frontend usaba apiPut pero la PATCH del nuevo flujo se quedaba sin
    handler. Ahora se aceptan ambos.
  • No había forma de reenviar el panel una vez perdido — endpoint nuevo.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_bot, get_db, require_guild_admin
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.snowflakes import coerce_optional_snowflake, stringify_fields, stringify_rows

router = APIRouter(
    prefix="/api/guilds/{guild_id}/voice-gen",
    tags=["voice-gen"],
)

_VG_KEYS = {
    "enabled",
    "generator_channel_id",
    "category_id",
    "panel_channel_id",
    "name_template",
    "default_limit",
    "panel_title",
    "panel_description",
    "panel_color",
    "auto_send_panel",
    "panel_embed_data",
}


class VoiceGenConfigUpdate(BaseModel):
    enabled:              Optional[int]  = None
    generator_channel_id: Optional[int | str]  = None
    category_id:          Optional[int | str]  = None
    panel_channel_id:     Optional[int | str]  = None
    name_template:        Optional[str]  = None
    default_limit:        Optional[int]  = None
    panel_title:          Optional[str]  = None
    panel_description:    Optional[str]  = None
    panel_color:          Optional[str]  = None
    auto_send_panel:      Optional[int]  = None
    # JSON serializado con la forma de MessageEditor (content + embed).
    panel_embed_data:     Optional[str]  = None


class ResendPanelBody(BaseModel):
    # Compatibilidad con clientes antiguos; el panel ya no pertenece a un VC.
    channel_id: Optional[int | str] = None


VG_CONFIG_ID_FIELDS = (
    "guild_id",
    "generator_channel_id",
    "category_id",
    "panel_channel_id",
    "panel_message_channel_id",
    "panel_message_id",
)
VG_CHANNEL_ID_FIELDS = (
    "guild_id",
    "channel_id",
    "owner_id",
    "panel_channel_id",
    "panel_message_id",
)


@router.get("/config")
async def get_voice_gen_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    cfg = db.get_voice_gen_config(guild_id)
    return {"guild_id": str(guild_id), "config": stringify_fields(cfg, VG_CONFIG_ID_FIELDS)}


@router.patch("/config")
async def patch_voice_gen_config(
    guild_id: int,
    body: VoiceGenConfigUpdate,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    payload = {
        k: v for k, v in body.model_dump().items() if v is not None and k in _VG_KEYS
    }
    for field in ("generator_channel_id", "category_id", "panel_channel_id"):
        if field in payload:
            payload[field] = coerce_optional_snowflake(payload[field], field)
    if payload:
        db.set_voice_gen_config(guild_id, **payload)
    return {
        "status": "ok",
        "updated": list(payload.keys()),
        "config": stringify_fields(db.get_voice_gen_config(guild_id), VG_CONFIG_ID_FIELDS),
    }


@router.put("/config")
async def put_voice_gen_config(
    guild_id: int,
    body: VoiceGenConfigUpdate,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    return await patch_voice_gen_config(guild_id, body, db, user)


@router.get("/channels")
async def get_voice_gen_channels(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    channels = db.get_voice_gen_channels_by_guild(guild_id)
    return {"guild_id": str(guild_id), "active_channels": stringify_rows(channels, VG_CHANNEL_ID_FIELDS), "total": len(channels)}


@router.post("/resend-panel")
async def resend_panel(
    guild_id: int,
    body: ResendPanelBody,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """
    Publica o actualiza el único panel permanente del servidor.

    El VC se resuelve cuando el propietario pulsa un botón, no al publicar el
    mensaje. `channel_id` se acepta únicamente por compatibilidad.
    """
    if bot is None:
        raise HTTPException(503, "Bot no conectado")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    cog = bot.get_cog("VoiceGen")
    if cog is None:
        raise HTTPException(503, "Cog VoiceGen no cargado")

    try:
        sent = await run_on_bot_loop(
            bot,
            lambda: cog.send_panel(guild, force=True),
            timeout=30,
        )
    except DiscordBridgeUnavailable as e:
        raise HTTPException(503, str(e))
    except DiscordBridgeTimeout as e:
        raise HTTPException(504, str(e))
    except Exception as e:
        raise HTTPException(500, f"No se pudo enviar el panel: {e}")

    if not sent:
        raise HTTPException(
            409,
            "Discord rechazó el panel o el canal configurado no está disponible",
        )

    return {"status": "ok"}
