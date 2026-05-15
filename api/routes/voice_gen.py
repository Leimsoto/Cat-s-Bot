"""
api/routes/voice_gen.py
───────────────────────
Endpoints REST para el módulo Generador de VCs (Join To Create).

GET   /api/guilds/{guild_id}/voice-gen/config         → obtiene config
PATCH /api/guilds/{guild_id}/voice-gen/config         → actualiza config (parcial)
PUT   /api/guilds/{guild_id}/voice-gen/config         → alias compat
GET   /api/guilds/{guild_id}/voice-gen/channels       → lista VCs activos
POST  /api/guilds/{guild_id}/voice-gen/resend-panel   → reenvía el panel a un VC

Antes:
  • El frontend usaba apiPut pero la PATCH del nuevo flujo se quedaba sin
    handler. Ahora se aceptan ambos.
  • No había forma de reenviar el panel una vez perdido — endpoint nuevo.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_bot, get_db, require_guild_admin

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
    generator_channel_id: Optional[int]  = None
    category_id:          Optional[int]  = None
    panel_channel_id:     Optional[int]  = None
    name_template:        Optional[str]  = None
    default_limit:        Optional[int]  = None
    panel_title:          Optional[str]  = None
    panel_description:    Optional[str]  = None
    panel_color:          Optional[str]  = None
    auto_send_panel:      Optional[int]  = None
    # JSON serializado con la forma de MessageEditor (content + embed).
    panel_embed_data:     Optional[str]  = None


class ResendPanelBody(BaseModel):
    channel_id: int


@router.get("/config")
async def get_voice_gen_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    cfg = db.get_voice_gen_config(guild_id)
    return {"guild_id": guild_id, "config": cfg}


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
    if payload:
        db.set_voice_gen_config(guild_id, **payload)
    return {"status": "ok", "updated": list(payload.keys())}


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
    return {"guild_id": guild_id, "active_channels": channels, "total": len(channels)}


@router.post("/resend-panel")
async def resend_panel(
    guild_id: int,
    body: ResendPanelBody,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """
    Reenvía el panel de control de un VC al canal de panel configurado.

    El front pasa el `channel_id` del VC dueño. El cog VoiceGen.send_panel
    construye el embed y los botones a partir de la config del guild.
    """
    if bot is None:
        raise HTTPException(503, "Bot no conectado")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    cog = bot.get_cog("VoiceGen")
    if cog is None:
        raise HTTPException(503, "Cog VoiceGen no cargado")

    vc = guild.get_channel(body.channel_id)
    if vc is None:
        raise HTTPException(404, "Canal no encontrado")

    row = db.get_voice_gen_channel(body.channel_id)
    if not row:
        raise HTTPException(404, "Ese canal no es un VC generado")

    try:
        await cog.send_panel(guild, vc, force=True)
    except Exception as e:
        raise HTTPException(500, f"No se pudo enviar el panel: {e}")

    return {"status": "ok"}
