"""
api/routes/moderation.py
────────────────────────
Endpoints de moderación.

GET   /api/guild/{guild_id}/moderation/actions          → historial (paginado)
GET   /api/guild/{guild_id}/moderation/user/{user_id}   → historial de un usuario
GET   /api/guild/{guild_id}/moderation/warns            → usuarios con warns activos
GET   /api/moderation/{guild_id}/cases                  → casos para Logs/Moderación
GET   /api/moderation/{guild_id}/appeals                → lista de apelaciones
PATCH /api/moderation/{guild_id}/appeals/{appeal_id}    → cambiar estado de apelación
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from api.deps import get_bot, get_db, require_guild_admin

logger = logging.getLogger("API.moderation")

router = APIRouter(prefix="/api/guild/{guild_id}/moderation", tags=["moderation"])

# Alias dashboard-friendly: el panel pide /api/moderation/{id}/cases
cases_router = APIRouter(prefix="/api/moderation", tags=["moderation"])


@cases_router.get("/{guild_id}/cases")
async def get_mod_cases(
    guild_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Casos de moderación normalizados para el dashboard.

    Expone los mismos registros que `/api/guild/{id}/moderation/actions`
    pero con la forma que esperan `Logs.jsx` y `Moderation.jsx` (campo
    `action` además de `action_type`, y respuesta como lista directa).
    """
    rows = db.get_mod_actions(guild_id, limit=limit, offset=offset) or []
    out = []
    for row in rows:
        item = dict(row)
        item.setdefault("action", item.get("action_type"))
        out.append(item)
    return out


@router.get("/actions")
async def get_mod_actions(
    guild_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista de acciones de moderación del servidor (paginado)."""
    actions = db.get_mod_actions(guild_id, limit=limit, offset=offset)
    return {"guild_id": guild_id, "actions": actions, "limit": limit, "offset": offset}


@router.get("/user/{user_id}")
async def get_user_mod_history(
    guild_id: int,
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Historial de moderación de un usuario específico."""
    history = db.get_user_history(user_id, guild_id, limit=limit)
    summary = db.get_user_action_summary(user_id, guild_id)
    user_record = db.get_user(user_id, guild_id)

    return {
        "guild_id": guild_id,
        "user_id": user_id,
        "user_record": user_record,
        "summary": summary,
        "history": history,
    }


@router.get("/warns")
async def get_active_warns(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista de usuarios con warns activos en el servidor."""
    users = db.get_users_with_warns(guild_id)
    return {"guild_id": guild_id, "users_with_warns": users}


# ── Appeals ──────────────────────────────────────────────────────────────────


@cases_router.get("/{guild_id}/appeals")
async def list_appeals(
    guild_id: int,
    status: Optional[str] = Query(None, description="PENDING | ACCEPTED | REJECTED"),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Devuelve las apelaciones del servidor, opcionalmente filtradas por estado."""
    rows = db.get_appeals_by_guild(guild_id, status=status) or []
    return [dict(row) for row in rows]


@cases_router.patch("/{guild_id}/appeals/{appeal_id}")
async def update_appeal(
    guild_id: int,
    appeal_id: int,
    body: dict,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Acepta o rechaza una apelación.

    Body: ``{"status": "ACCEPTED" | "REJECTED", "mod_message"?: str, "auto_remove"?: bool}``

    Si ``auto_remove`` y la sanción es ``WARN`` o ``MUTE``, intenta quitarla
    a través del bot. ``BAN`` queda fuera del flujo automático para evitar
    desbaneos por error desde el dashboard.
    """
    new_status = (body.get("status") or "").upper()
    if new_status not in {"ACCEPTED", "REJECTED"}:
        raise HTTPException(400, "status debe ser ACCEPTED o REJECTED")

    appeal = db.get_appeal(appeal_id)
    if not appeal or appeal.get("guild_id") != guild_id:
        raise HTTPException(404, "Apelación no encontrada")
    if appeal.get("status") and appeal["status"].upper() != "PENDING":
        raise HTTPException(409, f"La apelación ya está en estado {appeal['status']}")

    db.update_appeal_status(appeal_id, new_status)

    auto_remove = bool(body.get("auto_remove"))
    action_taken = None
    if new_status == "ACCEPTED" and auto_remove and bot is not None:
        action_type = (appeal.get("action_type") or "").upper()
        user_id = appeal.get("user_id")
        guild = bot.get_guild(guild_id)
        if guild and user_id:
            member = guild.get_member(user_id)
            if action_type == "WARN" and member:
                try:
                    db.clear_warns(user_id, guild_id)
                    action_taken = "warns_cleared"
                except Exception as exc:
                    logger.warning("No se pudieron limpiar warns: %s", exc)
            elif action_type == "MUTE" and member:
                cfg = db.get_config(guild_id) or {}
                role_id = cfg.get("mute_role_id") or 0
                role = guild.get_role(role_id)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Apelación aceptada")
                        db.clear_mute(user_id, guild_id)
                        action_taken = "unmuted"
                    except Exception as exc:
                        logger.warning("No se pudo quitar mute: %s", exc)

    return {
        "id": appeal_id,
        "status": new_status,
        "action_taken": action_taken,
    }
