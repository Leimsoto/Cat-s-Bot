"""
api/routes/autoresponses.py
───────────────────────────
CRUD de auto-respuestas por guild.

GET    /api/guilds/{guild_id}/autoresponses          → listar todas
POST   /api/guilds/{guild_id}/autoresponses          → crear nueva
PATCH  /api/guilds/{guild_id}/autoresponses/{ar_id}  → actualizar parcial
DELETE /api/guilds/{guild_id}/autoresponses/{ar_id}  → eliminar
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/autoresponses", tags=["autoresponses"])

MATCH_TYPES = {"contains", "exact", "word", "starts_with", "regex"}


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
    """Crear una nueva auto-respuesta.

    Body:
      trigger (str)            requerido
      response (str)           texto plano legacy (puede estar vacío si hay response_data)
      response_data (str|None) JSON serializado del MessageEditor
      channel_id (int|None)
      match_type (str)         "contains" | "exact" | "word" | "starts_with" | "regex"
      case_sensitive (bool)
      enabled (bool)
    """
    body = await request.json()
    trigger = (body.get("trigger") or "").strip()
    response = (body.get("response") or "").strip()
    response_data = body.get("response_data") or None
    channel_id = body.get("channel_id")
    match_type = (body.get("match_type") or "contains").lower()
    if match_type not in MATCH_TYPES:
        raise HTTPException(400, f"match_type inválido. Valores: {sorted(MATCH_TYPES)}")
    case_sensitive = 1 if body.get("case_sensitive") else 0
    enabled = 1 if body.get("enabled", True) else 0

    if not trigger:
        raise HTTPException(400, "trigger es requerido")
    if not response and not response_data:
        raise HTTPException(400, "Debes proporcionar response o response_data")

    ar_id = db.add_autoresponse(
        guild_id, channel_id, trigger, response or "",
        match_type=match_type,
        case_sensitive=case_sensitive,
        response_data=response_data,
        enabled=enabled,
    )
    return {"status": "ok", "id": ar_id}


@router.patch("/{ar_id}")
async def update_autoresponse(
    guild_id: int,
    ar_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza campos parciales de una auto-respuesta existente."""
    body = await request.json()
    payload = {}
    if "trigger" in body:
        payload["trigger"] = (body["trigger"] or "").strip()
    if "response" in body:
        payload["response"] = body["response"] or ""
    if "response_data" in body:
        payload["response_data"] = body["response_data"] or None
    if "channel_id" in body:
        payload["channel_id"] = body["channel_id"]
    if "match_type" in body:
        mt = (body["match_type"] or "contains").lower()
        if mt not in MATCH_TYPES:
            raise HTTPException(400, f"match_type inválido. Valores: {sorted(MATCH_TYPES)}")
        payload["match_type"] = mt
    if "case_sensitive" in body:
        payload["case_sensitive"] = 1 if body["case_sensitive"] else 0
    if "enabled" in body:
        payload["enabled"] = 1 if body["enabled"] else 0

    if not payload:
        raise HTTPException(400, "Sin campos válidos para actualizar")

    try:
        db.update_autoresponse(ar_id, **payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


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
