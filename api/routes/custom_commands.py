"""
api/routes/custom_commands.py
─────────────────────────────
CRUD de comandos personalizados por guild.

GET    /api/guilds/{guild_id}/custom-commands           → listar todos
POST   /api/guilds/{guild_id}/custom-commands           → crear nuevo
PUT    /api/guilds/{guild_id}/custom-commands/{name}    → actualizar
DELETE /api/guilds/{guild_id}/custom-commands/{name}    → eliminar
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/custom-commands", tags=["custom_commands"])


@router.get("")
async def list_custom_commands(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista todos los comandos personalizados del servidor."""
    return {"commands": db.get_custom_commands(guild_id)}


@router.post("")
async def create_custom_command(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crear un comando personalizado."""
    body = await request.json()
    name = body.get("name", "").strip()
    trigger_type = body.get("trigger_type", "prefix")
    trigger_value = body.get("trigger_value", "").strip()
    actions = body.get("actions", [])
    conditions = body.get("conditions", {})
    creator_id = _user.get("user_id", 0)

    if not name:
        raise HTTPException(400, "name es requerido")
    if not trigger_value:
        raise HTTPException(400, "trigger_value es requerido")

    # DB espera JSON strings para conditions y actions
    actions_str = json.dumps(actions, ensure_ascii=False) if isinstance(actions, (list, dict)) else str(actions)
    conditions_str = json.dumps(conditions, ensure_ascii=False) if isinstance(conditions, (list, dict)) else str(conditions)

    result = db.create_custom_command(
        guild_id=guild_id,
        name=name,
        trigger_type=trigger_type,
        trigger_value=trigger_value,
        actions=actions_str,
        conditions=conditions_str,
        creator_id=creator_id,
    )
    return {"status": "ok", "command": result}


@router.put("/{name}")
async def update_custom_command(
    guild_id: int,
    name: str,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualizar un comando personalizado."""
    body = await request.json()
    allowed = {"trigger_type", "trigger_value", "actions", "conditions", "enabled"}
    filtered = {}
    for k, v in body.items():
        if k not in allowed:
            continue
        # Serializar listas/dicts a JSON string para la DB
        if k in ("actions", "conditions") and isinstance(v, (list, dict)):
            filtered[k] = json.dumps(v, ensure_ascii=False)
        else:
            filtered[k] = v

    if not filtered:
        return {"status": "noop"}
    db.update_custom_command(guild_id, name, **filtered)
    return {"status": "ok", "updated": list(filtered.keys())}


@router.delete("/{name}")
async def delete_custom_command(
    guild_id: int,
    name: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Eliminar un comando personalizado."""
    db.delete_custom_command(guild_id, name)
    return {"status": "ok"}
