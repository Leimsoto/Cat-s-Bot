"""REST snapshots and exact role custody for recoverable role mutes."""
from __future__ import annotations

import asyncio
import json
from copy import copy
from datetime import datetime, timedelta, timezone

import discord

from cogs._role_safety import delegated_moderation_role_ids, member_is_effectively_muted
from cogs._sanction_locks import mute_reason_matches, reason_with_mute_effect


MUTE_PERMISSIONS = (
    "send_messages", "send_messages_in_threads", "create_public_threads",
    "create_private_threads", "speak",
)


async def fresh_members(bot, guild, user_id, actor_id=None):
    """Bind REST members, roles and channels to an isolated permission view."""
    ids = [int(user_id), int(bot.user.id)]
    if actor_id is not None:
        ids.append(int(actor_id))
    members, roles, channels, live_guild = await asyncio.gather(
        asyncio.gather(*(guild.fetch_member(value) for value in ids)),
        guild.fetch_roles(), guild.fetch_channels(), bot.fetch_guild(guild.id),
    )
    if live_guild.id != guild.id:
        raise PermissionError("No pude verificar el servidor actual.")
    view = copy(guild)
    view.owner_id = live_guild.owner_id
    view._roles = {role.id: copy(role) for role in roles}
    view._channels = {channel.id: copy(channel) for channel in channels}
    for item in (*view._roles.values(), *view._channels.values()):
        item.guild = view
    result = []
    for source in members:
        if any(int(value) not in view._roles for value in (guild.id, *source._roles)):
            raise PermissionError("No pude verificar todos los roles actuales.")
        member = copy(source)
        member.guild = view
        result.append(member)
    return result


def role_permissions(role):
    """Snapshot grants, including channel grants that can escalate a role."""
    overwrites = []
    for channel in role.guild.channels:
        allow, deny = channel.overwrites_for(role).pair()
        if allow.value or deny.value:
            overwrites.append([channel.id, allow.value, deny.value])
    return {"id": role.id, "permissions": role.permissions.value,
            "overwrites": sorted(overwrites)}


def plan_role_mute(member, bot_member, actor, mute_role):
    """Remove only roles that defeat Muted; reject unresolvable overwrites."""
    guild = member.guild
    if (
        member.id == guild.owner_id or member.bot or member.id == actor.id
        or member.top_role >= bot_member.top_role
        or (actor.id != guild.owner_id and member.top_role >= actor.top_role)
        or not bot_member.guild_permissions.manage_roles
        or not bot_member.guild_permissions.view_audit_log
    ):
        raise PermissionError("Los permisos o la jerarquía actuales no permiten este mute.")
    projected = copy(member)
    projected._roles = discord.utils.SnowflakeList(set(member._roles) | {mute_role.id})
    blocked = {role.id for role in member.roles if role.permissions.administrator and not role.is_default()}
    projected._roles = discord.utils.SnowflakeList(set(projected._roles) - blocked)
    for role in member.roles:
        if role.is_default() or role.id == mute_role.id:
            continue
        if role.permissions.administrator:
            blocked.add(role.id)
            continue
        for channel in guild.channels:
            if isinstance(channel, discord.CategoryChannel):
                continue
            effective = channel.permissions_for(projected)
            overwrite = channel.overwrites_for(role)
            if any(getattr(effective, name, False) and getattr(overwrite, name, None) is True
                   for name in MUTE_PERMISSIONS):
                blocked.add(role.id)
                break
    roles = [guild.get_role(value) for value in sorted(blocked)]
    if any(role.managed or role >= bot_member.top_role
           or (actor.id != guild.owner_id and role >= actor.top_role) for role in roles):
        raise PermissionError("Un rol que impide el mute no se puede retirar de forma segura.")
    projected._roles = discord.utils.SnowflakeList(set(projected._roles) - blocked)
    for channel in guild.channels:
        original = channel.permissions_for(member)
        muted = channel.permissions_for(projected)
        if muted.value & ~original.value:
            raise PermissionError(
                "Retirar un rol abriría acceso o permisos que el usuario no tenía. "
                "Revisa las excepciones de sus canales antes de silenciarlo."
            )
    if not member_is_effectively_muted(projected):
        raise PermissionError(
            "Los permisos propios de este usuario o un rol no gestionable impiden el mute. "
            "Revisa las excepciones de sus canales."
        )
    return roles


