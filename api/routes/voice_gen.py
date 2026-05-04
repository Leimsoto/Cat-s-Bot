"""
api/routes/voice_gen.py
───────────────────────
Endpoints REST para el módulo de generación de canales de voz (JTC).

GET  /api/guilds/{guild_id}/voice-gen/config   → Obtiene configuración
PUT  /api/guilds/{guild_id}/voice-gen/config   → Actualiza configuración
GET  /api/guilds/{guild_id}/voice-gen/channels → Lista canales activos
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.deps import get_db, require_guild_admin

router = APIRouter(
    prefix="/api/guilds/{guild_id}/voice-gen",
    tags=["voice-gen"],
)


class VoiceGenConfigUpdate(BaseModel):
    enabled:              Optional[int]  = None
    generator_channel_id: Optional[int]  = None
    category_id:          Optional[int]  = None
    panel_channel_id:     Optional[int]  = None
    name_template:        Optional[str]  = None
    default_limit:        Optional[int]  = None


@router.get("/config")
async def get_voice_gen_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Obtiene la configuración actual del generador de VCs."""
    cfg = db.get_voice_gen_config(guild_id)
    return {"guild_id": guild_id, "config": cfg}


@router.put("/config")
async def update_voice_gen_config(
    guild_id: int,
    body: VoiceGenConfigUpdate,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del generador de VCs."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        db.set_voice_gen_config(guild_id, **updates)
    return {"status": "ok", "message": "Configuración de Voice Gen actualizada."}


@router.get("/channels")
async def get_voice_gen_channels(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista los canales de voz generados activos en el servidor."""
    channels = db.get_voice_gen_channels_by_guild(guild_id)
    return {"guild_id": guild_id, "active_channels": channels, "total": len(channels)}
