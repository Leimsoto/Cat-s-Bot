"""
api/routes/autoroles.py
───────────────────────
Endpoints para Autoroles.

Dos modos:
  • Join autoroles: roles que se asignan al entrar al servidor.
  • Reaction roles: paneles donde el usuario reacciona para obtener un rol.

Endpoints:
  GET    /api/guilds/{guild_id}/autoroles/join              → Lista de roles join
  POST   /api/guilds/{guild_id}/autoroles/join              → Agrega rol join
  DELETE /api/guilds/{guild_id}/autoroles/join/{role_id}    → Quita rol join

  GET    /api/guilds/{guild_id}/autoroles/reactions                  → Paneles
  POST   /api/guilds/{guild_id}/autoroles/reactions                  → Crear/actualizar panel
  DELETE /api/guilds/{guild_id}/autoroles/reactions/{message_id}     → Eliminar panel
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin

router = APIRouter(
    prefix="/api/guilds/{guild_id}/autoroles",
    tags=["autoroles"],
)


# ── Join Autoroles ───────────────────────────────────────────────────────────

class JoinRoleBody(BaseModel):
    role_id: int = Field(..., description="ID del rol a asignar al unirse")


@router.get("/join")
async def list_join_roles(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista los roles configurados para asignación al unirse."""
    rows = db.get_join_autoroles(guild_id)
    return {"guild_id": guild_id, "join_roles": rows}


@router.post("/join")
async def add_join_role(
    guild_id: int,
    body: JoinRoleBody,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Agrega un rol a la lista de auto-asignación."""
    db.add_join_autorole(guild_id, body.role_id)
    return {"status": "ok", "role_id": body.role_id}


@router.delete("/join/{role_id}")
async def remove_join_role(
    guild_id: int,
    role_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Quita un rol de la lista de auto-asignación."""
    db.remove_join_autorole(guild_id, role_id)
    return {"status": "ok", "role_id": role_id}


# ── Reaction Roles ───────────────────────────────────────────────────────────

class ReactionPanelBody(BaseModel):
    message_id: int
    channel_id: int
    mapping_data: str = Field(..., description="JSON: {emoji: role_id}")


@router.get("/reactions")
async def list_reaction_panels(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista todos los paneles de reaction-role configurados."""
    panels = db.get_guild_autoroles(guild_id)
    return {"guild_id": guild_id, "panels": panels}


@router.post("/reactions")
async def upsert_reaction_panel(
    guild_id: int,
    body: ReactionPanelBody,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crea o actualiza un panel de reaction-role."""
    try:
        json.loads(body.mapping_data)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="El campo mapping_data debe ser un JSON válido.",
        )

    db.set_autorole(
        message_id=body.message_id,
        guild_id=guild_id,
        channel_id=body.channel_id,
        mapping_data=body.mapping_data,
    )
    return {"status": "ok", "message_id": body.message_id}


@router.delete("/reactions/{message_id}")
async def delete_reaction_panel(
    guild_id: int,
    message_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina un panel de reaction-role."""
    panel = db.get_autorole(message_id)
    if not panel or int(panel.get("guild_id", 0)) != guild_id:
        raise HTTPException(status_code=404, detail="Panel no encontrado en este servidor.")
    db.delete_autorole(message_id)
    return {"status": "ok", "message_id": message_id}
