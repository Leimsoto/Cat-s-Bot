"""Ajustes por canal y permisos nativos, con validación previa al lote."""

import asyncio
import copy
import json
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from api.deps import get_bot, get_db, require_guild_admin
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from cogs._sanction_locks import run_sanction_locked

router = APIRouter(prefix="/api/guilds/{guild_id}/channel-settings", tags=["channel-settings"])
COMMUNICATION_PERMISSIONS = (
    "view_channel", "send_messages", "send_messages_in_threads", "create_public_threads",
    "create_private_threads", "attach_files", "embed_links", "add_reactions",
    "read_message_history", "mention_everyone", "use_external_emojis",
)
CONFIGURABLE_CHANNEL_TYPES = {0, 2, 5, 15, 16}


def _id(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
        raise ValueError("Los IDs Discord deben ser strings numéricos positivos")
    return str(int(value))


def _ids(values):
    return list(dict.fromkeys(_id(value) for value in values))


def _notice(value):
    try:
        if len(value.encode("utf-16-le")) // 2 > 1975:
            raise ValueError("El texto admite un máximo de 1975 caracteres")
    except UnicodeEncodeError:
        raise ValueError("Texto con caracteres inválidos")
    return value


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleRule(SettingsModel):
    mode: Literal["inherit", "additional", "override", "off"] = "inherit"
    role_ids: list[str] = Field(default_factory=list)
    notice: str = "Necesitas el rol requerido para hablar en este canal."

    _valid_ids = field_validator("role_ids")(_ids)
    _valid_notice = field_validator("notice")(_notice)

    @model_validator(mode="after")
    def required_roles(self):
        if self.mode in {"additional", "override"} and (not self.role_ids or not self.notice.strip()):
            raise ValueError("Elige al menos un rol y escribe un aviso")
        return self


class ContentRules(SettingsModel):
    media_only: StrictBool = False
    block_links: StrictBool = False
    blocked_words: list[str] = Field(default_factory=list, max_length=100)
    notice: str = "Este mensaje no cumple las reglas de este canal."

    _valid_notice = field_validator("notice")(_notice)

    @field_validator("blocked_words")
    @classmethod
    def words(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Cada palabra/frase debe tener entre 1 y 200 caracteres")
        return list(dict.fromkeys(value.strip() for value in values))


class Whitelist(SettingsModel):
    role_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)

    _valid_ids = field_validator("role_ids", "user_ids")(_ids)


class TimeWindow(SettingsModel):
    days: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")

    @field_validator("days", mode="before")
    @classmethod
    def valid_days(cls, values):
        if not isinstance(values, list) or any(type(day) is not int or not 0 <= day <= 6 for day in values):
            raise ValueError("Días entre 0 (lunes) y 6 (domingo)")
        return sorted(set(values))

    @model_validator(mode="after")
    def distinct_times(self):
        if self.start == self.end:
            raise ValueError("Inicio y fin deben ser distintos; desactiva el horario para aplicar siempre")
        return self


class RestrictionSchedule(SettingsModel):
    enabled: StrictBool = False
    timezone: str = "Europe/Lisbon"
    windows: list[TimeWindow] = Field(default_factory=list, max_length=50)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Zona horaria IANA inválida")
        return value

    @model_validator(mode="after")
    def enabled_windows(self):
        if self.enabled and not self.windows:
            raise ValueError("Añade al menos una ventana para activar el horario")
        return self


class ChannelTrigger(SettingsModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    condition: Literal["any_message", "contains_text", "has_link", "no_media", "missing_role"]
    values: list[str] = Field(default_factory=list, max_length=100)
    delete: StrictBool = False
    response: str = ""
    notify_staff: StrictBool = False

    _valid_notice = field_validator("response")(_notice)

    @model_validator(mode="after")
    def validate_condition(self):
        if not self.name.strip():
            raise ValueError("Escribe un nombre para el trigger")
        if self.id in {"role", "content"}:
            raise ValueError("ID de trigger reservado")
        if self.condition in {"contains_text", "missing_role"} and not self.values:
            raise ValueError("Esta condición necesita al menos un valor")
        if self.condition == "missing_role":
            self.values = _ids(self.values)
        elif any(not value.strip() or len(value) > 200 for value in self.values):
            raise ValueError("Valores de trigger entre 1 y 200 caracteres")
        if not self.delete and not self.response.strip() and not self.notify_staff:
            raise ValueError("El trigger necesita al menos una acción")
        return self


class ChannelSettings(SettingsModel):
    version: Literal[1] = 1
    enabled: StrictBool = True
    role: RoleRule = Field(default_factory=RoleRule)
    restrictions: ContentRules = Field(default_factory=ContentRules)
    whitelist: Whitelist = Field(default_factory=Whitelist)
    schedule: RestrictionSchedule = Field(default_factory=RestrictionSchedule)
    staff_channel_id: str | None = None
    triggers: list[ChannelTrigger] = Field(default_factory=list, max_length=50)

    @field_validator("staff_channel_id")
    @classmethod
    def staff_id(cls, value):
        return _id(value) if value is not None else None

    @model_validator(mode="after")
    def validate_rules(self):
        if len({trigger.id for trigger in self.triggers}) != len(self.triggers):
            raise ValueError("IDs de triggers duplicados")
        if any(trigger.notify_staff for trigger in self.triggers) and self.staff_channel_id is None:
            raise ValueError("Selecciona un canal de staff para las notificaciones")
        if len(json.dumps(self.model_dump(), ensure_ascii=True)) > 65536:
            raise ValueError("La configuración supera el límite de 64 KiB por canal")
        return self


class SettingsBatch(SettingsModel):
    channel_ids: list[str] = Field(min_length=1)
    config: ChannelSettings

    _valid_ids = field_validator("channel_ids")(_ids)


class PermissionUpdate(SettingsModel):
    target_type: Literal["role", "member"]
    target_id: str
    permissions: dict[str, StrictBool | None]

    _valid_id = field_validator("target_id")(_id)

    @field_validator("permissions")
    @classmethod
    def valid_permissions(cls, values):
        if not values or any(name not in COMMUNICATION_PERMISSIONS for name in values):
            raise ValueError("Selecciona permisos de comunicación válidos")
        return values


async def _on_bot(bot, operation):
    try:
        return await run_on_bot_loop(bot, operation, timeout=30)
    except (DiscordBridgeTimeout, DiscordBridgeUnavailable) as exc:
        raise HTTPException(503, str(exc)) from exc
    except discord.Forbidden as exc:
        raise HTTPException(403, "Discord rechazó la operación por permisos insuficientes") from exc
    except discord.NotFound as exc:
        raise HTTPException(404, "Servidor, canal o miembro no encontrado") from exc
    except discord.HTTPException as exc:
        raise HTTPException(502, "Discord no pudo completar la operación") from exc


def _guild(bot, guild_id):
    guild = bot.get_guild(guild_id) if bot is not None else None
    if guild is None:
        raise HTTPException(503, "Servidor no disponible en el bot")
    return guild


def _channel_type(channel):
    return getattr(getattr(channel, "type", None), "value", None)


@router.get("")
async def get_channel_settings(guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)):
    global_config = db.get_config(guild_id)
    legacy = {str(row["channel_id"]): bool(row.get("media_only")) for row in db.get_all_channel_configs(guild_id)}
    rows = db.list_channel_settings(guild_id)
    for row in rows:
        row["legacy"] = {"media_only": legacy.get(row["channel_id"], False)}
    return {
        "guild_id": str(guild_id),
        "global_role": {"enabled": bool(global_config.get("message_role_enabled")), "role_id": str(global_config["message_role_id"]) if global_config.get("message_role_id") else None,
                        "notice": global_config.get("message_role_notice")},
        "default_config": ChannelSettings().model_dump(), "channels": rows,
        "thread_inheritance": "parent",
        "legacy_channels": [{"channel_id": channel_id, "media_only": True} for channel_id, enabled in legacy.items() if enabled],
    }


@router.put("")
async def put_channel_settings(guild_id: int, body: SettingsBatch, db=Depends(get_db), bot=Depends(get_bot), user=Depends(require_guild_admin)):
    async def validate():
        guild = _guild(bot, guild_id)
        channels, roles = await asyncio.gather(guild.fetch_channels(), guild.fetch_roles())
        channel_map = {str(channel.id): channel for channel in channels}
        role_ids = {str(role.id) for role in roles}
        for channel_id in body.channel_ids:
            channel = channel_map.get(channel_id)
            if channel is None or channel.guild.id != guild_id or _channel_type(channel) not in CONFIGURABLE_CHANNEL_TYPES:
                raise HTTPException(400, "Selecciona canales de texto, anuncios, voz, foro o multimedia de este servidor; los hilos heredan del padre")
        # Una política desactivada no ejecuta IDs antiguos (p. ej. un rol borrado).
        if not body.config.enabled:
            return
        used_roles = set(body.config.whitelist.role_ids)
        if body.config.role.mode in {"additional", "override"}:
            used_roles.update(body.config.role.role_ids)
        for trigger in body.config.triggers:
            if trigger.condition == "missing_role":
                used_roles.update(trigger.values)
        if str(guild_id) in used_roles or not used_roles.issubset(role_ids):
            raise HTTPException(400, "Todos los roles deben existir en este servidor y no pueden ser @everyone")
        for user_id in body.config.whitelist.user_ids:
            member = await guild.fetch_member(int(user_id))
            if member.guild.id != guild_id or member.id != int(user_id):
                raise HTTPException(400, "Usuario ajeno al servidor")
        if body.config.staff_channel_id is not None:
            channel = channel_map.get(body.config.staff_channel_id)
            if channel is None or not callable(getattr(channel, "send", None)):
                raise HTTPException(400, "El canal de staff debe permitir enviar mensajes en este servidor")

    await _on_bot(bot, validate)
    db.set_channel_settings_batch(guild_id, [int(value) for value in body.channel_ids], body.config.model_dump())
    return await get_channel_settings(guild_id, db, user)


@router.delete("/{channel_id}")
async def delete_channel_settings(guild_id: int, channel_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)):
    db.delete_channel_settings(guild_id, channel_id)
    return {"status": "ok"}


