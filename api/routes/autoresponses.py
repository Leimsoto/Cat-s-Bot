"""
api/routes/autoresponses.py
───────────────────────────
CRUD de auto-respuestas por guild.

GET    /api/guilds/{guild_id}/autoresponses          → listar todas
POST   /api/guilds/{guild_id}/autoresponses          → crear nueva
DELETE /api/guilds/{guild_id}/autoresponses/{ar_id}  → eliminar
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/autoresponses", tags=["autoresponses"])


@router.get("")
async def list_autoresponses(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista todas las auto-respuestas del servidor."""
    return {"autoresponses": db.get_autoresponses(guild_id)}


@router.post("")
async def create_autoresponse(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crear una nueva auto-respuesta."""
    body = await request.json()
    trigger = body.get("trigger", "").strip()
    response = body.get("response", "").strip()
    channel_id = body.get("channel_id")

    if not trigger or not response:
        raise HTTPException(400, "trigger y response son requeridos")

    ar_id = db.add_autoresponse(guild_id, channel_id, trigger, response)
    return {"status": "ok", "id": ar_id}


@router.delete("/{ar_id}")
async def delete_autoresponse(
    guild_id: int,
    ar_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Eliminar una auto-respuesta."""
    db.remove_autoresponse(ar_id)
    return {"status": "ok"}
