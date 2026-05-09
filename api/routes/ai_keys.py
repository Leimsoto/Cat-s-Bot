"""
api/routes/ai_keys.py
─────────────────────
Gestión del pool de API keys de IA.

Endpoints globales (master admin):
  GET    /api/ai/keys                              → lista del pool (api_key enmascarada)
  POST   /api/ai/keys                              → añade una key
  PATCH  /api/ai/keys/{key_id}                     → actualiza label/active/notes
  DELETE /api/ai/keys/{key_id}                     → elimina key (cascade asignaciones)
  GET    /api/ai/keys/health                       → reporte rápido del pool

Endpoints por guild (admin del guild):
  GET    /api/guilds/{guild_id}/ia/key             → key asignada al guild (enmascarada)
  POST   /api/guilds/{guild_id}/ia/key             → asigna {"key_id": <id>}
  DELETE /api/guilds/{guild_id}/ia/key             → desasigna

Reglas de negocio (impuestas en DatabaseManager):
  • Cada guild tiene como máximo una key (PRIMARY KEY).
  • Cada key cubre como máximo 2 guilds.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin, require_master_admin

logger = logging.getLogger("API.ai_keys")

router_admin = APIRouter(prefix="/api/ai/keys", tags=["ai-keys"])
router_guild = APIRouter(prefix="/api/guilds", tags=["ai-keys"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class AIKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=8, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class AIKeyUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    active: int | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=8, max_length=255)


class AssignKeyBody(BaseModel):
    key_id: int = Field(..., ge=1)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mask_key(api_key: str) -> str:
    """Enmascara la api_key dejando solo los últimos 4 caracteres visibles."""
    if not api_key or len(api_key) < 8:
        return "••••"
    return f"{api_key[:4]}…{api_key[-4:]}"


def _serialize_key(row: dict) -> dict:
    """Devuelve una key sin exponer la api_key completa al cliente."""
    return {
        "id": row.get("id"),
        "label": row.get("label"),
        "api_key_preview": _mask_key(row.get("api_key", "")),
        "active": int(row.get("active", 0)),
        "notes": row.get("notes"),
        "created_at": row.get("created_at"),
        "guilds_assigned": int(row.get("guilds_assigned", 0)),
    }


# ── Endpoints globales ───────────────────────────────────────────────────────


@router_admin.get("")
async def list_keys(
    db=Depends(get_db),
    _user: dict = Depends(require_master_admin),
):
    keys = db.list_ai_keys()
    return {"keys": [_serialize_key(k) for k in keys]}


@router_admin.get("/health")
async def pool_health(
    db=Depends(get_db),
    _user: dict = Depends(require_master_admin),
):
    return db.ai_key_pool_health()


@router_admin.post("")
async def create_key(
    body: AIKeyCreate,
    db=Depends(get_db),
    _user: dict = Depends(require_master_admin),
):
    try:
        new_id = db.add_ai_key(body.label, body.api_key, body.notes)
    except Exception as e:
        # El UNIQUE constraint de api_key produce IntegrityError en sqlite/maria
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg:
            raise HTTPException(409, "Esa API key ya está registrada en el pool")
        logger.exception("Error añadiendo ai_api_key")
        raise HTTPException(500, "No se pudo añadir la key")
    return {"status": "ok", "id": new_id}


@router_admin.patch("/{key_id}")
async def patch_key(
    key_id: int,
    body: AIKeyUpdate,
    db=Depends(get_db),
    _user: dict = Depends(require_master_admin),
):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        return {"status": "ok", "updated": []}
    if not db.get_ai_key(key_id):
        raise HTTPException(404, "Key no encontrada")
    try:
        db.update_ai_key(key_id, **payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "updated": list(payload.keys())}


@router_admin.delete("/{key_id}")
async def delete_key(
    key_id: int,
    db=Depends(get_db),
    _user: dict = Depends(require_master_admin),
):
    if not db.get_ai_key(key_id):
        raise HTTPException(404, "Key no encontrada")
    db.delete_ai_key(key_id)
    return {"status": "ok"}


# ── Endpoints por guild ──────────────────────────────────────────────────────


@router_guild.get("/{guild_id}/ia/key")
async def get_guild_key(
    guild_id: int,
    db=Depends(get_db),
    _user: dict = Depends(require_guild_admin),
):
    assigned = db.get_ai_key_for_guild(guild_id)
    if not assigned:
        return {"assigned": None}
    return {
        "assigned": {
            "id": assigned["id"],
            "label": assigned["label"],
            "api_key_preview": _mask_key(assigned.get("api_key", "")),
            "active": int(assigned.get("active", 0)),
            "assigned_at": assigned.get("assigned_at"),
        }
    }


@router_guild.post("/{guild_id}/ia/key")
async def assign_guild_key(
    guild_id: int,
    body: AssignKeyBody,
    db=Depends(get_db),
    _user: dict = Depends(require_guild_admin),
):
    """
    Asigna una key existente al guild. Reglas:
      • La key debe existir y estar activa.
      • La key no debe haber alcanzado su capacidad máxima de guilds.

    Si el guild ya tenía otra key, se reemplaza.
    """
    try:
        db.assign_ai_key_to_guild(guild_id, body.key_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@router_guild.delete("/{guild_id}/ia/key")
async def unassign_guild_key(
    guild_id: int,
    db=Depends(get_db),
    _user: dict = Depends(require_guild_admin),
):
    db.unassign_ai_key_from_guild(guild_id)
    return {"status": "ok"}