async def _native_context(bot, guild_id, channel_id, user):
    guild = _guild(bot, guild_id)
    channel, live_guild, bot_member = await asyncio.gather(guild.fetch_channel(channel_id), bot.fetch_guild(guild_id), guild.fetch_member(bot.user.id))
    if channel.guild.id != guild_id or live_guild.id != guild_id or _channel_type(channel) not in CONFIGURABLE_CHANNEL_TYPES:
        raise HTTPException(400, "Este canal no admite permisos propios; los hilos heredan del padre")
    # Resolver permisos con roles recién obtenidos, sin alterar la cache compartida.
    channel = copy.copy(channel)
    channel.guild = live_guild
    actor = None if user.get("is_master_admin") else await guild.fetch_member(int(user["user_id"]))
    actor_permissions = discord.Permissions.all() if actor is None else channel.permissions_for(actor)
    bot_permissions = channel.permissions_for(bot_member)
    allowed = actor_permissions.manage_channels and actor_permissions.manage_roles and bot_permissions.manage_channels and bot_permissions.manage_roles
    return channel, live_guild, actor, bot_member, actor_permissions, allowed


def _overwrite_row(channel, target, target_type, name=None):
    overwrite = channel.overwrites_for(target)
    return {"target_type": target_type, "target_id": str(target.id), "name": name or getattr(target, "display_name", None) or getattr(target, "name", str(target.id)),
            "permissions": {permission: getattr(overwrite, permission) for permission in COMMUNICATION_PERMISSIONS}}


