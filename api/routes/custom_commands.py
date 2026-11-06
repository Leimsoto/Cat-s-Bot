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


def _normalize_permission_data(value):
    if not value:
        return {"everyone": True, "role_ids": []}
    try:
        data = json.loads(value) if isinstance(value, str) else dict(value)
    except Exception:
        return {"everyone": False, "role_ids": []}
    if not isinstance(data, dict):
        return {"everyone": False, "role_ids": []}
    role_ids = data.get("role_ids") or []
    if not isinstance(role_ids, list):
        role_ids = []
    data["role_ids"] = [str(rid) for rid in role_ids if rid not in (None, "")]
    data["everyone"] = bool(data.get("everyone", True))
    return data


def _command_payload(row):
    out = dict(row)
    if "guild_id" in out and out.get("guild_id") not in (None, ""):
        out["guild_id"] = str(out["guild_id"])
    out["permission_data"] = _normalize_permission_data(out.get("permission_data"))
    return out


@router.get("")
async def list_custom_commands(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista todos los comandos personalizados del servidor."""
    return {"commands": [_command_payload(c) for c in db.get_custom_commands(guild_id)]}


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
    permission_data = _normalize_permission_data(body.get("permission_data") or {"everyone": True, "role_ids": []})
    delete_invocation = 1 if body.get("delete_invocation") else 0
    enabled = 1 if body.get("enabled", True) else 0
    creator_id = _user.get("user_id", 0)

    if not name or " " in name:
        raise HTTPException(400, "name es requerido y sin espacios")
    if db.get_custom_command(guild_id, name):
        raise HTTPException(409, "Ya existe un comando con ese nombre")
    if not response_data and not actions:
        raise HTTPException(400, "Debes proporcionar response_data o actions")

    actions_str = json.dumps(actions, ensure_ascii=False) if isinstance(actions, (list, dict)) else str(actions)
    conditions_str = json.dumps(conditions, ensure_ascii=False) if isinstance(conditions, (list, dict)) else str(conditions)
    permission_str = json.dumps(permission_data, ensure_ascii=False)

    db.create_custom_command(
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
            enabled=enabled,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "command": _command_payload(db.get_custom_command(guild_id, name))}


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
        if k == "permission_data":
            filtered[k] = json.dumps(_normalize_permission_data(v), ensure_ascii=False)
        elif k in ("actions", "conditions") and isinstance(v, (list, dict)):
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
