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

import asyncio
import json
import logging
from typing import Any, Optional

import discord
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from api.deps import get_bot, get_db, require_guild_admin
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.snowflakes import stringify_fields, stringify_rows
from cogs._role_safety import (
    delegated_bot_role_ids,
    safe_for_automatic_assignment,
    safe_for_automatic_removal,
)
from cogs._sanction_locks import sanction_lock
from cogs._moderation_history import IdentityResolver as _IdentityResolver, moderation_details, record_extra

logger = logging.getLogger("API.moderation")

router = APIRouter(prefix="/api/guild/{guild_id}/moderation", tags=["moderation"])

# Alias dashboard-friendly: el panel pide /api/moderation/{id}/cases
cases_router = APIRouter(prefix="/api/moderation", tags=["moderation"])


def _case_payload(row: dict) -> dict:
    """Normaliza nombres para dashboard/API sin cambiar el schema interno."""
    item = dict(row)
    item.setdefault("action", item.get("action_type"))
    item.setdefault("user_id", item.get("target_id"))
    item.setdefault("mod_id", item.get("moderator_id"))
    item.setdefault("case", item.get("case_number") or item.get("id"))
    return stringify_fields(
        item,
        ("guild_id", "target_id", "moderator_id", "user_id", "mod_id", "parent_case_id"),
    )


def _pending_payload(row: dict) -> dict:
    return stringify_fields(row, ("guild_id", "user_id", "case_id"))


async def _enrich_case_payload(row: dict, resolver: _IdentityResolver) -> dict:
    item = _case_payload(row)
    item.update(moderation_details(row))
    extra = record_extra(row)
    target = await resolver.resolve(item.get("target_id") or item.get("user_id"), extra.get("target_user"))
    moderator = await resolver.resolve(item.get("moderator_id") or item.get("mod_id"), extra.get("moderator_user"))
    item["target_user"] = target
    item["moderator_user"] = moderator
    item["target_display"] = target.get("display")
    item["target_tag"] = target.get("tag")
    item["target_avatar_url"] = target.get("avatar_url")
    item["moderator_display"] = moderator.get("display")
    item["moderator_tag"] = moderator.get("tag")
    item["moderator_avatar_url"] = moderator.get("avatar_url")
    return item


async def _enrich_pending_payload(row: dict, resolver: _IdentityResolver) -> dict:
    item = _pending_payload(row)
    target = await resolver.resolve(item.get("user_id"))
    item["target_user"] = target
    item["target_display"] = target.get("display")
    item["target_tag"] = target.get("tag")
    item["target_avatar_url"] = target.get("avatar_url")
    return item


async def _enrich_appeal_payload(row: dict, resolver: _IdentityResolver) -> dict:
    item = stringify_fields(row, ("guild_id", "user_id", "reviewer_id", "case_id"))
    user = await resolver.resolve(item.get("user_id"))
    reviewer = await resolver.resolve(item.get("reviewer_id"))
    item["user"] = user
    item["user_display"] = user.get("display")
    item["user_tag"] = user.get("tag")
    item["user_avatar_url"] = user.get("avatar_url")
    item["reviewer"] = reviewer
    item["reviewer_display"] = reviewer.get("display")
    item["reviewer_tag"] = reviewer.get("tag")
    return item


