from __future__ import annotations

import json
from collections.abc import Iterable

import discord


PRIVILEGED_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_messages",
    "manage_threads",
    "manage_events",
    "manage_expressions",
    "manage_emojis_and_stickers",
    "manage_nicknames",
    "view_audit_log",
    "mention_everyone",
    "kick_members",
    "ban_members",
    "moderate_members",
    "mute_members",
    "deafen_members",
    "move_members",
)


def safe_for_automatic_assignment(
    role: discord.Role | None,
    bot_member: discord.Member | None,
    *,
    forbidden_role_ids: Iterable[int] | None = (),
) -> bool:
    if role is None or bot_member is None:
        return False
    # ``None`` means the caller could not verify the current delegated-role
    # configuration. Automatic assignment must fail closed in that case.
    if forbidden_role_ids is None:
        return False
    blocked_ids: set[int] = set()
    for role_id in forbidden_role_ids:
        try:
            blocked_ids.add(int(role_id))
        except (TypeError, ValueError):
            continue
    if role.id in blocked_ids:
        return False
    role_guild = getattr(role, "guild", None)
    bot_guild = getattr(bot_member, "guild", None)
    if (
        role_guild is not None
        and bot_guild is not None
        and getattr(role_guild, "id", None) != getattr(bot_guild, "id", None)
    ):
        return False
    if role.is_default() or role.managed or role >= bot_member.top_role:
        return False
    if any(
        getattr(role.permissions, permission, False)
        for permission in PRIVILEGED_PERMISSIONS
    ):
        return False
    for channel in getattr(role_guild, "channels", ()):
        try:
            effective = channel.permissions_for(role)
        except (AttributeError, TypeError):
            continue
        if any(
            getattr(effective, permission, False)
            for permission in PRIVILEGED_PERMISSIONS
        ):
            return False
    return True


def safe_for_automatic_removal(
    role: discord.Role | None,
    bot_member: discord.Member | None,
) -> bool:
    """Allow revoking an exact role without applying assignment restrictions."""
    if role is None or bot_member is None:
        return False
    role_guild = getattr(role, "guild", None)
    bot_guild = getattr(bot_member, "guild", None)
    if (
        role_guild is None
        or bot_guild is None
        or getattr(role_guild, "id", None) != getattr(bot_guild, "id", None)
    ):
        return False
    return not role.is_default() and not role.managed and role < bot_member.top_role


def mute_role_has_effective_denies(
    guild: discord.Guild,
    role: discord.Role | None,
) -> bool:
    """Require explicit, effective mute denies on every relevant channel."""
    if role is None or getattr(role.guild, "id", None) != guild.id:
        return False

    text_types = tuple(
        channel_type
        for channel_type in (
            getattr(discord, "TextChannel", None),
            getattr(discord, "ForumChannel", None),
            getattr(discord, "MediaChannel", None),
            getattr(discord, "VoiceChannel", None),
            getattr(discord, "StageChannel", None),
            getattr(discord, "CategoryChannel", None),
        )
        if channel_type is not None
    )
    voice_types = tuple(
        channel_type
        for channel_type in (
            getattr(discord, "VoiceChannel", None),
            getattr(discord, "StageChannel", None),
            getattr(discord, "CategoryChannel", None),
        )
        if channel_type is not None
    )
    relevant_channels = 0
    for channel in guild.channels:
        checks_send = isinstance(channel, text_types)
        checks_speak = isinstance(channel, voice_types)
        if not checks_send and not checks_speak:
            continue
        relevant_channels += 1
        try:
            overwrite = channel.overwrites_for(role)
            effective = channel.permissions_for(role)
        except (AttributeError, TypeError):
            return False
        if checks_send and (
            overwrite.send_messages is not False
            or effective.send_messages
        ):
            return False
        if checks_send and any(
            getattr(overwrite, permission, None) is not False
            or getattr(effective, permission, False)
            for permission in (
                "send_messages_in_threads",
                "create_public_threads",
                "create_private_threads",
            )
        ):
            return False
        if checks_speak and (
            overwrite.speak is not False
            or effective.speak
        ):
            return False
    return relevant_channels > 0


