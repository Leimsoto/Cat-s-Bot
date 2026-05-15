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
    """Crear un comando personalizado.

    Body soportado:
      name (str)              requerido
      response_data (str)     JSON serializado MessageEditor (preferido)
      permission_data (dict)  ``{everyone: bool, role_ids: [int]}``
      delete_invocation (bool)
      actions (list)          legacy fallback
      conditions (dict)       legacy
    """
    body = await request.json()
    name = (body.get("name") or "").strip().lower()
    response_data = body.get("response_data")
    actions = body.get("actions") or []
    conditions = body.get("conditions") or {}
    permission_data = body.get("permission_data") or {"everyone": True, "role_ids": []}
    delete_invocation = 1 if body.get("delete_invocation") else 0
    creator_id = _user.get("user_id", 0)

    if not name or " " in name:
        raise HTTPException(400, "name es requerido y sin espacios")
    if not response_data and not actions:
        raise HTTPException(400, "Debes proporcionar response_data o actions")

    actions_str = json.dumps(actions, ensure_ascii=False) if isinstance(actions, (list, dict)) else str(actions)
    conditions_str = json.dumps(conditions, ensure_ascii=False) if isinstance(conditions, (list, dict)) else str(conditions)
    permission_str = json.dumps(permission_data, ensure_ascii=False)

    result = db.create_custom_command(
        guild_id=guild_id,
        name=name,
        trigger_type="prefix",
        trigger_value=name,
        actions=actions_str,
        conditions=conditions_str,
        creator_id=creator_id,
    )
    # Persistir nuevas columnas con update.
    try:
        db.update_custom_command(
            guild_id, name,
            response_data=response_data,
            permission_data=permission_str,
            delete_invocation=delete_invocation,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
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
    allowed = {
        "trigger_type", "trigger_value", "actions", "conditions",
        "enabled", "response_data", "permission_data", "delete_invocation",
    }
    filtered = {}
    for k, v in body.items():
        if k not in allowed:
            continue
        if k in ("actions", "conditions", "permission_data") and isinstance(v, (list, dict)):
            filtered[k] = json.dumps(v, ensure_ascii=False)
        elif k == "delete_invocation":
            filtered[k] = 1 if v else 0
        else:
            filtered[k] = v

    if not filtered:
        return {"status": "noop"}
    try:
        db.update_custom_command(guild_id, name.lower(), **filtered)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