@cases_router.get("/{guild_id}/cases")
async def get_mod_cases(
    guild_id: int,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: Optional[int] = Query(None),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Casos de moderación normalizados para el dashboard.

    Expone los mismos registros que `/api/guild/{id}/moderation/actions`
    pero con la forma que esperan `Logs.jsx` y `Moderation.jsx` (campo
    `action` además de `action_type`, y respuesta como lista directa).
    """
    if hasattr(db, "list_cases"):
        rows = db.list_cases(guild_id, user_id=user_id, limit=limit, offset=offset) or []
    else:
        rows = db.get_mod_actions(guild_id, limit=limit, offset=offset) or []
    resolver = _IdentityResolver(bot, guild_id)
    return [await _enrich_case_payload(row, resolver) for row in rows]


@cases_router.get("/{guild_id}/cases/{case_ref}")
async def get_mod_case_detail(
    guild_id: int,
    case_ref: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    case = db.get_case(guild_id, case_ref) if hasattr(db, "get_case") else None
    if not case:
        raise HTTPException(404, "Caso no encontrado")
    return await _enrich_case_payload(case, _IdentityResolver(bot, guild_id))


@cases_router.patch("/{guild_id}/cases/{case_ref}")
async def update_mod_case(
    guild_id: int,
    case_ref: int,
    body: dict,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    allowed = {"reason", "evidence_url", "status", "extra_data"}
    payload = {k: v for k, v in body.items() if k in allowed}
    if "status" in payload:
        status = str(payload["status"]).lower().strip()
        if status not in {"active", "expired", "revoked", "failed"}:
            raise HTTPException(400, "status inválido")
        payload["status"] = status
    case = db.update_case(guild_id, case_ref, **payload) if hasattr(db, "update_case") else None
    if not case:
        raise HTTPException(404, "Caso no encontrado")
    return await _enrich_case_payload(case, _IdentityResolver(bot, guild_id))


@cases_router.get("/{guild_id}/moderations")
async def get_active_moderations(
    guild_id: int,
    limit: int = Query(100, ge=1, le=200),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    cases = db.get_active_moderations(guild_id, limit=limit) if hasattr(db, "get_active_moderations") else []
    pending = db.get_pending_moderation_actions(guild_id, limit=limit) if hasattr(db, "get_pending_moderation_actions") else []
    resolver = _IdentityResolver(bot, guild_id)
    return {
        "cases": [await _enrich_case_payload(row, resolver) for row in (cases or [])],
        "pending": [await _enrich_pending_payload(row, resolver) for row in (pending or [])],
    }


@router.get("/actions")
async def get_mod_actions(
    guild_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Lista de acciones de moderación del servidor (paginado)."""
    actions = db.get_mod_actions(guild_id, limit=limit, offset=offset)
    resolver = _IdentityResolver(bot, guild_id)
    return {"guild_id": str(guild_id), "actions": [await _enrich_case_payload(row, resolver) for row in actions], "limit": limit, "offset": offset}


@router.get("/user/{user_id}")
async def get_user_mod_history(
    guild_id: int,
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Historial de moderación de un usuario específico."""
    history = db.get_user_history(user_id, guild_id, limit=limit)
    summary = db.get_user_action_summary(user_id, guild_id)
    user_record = db.get_user(user_id, guild_id)

    resolver = _IdentityResolver(bot, guild_id)
    return {
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "user": await resolver.resolve(user_id),
        "user_record": stringify_fields(user_record, ("guild_id", "user_id")) if user_record else None,
        "summary": summary,
        "history": [await _enrich_case_payload(row, resolver) for row in history],
    }


@router.get("/warns")
async def get_active_warns(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Lista de usuarios con warns activos en el servidor."""
    users = db.get_users_with_warns(guild_id)
    resolver = _IdentityResolver(bot, guild_id)
    enriched = []
    for row in stringify_rows(users, ("guild_id", "user_id")):
        payload = dict(row)
        identity = await resolver.resolve(payload.get("user_id"))
        payload["user"] = identity
        payload["user_display"] = identity.get("display")
        payload["user_tag"] = identity.get("tag")
        enriched.append(payload)
    return {"guild_id": str(guild_id), "users_with_warns": enriched}


# ── Appeals ──────────────────────────────────────────────────────────────────


@cases_router.get("/{guild_id}/appeals")
async def list_appeals(
    guild_id: int,
    status: Optional[str] = Query(None, description="PENDING | ACCEPTED | DENIED"),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Devuelve las apelaciones del servidor, opcionalmente filtradas por estado."""
    if status:
        status = status.upper()
        if status == "REJECTED":
            status = "DENIED"
    rows = db.get_appeals_by_guild(guild_id, status=status) or []
    resolver = _IdentityResolver(bot, guild_id)
    return [await _enrich_appeal_payload(row, resolver) for row in rows]


@cases_router.patch("/{guild_id}/appeals/{appeal_id}")
async def update_appeal(
    guild_id: int,
    appeal_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """Acepta o rechaza una apelación.

    Body: ``{"status": "ACCEPTED" | "DENIED", "mod_message"?: str, "auto_remove"?: bool}``

    Si ``auto_remove`` y la sanción es ``WARN`` o ``MUTE``, intenta quitarla
    a través del bot. ``BAN`` queda fuera del flujo automático para evitar
    desbaneos por error desde el dashboard.
    """
    new_status = (body.get("status") or "").upper()
    if new_status == "REJECTED":
        new_status = "DENIED"
    if new_status not in {"ACCEPTED", "DENIED"}:
        raise HTTPException(400, "status debe ser ACCEPTED o DENIED")

    appeal = db.get_appeal(appeal_id)
    if not appeal or appeal.get("guild_id") != guild_id:
        raise HTTPException(404, "Apelación no encontrada")
    if appeal.get("status") and appeal["status"].upper() != "PENDING":
        raise HTTPException(409, f"La apelación ya está en estado {appeal['status']}")

    auto_remove_raw = body.get("auto_remove", False)
    if not isinstance(auto_remove_raw, bool):
        raise HTTPException(400, "auto_remove debe ser true o false")
    auto_remove = auto_remove_raw
    action_type = (appeal.get("action_type") or "").upper()
    appeal_case = None
    case_id = 0
    if new_status == "ACCEPTED" and auto_remove and action_type in {"WARN", "MUTE"}:
        try:
            case_id = int(appeal.get("case_id") or 0)
        except (TypeError, ValueError):
            case_id = 0
        if not case_id:
            raise HTTPException(
                409,
                "La apelación legacy no está ligada a una sanción exacta",
            )
        appeal_case = db.get_appealable_active_case(
            guild_id,
            int(appeal.get("user_id") or 0),
            case_id,
            action_type,
        )
        if appeal_case is None:
            raise HTTPException(
                409,
                "La sanción apelada ya no es la sanción activa actual",
            )
    if (
        new_status == "ACCEPTED"
        and auto_remove
        and action_type in {"WARN", "MUTE"}
        and user.get("is_master_admin")
    ):
        raise HTTPException(
            403,
            "La retirada automática requiere una identidad Discord del servidor",
        )
    if (
        new_status == "ACCEPTED"
        and auto_remove
        and action_type == "MUTE"
        and not user.get("is_master_admin")
    ):
        target_id = appeal.get("user_id")
        if not target_id:
            raise HTTPException(409, "La apelación no tiene un usuario objetivo válido")
        if bot is None or getattr(bot, "user", None) is None:
            raise HTTPException(503, "Bot no conectado")
        if not int(user.get("user_id") or 0):
            raise HTTPException(403, "No se pudo verificar tu identidad Discord")
    if (
        new_status == "ACCEPTED"
        and auto_remove
        and action_type == "WARN"
        and (bot is None or getattr(bot, "user", None) is None)
    ):
        raise HTTPException(503, "Bot no conectado")
    if (
        new_status == "ACCEPTED"
        and auto_remove
        and action_type in {"WARN", "MUTE"}
        and not int(user.get("user_id") or 0)
    ):
        raise HTTPException(403, "No se pudo verificar tu identidad Discord")

    if not db.claim_pending_appeal(appeal_id, guild_id):
        raise HTTPException(409, "La apelación ya está siendo procesada")

    action_taken = None
    appeal_finalized = False
    try:
        claimed_appeal = db.get_appeal(appeal_id)
        if (
            not claimed_appeal
            or int(claimed_appeal.get("guild_id") or 0) != guild_id
            or str(claimed_appeal.get("status") or "").upper() != "PROCESSING"
        ):
            raise HTTPException(409, "No se pudo verificar la apelación reservada")
        appeal = claimed_appeal
        action_type = str(appeal.get("action_type") or "").upper()
        if new_status == "ACCEPTED" and auto_remove:
            user_id = appeal.get("user_id")
            if not user_id:
                raise HTTPException(409, "La apelación no tiene un usuario objetivo válido")
            try:
                case_id = int(appeal.get("case_id") or 0)
            except (TypeError, ValueError):
                case_id = 0
            if not case_id:
                raise HTTPException(
                    409,
                    "La apelación legacy no está ligada a una sanción exacta",
                )
            appeal_case = db.get_appealable_active_case(
                guild_id,
                int(user_id),
                case_id,
                action_type,
            )
            if appeal_case is None:
                raise HTTPException(
                    409,
                    "La sanción apelada ya no es la sanción activa actual",
                )

            if action_type == "WARN":
                actor_id = int(user.get("user_id") or 0)

                async def resolve_warn_on_bot():
                    guild = bot.get_guild(guild_id)
                    if guild is None:
                        raise RuntimeError("guild_not_found")
                    async with sanction_lock(bot, guild_id, int(user_id), "WARN"):
                        actor, fresh_roles, live_guild = await asyncio.gather(
                            guild.fetch_member(actor_id),
                            guild.fetch_roles(),
                            bot.fetch_guild(guild_id),
                        )
                        roles_by_id = {int(role.id): role for role in fresh_roles}
                        actor_role_ids = {guild_id}
                        actor_role_ids.update(
                            int(value) for value in getattr(actor, "_roles", ())
                        )
                        if any(value not in roles_by_id for value in actor_role_ids):
                            raise PermissionError("incomplete_actor_roles")
                        permissions_value = 0
                        for role_id in actor_role_ids:
                            permissions_value |= int(
                                roles_by_id[role_id].permissions.value
                            )
                        permissions = discord.Permissions(permissions_value)
                        if (
                            actor.id != int(live_guild.owner_id)
                            and not permissions.administrator
                        ):
                            raise PermissionError("admin_permission_changed")
                        if db.get_appealable_active_case(
                            guild_id,
                            int(user_id),
                            case_id,
                            action_type,
                        ) is None:
                            raise RuntimeError("warn_case_changed")
                        if not db.resolve_appealed_case(
                            guild_id,
                            int(user_id),
                            case_id,
                            action_type,
                            appeal_id,
                        ):
                            raise RuntimeError("warn_case_changed")

                try:
                    await run_on_bot_loop(
                        bot,
                        resolve_warn_on_bot,
                        timeout=None,
                        complete_on_cancel=True,
                    )
                    action_taken = "warn_removed"
                    appeal_finalized = True
                except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
                    raise HTTPException(503, str(exc)) from exc
                except PermissionError as exc:
                    raise HTTPException(
                        403, "Tus permisos de administrador cambiaron"
                    ) from exc
                except Exception as exc:
                    logger.warning("No se pudo retirar el warn exacto: %s", exc)
                    raise HTTPException(409, "No se pudo retirar el warn apelado") from exc

            elif action_type == "MUTE":
                actor_id = int(user.get("user_id") or 0)

                async def resolve_mute_on_bot():
                    guild = bot.get_guild(guild_id)
                    if guild is None:
                        raise RuntimeError("guild_not_found")
                    async with sanction_lock(bot, guild_id, int(user_id), "MUTE"):
                        current_case = db.get_appealable_active_case(
                            guild_id,
                            int(user_id),
                            case_id,
                            action_type,
                        )
                        if current_case is None:
                            raise RuntimeError("mute_case_changed")
                        try:
                            extra_data = current_case.get("extra_data")
                            parsed_extra = (
                                json.loads(extra_data)
                                if isinstance(extra_data, str)
                                else dict(extra_data or {})
                            )
                            mute_role_id = int(parsed_extra["role_id"])
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise RuntimeError("missing_mute_role_identity") from exc
                        async def current_mute_context():
                            async def fetch_target():
                                try:
                                    return await guild.fetch_member(int(user_id))
                                except discord.NotFound:
                                    return None

                            actor, target, bot_member, fresh_roles, live_guild = (
                                await asyncio.gather(
                                    guild.fetch_member(actor_id),
                                    fetch_target(),
                                    guild.fetch_member(bot.user.id),
                                    guild.fetch_roles(),
                                    bot.fetch_guild(guild_id),
                                )
                            )
                            roles_by_id = {
                                int(role.id): role for role in fresh_roles
                            }

                            def current_role_state(member):
                                role_ids = {guild_id}
                                role_ids.update(
                                    int(value)
                                    for value in getattr(member, "_roles", ())
                                )
                                if any(
                                    value not in roles_by_id for value in role_ids
                                ):
                                    raise RuntimeError("incomplete_role_state")
                                roles = [roles_by_id[value] for value in role_ids]
                                permissions_value = 0
                                for member_role in roles:
                                    permissions_value |= int(
                                        member_role.permissions.value
                                    )
                                return (
                                    discord.Permissions(permissions_value),
                                    max(roles),
                                    role_ids,
                                )

                            actor_permissions, actor_top, _actor_roles = (
                                current_role_state(actor)
                            )
                            if target is not None:
                                target_permissions, target_top, target_role_ids = (
                                    current_role_state(target)
                                )
                            else:
                                target_permissions = discord.Permissions.none()
                                target_top = roles_by_id[guild_id]
                                target_role_ids = set()
                            bot_permissions, bot_top, _bot_roles = (
                                current_role_state(bot_member)
                            )
                            owner_id = int(live_guild.owner_id)
                            if (
                                actor.id != owner_id
                                and not actor_permissions.administrator
                            ):
                                raise PermissionError("admin_permission_changed")
                            role = roles_by_id.get(mute_role_id)
                            for snapshot in parsed_extra.get("suppressed_roles", ()):
                                original_role = roles_by_id.get(int(snapshot["id"]))
                                if original_role is None or (actor.id != owner_id and original_role >= actor_top):
                                    raise PermissionError("original_role_hierarchy_changed")
                            if (
                                target is None
                                or role is None
                                or mute_role_id not in target_role_ids
                            ):
                                return target, None, target_role_ids
                            if not (
                                bot_permissions.administrator
                                or bot_permissions.manage_roles
                            ):
                                raise RuntimeError("bot_manage_roles_changed")
                            if target is not None and (
                                target.id == owner_id
                                or target_permissions.administrator
                                or (actor.id != owner_id and actor_top <= target_top)
                                or bot_top <= target_top
                            ):
                                raise PermissionError("target_hierarchy_changed")
                            if (
                                (actor.id != owner_id and role >= actor_top)
                                or role >= bot_top
                                or not safe_for_automatic_removal(role, bot_member)
                                or not safe_for_automatic_assignment(
                                    role,
                                    bot_member,
                                    forbidden_role_ids=delegated_bot_role_ids(
                                        db, guild_id
                                    ),
                                )
                            ):
                                raise RuntimeError("mute_role_unmanageable")
                            return target, role, target_role_ids

                        moderation_cog = bot.get_cog("Moderation")
                        effect_checker = getattr(
                            moderation_cog, "_mute_effect_state", None
                        )
                        if not callable(effect_checker):
                            raise RuntimeError("moderation_cog_unavailable")
                        effect_state = await effect_checker(
                            guild,
                            int(user_id),
                            mute_role_id,
                            current_case,
                        )
                        if effect_state in {"legacy", "unverified"}:
                            raise RuntimeError("mute_effect_identity_unverified")
                        if effect_state == "replaced":
                            raise RuntimeError("mute_effect_replaced")
                        if db.get_appealable_active_case(
                            guild_id,
                            int(user_id),
                            case_id,
                            action_type,
                        ) is None:
                            raise RuntimeError("mute_case_changed")
                        target, role, target_role_ids = await current_mute_context()
                        if effect_state == "match" and (target is None or role is None):
                            raise RuntimeError("mute_effect_changed")
                        effect_state = await effect_checker(
                            guild,
                            int(user_id),
                            mute_role_id,
                            current_case,
                        )
                        if effect_state in {"legacy", "unverified"}:
                            raise RuntimeError("mute_effect_identity_unverified")
                        if effect_state == "replaced":
                            raise RuntimeError("mute_effect_replaced")
                        target, role, target_role_ids = await current_mute_context()
                        if effect_state == "match" and (target is None or role is None):
                            raise RuntimeError("mute_effect_changed")
                        if effect_state == "absent" and role is not None:
                            raise RuntimeError("mute_effect_changed")
                        removed = (
                            effect_state == "match"
                            and target is not None
                            and role is not None
                            and mute_role_id in target_role_ids
                        )
                        if removed:
                            await target.remove_roles(
                                role, reason="Apelación aceptada"
                            )
                        restore = getattr(moderation_cog, "_restore_mute_roles", None)
                        if parsed_extra.get("suppressed_roles") and not callable(restore):
                            raise RuntimeError("mute_role_restoration_unavailable")
                        if callable(restore):
                            await restore(guild, int(user_id), current_case, actor_id=actor_id)
                        if not db.resolve_appealed_case(
                            guild_id,
                            int(user_id),
                            case_id,
                            action_type,
                            appeal_id,
                        ):
                            raise RuntimeError("mute_case_changed")
                        return removed

                try:
                    removed = await run_on_bot_loop(
                        bot,
                        resolve_mute_on_bot,
                        timeout=None,
                        complete_on_cancel=True,
                    )
                except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
                    raise HTTPException(503, str(exc)) from exc
                except PermissionError as exc:
                    raise HTTPException(
                        403, "Tus permisos o la jerarquía actual cambiaron"
                    ) from exc
                except Exception as exc:
                    logger.warning("No se pudo quitar mute: %s", exc)
                    raise HTTPException(409, "No se pudo retirar el mute") from exc
                action_taken = "unmuted" if removed else "already_unmuted"
                appeal_finalized = True

        if not appeal_finalized and not db.finalize_claimed_appeal(
            appeal_id, guild_id, new_status
        ):
            raise HTTPException(409, "No se pudo finalizar la apelación reservada")
    except BaseException:
        # WARN clear y role removal son idempotentes; liberar permite reintentar
        # también cuando la petición fue cancelada antes de finalizar el claim.
        db.release_appeal_claim(appeal_id, guild_id)
        raise

    return {
        "id": appeal_id,
        "status": new_status,
        "action_taken": action_taken,
    }
