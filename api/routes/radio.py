"""
api/routes/radio.py
───────────────────
Endpoints para configuración de la radio Lofi 24/7.

GET   /api/guilds/{guild_id}/radio/config   → obtiene config
PATCH /api/guilds/{guild_id}/radio/config   → actualiza config (solo campos enviados)

Antes:
  • Prefix singular (`/api/guild/...`) — el dashboard llama plural y devolvía 404.
  • Solo PUT — el dashboard envía PATCH y devolvía 405.
  • Body Pydantic estricto sin `auto_reconnect` ni `pause_on_empty`.
Estos tres detalles hacían que la página de Radio no guardase nada.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_db, require_guild_admin

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
    channel_id: Optional[int] = None
    stream_url: Optional[str] = None
    station_name: Optional[str] = None
    volume: Optional[int] = None
    auto_reconnect: Optional[int] = None
    pause_on_empty: Optional[int] = None


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
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza solo los campos enviados (None = no tocar)."""
    payload = {
        k: v
        for k, v in body.model_dump().items()
        if v is not None and k in _LOFI_KEYS
    }
    if payload:
        db.set_lofi_config(guild_id, **payload)
    return {"status": "ok", "updated": list(payload.keys())}


# Mantenemos PUT como alias por compat (algún cliente externo podría usarlo).
@router.put("/config")
async def put_radio_config(
    guild_id: int,
    body: RadioConfigUpdate,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    return await patch_radio_config(guild_id, body, db, user)