async def restore_roles(bot, guild, user_id, case, *, actor_id=None, db=None):
    """Restore our exact withdrawals, never a changed role or a new membership."""
    raw = case.get("extra_data") or {}
    extra = json.loads(raw) if isinstance(raw, str) else raw
    snapshots = extra.get("suppressed_roles") or []
    if not snapshots:
        return
    async def pending_roles():
        member, bot_member, *actors = await fresh_members(bot, guild, user_id, actor_id)
        if str(member.joined_at) != extra.get("mute_member_joined_at"):
            raise PermissionError("La membresía cambió; los roles retirados necesitan revisión manual.")
        if member.id == member.guild.owner_id or member.top_role >= bot_member.top_role:
            raise PermissionError("La jerarquía actual impide restaurar los roles retirados.")
        if not (bot_member.guild_permissions.manage_roles and bot_member.guild_permissions.view_audit_log):
            raise PermissionError("Necesito Gestionar roles y Ver el registro de auditoría para restaurar los roles.")
        actor = actors[0] if actors else None
        if actor and actor.id != member.guild.owner_id:
            delegated = delegated_moderation_role_ids(db, guild.id)
            allowed_roles = {role.id for role in actor.roles if not role.is_default()
                             and not role.managed and role < bot_member.top_role}
            if not (actor.guild_permissions.manage_roles
                    or (delegated is not None and allowed_roles.intersection(delegated))):
                raise PermissionError("Tus permisos cambiaron; la restauración fue cancelada.")
        pending = []
        for snapshot in snapshots:
            role = member.guild.get_role(int(snapshot["id"]))
            if role is None or role.managed or role >= bot_member.top_role:
                raise PermissionError("Un rol retirado fue borrado o dejó de ser gestionable; requiere revisión manual.")
            if actor and actor.id != member.guild.owner_id and role >= actor.top_role:
                raise PermissionError("Tu jerarquía no permite devolver uno de los roles retirados.")
            if role_permissions(role) != {key: snapshot[key] for key in ("id", "permissions", "overwrites")}:
                raise PermissionError("Los permisos de un rol retirado cambiaron; requiere revisión manual.")
            if role.id not in member._roles:
                if snapshot.get("restored"):
                    raise PermissionError("Un rol ya restaurado fue retirado después; requiere revisión manual.")
                pending.append(role)
        return member, pending

    member, pending = await pending_roles()
    if not pending:
        return
    created = datetime.fromisoformat(str(case["created_at"]).replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    changes = {}
    async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.member_role_update,
                                        after=created - timedelta(minutes=5), oldest_first=False):
        if getattr(entry.target, "id", None) != int(user_id):
            continue
        before = {role.id for role in (getattr(entry.before, "roles", None) or ())}
        after = {role.id for role in (getattr(entry.after, "roles", None) or ())}
        for role in pending:
            if role.id in changes or role.id not in before | after:
                continue
            changes[role.id] = (role.id in before and role.id not in after
                and getattr(getattr(entry, "user", None), "id", None) == bot.user.id
                and mute_reason_matches(entry.reason, extra.get("mute_effect_token", "")))
    snapshots_by_id = {int(snapshot["id"]): snapshot for snapshot in snapshots}
    if any(not changes.get(role.id, bool(snapshots_by_id[role.id].get("withdrawal_audit_id"))
                           and not snapshots_by_id[role.id].get("restoring")) for role in pending):
        raise PermissionError("No pude confirmar qué roles retiró este mute; la restauración sigue pendiente.")
    for role in pending:
        member, fresh_pending = await pending_roles()
        role = next((item for item in fresh_pending if item.id == role.id), None)
        if role is None:
            continue
        snapshot = snapshots_by_id[role.id]
        snapshot["restoring"] = True
        if db is not None and not db.update_case_by_id(
            guild.id, int(case["id"]), extra_data=json.dumps(extra)
        ):
            raise RuntimeError("mute_role_restore_intent_not_persisted")
        await member.add_roles(role, reason=reason_with_mute_effect(
            "Restaurar rol retirado por mute", extra["mute_effect_token"]))
        confirmed = await guild.fetch_member(int(user_id))
        if role.id not in confirmed._roles:
            raise RuntimeError("mute_roles_restore_not_confirmed")
        snapshot["restored"] = True
        if db is not None and not db.update_case_by_id(
            guild.id, int(case["id"]), extra_data=json.dumps(extra)
        ):
            raise RuntimeError("mute_role_restore_receipt_not_persisted")


async def confirm_mute_receipts(bot, guild, user_id, case, db):
    """Keep verified mute-add and withdrawal receipts beyond audit retention."""
    raw = case.get("extra_data") or {}
    extra = json.loads(raw) if isinstance(raw, str) else raw
    snapshots = {int(value["id"]): value for value in extra.get("suppressed_roles", ())}
    mute_role_id = int(extra["role_id"])
    expected = snapshots.keys() | {mute_role_id}
    recorded = {role_id for role_id, snapshot in snapshots.items() if snapshot.get("withdrawal_audit_id")}
    if extra.get("mute_add_audit_id"):
        recorded.add(mute_role_id)
    after = datetime.fromisoformat(str(case["created_at"]).replace("Z", "+00:00"))
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    for attempt in range(4):
        seen = set()
        async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.member_role_update,
                                            after=after - timedelta(minutes=5), oldest_first=False):
            if getattr(entry.target, "id", None) != int(user_id):
                continue
            before = {value.id for value in (getattr(entry.before, "roles", None) or ())}
            added = {value.id for value in (getattr(entry.after, "roles", None) or ())}
            for role_id in expected & (before | added) - seen:
                seen.add(role_id)
                correct_change = (role_id in added and role_id not in before) if role_id == mute_role_id else (role_id in before and role_id not in added)
                if (correct_change
                    and getattr(getattr(entry, "user", None), "id", None) == bot.user.id
                    and mute_reason_matches(entry.reason, extra.get("mute_effect_token", ""))):
                    if role_id == mute_role_id:
                        extra["mute_add_audit_id"] = int(entry.id)
                    else:
                        snapshots[role_id]["withdrawal_audit_id"] = int(entry.id)
                else:
                    raise PermissionError("La retirada de un rol cambió fuera de este mute.")
        if len(seen | recorded) == len(expected):
            if not db.update_case_by_id(guild.id, int(case["id"]), extra_data=json.dumps(extra)):
                raise RuntimeError("mute_role_receipts_not_persisted")
            return
        if attempt < 3:
            await asyncio.sleep(0.75)
    raise RuntimeError("mute_role_withdrawals_unverified")