@router.get("/{channel_id}/permissions")
async def get_native_permissions(guild_id: int, channel_id: int, bot=Depends(get_bot), user=Depends(require_guild_admin)):
    async def read():
        channel, guild, _actor, _bot_member, _permissions, allowed = await _native_context(bot, guild_id, channel_id, user)
        rows = []
        for overwrite in channel._overwrites:
            target_type = "role" if overwrite.is_role() else "member"
            target = guild.get_role(overwrite.id) if overwrite.is_role() else guild.get_member(overwrite.id)
            target = target or discord.Object(id=overwrite.id)
            rows.append(_overwrite_row(channel, target, target_type))
        return {"guild_id": str(guild_id), "channel_id": str(channel_id), "can_manage": bool(allowed),
                "available_permissions": list(COMMUNICATION_PERMISSIONS), "overwrites": rows}
    return await _on_bot(bot, read)


@router.patch("/{channel_id}/permissions")
async def patch_native_permissions(guild_id: int, channel_id: int, body: PermissionUpdate, bot=Depends(get_bot), user=Depends(require_guild_admin)):
    async def apply():
        channel, guild, actor, bot_member, permissions, allowed = await _native_context(bot, guild_id, channel_id, user)
        if not allowed:
            raise HTTPException(403, "Tú y el bot necesitáis Gestionar canales y Gestionar roles en este canal")
        target = guild.get_role(int(body.target_id)) if body.target_type == "role" else await guild.fetch_member(int(body.target_id))
        if target is None or getattr(target.guild, "id", None) != guild_id:
            raise HTTPException(400, "El destinatario debe existir en este servidor")

        def top_role(member):
            ids = {guild_id, *map(int, member._roles)}
            roles = [guild.get_role(role_id) for role_id in ids]
            if any(role is None for role in roles):
                raise HTTPException(409, "No se pudo verificar la jerarquía completa")
            return max(roles)

        target_role = target if body.target_type == "role" else top_role(target)
        if target_role >= top_role(bot_member) or body.target_type == "member" and target.id == guild.owner_id:
            raise HTTPException(403, "El destinatario debe estar debajo del rol del bot")
        if actor is not None and actor.id != guild.owner_id and target.id != actor.id and target_role >= top_role(actor):
            raise HTTPException(403, "El destinatario debe estar debajo de tu rol")
        if any(value is True and not getattr(permissions, key) for key, value in body.permissions.items()):
            raise HTTPException(403, "Solo puedes permitir permisos que posees en este canal")
        overwrite = channel.overwrites_for(target)
        overwrite.update(**body.permissions)
        await channel.set_permissions(target, overwrite=None if overwrite.is_empty() else overwrite,
                                      reason=f"Ajustes granulares desde dashboard por {user.get('user_id', 'master')}")
        # Construir respuesta desde la operación aplicada, sin depender de cache.
        row = _overwrite_row(channel, target, body.target_type)
        row["permissions"] = {permission: getattr(overwrite, permission) for permission in COMMUNICATION_PERMISSIONS}
        return {"status": "ok", "guild_id": str(guild_id), "channel_id": str(channel_id), "overwrite": row}
    async def serialized():
        return await run_sanction_locked(
            bot, guild_id, int(body.target_id),
            f"CHANNEL_PERMISSION:{channel_id}:{body.target_type}", apply,
        )
    return await _on_bot(bot, serialized)
