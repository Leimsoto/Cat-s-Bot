"""
api/routes/channels.py
──────────────────────
Endpoints para configurar el filtro multimedia y las autorreacciones de canales.

GET /api/guild/{guild_id}/channels              → Configs especiales de todos los canales
PUT /api/guild/{guild_id}/channels/{channel_id} → Actualizar la config de un canal
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db, require_guild_admin
from api.snowflakes import coerce_snowflake, stringify_rows
from pydantic import BaseModel, ConfigDict
from typing import Optional

router = APIRouter(prefix="/api/guild/{guild_id}/channels", tags=["channels"])

class ChannelConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_only: Optional[bool] = None
    media_config: Optional[str] = None
    auto_react: Optional[str] = None

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
    db.set_channel_config(coerce_snowflake(channel_id, "channel_id"), guild_id, **update_data)
        
    return {"status": "ok", "message": "Configuración de canal actualizada."}