def member_is_effectively_muted(member: discord.Member) -> bool:
    """Verify that the member cannot send or speak despite their other roles."""
    guild = member.guild
    text_types = tuple(
        channel_type
        for channel_type in (
            getattr(discord, "TextChannel", None),
            getattr(discord, "ForumChannel", None),
            getattr(discord, "MediaChannel", None),
            getattr(discord, "VoiceChannel", None),
            getattr(discord, "StageChannel", None),
        )
        if channel_type is not None
    )
    voice_types = tuple(
        channel_type
        for channel_type in (
            getattr(discord, "VoiceChannel", None),
            getattr(discord, "StageChannel", None),
        )
        if channel_type is not None
    )
    relevant_channels = 0
    for channel in guild.channels:
        checks_send = isinstance(channel, text_types)
        checks_speak = isinstance(channel, voice_types)
        if not checks_send and not checks_speak:
            continue
        relevant_channels += 1
        effective = channel.permissions_for(member)
        if checks_send and any(
            getattr(effective, permission, False)
            for permission in (
                "send_messages",
                "send_messages_in_threads",
                "create_public_threads",
                "create_private_threads",
            )
        ):
            return False
        if checks_speak and effective.speak:
            return False
    return relevant_channels > 0


def delegated_moderation_role_ids(db, guild_id: int) -> set[int] | None:
    """Return current bot-delegated mod/staff roles, or ``None`` on failure."""
    if db is None:
        return None
    try:
        server_cfg = db.get_server_config(guild_id) or {}
        guild_cfg = db.get_config(guild_id) or {}
        configured_ids = (
            server_cfg.get("mod_role_id"),
            server_cfg.get("staff_role_id"),
            guild_cfg.get("staff_role_id"),
        )
    except Exception:
        return None

    role_ids: set[int] = set()
    for role_id in configured_ids:
        if not role_id:
            continue
        try:
            role_ids.add(int(role_id))
        except (TypeError, ValueError):
            continue
    return role_ids


def delegated_bot_role_ids(db, guild_id: int) -> set[int] | None:
    """Return roles that delegate access to privileged bot capabilities."""
    if db is None:
        return None
    try:
        server_cfg = db.get_server_config(guild_id) or {}
        guild_cfg = db.get_config(guild_id) or {}
        configured_ids = [
            server_cfg.get("mod_role_id"),
            server_cfg.get("staff_role_id"),
            server_cfg.get("embed_role_id"),
            server_cfg.get("channels_role_id"),
            server_cfg.get("users_role_id"),
            guild_cfg.get("staff_role_id"),
        ]

        get_ai_config = getattr(db, "get_ai_config", None)
        if callable(get_ai_config):
            configured_ids.append((get_ai_config(guild_id) or {}).get("ai_role_id"))

        get_ticket_categories = getattr(db, "get_ticket_categories", None)
        if callable(get_ticket_categories):
            configured_ids.extend(
                category.get("staff_role_id")
                for category in (get_ticket_categories(guild_id) or [])
                if isinstance(category, dict)
            )

        get_ticket_config = getattr(db, "get_ticket_config", None)
        if callable(get_ticket_config):
            ticket_cfg = get_ticket_config(guild_id) or {}
            for field in ("allowed_roles", "immune_roles"):
                values = ticket_cfg.get(field) or []
                if isinstance(values, str):
                    values = json.loads(values)
                if not isinstance(values, (list, tuple, set)):
                    return None
                configured_ids.extend(values)
    except Exception:
        return None

    role_ids: set[int] = set()
    for role_id in configured_ids:
        if not role_id:
            continue
        try:
            role_ids.add(int(role_id))
        except (TypeError, ValueError):
            continue
    return role_ids


def self_service_forbidden_role_ids(db, guild_id: int) -> set[int] | None:
    """Roles que nunca deben concederse o retirarse mediante autoservicio."""
    role_ids = delegated_bot_role_ids(db, guild_id)
    if role_ids is None:
        return None
    try:
        guild_cfg = db.get_config(guild_id) or {}
        server_cfg = db.get_server_config(guild_id) or {}
        containment_ids = (
            guild_cfg.get("mute_role_id"),
            server_cfg.get("anti_alt_role_id"),
        )
    except Exception:
        return None
    for role_id in containment_ids:
        if not role_id:
            continue
        try:
            role_ids.add(int(role_id))
        except (TypeError, ValueError):
            continue
    return role_ids
