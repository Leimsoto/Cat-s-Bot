"""
cogs/moderation.py
──────────────────
Cog de moderación completo.

Comandos slash:
  /ban         – Banear usuario
  /tempban     – Banear temporalmente
  /unban       – Desbanear por ID
  /mute        – Silenciar con rol
  /unmute      – Dessilenciar
  /kick        – Expulsar
  /warn        – Advertir (con consecuencias automáticas)
  /warns       – Ver warns de un usuario
  /clearwarns  – Limpiar warns (admin)
  /appeals list – Listar apelaciones

  La configuración se gestiona desde el Dashboard Web.
"""

import asyncio
import json
import logging
import re
from copy import copy
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands, tasks
from cogs._moderation_history import interaction_metadata
from cogs._moderation_evidence import capture_manual
from cogs._mute_roles import confirm_mute_receipts, fresh_members, plan_role_mute, role_permissions, restore_roles

from cogs._role_safety import (
    delegated_bot_role_ids,
    delegated_moderation_role_ids,
    member_is_effectively_muted,
    mute_role_has_effective_denies,
    safe_for_automatic_assignment,
    safe_for_automatic_removal,
)
from cogs.channels import check_channel_perms
from cogs._sanction_locks import (
    ban_reason_matches,
    new_ban_effect_token,
    new_mute_effect_token,
    mute_reason_matches,
    reason_with_ban_effect,
    reason_with_mute_effect,
    run_sanction_locked,
    run_sanctions_locked,
    sanction_lock,
)

def _voice(cog):
    """Return bot.catbot_voice if available, else a no-op fallback."""
    v = getattr(cog.bot, "catbot_voice", None)
    if v:
        return v
    class _Fallback:
        def line(self, role, text): return text
        def get(self, name): return ""
        def embed(self, title=None, description=None, kind="info", url=None):
            import discord
            return discord.Embed(title=title, description=description)
    return _Fallback()



logger = logging.getLogger("Moderation")

URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
INVITE_RE = re.compile(r"discord\.gg/|discord(?:app)?\.com/invite/", re.IGNORECASE)


# ── Utilidades de tiempo ──────────────────────────────────────────────────────

def parse_duration(raw: str) -> Optional[int]:
    """
    Convierte un string de tiempo a segundos.
    Acepta: '30s', '5m', '2h', '1d', '1w'
    Sin unidad → se interpreta como minutos.
    """
    if not raw:
        return None
    raw = raw.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        if raw[-1] in units:
            total = int(raw[:-1]) * units[raw[-1]]
        else:
            total = int(raw) * 60
        return total if total > 0 else None
    except (ValueError, IndexError):
        return None


def fmt_duration(seconds: Optional[int]) -> str:
    """Convierte segundos a texto legible. None → 'Permanente'."""
    if seconds is None:
        return "Permanente ♾️"
    parts = []
    for label, unit in (("sem", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    return " ".join(parts) if parts else "0s"


def _parse_discord_user_id(raw: str) -> Optional[int]:
    """Acepta un snowflake numérico o una mención de usuario de Discord."""
    match = re.fullmatch(r"(?:<@!?(\d+)>|(\d+))", raw.strip())
    if match is None:
        return None
    user_id = int(match.group(1) or match.group(2))
    return user_id if 0 < user_id < 2**64 else None


# ── Embed de warn configurable ────────────────────────────────────────────────

def build_warn_embed(
    cfg: dict,
    usuario: discord.Member,
    moderador: discord.Member,
    razon: str,
    warns: int,
) -> discord.Embed:
    """
    Construye el embed de warn.
    Si guild_config.warn_embed_config tiene un JSON válido lo usa;
    de lo contrario aplica el embed por defecto.

    Placeholders disponibles en el JSON:
      {user}       → mención del usuario
      {username}   → nombre del usuario
      {reason}     → razón
      {warns}      → warns actuales
      {moderator}  → nombre del moderador
      {server}     → nombre del servidor
    """
    embed_cfg: Optional[dict] = None
    if cfg.get("warn_embed_config"):
        try:
            embed_cfg = json.loads(cfg["warn_embed_config"])
            if not isinstance(embed_cfg, dict):
                logger.warning("warn_embed_config inválido: no es un objeto JSON")
                embed_cfg = None
        except json.JSONDecodeError:
            logger.warning("warn_embed_config contiene JSON inválido")

    repl = {
        "{user}": usuario.mention,
        "{username}": str(usuario),
        "{reason}": razon,
        "{warns}": str(warns),
        "{moderator}": moderador.display_name,
        "{server}": usuario.guild.name,
    }

    def sub(text: str) -> str:
        for k, v in repl.items():
            text = text.replace(k, v)
        return text

    if embed_cfg:
        raw_color = embed_cfg.get("color", "FFA500").strip("#")
        try:
            color = discord.Color(int(raw_color, 16))
        except ValueError:
            color = discord.Color.orange()

        embed = discord.Embed(
            title=sub(embed_cfg.get("title", "⚠️ Advertencia")),
            description=sub(embed_cfg.get("description", "{user} recibió una advertencia.")),
            color=color,
        )
        for field in embed_cfg.get("fields", []):
            embed.add_field(
                name=sub(field.get("name", "")),
                value=sub(field.get("value", "")),
                inline=field.get("inline", False),
            )
        if embed_cfg.get("footer"):
            embed.set_footer(text=sub(embed_cfg["footer"]))
    else:
        # Embed por defecto
        embed = discord.Embed(
            title="⚠️ Advertencia emitida",
            description=f"{usuario.mention} ha recibido una advertencia.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=moderador.mention, inline=True)
        embed.add_field(name="⚠️ Warns", value=f"`{warns}`", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f"ID usuario: {usuario.id}")

    return embed


# ── Modal para personalizar el embed de warn ──────────────────────────────────

class WarnEmbedModal(discord.ui.Modal, title="Personalizar embed de warn"):
    emb_title = discord.ui.TextInput(
        label="Título",
        default="⚠️ Advertencia",
        max_length=256,
    )
    description = discord.ui.TextInput(
        label="Descripción  →  placeholders disponibles abajo",
        placeholder="{user} {username} {reason} {warns} {moderator} {server}",
        default="{user} recibió una advertencia en **{server}**.",
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )
    color = discord.ui.TextInput(
        label="Color hex (sin #)",
        default="FFA500",
        max_length=8,
        required=False,
    )
    footer = discord.ui.TextInput(
        label="Pie de página",
        default="Moderador: {moderator}  |  Warns totales: {warns}",
        max_length=512,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cfg_json = json.dumps({
            "title": self.emb_title.value,
            "description": self.description.value,
            "color": self.color.value or "FFA500",
            "footer": self.footer.value,
            "fields": [],
        }, ensure_ascii=False)

        # Guardar en DB
        interaction.client.db.set_config(
            interaction.guild_id, warn_embed_config=cfg_json
        )

        # Vista previa
        guild_cfg = interaction.client.db.get_config(interaction.guild_id)
        preview = build_warn_embed(
            guild_cfg,
            interaction.user,   # type: ignore
            interaction.user,   # type: ignore
            "Esta es una advertencia de ejemplo",
            1,
        )
        await interaction.response.send_message(
            "✅ Embed configurado. **Vista previa:**",
            embed=preview,
            ephemeral=True,
        )


# ── Cog principal ─────────────────────────────────────────────────────────────

class Moderation(commands.Cog):
    """Comandos de moderación: ban, mute, warn, kick y configuración."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore  # inyectado desde main.py
        try:
            self.db.recover_processing_moderation_actions()
            self.db.recover_processing_log_outbox()
        except Exception as exc:
            logger.warning("No se pudieron recuperar jobs en processing: %s", exc)
        self._ban_reconciliation_ready = asyncio.Event()
        self._ban_reconciliation_task = asyncio.create_task(
            self._reconcile_applying_bans()
        )
        self._check_mutes.start()
        self._check_tempbans.start()
        self._check_pending_moderation.start()
        self._flush_log_outbox.start()

    def cog_unload(self):
        self._ban_reconciliation_task.cancel()
        self._check_mutes.cancel()
        self._check_tempbans.cancel()
        self._check_pending_moderation.cancel()
        self._flush_log_outbox.cancel()

    # ── Helpers privados ──────────────────────────────────────────────────────

    async def _resolve_modlog(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Resuelve el canal de modlog. Usa caché y, si falla, intenta fetch.

        Devuelve ``None`` si el modlog está deshabilitado, sin configurar o
        si el canal ya no existe / el bot no lo ve.
        """
        srv_cfg = self.db.get_server_config(guild.id)
        if not srv_cfg.get("modlog_enabled", 1):
            return None

        ch_id = srv_cfg.get("modlog_channel")
        if not ch_id:
            return None

        channel = guild.get_channel(ch_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(ch_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "Canal de modlog inválido o no accesible en %s (%s)",
                guild.name, ch_id,
            )
            return None
        return channel

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed) -> bool:
        """Envía un embed al canal de modlog. Devuelve True si tuvo éxito."""
        channel = await self._resolve_modlog(guild)
        if channel is None:
            self._enqueue_modlog_outbox(guild, embed, None, "modlog_channel_unavailable")
            return False
        try:
            from cogs._managed_messages import send_managed
            await send_managed(self.bot, guild.id, "moderation", channel.send, embed=embed)
            return True
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar logs en %s", guild.name)
            self._enqueue_modlog_outbox(guild, embed, channel.id, "missing_send_messages")
        except discord.HTTPException as exc:
            logger.warning("No se pudo enviar modlog en %s: %s", guild.name, exc)
            self._enqueue_modlog_outbox(guild, embed, channel.id, str(exc))
        return False

    def _enqueue_modlog_outbox(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        channel_id: Optional[int],
        error: Optional[str] = None,
    ) -> None:
        """Guarda un log crítico para reintento si el envío directo falla."""
        try:
            srv_cfg = self.db.get_server_config(guild.id)
            if not srv_cfg.get("modlog_enabled", 1):
                return
            target_channel_id = channel_id or srv_cfg.get("modlog_channel")
            if not target_channel_id:
                return
            self.db.enqueue_log_outbox(
                guild.id,
                "moderation",
                {
                    "embed": embed.to_dict(),
                    "source": "moderation_cog",
                    "last_error": (error or "")[:500],
                },
                channel_id=int(target_channel_id),
            )
        except Exception as exc:
            logger.warning("No se pudo encolar modlog fallido en %s: %s", guild.name, exc)

    async def _notify_modlog_issue(self, interaction: discord.Interaction) -> None:
        """Avisa al moderador (ephemeral followup) que el modlog falló.

        Discrimina entre: no configurado, canal inválido y sin permisos.
        """
        srv_cfg = self.db.get_server_config(interaction.guild_id)
        if not srv_cfg.get("modlog_enabled", 1):
            return
        ch_id = srv_cfg.get("modlog_channel")
        if not ch_id:
            msg = (
                "⚠️ La acción se aplicó pero **no hay canal de mod-logs**."
                " Configúralo en el dashboard → Moderación."
            )
        else:
            msg = (
                f"⚠️ La acción se aplicó pero el canal de mod-logs <#{ch_id}>"
                " no es accesible (borrado o sin permisos del bot)."
                " Revisa la configuración en el dashboard."
            )
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _safe_interaction_send(
        self,
        interaction: discord.Interaction,
        content: Optional[str] = None,
        *,
        embed: Optional[discord.Embed] = None,
        ephemeral: bool = False,
    ) -> bool:
        """Responde una interacción sin dejar que tokens expirados rompan el comando."""
        try:
            if not interaction.response.is_done():
                from cogs._managed_messages import send_managed
                await send_managed(self.bot, interaction.guild_id, "moderation", interaction.response.send_message,
                                   content=content, embed=embed, ephemeral=ephemeral)
            else:
                from cogs._managed_messages import send_managed
                await send_managed(self.bot, interaction.guild_id, "moderation", interaction.followup.send,
                                   content=content, embed=embed, ephemeral=ephemeral)
            return True
        except discord.NotFound:
            logger.warning("No se pudo responder: interacción/webhook expirado o desconocido")
            return False
        except discord.HTTPException as exc:
            logger.warning("No se pudo responder interacción: %s", exc)
            return False

    async def _safe_defer(self, interaction: discord.Interaction, *, ephemeral: bool = False) -> bool:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True, ephemeral=ephemeral)
            return True
        except discord.NotFound:
            logger.warning("No se pudo deferir: interacción expirada o desconocida")
            return False
        except discord.HTTPException as exc:
            logger.warning("No se pudo deferir interacción: %s", exc)
            return False

    async def _ensure_mute_role(
        self, guild: discord.Guild,
    ) -> Optional[discord.Role]:
        """Devuelve el rol de mute. Si no existe, intenta crear uno.

        Reglas:
          1. Si ``config.mute_role_id`` apunta a un rol existente → devolverlo.
          2. Si hay un rol llamado "Muted"/"Silenciado" → adoptarlo y persistir id.
          3. Si el bot tiene ``manage_roles`` y ``manage_channels`` → crear rol
             "Muted" + deny ``send_messages`` y ``speak`` en cada canal.
        """
        cfg = self.db.get_config(guild.id)
        try:
            role_id = int(cfg.get("mute_role_id") or 0)
        except (TypeError, ValueError):
            role_id = 0
        bot_member = guild.get_member(self.bot.user.id) if self.bot.user else None
        role = guild.get_role(role_id) if role_id else None
        forbidden_role_ids = delegated_bot_role_ids(self.db, guild.id)
        if safe_for_automatic_assignment(
            role,
            bot_member,
            forbidden_role_ids=forbidden_role_ids,
        ):
            if mute_role_has_effective_denies(guild, role):
                return role
            await self._apply_mute_overwrites(guild, role)
            role = guild.get_role(role.id)
            if mute_role_has_effective_denies(guild, role):
                return role
        if role:
            logger.warning("Rol mute inseguro ignorado en %s: %s", guild.id, role.id)

        for name in ("Muted", "Silenciado", "Muteado"):
            existing = discord.utils.find(
                lambda r: r.name.lower() == name.lower(), guild.roles
            )
            if safe_for_automatic_assignment(
                existing,
                bot_member,
                forbidden_role_ids=forbidden_role_ids,
            ):
                await self._apply_mute_overwrites(guild, existing)
                existing = guild.get_role(existing.id)
                if not mute_role_has_effective_denies(guild, existing):
                    continue
                try:
                    self.db.set_config(guild.id, mute_role_id=existing.id)
                except Exception as exc:
                    logger.warning("No se pudo persistir mute_role_id: %s", exc)
                return existing

        if not bot_member or not (
            bot_member.guild_permissions.manage_roles
            and bot_member.guild_permissions.manage_channels
        ):
            return None
        try:
            new_role = await guild.create_role(
                name="Muted",
                reason="Auto-creado para auto-mute por warns",
                color=discord.Color.dark_grey(),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("No se pudo crear rol Muted en %s: %s", guild.name, exc)
            return None

        # No se adopta un rol parcial: todos los canales relevantes deben
        # confirmar los denies antes de persistirlo o usarlo.
        changed = await self._apply_mute_overwrites(guild, new_role)
        new_role = guild.get_role(new_role.id)
        if changed == 0 or not mute_role_has_effective_denies(guild, new_role):
            if new_role is not None:
                try:
                    await new_role.delete(reason="Configuración de mute incompleta")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return None

        try:
            self.db.set_config(guild.id, mute_role_id=new_role.id)
        except Exception as exc:
            logger.warning("No se pudo persistir mute_role_id nuevo: %s", exc)
        return new_role

    async def _dm(
        self,
        user: Union[discord.Member, discord.User],
        embed: discord.Embed,
        view: Optional[discord.ui.View] = None,
    ) -> None:
        try:
            if view:
                await user.send(embed=embed, view=view)
            else:
                await user.send(embed=embed)
        except discord.Forbidden:
            logger.info("No se pudo enviar DM a %s (%s): DMs cerrados o bloqueados", user, user.id)
        except discord.HTTPException as exc:
            logger.warning("Error enviando DM a %s (%s): %s", user, user.id, exc)

    def _member_has_mod_perms(
        self,
        guild: discord.Guild,
        user: discord.Member,
        perm_name: str,
    ) -> bool:
        user_guild = getattr(user, "guild", None)
        if user_guild is not None and getattr(user_guild, "id", None) != guild.id:
            return False

        if getattr(user.guild_permissions, "administrator", False):
            return True
        if getattr(user.guild_permissions, perm_name, False):
            return True

        delegated_ids = delegated_moderation_role_ids(
            getattr(self, "db", None), guild.id
        )
        if delegated_ids is None:
            return False
        return any(role.id in delegated_ids for role in user.roles)

    def _has_mod_perms(self, interaction: discord.Interaction, perm_name: str) -> bool:
        user = interaction.user
        guild = interaction.guild
        if guild is None or not isinstance(user, discord.Member):
            return False
        return self._member_has_mod_perms(guild, user, perm_name)

    @staticmethod
    def _enabled_config_flag(value: object, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _current_warn_consequence(
        self, guild_id: int, user_id: int
    ) -> tuple[Optional[str], int, Optional[int]]:
        """Devuelve la consecuencia vigente usando contador y configuración actuales."""
        try:
            cfg = self.db.get_config(guild_id) or {}
            warns = int((self.db.get_user(user_id, guild_id) or {}).get("warns") or 0)
            ban_threshold = max(1, int(cfg.get("warn_ban_threshold", 7) or 7))
            kick_threshold = max(1, int(cfg.get("warn_kick_threshold", 5) or 5))
            mute_threshold = max(1, int(cfg.get("warn_mute_threshold", 3) or 3))
            mute_duration = max(
                60, int(cfg.get("warn_mute_duration", 3600) or 3600)
            )
        except (AttributeError, TypeError, ValueError):
            return None, 0, None
        if self._enabled_config_flag(
            cfg.get("warn_ban_enabled"), default=False
        ) and warns >= ban_threshold:
            return "BAN", warns, None
        if self._enabled_config_flag(
            cfg.get("warn_kick_enabled"), default=False
        ) and warns >= kick_threshold:
            return "KICK", warns, None
        if self._enabled_config_flag(
            cfg.get("warn_mute_enabled"), default=True
        ) and warns >= mute_threshold:
            return "MUTE", warns, mute_duration
        return None, warns, None

    async def _fresh_moderation_context(
        self,
        interaction: discord.Interaction,
        perm_name: str,
        *,
        target_id: Optional[int] = None,
        allow_absent_target: bool = False,
        action_type: str = "",
        require_bot_permission: bool = False,
    ) -> tuple[Optional[discord.Member], Optional[discord.Member], Optional[str]]:
        """Re-fetch actor/target and authorize immediately before a sensitive sink."""
        guild = interaction.guild
        if (
            guild is None
            or interaction.guild_id != guild.id
            or self.bot.user is None
        ):
            return None, None, "No pude verificar el servidor actual."

        target_missing = object()

        async def fetch_target():
            if target_id is None:
                return None
            try:
                return await guild.fetch_member(target_id)
            except discord.NotFound:
                return target_missing

        try:
            target_result, actor, bot_member, live_roles, live_guild = await asyncio.gather(
                fetch_target(),
                guild.fetch_member(interaction.user.id),
                guild.fetch_member(self.bot.user.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None, None, "No pude verificar permisos y jerarquías actuales."
        if target_result is target_missing:
            if not allow_absent_target:
                return None, None, "El usuario ya no pertenece a este servidor."
            target: Optional[discord.Member] = None
        else:
            target = target_result
        if getattr(live_guild, "id", None) != guild.id:
            return None, None, "La identidad actual del servidor no coincide."

        roles_by_id = {int(role.id): role for role in live_roles}

        def current_role_state(member: discord.Member):
            role_ids = {guild.id}
            role_ids.update(int(role_id) for role_id in getattr(member, "_roles", ()))
            if any(role_id not in roles_by_id for role_id in role_ids):
                return None
            roles = [roles_by_id[role_id] for role_id in role_ids]
            permissions_value = 0
            for role in roles:
                permissions_value |= int(role.permissions.value)
            return discord.Permissions(permissions_value), max(roles), role_ids

        actor_state = current_role_state(actor)
        bot_state = current_role_state(bot_member)
        target_state = current_role_state(target) if target is not None else None
        if actor_state is None or bot_state is None or (
            target is not None and target_state is None
        ):
            return None, None, "No pude verificar la jerarquía completa de roles."

        actor_permissions, actor_top_role, actor_role_ids = actor_state
        bot_permissions, bot_top_role, _bot_role_ids = bot_state
        owner_id = int(live_guild.owner_id)
        if require_bot_permission and not (
            bot_permissions.administrator or getattr(bot_permissions, perm_name, False)
        ):
            return None, None, "El bot no tiene el permiso necesario para esta consecuencia."
        delegated_ids = delegated_moderation_role_ids(self.db, guild.id)
        if delegated_ids is None:
            return None, None, "No pude verificar los roles delegados actuales."
        valid_delegated_ids = {
            role_id
            for role_id in delegated_ids
            if (
                (role := roles_by_id.get(int(role_id))) is not None
                and not role.is_default()
                and not role.managed
                and role < bot_top_role
            )
        }
        actor_allowed = bool(
            actor.id == owner_id
            or actor_permissions.administrator
            or getattr(actor_permissions, perm_name, False)
            or actor_role_ids.intersection(valid_delegated_ids)
        )
        if not actor_allowed:
            return None, None, "Tus permisos de moderación cambiaron; la operación fue cancelada."
        if target is not None:
            target_permissions, target_top_role, _target_role_ids = target_state
            if target.bot:
                return None, None, "No puedes moderar a un bot."
            if actor.id == target.id:
                return None, None, "No puedes moderarte a ti mismo."
            if target.id == owner_id:
                return None, None, "No puedes moderar al dueño del servidor."
            if target_permissions.administrator and action_type == "TIMEOUT":
                return None, None, "Discord no permite aplicar timeout a administradores. Usa /mute."
            if target_permissions.administrator and action_type.startswith("AUTO_"):
                return None, None, "La moderación automática mantiene la protección de administradores."
            if actor.id != owner_id and actor_top_role <= target_top_role:
                return None, None, "Tu rol no es suficientemente alto para moderar a este usuario."
            if bot_top_role <= target_top_role:
                return None, None, "Mi rol no es suficiente para moderar a este usuario."
        return actor, target, None

    async def _fresh_owner_or_admin(
        self, interaction: discord.Interaction
    ) -> tuple[Optional[discord.Member], Optional[str]]:
        guild = interaction.guild
        if guild is None or interaction.guild_id != guild.id:
            return None, "No pude verificar el servidor actual."
        try:
            actor, live_roles, live_guild = await asyncio.gather(
                guild.fetch_member(interaction.user.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None, "No pude verificar tus permisos actuales."
        roles_by_id = {int(role.id): role for role in live_roles}
        role_ids = {guild.id}
        role_ids.update(int(role_id) for role_id in getattr(actor, "_roles", ()))
        if any(role_id not in roles_by_id for role_id in role_ids):
            return None, "No pude verificar todos tus roles actuales."
        permissions_value = 0
        for role_id in role_ids:
            permissions_value |= int(roles_by_id[role_id].permissions.value)
        permissions = discord.Permissions(permissions_value)
        if actor.id != int(live_guild.owner_id) and not permissions.administrator:
            return None, "Este comando requiere Administrador."
        return actor, None

    async def _fresh_mute_role_context(
        self,
        interaction: discord.Interaction,
        target_id: int,
        role_id: int,
        *,
        allow_absent_target: bool = False,
        allow_absent_effect: bool = False,
        for_assignment: bool = False,
    ) -> tuple[
        Optional[discord.Member],
        Optional[discord.Member],
        Optional[discord.Role],
        Optional[str],
    ]:
        """Obtiene autorización, jerarquías y rol de mute en una instantánea REST."""
        guild = interaction.guild
        if guild is None or interaction.guild_id != guild.id or not self.bot.user:
            return None, None, None, "No pude verificar el servidor actual."
        target_missing = object()

        async def fetch_target():
            try:
                return await guild.fetch_member(int(target_id))
            except discord.NotFound:
                return target_missing

        try:
            target_result, actor, bot_member, live_roles, live_guild = await asyncio.gather(
                fetch_target(),
                guild.fetch_member(interaction.user.id),
                guild.fetch_member(self.bot.user.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None, None, None, "No pude verificar permisos y roles actuales."
        if target_result is target_missing:
            if not allow_absent_target:
                return None, None, None, "El usuario ya no pertenece al servidor."
            target: Optional[discord.Member] = None
        else:
            target = target_result
        roles_by_id = {int(role.id): role for role in live_roles}

        target_role_ids = set()
        if target is not None:
            target_role_ids = {guild.id}
            target_role_ids.update(
                int(value) for value in getattr(target, "_roles", ())
            )
        mute_role = roles_by_id.get(int(role_id))
        effect_absent_snapshot = bool(
            target is None
            or mute_role is None
            or int(role_id) not in target_role_ids
        )

        def role_state(member: discord.Member):
            role_ids = {guild.id}
            role_ids.update(int(value) for value in getattr(member, "_roles", ()))
            if any(value not in roles_by_id for value in role_ids):
                return None
            roles = [roles_by_id[value] for value in role_ids]
            permissions_value = 0
            for role in roles:
                permissions_value |= int(role.permissions.value)
            return discord.Permissions(permissions_value), max(roles), role_ids

        actor_state = role_state(actor)
        bot_state = role_state(bot_member)
        target_state = (
            role_state(target)
            if target is not None
            and not (allow_absent_effect and effect_absent_snapshot)
            else None
        )
        if actor_state is None or bot_state is None or (
            target is not None
            and target_state is None
            and not (allow_absent_effect and effect_absent_snapshot)
        ):
            return None, None, None, "No pude verificar la jerarquía completa."
        actor_permissions, actor_top_role, actor_role_ids = actor_state
        bot_permissions, bot_top_role, _bot_role_ids = bot_state
        owner_id = int(live_guild.owner_id)
        delegated_ids = delegated_moderation_role_ids(self.db, guild.id)
        if delegated_ids is None:
            return None, None, None, "No pude verificar los roles delegados actuales."
        valid_delegated_ids = {
            role_id
            for role_id in delegated_ids
            if (
                (role := roles_by_id.get(int(role_id))) is not None
                and not role.is_default()
                and not role.managed
                and role < bot_top_role
            )
        }
        if not (
            actor.id == owner_id
            or actor_permissions.administrator
            or actor_permissions.manage_roles
            or actor_role_ids.intersection(valid_delegated_ids)
        ):
            return None, None, None, "Tus permisos cambiaron; la operación fue cancelada."
        if not for_assignment and target is not None:
            case = self._active_mute_case(guild.id, target.id)
            for snapshot in self._json_object((case or {}).get("extra_data")).get("suppressed_roles", ()):
                original_role = roles_by_id.get(int(snapshot["id"]))
                if original_role is None or (actor.id != owner_id and original_role >= actor_top_role):
                    return None, None, None, "Tu jerarquía no permite devolver los roles retirados por este mute."
        if allow_absent_effect and effect_absent_snapshot:
            return actor, target, None, None
        if target is not None:
            target_permissions, target_top_role, _target_role_ids = target_state
            if target.bot or actor.id == target.id or target.id == owner_id:
                return None, None, None, "El objetivo ya no puede ser moderado."
            if actor.id != owner_id and actor_top_role <= target_top_role:
                return None, None, None, "Tu jerarquía ya no permite esta operación."
            if bot_top_role <= target_top_role:
                return None, None, None, "Mi jerarquía ya no permite esta operación."
        if not (
            bot_permissions.administrator or bot_permissions.view_audit_log
        ):
            return None, None, None, "Necesito Ver el registro de auditoría para identificar el mute."
        if for_assignment:
            forbidden_ids = delegated_bot_role_ids(self.db, guild.id)
            if not (
                mute_role is not None
                and mute_role < bot_top_role
                and safe_for_automatic_assignment(
                    mute_role,
                    bot_member,
                    forbidden_role_ids=forbidden_ids,
                )
                and mute_role_has_effective_denies(guild, mute_role)
            ):
                return None, None, None, "El rol de mute ya no es seguro."
        elif not self._safe_mute_role_removal(
            guild,
            mute_role,
            bot_member,
            bot_top_role=bot_top_role,
        ):
            return None, None, None, "El rol histórico de mute ya no es gestionable."
        return actor, target, mute_role, None

    def _has_config_perms(self, interaction: discord.Interaction) -> bool:
        """Permisos para tocar configuración del bot en el servidor."""
        user = interaction.user
        guild = interaction.guild
        if not guild or not isinstance(user, discord.Member):
            return False
        if user.id == guild.owner_id:
            return True
        perms = user.guild_permissions
        return bool(perms.administrator or perms.manage_guild)

    async def _fresh_config_role(
        self,
        interaction: discord.Interaction,
        role_id: int,
        *,
        owner_or_admin_only: bool,
    ) -> tuple[Optional[discord.Role], Optional[str]]:
        """Fetch actor, role list and bot immediately before a role-config write."""
        guild = interaction.guild
        if guild is None or interaction.guild_id != guild.id or not self.bot.user:
            return None, "No pude verificar el servidor actual."
        try:
            actor, bot_member, live_roles, live_guild = await asyncio.gather(
                guild.fetch_member(interaction.user.id),
                guild.fetch_member(self.bot.user.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None, "No pude verificar permisos y jerarquía actuales."
        if getattr(live_guild, "id", None) != guild.id:
            return None, "La identidad actual del servidor no coincide."

        roles_by_id = {int(item.id): item for item in live_roles}

        def role_state(member: discord.Member):
            role_ids = {guild.id}
            role_ids.update(int(item) for item in getattr(member, "_roles", ()))
            if any(item not in roles_by_id for item in role_ids):
                return None
            roles = [roles_by_id[item] for item in role_ids]
            permissions_value = 0
            for item in roles:
                permissions_value |= int(item.permissions.value)
            return discord.Permissions(permissions_value), max(roles)

        actor_state = role_state(actor)
        bot_state = role_state(bot_member)
        if actor_state is None or bot_state is None:
            return None, "No pude verificar la jerarquía completa de roles."
        actor_permissions, actor_top = actor_state
        _bot_permissions, bot_top = bot_state
        owner_id = int(live_guild.owner_id)

        if owner_or_admin_only:
            if actor.id != owner_id and not actor_permissions.administrator:
                return None, "Solo el dueño o un administrador puede cambiar ese rol."
        elif actor.id != owner_id and not (
            actor_permissions.administrator
            or (
                actor_permissions.manage_roles
                and actor_permissions.manage_channels
            )
        ):
            return None, "Necesitas Administrador o Gestionar roles y canales."

        role = roles_by_id.get(int(role_id))
        if role is None or role.is_default() or role.managed:
            return None, "Ese rol no existe o no puede gestionarse."
        if actor.id != owner_id and role >= actor_top:
            return None, "El rol debe estar por debajo de tu rol más alto."
        if role >= bot_top:
            return None, "El rol debe estar por debajo de mi rol más alto."
        return role, None

    @staticmethod
    def _mute_overwrite() -> discord.PermissionOverwrite:
        return discord.PermissionOverwrite(
            send_messages=False,
            add_reactions=False,
            speak=False,
            send_messages_in_threads=False,
            create_public_threads=False,
            create_private_threads=False,
        )

    async def _apply_mute_overwrites(self, guild: discord.Guild, role: discord.Role) -> int:
        """Aplica permisos del rol Muted en canales visibles para el bot, best-effort."""
        bot_member = guild.get_member(self.bot.user.id) if self.bot.user else None
        if not bot_member or not bot_member.guild_permissions.manage_channels:
            return 0
        overwrite = self._mute_overwrite()
        changed = 0
        for ch in guild.channels:
            try:
                await ch.set_permissions(role, overwrite=overwrite, reason="Mute role setup")
                changed += 1
            except (discord.Forbidden, discord.HTTPException):
                continue
        return changed

    async def _confirm_effective_mute(
        self,
        guild: discord.Guild,
        user_id: int,
        role: discord.Role,
    ) -> Optional[discord.Member]:
        """Keep a mute only when the member's combined permissions deny it."""
        member, live_role, removal_state = await self._fresh_mute_removal_context(
            guild, user_id, role.id
        )
        if removal_state != "safe" or member is None or live_role is None:
            logger.warning("Mute verification guild=%s user=%s role=%s category=%s", guild.id, user_id, role.id, removal_state)
            return None
        if member_is_effectively_muted(member):
            return member
        logger.warning("Mute verification guild=%s user=%s role=%s category=ineffective_permissions", guild.id, user_id, role.id)
        try:
            await member.remove_roles(
                live_role, reason="Mute inefectivo; reversión segura"
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    def _safe_mute_role_removal(
        self,
        guild: discord.Guild,
        role: Optional[discord.Role],
        bot_member: Optional[discord.Member],
        *,
        bot_top_role: Optional[discord.Role] = None,
    ) -> bool:
        """No retira un antiguo rol de mute si ahora delega privilegios."""
        forbidden_ids = delegated_bot_role_ids(self.db, guild.id)
        return bool(
            (bot_top_role is None or (role is not None and role < bot_top_role))
            and safe_for_automatic_removal(role, bot_member)
            and safe_for_automatic_assignment(
                role,
                bot_member,
                forbidden_role_ids=forbidden_ids,
            )
        )

    async def _fresh_mute_removal_context(
        self,
        guild: discord.Guild,
        user_id: int,
        role_id: int,
    ) -> tuple[Optional[discord.Member], Optional[discord.Role], str]:
        """Resuelve miembro, rol y jerarquía actuales justo antes de retirarlo."""
        if not self.bot.user:
            return None, None, "unverified"
        target_missing = object()

        async def fetch_target():
            try:
                return await guild.fetch_member(int(user_id))
            except discord.NotFound:
                return target_missing

        try:
            target_result, live_roles, bot_member, live_channels, live_guild = await asyncio.gather(
                fetch_target(),
                guild.fetch_roles(),
                guild.fetch_member(self.bot.user.id),
                guild.fetch_channels(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InvalidData):
            return None, None, "unverified"
        if live_guild.id != guild.id:
            return None, None, "unverified"
        if target_result is target_missing:
            return None, None, "absent"
        # Permission evaluation must use these REST results, never the Gateway cache.
        view = copy(guild)
        view.owner_id = live_guild.owner_id
        view._roles = {role.id: copy(role) for role in live_roles}
        view._channels = {channel.id: copy(channel) for channel in live_channels}
        for role in view._roles.values():
            role.guild = view
        for channel in view._channels.values():
            channel.guild = view
        member = copy(target_result)
        member.guild = view
        bot_member = copy(bot_member)
        bot_member.guild = view
        live_role = view.get_role(int(role_id))
        member_role_ids = {
            int(value) for value in getattr(member, "_roles", ())
        }
        if live_role is None or int(role_id) not in member_role_ids:
            return member, None, "absent"

        bot_role_ids = {guild.id}
        bot_role_ids.update(
            int(value) for value in getattr(bot_member, "_roles", ())
        )
        roles_by_id = {int(current_role.id): current_role for current_role in live_roles}
        if any(role_id_value not in roles_by_id for role_id_value in bot_role_ids | member_role_ids):
            return member, live_role, "unverified"
        bot_top_role = max(roles_by_id[value] for value in bot_role_ids)
        if not self._safe_mute_role_removal(
            guild,
            live_role,
            bot_member,
            bot_top_role=bot_top_role,
        ):
            return member, live_role, "unsafe"
        return member, live_role, "safe"

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Keep the configured mute role effective on newly created channels."""
        guild = channel.guild
        try:
            role_id = int((self.db.get_config(guild.id) or {}).get("mute_role_id") or 0)
        except (TypeError, ValueError):
            return
        role = guild.get_role(role_id) if role_id else None
        bot_member = guild.me
        if not safe_for_automatic_assignment(
            role,
            bot_member,
            forbidden_role_ids=delegated_bot_role_ids(self.db, guild.id),
        ):
            return
        try:
            await channel.set_permissions(
                role,
                overwrite=self._mute_overwrite(),
                reason="Mute role setup for new channel",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "No se pudo aplicar el rol mute %s al nuevo canal %s",
                role.id,
                channel.id,
            )

    def _can_moderate(
        self,
        actor: discord.Member,
        target: discord.Member,
        *,
        bot_member: Optional[discord.Member] = None,
        action_type: str = "",
    ) -> Optional[str]:
        """
        Verifica jerarquía de roles.
        Retorna None si la acción es válida, o un string de error si no.
        """
        if target.bot:
            return "No puedes moderar a un bot."
        if actor.id == target.id:
            return "No puedes moderarte a ti mismo."
        if target.id == actor.guild.owner_id:
            return "No puedes moderar al dueño del servidor."
        if target.guild_permissions.administrator and action_type == "TIMEOUT":
            return "Discord no permite aplicar timeout a administradores. Usa /mute."
        if actor.id != actor.guild.owner_id and actor.top_role <= target.top_role:
            return "Tu rol no es suficientemente alto para moderar a este usuario."
        if bot_member is None and self.bot.user:
            bot_member = actor.guild.get_member(self.bot.user.id)
        if bot_member is None:
            return "No puedo verificar mi jerarquía de roles."
        if bot_member.top_role <= target.top_role:
            return "Mi rol no es suficiente para moderar a este usuario."
        return None

    @staticmethod
    def _json_object(raw: object) -> dict:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            value = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _ban_effect_token(self, case: Optional[Dict]) -> str:
        if not case:
            return ""
        return str(
            self._json_object(case.get("extra_data")).get("ban_effect_token") or ""
        ).strip()

    def _mute_effect_token(self, case: Optional[Dict]) -> str:
        if not case:
            return ""
        return str(
            self._json_object(case.get("extra_data")).get("mute_effect_token") or ""
        ).strip()

    async def _mute_effect_state(
        self,
        guild: discord.Guild,
        user_id: int,
        role_id: int,
        case: Optional[Dict],
        *,
        member: Optional[discord.Member] = None,
    ) -> str:
        """Retorna match, absent, replaced, legacy o unverified."""
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except discord.NotFound:
                return "absent"
        member_role_ids = {
            int(value) for value in getattr(member, "_roles", ())
        }
        if int(role_id) not in member_role_ids:
            return "absent"
        token = self._mute_effect_token(case)
        if not token:
            return "legacy"
        extra = self._json_object((case or {}).get("extra_data"))
        try:
            created_at = datetime.fromisoformat(
                str((case or {})["created_at"]).replace("Z", "+00:00")
            )
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            audit_after = created_at - timedelta(minutes=5)
        except (KeyError, TypeError, ValueError):
            return "unverified"
        try:
            async for entry in guild.audit_logs(
                limit=None,
                action=discord.AuditLogAction.member_role_update,
                after=audit_after,
                oldest_first=False,
            ):
                if int(getattr(entry.target, "id", 0) or 0) != int(user_id):
                    continue
                before_ids = {
                    int(role.id)
                    for role in (getattr(entry.before, "roles", None) or ())
                }
                after_ids = {
                    int(role.id)
                    for role in (getattr(entry.after, "roles", None) or ())
                }
                if int(role_id) not in before_ids.union(after_ids):
                    continue
                if (int(role_id) in after_ids and mute_reason_matches(entry.reason, token)
                    and (not extra.get("mute_add_audit_id") or
                         getattr(getattr(entry, "user", None), "id", None) == self.bot.user.id)):
                    return "match"
                return "replaced"
        except (discord.Forbidden, discord.HTTPException):
            return "unverified"
        if (extra.get("mute_add_audit_id")
            and str(member.joined_at) == extra.get("mute_member_joined_at")):
            return "match"
        return "unverified"

    async def _confirm_mute_effect_state(
        self,
        guild: discord.Guild,
        user_id: int,
        role_id: int,
        case: Optional[Dict],
        *,
        member: Optional[discord.Member] = None,
    ) -> str:
        """Tolera la breve demora de propagación del audit log tras add_roles."""
        state = "unverified"
        for attempt in range(4):
            state = await self._mute_effect_state(
                guild,
                user_id,
                role_id,
                case,
                member=member,
            )
            if state != "unverified" or attempt == 3:
                return state
            await asyncio.sleep(0.75)
        return state

    async def _ban_effect_state(
        self,
        guild: discord.Guild,
        user_id: int,
        case: Optional[Dict],
    ) -> str:
        """Retorna match, absent, replaced o legacy para el ban actual."""
        token = self._ban_effect_token(case)
        if not token:
            return "legacy"
        try:
            entry = await guild.fetch_ban(discord.Object(id=int(user_id)))
        except discord.NotFound:
            return "absent"
        return "match" if ban_reason_matches(entry.reason, token) else "replaced"

    async def _confirm_ban_effect(
        self, guild: discord.Guild, user_id: int, token: str
    ) -> None:
        entry = await guild.fetch_ban(discord.Object(id=int(user_id)))
        if not ban_reason_matches(entry.reason, token):
            raise RuntimeError("ban_effect_identity_not_confirmed")

    def _current_ban_matches_active_case(
        self, guild_id: int, user_id: int, reason: object
    ) -> bool:
        try:
            cases = self.db.list_cases(guild_id, user_id=user_id, limit=100)
        except Exception:
            return False
        for case in cases:
            if (
                str(case.get("status") or "active").lower() == "active"
                and str(case.get("action_type") or "").upper()
                in {"BAN", "TEMPBAN", "FORCEBAN", "AUTO_BAN"}
                and ban_reason_matches(reason, self._ban_effect_token(case))
            ):
                return True
        return False

    async def _reconcile_applying_bans(self) -> None:
        """Reconcilia intents de sanción; los bloqueos posteriores son por usuario."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            unresolved = False
            try:
                cases = self.db.get_applying_ban_cases()
            except Exception as exc:
                logger.error("No se pudieron leer bans en applying: %s", exc)
                cases = []
                unresolved = True
            for snapshot in cases:
                try:
                    guild_id = int(snapshot["guild_id"])
                    user_id = int(snapshot["target_id"])
                    case_id = int(snapshot["id"])
                except (KeyError, TypeError, ValueError):
                    unresolved = True
                    continue
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    unresolved = True
                    continue

                async def reconcile_case():
                    case = self.db.get_case_by_id(guild_id, case_id)
                    case_status = str(
                        (case or {}).get("status") or ""
                    ).lower()
                    if (
                        case is None
                        or case_status not in {"applying", "effect_confirmed"}
                    ):
                        return
                    action_type = str(case.get("action_type") or "").upper()
                    if case_status == "effect_confirmed" and action_type != "SOFTBAN":
                        return
                    token = self._ban_effect_token(case)
                    if not token:
                        self.db.abandon_prepared_ban_case(
                            guild_id,
                            user_id,
                            case_id,
                            "missing_ban_effect_identity",
                        )
                        return
                    try:
                        entry = await guild.fetch_ban(discord.Object(id=user_id))
                    except discord.NotFound:
                        if action_type == "SOFTBAN":
                            if case_status == "effect_confirmed":
                                if not self.db.complete_prepared_softban_case(
                                    guild_id, user_id, case_id
                                ):
                                    raise RuntimeError("prepared_softban_case_changed")
                            else:
                                self.db.abandon_prepared_ban_case(
                                    guild_id,
                                    user_id,
                                    case_id,
                                    "prepared_softban_effect_absent",
                                )
                            return
                        self.db.abandon_prepared_ban_case(
                            guild_id,
                            user_id,
                            case_id,
                            "prepared_ban_effect_absent",
                            retire_previous=True,
                        )
                        return
                    if not ban_reason_matches(entry.reason, token):
                        previous_is_current = self._current_ban_matches_active_case(
                            guild_id, user_id, entry.reason
                        )
                        self.db.abandon_prepared_ban_case(
                            guild_id,
                            user_id,
                            case_id,
                            "prepared_ban_effect_replaced",
                            retire_previous=not previous_is_current,
                        )
                        return
                    if action_type == "SOFTBAN":
                        if case_status == "applying" and not (
                            self.db.confirm_prepared_softban_effect(
                                guild_id, user_id, case_id
                            )
                        ):
                            raise RuntimeError("prepared_softban_confirmation_changed")
                        try:
                            await guild.unban(
                                discord.Object(id=user_id),
                                reason="Recuperación de softban interrumpido",
                            )
                        except discord.NotFound:
                            pass
                        if not self.db.complete_prepared_softban_case(
                            guild_id, user_id, case_id
                        ):
                            raise RuntimeError("prepared_softban_case_changed")
                        return
                    duration_raw = case.get("duration_seconds")
                    duration = int(duration_raw) if duration_raw is not None else None
                    expires_at = None
                    if duration is not None:
                        created_at = datetime.fromisoformat(str(case["created_at"]))
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=timezone.utc)
                        expires_at = (
                            created_at + timedelta(seconds=duration)
                        ).isoformat()
                    if not self.db.activate_prepared_ban_case(
                        guild_id,
                        user_id,
                        case_id,
                        int(case["moderator_id"]),
                        str(case.get("reason") or "Sin razón especificada"),
                        duration,
                        expires_at,
                    ):
                        raise RuntimeError("prepared_ban_case_changed")

                try:
                    await run_sanction_locked(
                        self.bot,
                        guild_id,
                        user_id,
                        "BAN",
                        reconcile_case,
                    )
                except asyncio.CancelledError:
                    raise
                except (discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning(
                        "No se pudo reconciliar ban applying %s: %s", case_id, exc
                    )
                    unresolved = True
                except Exception as exc:
                    logger.error(
                        "Error reconciliando ban applying %s: %s",
                        case_id,
                        exc,
                        exc_info=True,
                    )
                    unresolved = True
            try:
                mute_cases = self.db.get_applying_mute_cases()
            except Exception as exc:
                logger.error("No se pudieron leer mutes en applying: %s", exc)
                mute_cases = []
                unresolved = True
            for snapshot in mute_cases:
                try:
                    guild_id = int(snapshot["guild_id"])
                    user_id = int(snapshot["target_id"])
                    case_id = int(snapshot["id"])
                except (KeyError, TypeError, ValueError):
                    unresolved = True
                    continue
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue

                async def reconcile_mute_case():
                    case = self.db.get_case_by_id(guild_id, case_id)
                    if (
                        case is None
                        or str(case.get("status") or "").lower() != "applying"
                    ):
                        return
                    extra = self._json_object(case.get("extra_data"))
                    try:
                        role_id = int(extra["role_id"])
                    except (KeyError, TypeError, ValueError):
                        self.db.abandon_prepared_mute_case(
                            guild_id, user_id, case_id
                        )
                        return
                    if not self._mute_effect_token(case):
                        self.db.abandon_prepared_mute_case(
                            guild_id, user_id, case_id
                        )
                        return
                    live_roles, bot_member = await asyncio.gather(
                        guild.fetch_roles(),
                        guild.fetch_member(self.bot.user.id),
                    )
                    role = discord.utils.get(live_roles, id=role_id)
                    if role is None:
                        await self._restore_mute_roles(guild, user_id, case)
                        self.db.abandon_prepared_mute_case(
                            guild_id, user_id, case_id
                        )
                        return
                    effect_state = await self._mute_effect_state(
                        guild,
                        user_id,
                        role_id,
                        case,
                    )
                    if effect_state in {"absent", "replaced", "legacy"}:
                        if effect_state != "absent" and extra.get("suppressed_roles"):
                            raise RuntimeError("prepared_mute_roles_need_manual_review")
                        await self._restore_mute_roles(guild, user_id, case)
                        self.db.abandon_prepared_mute_case(
                            guild_id, user_id, case_id
                        )
                        return
                    if effect_state != "match":
                        raise RuntimeError("prepared_mute_effect_unverified")
                    if extra.get("mute_restore_started"):
                        member, removal_role, state = await self._fresh_mute_removal_context(
                            guild, user_id, role_id
                        )
                        if state != "safe":
                            raise RuntimeError("prepared_mute_rollback_not_safe")
                        await member.remove_roles(removal_role, reason="Revertir mute incompleto")
                        await self._restore_mute_roles(guild, user_id, case)
                        self.db.abandon_prepared_mute_case(guild_id, user_id, case_id)
                        return
                    confirmed_member = await self._confirm_effective_mute(
                        guild, user_id, role
                    )
                    if confirmed_member is None:
                        try:
                            remaining_member = await guild.fetch_member(user_id)
                        except discord.NotFound:
                            remaining_member = None
                        if remaining_member is not None and role_id in {
                            int(value)
                            for value in getattr(remaining_member, "_roles", ())
                        }:
                            raise RuntimeError(
                                "prepared_mute_rollback_unconfirmed"
                            )
                        await self._restore_mute_roles(guild, user_id, case)
                        self.db.abandon_prepared_mute_case(
                            guild_id, user_id, case_id
                        )
                        return
                    await confirm_mute_receipts(self.bot, guild, user_id, case, self.db)
                    if not self.db.activate_prepared_mute_case(
                        guild_id, user_id, case_id
                    ):
                        raise RuntimeError("prepared_mute_case_changed")

                try:
                    await run_sanction_locked(
                        self.bot,
                        guild_id,
                        user_id,
                        "MUTE",
                        reconcile_mute_case,
                    )
                except asyncio.CancelledError:
                    raise
                except (discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning(
                        "No se pudo reconciliar mute applying %s: %s", case_id, exc
                    )
                    unresolved = True
                except Exception as exc:
                    logger.error(
                        "Error reconciliando mute applying %s: %s",
                        case_id,
                        exc,
                        exc_info=True,
                    )
                    unresolved = True
            if unresolved:
                logger.warning(
                    "Quedan sanciones applying pendientes de reconciliación"
                )
            self._ban_reconciliation_ready.set()
            await asyncio.sleep(15)

    async def _expire_tempban_case_locked(
        self,
        guild: discord.Guild,
        user_id: int,
        case_id: int,
    ) -> str:
        """Expira el tempban exacto; debe ejecutarse bajo el lock BAN."""
        if self.db.has_applying_ban_case(guild.id, int(user_id)):
            return "applying"
        case = self.db.get_appealable_active_case(
            guild.id, int(user_id), int(case_id), "TEMPBAN"
        )
        if case is None:
            return "stale"
        effect_state = await self._ban_effect_state(guild, user_id, case)
        if effect_state == "legacy":
            return "legacy"
        if effect_state == "replaced":
            self.db.clear_tempban_case(guild.id, user_id, case_id)
            self.db.update_case_by_id(guild.id, case_id, status="revoked")
            return "replaced"
        if effect_state == "match":
            try:
                await guild.unban(
                    discord.Object(id=int(user_id)),
                    reason="Tempban expirado automáticamente",
                )
            except discord.NotFound:
                pass
        self.db.clear_tempban_case(guild.id, user_id, case_id)
        self.db.update_case_by_id(guild.id, case_id, status="expired")
        self.db.log_action(
            guild.id,
            user_id,
            self.bot.user.id,
            "TEMPBAN_EXPIRED",
            "Tempban expirado automáticamente",
            parent_case_id=case_id,
            status="expired",
        )
        return "expired"

    async def _restore_mute_roles(self, guild, user_id, case, *, actor_id=None):
        if not case:
            return
        extra = self._json_object(case.get("extra_data"))
        if not extra.get("suppressed_roles"):
            return
        # Persist recovery direction before the first restoration side effect.
        if not extra.get("mute_restore_started"):
            extra["mute_restore_started"] = True
            case = self.db.update_case_by_id(
                guild.id, int(case["id"]), extra_data=json.dumps(extra)
            )
            if not case:
                raise RuntimeError("mute_restore_intent_not_persisted")
        await restore_roles(self.bot, guild, user_id, case, actor_id=actor_id, db=self.db)

    async def _apply_role_mute(
        self, interaction, target_id, role_id, action_type, reason, duration,
        *, moderator_id=None, parent_case_id=None, job_action="MUTE_EXPIRE", metadata=None, evidence=None, evidence_url=None,
    ):
        guild = interaction.guild
        member, bot_member, actor = await fresh_members(
            self.bot, guild, target_id, interaction.user.id
        )
        if not self._member_has_mod_perms(member.guild, actor, "manage_roles"):
            raise PermissionError("Tus permisos cambiaron; la operación fue cancelada.")
        if action_type.startswith("AUTO_") and member.guild_permissions.administrator:
            raise PermissionError("La moderación automática mantiene la protección de administradores.")
        role = member.guild.get_role(role_id)
        if not (safe_for_automatic_assignment(
            role, bot_member, forbidden_role_ids=delegated_bot_role_ids(self.db, guild.id)
        ) and mute_role_has_effective_denies(member.guild, role)):
            raise PermissionError("El rol de mute ya no es seguro.")
        suppressed = plan_role_mute(member, bot_member, actor, role)
        token = new_mute_effect_token()
        expiry, case_id = self._prepare_mute_record(
            guild.id, target_id, moderator_id or actor.id, action_type, reason,
            duration, role_id, job_action=job_action, parent_case_id=parent_case_id, evidence=evidence, evidence_url=evidence_url,
            extra={**(metadata if metadata is not None else interaction_metadata(interaction, target_id, actor)),
                "mute_effect_token": token,
                "suppressed_roles": [role_permissions(value) for value in suppressed],
                "mute_member_joined_at": str(member.joined_at)},
        )
        audit_reason = reason_with_mute_effect(f"{action_type}: {reason} | Mod: {actor}", token)
        try:
            await member.add_roles(role, reason=audit_reason)
            for suppressed_role in suppressed:
                await member.remove_roles(suppressed_role, reason=audit_reason)
            confirmed = await self._confirm_effective_mute(guild, target_id, role)
            if confirmed is None:
                raise RuntimeError("ineffective_mute")
            case = self.db.get_case_by_id(guild.id, case_id)
            await confirm_mute_receipts(self.bot, guild, target_id, case, self.db)
            if await self._confirm_mute_effect_state(
                guild, target_id, role_id, case, member=confirmed
            ) != "match":
                raise RuntimeError("mute_effect_identity_not_confirmed")
            if not self.db.activate_prepared_mute_case(guild.id, target_id, case_id):
                raise RuntimeError("mute_intent_changed")
            return actor, confirmed, expiry, case_id
        except Exception:
            case = self.db.get_case_by_id(guild.id, case_id)
            try:
                effect = await self._mute_effect_state(guild, target_id, role_id, case)
                if effect == "match":
                    rollback_member, rollback_role, state = await self._fresh_mute_removal_context(
                        guild, target_id, role_id
                    )
                    if state != "safe":
                        raise RuntimeError("mute_rollback_not_safe")
                    await rollback_member.remove_roles(rollback_role, reason="Revertir mute incompleto")
                elif effect != "absent":
                    raise RuntimeError("mute_rollback_identity_unverified")
                await self._restore_mute_roles(guild, target_id, case)
                self.db.abandon_prepared_mute_case(guild.id, target_id, case_id)
            except Exception:
                logger.warning("Mute rollback pendiente guild=%s user=%s case=%s", guild.id, target_id, case_id)
                raise RuntimeError("mute_rollback_pending") from None
            raise RuntimeError("mute_rolled_back") from None

    def _prepare_mute_record(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action_type: str,
        reason: str,
        duration_secs: Optional[int],
        role_id: int,
        *,
        job_action: str = "MUTE_EXPIRE",
        parent_case_id: Optional[int] = None,
        extra: Optional[Dict] = None,
        evidence=None, evidence_url=None,
    ) -> tuple[Optional[datetime], int]:
        """Persiste una intención recuperable antes de tocar el rol Discord."""
        configured_role_id = int(
            (self.db.get_config(guild_id) or {}).get("mute_role_id") or 0
        )
        if configured_role_id != int(role_id):
            raise ValueError("mute_role_configuration_changed")
        if self.db.has_active_mute_case(guild_id, user_id) or self.db.has_applying_mute_case(
            guild_id, user_id
        ):
            raise LookupError("existing_mute_case")
        mute_start = datetime.now(timezone.utc)
        expiry: Optional[datetime] = None
        if duration_secs is not None:
            expiry = mute_start + timedelta(seconds=int(duration_secs))

        case_extra = dict(extra or {})
        case_extra.update(
            {
                "duration_secs": duration_secs,
                "role_id": int(role_id),
                "mute_job_action": str(job_action).upper(),
                "mute_start": mute_start.isoformat(),
            }
        )
        if expiry is not None:
            case_extra["expires_at"] = expiry.isoformat()
        case_id = self.db.log_action(
            guild_id,
            user_id,
            moderator_id,
            action_type,
            reason,
            case_extra,
            status="applying",
            duration_seconds=duration_secs,
            expires_at=expiry.isoformat() if expiry else None,
            parent_case_id=parent_case_id, evidence=evidence, evidence_url=evidence_url,
        )
        if not case_id:
            raise RuntimeError("mute_intent_not_persisted")
        return expiry, case_id

    def _replace_mute_record(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action_type: str,
        reason: str,
        duration_secs: Optional[int],
        role_id: int,
        *,
        job_action: str = "MUTE_EXPIRE",
        parent_case_id: Optional[int] = None,
        extra: Optional[Dict] = None,
    ) -> tuple[Optional[datetime], int]:
        """Compatibilidad: prepara y activa el tracking de mute atómicamente."""
        expiry, case_id = self._prepare_mute_record(
            guild_id,
            user_id,
            moderator_id,
            action_type,
            reason,
            duration_secs,
            role_id,
            job_action=job_action,
            parent_case_id=parent_case_id,
            extra=extra,
        )
        if not self.db.activate_prepared_mute_case(guild_id, user_id, case_id):
            raise RuntimeError("mute_intent_changed")
        return expiry, case_id

    def _active_mute_case(self, guild_id: int, user_id: int) -> Optional[Dict]:
        return self.db.get_active_mute_case(guild_id, user_id)

    def _active_mute_role_id(self, guild_id: int, user_id: int) -> int:
        """Resolve the exact role recorded by the current mute sanction."""
        case = self._active_mute_case(guild_id, user_id)
        if case:
            try:
                return int(self._json_object(case.get("extra_data"))["role_id"])
            except (KeyError, TypeError, ValueError):
                pass
        try:
            return int((self.db.get_config(guild_id) or {}).get("mute_role_id") or 0)
        except (TypeError, ValueError):
            return 0

    def _mute_job_role_id(self, job: Dict) -> Optional[int]:
        """Return the exact role only while this job is the current mute."""
        try:
            guild_id = int(job["guild_id"])
            user_id = int(job["user_id"])
            case_id = int(job["case_id"])
            execute_at = datetime.fromisoformat(str(job["execute_at"]))
            job_extra = self._json_object(job.get("extra_data"))
            role_id = int(job_extra["role_id"])
            extra_expiry = datetime.fromisoformat(str(job_extra["expires_at"]))
        except (KeyError, TypeError, ValueError):
            return None
        if role_id <= 0 or execute_at != extra_expiry:
            return None

        case = self.db.get_case_by_id(guild_id, case_id)
        if not case or str(case.get("status") or "").lower() != "active":
            return None
        if int(case.get("target_id") or 0) != user_id:
            return None
        job_action = str(job.get("action_type") or "").upper()
        expected_cases = {
            "MUTE_EXPIRE": {"MUTE", "AUTO_MUTE"},
            "HARDMUTE_EXPIRE": {"HARDMUTE"},
            "UNMUTE": {"MUTE", "AUTO_MUTE", "HARDMUTE"},
        }
        if str(case.get("action_type") or "").upper() not in expected_cases.get(
            job_action, set()
        ):
            return None

        case_extra = self._json_object(case.get("extra_data"))
        try:
            case_role_id = int(case_extra["role_id"])
            case_expiry = datetime.fromisoformat(str(case.get("expires_at")))
            embedded_expiry = datetime.fromisoformat(str(case_extra["expires_at"]))
            record = self.db.get_user(user_id, guild_id)
            record_start = datetime.fromisoformat(str(record["mute_start"]))
            record_expiry = record_start + timedelta(seconds=int(record["mute_duration"]))
        except (KeyError, TypeError, ValueError):
            return None
        if not (
            case_role_id == role_id
            and case_expiry == execute_at
            and embedded_expiry == execute_at
            and record_expiry == execute_at
        ):
            return None
        return role_id

    # ── Tarea: expiración de mutes ────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _check_mutes(self):
        """Revisa cada minuto si algún mute temporal ha expirado."""
        try:
            for record in self.db.get_active_mutes():
                try:
                    guild = self.bot.get_guild(record["guild_id"])
                    if not guild:
                        continue
                    user_id = int(record["user_id"])

                    async def expire_legacy_mute():
                        if self.db.has_applying_mute_case(guild.id, user_id):
                            return "applying", None
                        if self.db.has_pending_moderation_action(
                            guild.id,
                            user_id,
                            ["MUTE_EXPIRE", "HARDMUTE_EXPIRE", "UNMUTE"],
                        ):
                            return "scheduled", None
                        current = self.db.get_user(user_id, guild.id)
                        if (
                            str(current.get("mute_start"))
                            != str(record.get("mute_start"))
                            or int(current.get("mute_duration") or 0)
                            != int(record.get("mute_duration") or 0)
                        ):
                            return "replaced", None
                        try:
                            start = datetime.fromisoformat(str(record["mute_start"]))
                            expiry = start + timedelta(
                                seconds=int(record["mute_duration"])
                            )
                        except (KeyError, TypeError, ValueError):
                            return "invalid", None
                        if datetime.now(timezone.utc) < expiry:
                            return "not_due", None
                        if not self.bot.user:
                            return "missing_bot", None
                        mute_role_id = self._active_mute_role_id(guild.id, user_id)
                        try:
                            current_member = await guild.fetch_member(user_id)
                        except discord.NotFound:
                            current_member = None
                        active_case = self._active_mute_case(guild.id, user_id)
                        effect_state = (
                            await self._mute_effect_state(
                                guild,
                                user_id,
                                mute_role_id,
                                active_case,
                                member=current_member,
                            )
                            if current_member is not None
                            else "absent"
                        )
                        if effect_state in {"legacy", "unverified"}:
                            return effect_state, current_member
                        if effect_state == "replaced":
                            if self._json_object((active_case or {}).get("extra_data")).get("suppressed_roles"):
                                raise PermissionError("El mute fue reemplazado; los roles retirados requieren revisión manual.")
                            self.db.clear_mute(user_id, guild.id)
                            if active_case:
                                self.db.update_case_by_id(
                                    guild.id,
                                    int(active_case["id"]),
                                    status="revoked",
                                )
                            return "replaced_effect", current_member
                        if effect_state == "match":
                            removal_member, removal_role, removal_state = (
                                await self._fresh_mute_removal_context(
                                    guild, user_id, mute_role_id
                                )
                            )
                            if removal_state in {"unsafe", "unverified"}:
                                return removal_state, removal_member
                            if (
                                removal_state == "safe"
                                and removal_member is not None
                                and removal_role is not None
                            ):
                                final_effect_state = await self._mute_effect_state(
                                    guild,
                                    user_id,
                                    mute_role_id,
                                    active_case,
                                )
                                if final_effect_state in {"legacy", "unverified"}:
                                    return final_effect_state, removal_member
                                if final_effect_state == "replaced":
                                    if self._json_object((active_case or {}).get("extra_data")).get("suppressed_roles"):
                                        raise PermissionError("El mute fue reemplazado; los roles retirados requieren revisión manual.")
                                    self.db.clear_mute(user_id, guild.id)
                                    if active_case:
                                        self.db.update_case_by_id(
                                            guild.id,
                                            int(active_case["id"]),
                                            status="revoked",
                                        )
                                    return "replaced_effect", removal_member
                                if final_effect_state == "match":
                                    await removal_member.remove_roles(
                                        removal_role,
                                        reason="Mute expirado automáticamente",
                                    )
                            current_member = removal_member
                        await self._restore_mute_roles(guild, user_id, active_case)
                        self.db.clear_mute(user_id, guild.id)
                        self.db.revoke_active_moderations(
                            guild.id,
                            user_id,
                            ["MUTE", "AUTO_MUTE", "HARDMUTE"],
                            status="expired",
                        )
                        self.db.log_action(
                            guild.id,
                            user_id,
                            self.bot.user.id,
                            "AUTO_UNMUTE",
                            "Mute temporal expirado",
                            status="expired",
                        )
                        return "expired", current_member

                    try:
                        result, member = await run_sanction_locked(
                            self.bot,
                            guild.id,
                            user_id,
                            "MUTE_EXPIRE",
                            expire_legacy_mute,
                        )
                    except discord.Forbidden:
                        logger.warning(
                            "Sin permisos para quitar mute a %s en %s",
                            user_id,
                            guild.name,
                        )
                        continue
                    except discord.HTTPException as exc:
                        logger.warning(
                            "Error quitando mute expirado a %s en %s: %s",
                            user_id,
                            guild.name,
                            exc,
                        )
                        continue
                    if result == "invalid":
                        logger.warning(
                            "Registro de mute inválido para user_id=%s guild_id=%s",
                            user_id,
                            guild.id,
                        )
                        continue
                    if result == "unsafe":
                        logger.warning(
                            "Mute expirado no retirado en %s: rol inseguro",
                            guild.id,
                        )
                        continue
                    if result in {"legacy", "unverified"}:
                        logger.warning(
                            "Mute expirado no retirado en %s: identidad del efecto no verificable",
                            guild.id,
                        )
                        continue
                    if result == "replaced_effect":
                        logger.warning(
                            "Mute expirado %s cancelado sin retirar el rol: el efecto fue reemplazado",
                            user_id,
                        )
                        continue
                    if result != "expired":
                        continue

                    log_embed = discord.Embed(
                        title="Mute expirado",
                        description=f"<@{user_id}> fue desmuteado automáticamente.",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    log_embed.set_footer(text=f"ID: {user_id}")
                    await self._send_log(guild, log_embed)
                    logger.info("Mute expirado: %s en %s", user_id, guild.name)

                except Exception as exc:
                    logger.error("Error al expirar mute individual: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Error en _check_mutes: %s", exc, exc_info=True)

    @_check_mutes.before_loop
    async def _before_check_mutes(self):
        await self.bot.wait_until_ready()
        await self._ban_reconciliation_ready.wait()

    # ── Tarea: expiración de tempbans ──────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _check_tempbans(self):
        """Revisa cada minuto si algún tempban ha expirado."""
        try:
            for record in self.db.get_active_tempbans():
                try:
                    guild = self.bot.get_guild(record["guild_id"])
                    if not guild:
                        logger.warning(
                            "Tempban %s conservado: guild %s no está disponible",
                            record.get("id"),
                            record.get("guild_id"),
                        )
                        continue

                    if record.get("case_id") and self.db.has_pending_moderation_action(
                        guild.id,
                        record["user_id"],
                        ["TEMPBAN_EXPIRE", "UNBAN"],
                    ):
                        continue

                    start = datetime.fromisoformat(record["ban_start"])
                    expiry = start + timedelta(seconds=record["ban_duration"])

                    if datetime.now(timezone.utc) >= expiry:
                        case_id = record.get("case_id")
                        if not case_id:
                            logger.warning(
                                "Tempban legacy %s no expirado: falta identidad de caso",
                                record.get("id"),
                            )
                            continue
                        user_id = int(record["user_id"])

                        async def expire_record():
                            result = await self._expire_tempban_case_locked(
                                guild, user_id, int(case_id)
                            )
                            if result == "stale":
                                self.db.clear_tempban(record["id"])
                            return result

                        try:
                            result = await run_sanction_locked(
                                self.bot,
                                guild.id,
                                user_id,
                                "TEMPBAN_EXPIRE",
                                expire_record,
                            )
                        except discord.Forbidden:
                            logger.warning("Sin permisos para desbanear tempban expirado de %s en %s", user_id, guild.name)
                            continue
                        except discord.HTTPException as exc:
                            logger.warning("Error desbaneando tempban expirado %s en %s: %s", user_id, guild.name, exc)
                            continue

                        if result == "legacy":
                            logger.warning(
                                "Tempban %s no expirado: el caso no conserva identidad del ban",
                                case_id,
                            )
                            continue
                        if result == "applying":
                            continue
                        if result == "replaced":
                            logger.warning(
                                "Tempban %s cancelado sin unban: el efecto fue reemplazado",
                                case_id,
                            )
                            continue
                        if result != "expired":
                            continue

                        log_embed = discord.Embed(
                            title="Tempban expirado",
                            description=f"<@{user_id}> fue desbaneado automáticamente.",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        log_embed.set_footer(text=f"ID: {user_id}")
                        await self._send_log(guild, log_embed)
                        logger.info("Tempban expirado: %s en %s", user_id, guild.name)

                except Exception as exc:
                    logger.error("Error al expirar tempban individual: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Error en _check_tempbans: %s", exc, exc_info=True)

    @_check_tempbans.before_loop
    async def _before_check_tempbans(self):
        await self.bot.wait_until_ready()
        await self._ban_reconciliation_ready.wait()

    # ── Tarea: scheduler idempotente de moderación ────────────────────────────

    @tasks.loop(minutes=1)
    async def _check_pending_moderation(self):
        """Procesa expiraciones persistentes para tempban/mute/timeout."""
        now = datetime.now(timezone.utc)
        try:
            pending = self.db.get_due_pending_moderation_actions(now.isoformat())
        except Exception as exc:
            logger.error("Error leyendo pending_moderation_actions: %s", exc, exc_info=True)
            return

        for job in pending:
            action_id = job.get("id")
            if not self.db.claim_pending_moderation_action(int(action_id)):
                continue
            job["status"] = "processing"
            try:
                guild = self.bot.get_guild(job["guild_id"])
                if not guild:
                    self._retry_pending_moderation(job, "guild_not_found")
                    continue

                action_type = (job.get("action_type") or "").upper()
                user_id = int(job["user_id"])
                case_id = job.get("case_id")
                member = guild.get_member(user_id)

                if action_type in {"TEMPBAN_EXPIRE", "UNBAN"}:
                    if not case_id:
                        self.db.update_pending_moderation_action(
                            action_id, "failed", "legacy_tempban_without_case_identity"
                        )
                        continue

                    async def expire_tempban_job():
                        return await self._expire_tempban_case_locked(
                            guild, user_id, int(case_id)
                        )

                    try:
                        result = await run_sanction_locked(
                            self.bot,
                            guild.id,
                            user_id,
                            "TEMPBAN_EXPIRE",
                            expire_tempban_job,
                        )
                    except discord.Forbidden:
                        self.db.update_pending_moderation_action(action_id, "failed", "missing_ban_members")
                        continue
                    if result == "stale":
                        self.db.update_pending_moderation_action(
                            action_id, "cancelled", "stale_tempban_identity"
                        )
                        continue
                    if result == "applying":
                        self._retry_pending_moderation(
                            job, "ban_activation_pending"
                        )
                        continue
                    if result == "legacy":
                        self.db.update_pending_moderation_action(
                            action_id, "failed", "missing_ban_effect_identity"
                        )
                        continue
                    if result == "replaced":
                        self.db.update_pending_moderation_action(
                            action_id, "cancelled", "ban_effect_replaced"
                        )
                        continue

                elif action_type in {"MUTE_EXPIRE", "HARDMUTE_EXPIRE", "UNMUTE"}:
                    async def expire_mute_job():
                        if self.db.has_applying_mute_case(guild.id, user_id):
                            return "applying"
                        mute_role_id = self._mute_job_role_id(job)
                        if mute_role_id is None:
                            return "stale"
                        if not self.bot.user:
                            return "missing_bot"
                        try:
                            current_member = await guild.fetch_member(user_id)
                        except discord.NotFound:
                            current_member = None
                        current_case = (
                            self.db.get_case_by_id(guild.id, int(case_id))
                            if case_id
                            else None
                        )
                        effect_state = (
                            await self._mute_effect_state(
                                guild,
                                user_id,
                                mute_role_id,
                                current_case,
                                member=current_member,
                            )
                            if current_member is not None
                            else "absent"
                        )
                        if effect_state in {"legacy", "unverified"}:
                            return effect_state
                        if effect_state == "replaced":
                            if self._json_object((current_case or {}).get("extra_data")).get("suppressed_roles"):
                                raise PermissionError("El mute fue reemplazado; los roles retirados requieren revisión manual.")
                            self.db.clear_mute(user_id, guild.id)
                            if case_id:
                                self.db.update_case_by_id(
                                    guild.id, int(case_id), status="revoked"
                                )
                            return "replaced_effect"
                        if effect_state == "match":
                            removal_member, removal_role, removal_state = (
                                await self._fresh_mute_removal_context(
                                    guild, user_id, mute_role_id
                                )
                            )
                            if removal_state == "unverified":
                                return "unverified"
                            if removal_state == "unsafe":
                                return "unmanageable"
                            if self._mute_job_role_id(job) != mute_role_id:
                                return "stale"
                            if (
                                removal_state == "safe"
                                and removal_member is not None
                                and removal_role is not None
                            ):
                                final_effect_state = await self._mute_effect_state(
                                    guild,
                                    user_id,
                                    mute_role_id,
                                    current_case,
                                )
                                if final_effect_state in {"legacy", "unverified"}:
                                    return final_effect_state
                                if final_effect_state == "replaced":
                                    if self._json_object((current_case or {}).get("extra_data")).get("suppressed_roles"):
                                        raise PermissionError("El mute fue reemplazado; los roles retirados requieren revisión manual.")
                                    self.db.clear_mute(user_id, guild.id)
                                    if case_id:
                                        self.db.update_case_by_id(
                                            guild.id,
                                            int(case_id),
                                            status="revoked",
                                        )
                                    return "replaced_effect"
                                if final_effect_state == "match":
                                    await removal_member.remove_roles(
                                        removal_role,
                                        reason="Mute expirado automáticamente",
                                    )
                        if self._mute_job_role_id(job) != mute_role_id:
                            return "stale"
                        await self._restore_mute_roles(guild, user_id, current_case)
                        self.db.clear_mute(user_id, guild.id)
                        if case_id:
                            self.db.update_case_by_id(
                                guild.id, int(case_id), status="expired"
                            )
                        self.db.log_action(
                            guild.id,
                            user_id,
                            self.bot.user.id,
                            "MUTE_EXPIRED",
                            "Mute expirado automáticamente",
                            parent_case_id=int(case_id) if case_id else None,
                            status="expired",
                        )
                        return "expired"

                    try:
                        result = await run_sanction_locked(
                            self.bot,
                            guild.id,
                            user_id,
                            action_type,
                            expire_mute_job,
                        )
                    except discord.Forbidden:
                        self.db.update_pending_moderation_action(
                            action_id, "failed", "missing_manage_roles"
                        )
                        continue
                    if result == "stale":
                        self.db.update_pending_moderation_action(
                            action_id, "cancelled", "stale_mute_identity"
                        )
                        continue
                    if result == "applying":
                        self._retry_pending_moderation(
                            job, "mute_activation_pending"
                        )
                        continue
                    if result in {"missing_bot", "unmanageable"}:
                        self.db.update_pending_moderation_action(
                            action_id, "failed", f"{result}_mute_role"
                        )
                        continue
                    if result in {"legacy", "unverified"}:
                        self.db.update_pending_moderation_action(
                            action_id, "failed", "mute_effect_identity_unverified"
                        )
                        continue
                    if result == "replaced_effect":
                        self.db.update_pending_moderation_action(
                            action_id, "cancelled", "mute_effect_replaced"
                        )
                        continue

                elif action_type in {"TIMEOUT_EXPIRE", "UNTIMEOUT"}:
                    if case_id:
                        self.db.update_case_by_id(guild.id, int(case_id), status="expired")
                    self.db.log_action(
                        guild.id, user_id, self.bot.user.id,
                        "TIMEOUT_EXPIRED", "Timeout expirado automáticamente",
                        parent_case_id=int(case_id) if case_id else None,
                        status="expired",
                    )
                else:
                    self.db.update_pending_moderation_action(action_id, "failed", f"unknown_action:{action_type}")
                    continue

                self.db.update_pending_moderation_action(action_id, "done")
            except Exception as exc:
                logger.error("Error procesando pending moderation %s: %s", action_id, exc, exc_info=True)
                try:
                    self._retry_pending_moderation(job, str(exc)[:500])
                except Exception:
                    pass

    def _retry_pending_moderation(self, job: Dict, error: str, max_attempts: int = 5) -> None:
        attempts = int(job.get("attempts") or 0)
        status = "failed" if attempts + 1 >= max_attempts else "pending"
        self.db.update_pending_moderation_action(int(job["id"]), status, error[:500])

    @_check_pending_moderation.before_loop
    async def _before_check_pending_moderation(self):
        await self.bot.wait_until_ready()
        await self._ban_reconciliation_ready.wait()

    # ── Tarea: reintento de logs críticos ─────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _flush_log_outbox(self):
        """Reintenta logs de moderación/automod que no pudieron enviarse."""
        try:
            rows = self.db.get_pending_log_outbox(limit=25)
        except Exception as exc:
            logger.error("Error leyendo log_outbox: %s", exc, exc_info=True)
            return

        for row in rows:
            if not self.db.claim_log_outbox(int(row["id"])):
                continue
            row["status"] = "processing"
            try:
                log_id = int(row["id"])
                attempts = int(row.get("attempts") or 0)
                guild = self.bot.get_guild(int(row["guild_id"]))
                if guild is None:
                    self._mark_log_outbox_retry(row, "guild_not_found")
                    continue

                channel_id = row.get("channel_id")
                if not channel_id:
                    srv_cfg = self.db.get_server_config(guild.id)
                    channel_id = srv_cfg.get("modlog_channel")
                if not channel_id:
                    self.db.mark_log_outbox(log_id, "failed", "modlog_channel_not_configured")
                    continue

                channel = guild.get_channel(int(channel_id))
                if channel is None:
                    try:
                        channel = await guild.fetch_channel(int(channel_id))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                        self._mark_log_outbox_retry(row, f"channel_unavailable:{exc}")
                        continue

                if not isinstance(channel, discord.TextChannel):
                    self.db.mark_log_outbox(log_id, "failed", "target_is_not_text_channel")
                    continue

                try:
                    payload = json.loads(row.get("payload") or "{}")
                except json.JSONDecodeError:
                    self.db.mark_log_outbox(log_id, "failed", "invalid_payload_json")
                    continue

                embed_data = payload.get("embed")
                if not isinstance(embed_data, dict):
                    self.db.mark_log_outbox(log_id, "failed", "missing_embed_payload")
                    continue

                await channel.send(embed=discord.Embed.from_dict(embed_data), allowed_mentions=discord.AllowedMentions.none())
                self.db.mark_log_outbox(log_id, "sent")
                logger.info("log_outbox enviado: id=%s attempts=%s", log_id, attempts)
            except (discord.Forbidden, discord.HTTPException) as exc:
                self._mark_log_outbox_retry(row, str(exc))
            except Exception as exc:
                logger.error("Error procesando log_outbox %s: %s", row.get("id"), exc, exc_info=True)
                self._mark_log_outbox_retry(row, str(exc))

    def _mark_log_outbox_retry(self, row: Dict, error: str, max_attempts: int = 5) -> None:
        """Mantiene pendiente un log hasta max_attempts; luego lo marca failed."""
        try:
            attempts = int(row.get("attempts") or 0)
            status = "failed" if attempts + 1 >= max_attempts else "pending"
            self.db.mark_log_outbox(int(row["id"]), status, error[:500])
        except Exception as exc:
            logger.warning("No se pudo actualizar log_outbox %s: %s", row.get("id"), exc)

    @_flush_log_outbox.before_loop
    async def _before_flush_log_outbox(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────────────────────────────────
    # /ban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="ban",
        description="Banea a un usuario, incluso si ya no está en el servidor",
    )
    @app_commands.describe(
        usuario="Usuario a banear (puede estar fuera del servidor)",
        usuario_id="ID del usuario si no aparece en el selector",
        razon="Razón del ban",
        duracion="Opcional: si se indica, el ban será temporal. Ej: 30m, 2h, 1d",
        eliminar_mensajes="Días de mensajes a eliminar (0-7, por defecto 0)",
        evidencia_url="URL opcional con evidencia",
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        razon: str,
        usuario: Optional[Union[discord.Member, discord.User]] = None,
        usuario_id: Optional[str] = None,
        duracion: Optional[str] = None,
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 0,
        evidencia_url: Optional[str] = None,
        mensaje_url: Optional[str] = None,
        archivo: Optional[discord.Attachment] = None,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        razon = razon.strip()
        if not razon:
            return await interaction.response.send_message(
                "❌ Escribe el motivo en la opción `razon`. No se ha aplicado ninguna sanción.",
                ephemeral=True,
            )

        raw_user_id = usuario_id.strip() if usuario_id else ""
        if usuario is None and not raw_user_id:
            return await interaction.response.send_message(
                "❌ Indica un usuario en el selector o escribe su ID en `usuario_id`.",
                ephemeral=True,
            )
        if usuario is not None and raw_user_id:
            return await interaction.response.send_message(
                "❌ Usa solo una opción: `usuario` o `usuario_id`.",
                ephemeral=True,
            )

        if raw_user_id:
            target_id = _parse_discord_user_id(raw_user_id)
            if target_id is None:
                return await interaction.response.send_message(
                    "❌ Esa ID no se parece a un ID válido de Discord.",
                    ephemeral=True,
                )
        else:
            assert usuario is not None
            target_id = usuario.id

        duration_secs: Optional[int] = None
        expiry: Optional[datetime] = None
        if duracion:
            duration_secs = parse_duration(duracion)
            if duration_secs is None:
                return await interaction.response.send_message(
                    _voice(self).line("error", "Formato inválido. Ejemplos: `30m` · `2h` · `1d` · `1w`"),
                    ephemeral=True,
                )

        await interaction.response.defer()

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send(
                "❌ Este comando solo funciona dentro de un servidor.", ephemeral=True
            )

        member: Optional[discord.Member]
        if isinstance(usuario, discord.Member):
            member = usuario
        else:
            member = guild.get_member(target_id)
            if member is None:
                try:
                    member = await guild.fetch_member(target_id)
                except discord.NotFound:
                    member = None
                except (discord.Forbidden, discord.HTTPException):
                    return await interaction.followup.send(
                        "❌ No puedo verificar si ese usuario sigue en el servidor. Inténtalo de nuevo.",
                        ephemeral=True,
                    )

        if member is not None:
            err = self._can_moderate(interaction.user, member)  # type: ignore[arg-type]
            if err:
                return await interaction.followup.send(
                    _voice(self).line("error", err), ephemeral=True
                )

        resolved_user: Optional[Union[discord.Member, discord.User]] = member or usuario
        if resolved_user is None:
            get_user = getattr(self.bot, "get_user", None)
            cached_user = get_user(target_id) if callable(get_user) else None
            if isinstance(cached_user, discord.User):
                resolved_user = cached_user

        action_type = "TEMPBAN" if duration_secs is not None else "BAN"

        async def apply_ban():
            current_actor, current_member, auth_error = await self._fresh_moderation_context(
                interaction,
                "ban_members",
                target_id=target_id,
                allow_absent_target=True,
            )
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "autorización no verificable")
            evidence = await capture_manual(self.bot, interaction, mensaje_url, archivo, evidencia_url)
            current_actor, current_member, auth_error = await self._fresh_moderation_context(
                interaction, "ban_members", target_id=target_id, allow_absent_target=True,
            )
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "autorización no verificable")
            ban_target = current_member or discord.Object(id=target_id)
            effect_token = new_ban_effect_token()
            current_case_id = self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                action_type,
                razon,
                {**interaction_metadata(interaction, current_member or resolved_user or target_id, current_actor), **{
                    "delete_days": eliminar_mensajes,
                    "duration_secs": duration_secs,
                    "target_input": "id" if raw_user_id else "selector",
                    "ban_effect_token": effect_token,
                }},
                status="applying",
                evidence_url=evidencia_url, evidence=evidence,
                duration_seconds=duration_secs,
            )
            if not current_case_id:
                raise RuntimeError("ban_intent_not_persisted")
            await guild.ban(
                ban_target,
                reason=reason_with_ban_effect(
                    f"{action_type} {fmt_duration(duration_secs) if duration_secs is not None else ''} | {razon} | Mod: {current_actor}",
                    effect_token,
                ),
                delete_message_seconds=eliminar_mensajes * 86400,
            )
            await self._confirm_ban_effect(guild, target_id, effect_token)
            current_expiry = (
                datetime.now(timezone.utc) + timedelta(seconds=duration_secs)
                if duration_secs is not None
                else None
            )
            if not self.db.activate_prepared_ban_case(
                interaction.guild_id,
                target_id,
                current_case_id,
                current_actor.id,
                razon,
                duration_secs,
                current_expiry.isoformat() if current_expiry else None,
            ):
                raise RuntimeError("ban_intent_changed")
            return current_actor, current_member, current_case_id, current_expiry

        try:
            current_actor, current_member, case_id, expiry = await run_sanction_locked(
                self.bot,
                guild.id,
                target_id,
                action_type,
                apply_ban,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except RuntimeError:
            logger.error(
                "Ban de %s aplicado sin identidad confirmada; requiere revisión manual",
                target_id,
            )
            return await interaction.followup.send(
                "⚠️ Discord pudo aplicar el ban, pero no se pudo vincular de forma segura al caso. Revísalo manualmente.",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para banear a %s en %s", target_id, guild)
            return await interaction.followup.send(
                _voice(self).line("error", "Al gato le faltan permisos para banear a este usuario."),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error baneando a %s en %s: %s", target_id, guild, exc)
            return await interaction.followup.send(
                _voice(self).line("error", "El gato perdió la cuerda. No se pudo completar el ban."),
                ephemeral=True,
            )
        if current_member is not None:
            resolved_user = current_member

        if resolved_user is not None and case_id:
            # La apelación solo se ofrece después de persistir la sanción exacta.
            view = AppealUserView(
                self.bot, interaction.guild_id, action_type, razon, case_id
            )
            await self._dm(
                resolved_user,
                discord.Embed(
                    title="Has sido baneado temporalmente" if duration_secs else "Has sido baneado",
                    description=f"Has sido baneado de **{guild.name}**.",
                    color=discord.Color.dark_red(),
                ).add_field(name="Duración", value=fmt_duration(duration_secs))
                 .add_field(name="Razón", value=razon)
                 .add_field(name="Moderador", value=interaction.user.display_name),
                view=view,
            )

        target_label = str(resolved_user) if resolved_user is not None else f"ID {target_id}"
        embed = discord.Embed(
            title="Usuario baneado temporalmente" if duration_secs else "Usuario baneado",
            description=(
                f"**{target_label}** ha sido baneado por **{fmt_duration(duration_secs)}**."
                if duration_secs else f"**{target_label}** ha sido baneado permanentemente."
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        if resolved_user is not None:
            embed.set_thumbnail(url=resolved_user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"<@{target_id}>\n`{target_id}`", inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Msgs eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        if duration_secs and expiry:
            embed.add_field(name="⏱️ Duración", value=fmt_duration(duration_secs), inline=True)
            embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        if evidencia_url:
            embed.add_field(name="Evidencia", value=evidencia_url, inline=False)
        embed.add_field(name="Razón", value=razon, inline=False)

        self._add_evidence_status(embed, interaction.guild_id, case_id)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @ban.error
    async def ban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    @app_commands.command(name="forceban", description="Banea por ID aunque el usuario no esté en el servidor")
    @app_commands.describe(
        user_id="ID del usuario",
        razon="Razón del forceban",
        duracion="Opcional: duración del ban temporal",
        eliminar_mensajes="Días de mensajes a eliminar (0-7)",
    )
    async def forceban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        razon: str = "Sin razón especificada",
        duracion: Optional[str] = None,
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        try:
            uid = int(user_id.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Esa ID no se parece a un ID de Discord.", ephemeral=True)

        target = interaction.guild.get_member(uid)
        if target is None:
            try:
                target = await interaction.guild.fetch_member(uid)
            except discord.NotFound:
                target = None
            except (discord.Forbidden, discord.HTTPException):
                return await interaction.response.send_message(
                    "❌ No puedo verificar la jerarquía actual de ese usuario.",
                    ephemeral=True,
                )
        if target is not None:
            err = self._can_moderate(interaction.user, target)  # type: ignore[arg-type]
            if err:
                return await interaction.response.send_message(
                    _voice(self).line("error", err), ephemeral=True
                )

        secs = parse_duration(duracion) if duracion else None
        if duracion and secs is None:
            return await interaction.response.send_message("❌ Duración inválida. Ejemplos: `30m`, `2h`, `1d`.", ephemeral=True)
        await interaction.response.defer()
        action = "TEMPBAN" if secs is not None else "FORCEBAN"

        async def apply_forceban():
            current_actor, current_target, auth_error = await self._fresh_moderation_context(
                interaction,
                "ban_members",
                target_id=uid,
                allow_absent_target=True,
            )
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "autorización no verificable")
            effect_token = new_ban_effect_token()
            current_case_id = self.db.log_action(
                interaction.guild_id,
                uid,
                current_actor.id,
                action,
                razon,
                {**interaction_metadata(interaction, uid, current_actor), **{
                    "forceban": True,
                    "delete_days": eliminar_mensajes,
                    "duration_secs": secs,
                    "ban_effect_token": effect_token,
                }},
                status="applying",
                duration_seconds=secs,
            )
            if not current_case_id:
                raise RuntimeError("ban_intent_not_persisted")
            await interaction.guild.ban(
                current_target or discord.Object(id=uid),
                reason=reason_with_ban_effect(
                    f"Forceban {fmt_duration(secs) if secs is not None else ''} | {razon} | Mod: {current_actor}",
                    effect_token,
                ),
                delete_message_seconds=eliminar_mensajes * 86400,
            )
            await self._confirm_ban_effect(
                interaction.guild, uid, effect_token
            )
            current_expiry = (
                datetime.now(timezone.utc) + timedelta(seconds=secs)
                if secs is not None
                else None
            )
            if not self.db.activate_prepared_ban_case(
                interaction.guild_id,
                uid,
                current_case_id,
                current_actor.id,
                razon,
                secs,
                current_expiry.isoformat() if current_expiry else None,
            ):
                raise RuntimeError("ban_intent_changed")
            return current_actor, current_case_id, current_expiry

        try:
            current_actor, case_id, expiry = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                uid,
                action,
                apply_forceban,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except RuntimeError:
            logger.error(
                "Forceban de %s aplicado sin identidad confirmada; requiere revisión manual",
                uid,
            )
            return await interaction.followup.send(
                "⚠️ Discord pudo aplicar el ban, pero no se pudo vincular de forma segura al caso. Revísalo manualmente.",
                ephemeral=True,
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo permisos para banear por ID.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ No se pudo completar el forceban: {exc}", ephemeral=True)

        embed = discord.Embed(
            title="Forceban aplicado",
            description=f"ID `{uid}` fue baneada" + (f" por **{fmt_duration(secs)}**." if secs else "."),
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Msgs eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        if expiry:
            embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @app_commands.command(name="softban", description="Banea y desbanea para limpiar mensajes")
    @app_commands.describe(usuario="Usuario", razon="Razón", eliminar_mensajes="Días de mensajes a eliminar (0-7)")
    async def softban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 1,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(_voice(self).line("error", err), ephemeral=True)
        await interaction.response.defer()
        target_id = usuario.id

        async def apply_softban():
            current_actor, current_target, auth_error = await self._fresh_moderation_context(
                interaction, "ban_members", target_id=target_id
            )
            if auth_error or current_actor is None or current_target is None:
                raise PermissionError(auth_error or "autorización no verificable")
            effect_token = new_ban_effect_token()
            current_case_id = self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                "SOFTBAN",
                razon,
                {**interaction_metadata(interaction, target_id, current_actor), **{
                    "delete_days": eliminar_mensajes,
                    "ban_effect_token": effect_token,
                }},
                status="applying",
            )
            if not current_case_id:
                raise RuntimeError("softban_intent_not_persisted")
            await current_target.ban(
                reason=reason_with_ban_effect(
                    f"Softban: {razon} | Mod: {current_actor}",
                    effect_token,
                ),
                delete_message_seconds=eliminar_mensajes * 86400,
            )
            entry = await interaction.guild.fetch_ban(discord.Object(id=target_id))
            if not ban_reason_matches(entry.reason, effect_token):
                raise RuntimeError("softban_replaced_before_cleanup")
            if not self.db.confirm_prepared_softban_effect(
                interaction.guild_id, target_id, current_case_id
            ):
                raise RuntimeError("softban_confirmation_changed")
            await interaction.guild.unban(
                entry.user,
                reason=f"Softban cleanup completado | Mod: {current_actor}",
            )
            if not self.db.complete_prepared_softban_case(
                interaction.guild_id, target_id, current_case_id
            ):
                raise RuntimeError("softban_intent_changed")
            return current_actor, current_target

        try:
            current_actor, usuario = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "SOFTBAN",
                apply_softban,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except RuntimeError:
            return await interaction.followup.send(
                "❌ El ban cambió durante el softban; no se retiró el efecto nuevo.",
                ephemeral=True,
            )
        except discord.NotFound:
            return await interaction.followup.send(
                "❌ Discord no confirmó el ban del softban.", ephemeral=True
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo permisos/jerarquía para softban.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ No se pudo completar el softban: {exc}", ephemeral=True)
        embed = discord.Embed(
            title="Softban aplicado",
            description=f"{usuario.mention} fue baneado y desbaneado para limpiar mensajes.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Mensajes eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /tempban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="tempban", description="Banea temporalmente a un usuario del servidor")
    @app_commands.describe(
        usuario="Usuario a banear temporalmente",
        duracion="Duración: 30m, 2h, 1d, 1w",
        razon="Razón del tempban",
        eliminar_mensajes="Días de mensajes a eliminar (0-7, por defecto 0)",
    )
    async def tempban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: str,
        razon: str = "Sin razón especificada",
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        err = self._can_moderate(interaction.user, usuario)
        if err:
            return await interaction.response.send_message(_voice(self).line("error", err), ephemeral=True)

        secs = parse_duration(duracion)
        if secs is None:
            return await interaction.response.send_message(
                _voice(self).line("error", "Formato inválido. Ejemplos: `30m` · `2h` · `1d` · `1w`"),
                ephemeral=True,
            )

        await interaction.response.defer()

        target_id = usuario.id

        async def apply_tempban():
            current_actor, current_target, auth_error = await self._fresh_moderation_context(
                interaction, "ban_members", target_id=target_id
            )
            if auth_error or current_actor is None or current_target is None:
                raise PermissionError(auth_error or "autorización no verificable")
            effect_token = new_ban_effect_token()
            current_case_id = self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                "TEMPBAN",
                razon,
                {**interaction_metadata(interaction, target_id, current_actor), **{
                    "duration_secs": secs,
                    "delete_days": eliminar_mensajes,
                    "ban_effect_token": effect_token,
                }},
                status="applying",
                duration_seconds=secs,
            )
            if not current_case_id:
                raise RuntimeError("ban_intent_not_persisted")
            await current_target.ban(
                reason=reason_with_ban_effect(
                    f"Tempban {fmt_duration(secs)} | {razon} | Mod: {current_actor}",
                    effect_token,
                ),
                delete_message_seconds=eliminar_mensajes * 86400,
            )
            await self._confirm_ban_effect(
                interaction.guild, target_id, effect_token
            )
            current_expiry = datetime.now(timezone.utc) + timedelta(seconds=secs)
            if not self.db.activate_prepared_ban_case(
                interaction.guild_id,
                target_id,
                current_case_id,
                current_actor.id,
                razon,
                secs,
                current_expiry.isoformat(),
            ):
                raise RuntimeError("ban_intent_changed")
            return current_actor, current_target, current_case_id, current_expiry

        try:
            current_actor, usuario, case_id, expiry = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "TEMPBAN",
                apply_tempban,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except RuntimeError:
            logger.error(
                "Tempban de %s aplicado sin identidad confirmada; requiere revisión manual",
                target_id,
            )
            return await interaction.followup.send(
                "⚠️ Discord pudo aplicar el ban, pero no se pudo vincular de forma segura al caso. Revísalo manualmente.",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para tempbanear a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                _voice(self).line("error", "Al gato le faltan permisos para banear a este usuario."),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error tempbaneando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                _voice(self).line("error", "El gato perdió la cuerda. No se pudo completar el tempban."),
                ephemeral=True,
            )

        if case_id:
            view = AppealUserView(
                self.bot, interaction.guild_id, "TEMPBAN", razon, case_id
            )
            await self._dm(
                usuario,
                discord.Embed(
                    title="Has sido baneado temporalmente",
                    description=f"Has sido baneado temporalmente de **{interaction.guild.name}**.",
                    color=discord.Color.dark_red(),
                ).add_field(name="Duración", value=fmt_duration(secs))
                 .add_field(name="Razón", value=razon)
                 .add_field(name="Moderador", value=interaction.user.display_name),
                view=view,
            )

        embed = discord.Embed(
            title="Usuario baneado temporalmente",
            description=f"**{usuario}** ha sido baneado por **{fmt_duration(secs)}**.",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏱️ Duración", value=fmt_duration(secs), inline=True)
        embed.add_field(name="Msgs eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @tempban.error
    async def tempban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /unban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Desbanea un usuario usando su ID")
    @app_commands.describe(
        user_id="ID numérica del usuario a desbanear",
        razon="Razón del desbaneo",
    )
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        await interaction.response.defer()

        try:
            uid = int(user_id.strip())
        except ValueError:
            return await interaction.followup.send(_voice(self).line("error", "Esa ID no se parece a un ID de Discord."), ephemeral=True)

        async def apply_unban():
            auth_context, entry = await asyncio.gather(
                self._fresh_moderation_context(interaction, "ban_members"),
                interaction.guild.fetch_ban(discord.Object(id=uid)),
            )
            current_actor, _, auth_error = auth_context
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "autorización no verificable")
            await interaction.guild.unban(
                entry.user, reason=f"{razon} | Mod: {current_actor}"
            )
            self.db.clear_tempbans_for_user(uid, interaction.guild_id)
            self.db.cancel_pending_moderation_actions(
                interaction.guild_id,
                uid,
                ["TEMPBAN_EXPIRE", "UNBAN"],
                reason="manual_unban",
            )
            self.db.revoke_active_moderations(
                interaction.guild_id,
                uid,
                ["BAN", "TEMPBAN", "FORCEBAN", "AUTO_BAN"],
            )
            self.db.log_action(
                interaction.guild_id,
                uid,
                current_actor.id,
                "UNBAN",
                razon, extra=interaction_metadata(interaction, entry.user, current_actor),
                status="revoked",
            )
            return current_actor, entry

        try:
            current_actor, entry = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                uid,
                "UNBAN",
                apply_unban,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except discord.NotFound:
            return await interaction.followup.send(
                f"❌ No existe un ban activo con ID `{uid}`.", ephemeral=True
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para desbanear ID %s en %s", uid, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para desbanear a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error desbaneando a %s en %s: %s", entry.user, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar el desbaneo. Inténtalo de nuevo.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="✅ Usuario desbaneado",
            description=f"**{entry.user}** fue desbaneado.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=entry.user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{entry.user.mention}\n`{uid}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @unban.error
    async def unban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /kick
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Expulsa a un usuario del servidor")
    @app_commands.describe(usuario="Usuario a expulsar", razon="Razón de la expulsión")
    async def kick(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str,
        mensaje_url: Optional[str] = None,
        archivo: Optional[discord.Attachment] = None,
        evidencia_url: Optional[str] = None,
    ):
        if not self._has_mod_perms(interaction, "kick_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        razon = razon.strip()
        if not razon:
            return await interaction.response.send_message(
                "❌ Escribe el motivo en la opción `razon`. No se ha aplicado ninguna sanción.",
                ephemeral=True,
            )

        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(_voice(self).line("error", err), ephemeral=True)

        await interaction.response.defer()

        current_actor, current_target, auth_error = await self._fresh_moderation_context(
            interaction, "kick_members", target_id=usuario.id
        )
        if auth_error:
            return await interaction.followup.send(
                _voice(self).line("error", auth_error), ephemeral=True
            )
        evidence = await capture_manual(self.bot, interaction, mensaje_url, archivo, evidencia_url)
        current_actor, current_target, auth_error = await self._fresh_moderation_context(
            interaction, "kick_members", target_id=usuario.id,
        )
        if auth_error or current_target is None:
            return await interaction.followup.send(auth_error or "No pude verificar la operación.", ephemeral=True)
        usuario = current_target
        try:
            await usuario.kick(reason=f"{razon} | Mod: {current_actor}")
        except discord.Forbidden:
            logger.warning("Sin permisos para expulsar a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para expulsar a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error expulsando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar la expulsión. Inténtalo de nuevo.",
                ephemeral=True,
            )

        case_id = self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id, "KICK", razon, extra=interaction_metadata(interaction, usuario, interaction.user),
            evidence_url=evidencia_url, evidence=evidence,
        )

        if case_id:
            view = AppealUserView(
                self.bot, interaction.guild_id, "KICK", razon, case_id
            )
            await self._dm(
                usuario,
                discord.Embed(
                    title="Has sido expulsado",
                    description=f"Has sido expulsado de **{interaction.guild.name}**.",
                    color=discord.Color.orange(),
                ).add_field(name="Razón", value=razon)
                 .add_field(name="Moderador", value=interaction.user.display_name),
                view=view,
            )

        embed = discord.Embed(
            title="Usuario expulsado",
            description=f"**{usuario}** fue expulsado del servidor.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        self._add_evidence_status(embed, interaction.guild_id, case_id)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @kick.error
    async def kick_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /mute
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Silencia a un usuario con el rol de mute configurado")
    @app_commands.describe(
        usuario="Usuario a silenciar",
        duracion="Duración: 30m, 2h, 1d, 1w — omitir para permanente",
        razon="Razón del mute",
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: Optional[str] = None,
        razon: str = "Sin razón especificada",
        mensaje_url: Optional[str] = None,
        archivo: Optional[discord.Attachment] = None,
        evidencia_url: Optional[str] = None,
    ):
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("❌ Este comando solo funciona en servidores.", ephemeral=True)

        if not self._has_mod_perms(interaction, "manage_roles"):
            return await interaction.followup.send(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        _, preflight_target, preflight_error = await self._fresh_moderation_context(
            interaction, "manage_roles", target_id=usuario.id
        )
        if preflight_error or preflight_target is None:
            return await interaction.followup.send(
                _voice(self).line(
                    "error", preflight_error or "No pude verificar la operación."
                ),
                ephemeral=True,
            )
        usuario = preflight_target
        secs: Optional[int] = None
        if duracion:
            secs = parse_duration(duracion)
            if secs is None:
                return await interaction.followup.send(
                    _voice(self).line("error", "Formato inválido. Ejemplos: `30m` · `2h` · `1d` · `1w`"),
                    ephemeral=True,
                )
        mute_role = await self._ensure_mute_role(guild)

        if not mute_role:
            return await interaction.followup.send(
                "❌ No hay rol de mute configurado.\n"
                "Usa `/modconfig mute_role` o el dashboard para asignarlo.",
                ephemeral=True,
            )

        if mute_role in usuario.roles:
            return await interaction.followup.send(
                f"⚠️ {usuario.mention} ya está silenciado.", ephemeral=True
            )

        target_id = usuario.id
        mute_role_id = mute_role.id

        async def apply_mute():
            current_actor, current_target, current_role, auth_error = (
                await self._fresh_mute_role_context(
                    interaction,
                    target_id,
                    mute_role_id,
                    for_assignment=True,
                )
            )
            if (
                auth_error
                or current_actor is None
                or current_target is None
                or current_role is None
            ):
                raise PermissionError(auth_error or "No pude verificar la operación.")
            if mute_role_id in {
                int(value) for value in getattr(current_target, "_roles", ())
            }:
                raise LookupError("already_muted")
            evidence = await capture_manual(self.bot, interaction, mensaje_url, archivo, evidencia_url)
            current_actor, confirmed_member, current_expiry, current_case_id = await self._apply_role_mute(
                interaction, target_id, mute_role_id, "MUTE", razon, secs, evidence=evidence, evidence_url=evidencia_url
            )
            return current_actor, confirmed_member, current_role, current_expiry, current_case_id

        try:
            current_actor, usuario, mute_role, expiry, case_id = await run_sanction_locked(
                self.bot,
                guild.id,
                target_id,
                "MUTE",
                apply_mute,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except ValueError:
            return await interaction.followup.send(
                "❌ El rol de mute dejó de ser seguro y la operación fue cancelada.",
                ephemeral=True,
            )
        except LookupError:
            return await interaction.followup.send(
                f"⚠️ <@{target_id}> ya está silenciado.", ephemeral=True
            )
        except RuntimeError as exc:
            return await interaction.followup.send(
                "⚠️ El mute no se pudo completar y sus cambios se revirtieron." if str(exc) == "mute_rolled_back" else
                "⚠️ No se pudo confirmar y activar el mute de forma segura; quedó pendiente de reconciliación.",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para mutear a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para aplicar el rol de mute.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error muteando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar el mute. Inténtalo de nuevo.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Usuario silenciado",
            description=f"{usuario.mention} ha sido silenciado.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="⏱️ Duración", value=fmt_duration(secs), inline=True)
        if expiry:
            embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        self._add_evidence_status(embed, interaction.guild_id, case_id)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

        if case_id:
            view = AppealUserView(
                self.bot, interaction.guild_id, "MUTE", razon, case_id
            )
            await self._dm(
                usuario,
                discord.Embed(
                    title="Has sido silenciado",
                    description=f"Has sido silenciado en **{interaction.guild.name}**.",
                    color=discord.Color.red(),
                ).add_field(name="Duración", value=fmt_duration(secs))
                 .add_field(name="Razón", value=razon),
                view=view,
            )

    @mute.error
    async def mute_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    @app_commands.command(name="hardmute", description="Silencia creando/adoptando rol Muted y persistiendo expiración")
    @app_commands.describe(
        usuario="Usuario a silenciar",
        duracion="Duración: 30m, 2h, 1d, 1w — omitir para permanente",
        razon="Razón del hardmute",
    )
    async def hardmute(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: Optional[str] = None,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "manage_roles"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(_voice(self).line("error", err), ephemeral=True)
        secs = parse_duration(duracion) if duracion else None
        if duracion and secs is None:
            return await interaction.response.send_message("❌ Duración inválida. Ejemplos: `30m`, `2h`, `1d`.", ephemeral=True)

        await interaction.response.defer()
        _, preflight_target, preflight_error = await self._fresh_moderation_context(
            interaction, "manage_roles", target_id=usuario.id
        )
        if preflight_error or preflight_target is None:
            return await interaction.followup.send(
                _voice(self).line(
                    "error", preflight_error or "No pude verificar la operación."
                ),
                ephemeral=True,
            )
        usuario = preflight_target
        mute_role = await self._ensure_mute_role(interaction.guild)
        if not mute_role:
            return await interaction.followup.send("❌ No pude crear/adoptar el rol Muted. Revisa `Gestionar roles` y jerarquía.", ephemeral=True)
        if mute_role in usuario.roles:
            return await interaction.followup.send(f"⚠️ {usuario.mention} ya está silenciado.", ephemeral=True)
        target_id = usuario.id
        mute_role_id = mute_role.id

        async def apply_hardmute():
            current_actor, current_target, current_role, auth_error = (
                await self._fresh_mute_role_context(
                    interaction,
                    target_id,
                    mute_role_id,
                    for_assignment=True,
                )
            )
            if (
                auth_error
                or current_actor is None
                or current_target is None
                or current_role is None
            ):
                raise PermissionError(auth_error or "No pude verificar la operación.")
            if mute_role_id in {
                int(value) for value in getattr(current_target, "_roles", ())
            }:
                raise LookupError("already_muted")
            return await self._apply_role_mute(
                interaction, target_id, mute_role_id, "HARDMUTE", razon, secs,
                job_action="HARDMUTE_EXPIRE",
            )

        try:
            current_actor, usuario, expiry, case_id = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "HARDMUTE",
                apply_hardmute,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except ValueError:
            return await interaction.followup.send(
                "❌ El rol de mute dejó de ser seguro y la operación fue cancelada.",
                ephemeral=True,
            )
        except LookupError:
            return await interaction.followup.send(
                f"⚠️ <@{target_id}> ya está silenciado.", ephemeral=True
            )
        except RuntimeError as exc:
            return await interaction.followup.send(
                "⚠️ El hardmute no se pudo completar y sus cambios se revirtieron." if str(exc) == "mute_rolled_back" else
                "⚠️ No se pudo confirmar y activar el hardmute de forma segura; quedó pendiente de reconciliación.",
                ephemeral=True,
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo permisos/jerarquía para aplicar hardmute.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ No se pudo aplicar hardmute: {exc}", ephemeral=True)

        embed = discord.Embed(
            title="Hardmute aplicado",
            description=f"{usuario.mention} fue silenciado con rol Muted.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Duración", value=fmt_duration(secs), inline=True)
        if expiry:
            embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /unmute
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Quita el silencio a un usuario")
    @app_commands.describe(usuario="Usuario a desilenciar", razon="Razón del unmute")
    async def unmute(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "manage_roles"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        err = self._can_moderate(interaction.user, usuario)  # type: ignore[arg-type]
        if err:
            return await interaction.response.send_message(
                _voice(self).line("error", err), ephemeral=True
            )
        guild = interaction.guild
        target_id = usuario.id

        async def apply_unmute():
            mute_role_id = self._active_mute_role_id(
                interaction.guild_id, target_id
            )
            if not mute_role_id:
                raise LookupError("missing_mute_role")
            current_actor, current_target, mute_role, auth_error = (
                await self._fresh_mute_role_context(
                    interaction,
                    target_id,
                    mute_role_id,
                    allow_absent_effect=True,
                )
            )
            if (
                auth_error
                or current_actor is None
                or current_target is None
            ):
                raise PermissionError(auth_error or "No pude verificar la operación.")
            active_case = self._active_mute_case(interaction.guild_id, target_id)
            if mute_role is not None:
                await current_target.remove_roles(
                    mute_role, reason=f"Unmute: {razon} | Mod: {current_actor}"
                )
            elif active_case is None:
                raise LookupError("not_muted")
            await self._restore_mute_roles(
                guild, target_id, active_case, actor_id=current_actor.id
            )
            self.db.clear_mute(target_id, interaction.guild_id)
            self.db.cancel_pending_moderation_actions(
                interaction.guild_id,
                target_id,
                ["MUTE_EXPIRE", "HARDMUTE_EXPIRE", "UNMUTE"],
                reason="manual_unmute",
            )
            self.db.revoke_active_moderations(
                interaction.guild_id,
                target_id,
                ["MUTE", "AUTO_MUTE", "HARDMUTE"],
            )
            self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                "UNMUTE",
                razon, extra=interaction_metadata(interaction, target_id, current_actor),
                status="revoked",
            )
            return current_actor, current_target, mute_role

        try:
            current_actor, usuario, mute_role = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "UNMUTE",
                apply_unmute,
            )
        except PermissionError as exc:
            return await interaction.response.send_message(
                _voice(self).line("error", str(exc)),
                ephemeral=True,
            )
        except LookupError:
            return await interaction.response.send_message(
                f"⚠️ <@{target_id}> no está silenciado.",
                ephemeral=True,
            )
        except ValueError:
            return await interaction.response.send_message(
                "❌ El rol histórico de mute ya no está debajo de mi rol.",
                ephemeral=True,
            )
        except RuntimeError:
            return await interaction.response.send_message(
                "⚠️ La restauración de roles sigue pendiente; el caso permanece abierto para reintentarlo.",
                ephemeral=True,
            )
        except discord.NotFound:
            return await interaction.response.send_message(
                "❌ No pude verificar el usuario o el rol actual.", ephemeral=True
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para quitar mute a %s en %s", usuario, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos suficientes para quitar el rol de mute.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error quitando mute a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo completar el unmute. Inténtalo de nuevo.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Usuario desilenciado",
            description=f"{usuario.mention} fue desilenciado.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=usuario.mention, inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

        await self._dm(
            usuario,
            discord.Embed(
                title="Fuiste desilenciado",
                description=f"Tu silencio en **{interaction.guild.name}** fue levantado.",
                color=discord.Color.green(),
            ).add_field(name="Razón", value=razon),
        )

    @unmute.error
    async def unmute_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /timeout y /untimeout
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="timeout", description="Aplica timeout nativo de Discord a un usuario")
    @app_commands.describe(
        usuario="Usuario a timeoutear",
        duracion="Duración: 30m, 2h, 1d. Máximo 28d por Discord",
        razon="Razón del timeout",
        evidencia_url="URL opcional con evidencia",
    )
    async def timeout_cmd(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: str,
        razon: str = "Sin razón especificada",
        evidencia_url: Optional[str] = None,
    ):
        if not await self._safe_defer(interaction):
            return
        if not self._has_mod_perms(interaction, "moderate_members"):
            await self._safe_interaction_send(
                interaction,
                _voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."),
                ephemeral=True,
            )
            return
        err = self._can_moderate(interaction.user, usuario, action_type="TIMEOUT")  # type: ignore
        if err:
            await self._safe_interaction_send(interaction, _voice(self).line("error", err), ephemeral=True)
            return

        secs = parse_duration(duracion)
        max_timeout = 28 * 86400
        if secs is None or secs <= 0:
            await self._safe_interaction_send(interaction, "❌ Duración inválida. Ejemplos: `30m`, `2h`, `1d`.", ephemeral=True)
            return
        if secs > max_timeout:
            await self._safe_interaction_send(
                interaction,
                "❌ Discord solo permite timeouts de hasta 28 días. Usa `/mute` para duraciones más largas.",
                ephemeral=True,
            )
            return

        until = datetime.now(timezone.utc) + timedelta(seconds=secs)
        current_actor, current_target, auth_error = await self._fresh_moderation_context(
            interaction, "moderate_members", target_id=usuario.id, action_type="TIMEOUT"
        )
        if auth_error:
            await self._safe_interaction_send(
                interaction, _voice(self).line("error", auth_error), ephemeral=True
            )
            return
        usuario = current_target
        try:
            await usuario.timeout(until, reason=f"Timeout: {razon} | Mod: {current_actor}")
        except discord.Forbidden:
            await self._safe_interaction_send(interaction, "❌ No tengo permisos/jerarquía para aplicar timeout.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await self._safe_interaction_send(interaction, f"❌ No se pudo aplicar timeout: {exc}", ephemeral=True)
            return

        case_id = self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id,
            "TIMEOUT", razon, {**interaction_metadata(interaction, usuario, interaction.user), **{"duration_secs": secs}},
            evidence_url=evidencia_url,
            duration_seconds=secs,
            expires_at=until.isoformat(),
        )
        self.db.add_pending_moderation_action(
            interaction.guild_id, usuario.id, "TIMEOUT_EXPIRE", until.isoformat(), case_id=case_id,
        )

        embed = discord.Embed(
            title="Timeout aplicado",
            description=f"{usuario.mention} fue aislado por **{fmt_duration(secs)}**.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Expira", value=f"<t:{int(until.timestamp())}:R>", inline=True)
        if evidencia_url:
            embed.add_field(name="Evidencia", value=evidencia_url, inline=False)
        embed.add_field(name="Razón", value=razon, inline=False)
        await self._safe_interaction_send(interaction, embed=embed)
        await self._send_log(interaction.guild, embed)

    @timeout_cmd.error
    async def timeout_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    @app_commands.command(name="untimeout", description="Quita el timeout nativo de Discord a un usuario")
    @app_commands.describe(usuario="Usuario", razon="Razón")
    async def untimeout(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not await self._safe_defer(interaction):
            return
        if not self._has_mod_perms(interaction, "moderate_members"):
            await self._safe_interaction_send(
                interaction,
                _voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."),
                ephemeral=True,
            )
            return
        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            await self._safe_interaction_send(interaction, _voice(self).line("error", err), ephemeral=True)
            return
        current_actor, current_target, auth_error = await self._fresh_moderation_context(
            interaction, "moderate_members", target_id=usuario.id
        )
        if auth_error:
            await self._safe_interaction_send(
                interaction, _voice(self).line("error", auth_error), ephemeral=True
            )
            return
        usuario = current_target
        try:
            await usuario.timeout(None, reason=f"Untimeout: {razon} | Mod: {current_actor}")
        except discord.Forbidden:
            await self._safe_interaction_send(interaction, "❌ No tengo permisos/jerarquía para quitar timeout.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await self._safe_interaction_send(interaction, f"❌ No se pudo quitar timeout: {exc}", ephemeral=True)
            return

        self.db.cancel_pending_moderation_actions(
            interaction.guild_id,
            usuario.id,
            ["TIMEOUT_EXPIRE", "UNTIMEOUT"],
            reason="manual_untimeout",
        )
        self.db.revoke_active_moderations(
            interaction.guild_id,
            usuario.id,
            ["TIMEOUT"],
        )
        self.db.log_action(interaction.guild_id, usuario.id, interaction.user.id, "UNTIMEOUT", razon, extra=interaction_metadata(interaction, usuario, interaction.user), status="revoked")
        embed = discord.Embed(
            title="Timeout retirado",
            description=f"{usuario.mention} ya no está en timeout.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=usuario.mention, inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        await self._safe_interaction_send(interaction, embed=embed)
        await self._send_log(interaction.guild, embed)

    @untimeout.error
    async def untimeout_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /warn
    # ─────────────────────────────────────────────────────────────────────────

    def _add_evidence_status(self, embed, guild_id, case_id):
        summary = self.db.case_evidence_summary(guild_id, case_id)
        note = f"{summary['evidence_count']} archivos conservados en el registro privado."
        if summary["evidence_errors"]:
            note += " Captura incompleta; el motivo figura en el registro."
        embed.add_field(name="Evidencia", value=note, inline=False)

    async def apply_warn_consequence(
        self, interaction, usuario, warn_case_id, *, policy_check=None, metadata=None,
    ) -> tuple[Optional[discord.Embed], Optional[str]]:
        """Apply dashboard warn thresholds for both manual and AutoMod warnings."""
        target_id = usuario.id
        consequence_metadata = {
            **(metadata if metadata is not None else
               interaction_metadata(interaction, usuario, self.bot.user)),
            "trigger": "warn_threshold",
        }

        async def check_policy():
            if policy_check is not None and not await policy_check():
                raise LookupError("warn_policy_changed")

        # ── Consecuencias automáticas (de mayor a menor severidad) ────────────

        consequence_action, warns, consequence_duration = (
            self._current_warn_consequence(interaction.guild_id, target_id)
        )

        consequence_embed: Optional[discord.Embed] = None
        consequence_warning: Optional[str] = None

        # Ban automático
        if consequence_action == "BAN":
            async def apply_warn_ban():
                _, ban_target, ban_auth_error = await self._fresh_moderation_context(
                    interaction,
                    "ban_members",
                    target_id=usuario.id,
                    action_type="AUTO_BAN",
                    require_bot_permission=True,
                )
                if ban_auth_error or ban_target is None:
                    raise PermissionError(
                        ban_auth_error or "no pude verificar el usuario objetivo."
                    )
                await check_policy()
                live_action, live_warns, _ = self._current_warn_consequence(
                    interaction.guild_id, ban_target.id
                )
                if live_action != "BAN":
                    raise LookupError("warn_policy_changed")
                effect_token = new_ban_effect_token()
                current_case_id = self.db.log_action(
                    interaction.guild_id,
                    ban_target.id,
                    self.bot.user.id,
                    "AUTO_BAN",
                    f"Alcanzó {live_warns} warns",
                    {**consequence_metadata, **{
                        "ban_effect_token": effect_token,
                    }},
                    status="applying",
                    parent_case_id=warn_case_id,
                )
                if not current_case_id:
                    raise RuntimeError("ban_intent_not_persisted")
                try:
                    await ban_target.ban(
                        reason=reason_with_ban_effect(
                            f"Auto-ban: alcanzó {live_warns} warns",
                            effect_token,
                        )
                    )
                except discord.Forbidden:
                    self.db.update_case_by_id(interaction.guild_id, current_case_id, status="failed")
                    raise
                await self._confirm_ban_effect(
                    interaction.guild, ban_target.id, effect_token
                )
                if not self.db.activate_prepared_ban_case(
                    interaction.guild_id,
                    ban_target.id,
                    current_case_id,
                    self.bot.user.id,
                    f"Alcanzó {live_warns} warns",
                    None,
                    None,
                ):
                    raise RuntimeError("ban_intent_changed")
                return ban_target, live_warns

            try:
                usuario, warns = await run_sanctions_locked(
                    self.bot,
                    interaction.guild_id,
                    usuario.id,
                    ("WARN", "AUTO_BAN"),
                    apply_warn_ban,
                )
                consequence_embed = discord.Embed(
                    title="Ban automático",
                    description=f"{usuario.mention} fue baneado por alcanzar **{warns} warns**.",
                    color=discord.Color.dark_red(),
                    timestamp=datetime.now(timezone.utc),
                )
            except PermissionError as exc:
                consequence_warning = (
                    "⚠️ Auto-ban cancelado: "
                    f"{exc}"
                )
            except LookupError:
                consequence_warning = (
                    "ℹ️ Auto-ban cancelado: la política o el umbral de warns cambió."
                )
            except RuntimeError:
                logger.error(
                    "Auto-ban por warns aplicado sin identidad confirmada para %s",
                    usuario.id,
                )
                consequence_warning = (
                    "⚠️ Discord pudo aplicar el auto-ban, pero requiere revisión manual."
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-ban de %s", usuario)
                consequence_warning = (
                    "⚠️ Auto-ban falló: el bot no tiene permiso `Banear miembros`"
                    " o su rol está debajo del usuario."
                )
            except discord.HTTPException:
                consequence_warning = "⚠️ Auto-ban sin confirmar: no se pudo completar la operación con Discord."

        # Kick automático (solo si no se baneó)
        elif consequence_action == "KICK":
            async def apply_warn_kick():
                _, kick_target, kick_auth_error = await self._fresh_moderation_context(
                    interaction,
                    "kick_members",
                    target_id=usuario.id,
                    action_type="AUTO_KICK",
                    require_bot_permission=True,
                )
                if kick_auth_error or kick_target is None:
                    raise PermissionError(
                        kick_auth_error or "no pude verificar el usuario objetivo."
                    )
                await check_policy()
                live_action, live_warns, _ = self._current_warn_consequence(
                    interaction.guild_id, kick_target.id
                )
                if live_action != "KICK":
                    raise LookupError("warn_policy_changed")
                await kick_target.kick(
                    reason=f"Auto-kick: alcanzó {live_warns} warns"
                )
                self.db.log_action(
                    interaction.guild_id,
                    kick_target.id,
                    self.bot.user.id,
                    "AUTO_KICK",
                    f"Alcanzó {live_warns} warns", extra=consequence_metadata,
                    parent_case_id=warn_case_id,
                )
                return kick_target, live_warns

            try:
                usuario, warns = await run_sanctions_locked(
                    self.bot,
                    interaction.guild_id,
                    usuario.id,
                    ("WARN", "AUTO_KICK"),
                    apply_warn_kick,
                )
                consequence_embed = discord.Embed(
                    title="Kick automático",
                    description=f"{usuario.mention} fue expulsado por alcanzar **{warns} warns**.",
                    color=discord.Color.dark_orange(),
                    timestamp=datetime.now(timezone.utc),
                )
            except PermissionError as exc:
                consequence_warning = f"⚠️ Auto-kick cancelado: {exc}"
            except LookupError:
                consequence_warning = (
                    "ℹ️ Auto-kick cancelado: la política o el umbral de warns cambió."
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-kick de %s", usuario)
                consequence_warning = (
                    "⚠️ Auto-kick falló: el bot no tiene permiso `Expulsar miembros`"
                    " o su rol está debajo del usuario."
                )
            except discord.HTTPException:
                consequence_warning = "⚠️ Auto-kick sin confirmar: no se pudo completar la operación con Discord."

        # Mute automático (solo si no se baneó ni kickeó)
        elif consequence_action == "MUTE":
            async def apply_warn_mute():
                live_action, _, _ = self._current_warn_consequence(
                    interaction.guild_id, target_id
                )
                if live_action != "MUTE":
                    raise LookupError("warn_policy_changed")
                try:
                    mute_role_id = int(
                        (self.db.get_config(interaction.guild_id) or {}).get(
                            "mute_role_id"
                        )
                        or 0
                    )
                except (TypeError, ValueError):
                    mute_role_id = 0
                if not mute_role_id:
                    raise ValueError("missing_mute_role")

                _, current_target, current_role, current_error = (
                    await self._fresh_mute_role_context(
                        interaction,
                        target_id,
                        mute_role_id,
                        for_assignment=True,
                    )
                )
                if (
                    current_error
                    or current_target is None
                    or current_role is None
                ):
                    raise PermissionError(
                        current_error or "no pude verificar el usuario objetivo."
                    )
                if mute_role_id in {
                    int(value) for value in getattr(current_target, "_roles", ())
                }:
                    raise LookupError("already_muted")
                await check_policy()
                live_action, live_warns, live_duration = (
                    self._current_warn_consequence(
                        interaction.guild_id, current_target.id
                    )
                )
                if live_action != "MUTE" or live_duration is None:
                    raise LookupError("warn_policy_changed")
                _, confirmed_member, _, _ = await self._apply_role_mute(
                    interaction, target_id, mute_role_id, "AUTO_MUTE",
                    f"Alcanzó {live_warns} warns", live_duration,
                    moderator_id=self.bot.user.id, parent_case_id=warn_case_id,
                    metadata=consequence_metadata,
                )
                return confirmed_member, live_warns, live_duration

            try:
                usuario, warns, consequence_duration = await run_sanctions_locked(
                    self.bot,
                    interaction.guild_id,
                    target_id,
                    ("WARN", "AUTO_MUTE"),
                    apply_warn_mute,
                )
                consequence_embed = discord.Embed(
                    title="Mute automático",
                    description=(
                        f"{usuario.mention} fue silenciado por alcanzar **{warns} warns**.\n"
                        f"Duración: **{fmt_duration(consequence_duration)}**"
                    ),
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc),
                )
            except PermissionError as exc:
                consequence_warning = f"⚠️ Auto-mute cancelado: {exc}"
            except ValueError:
                consequence_warning = (
                    "⚠️ Auto-mute cancelado: configura primero un rol de mute seguro."
                )
            except LookupError as exc:
                if str(exc) == "warn_policy_changed":
                    consequence_warning = (
                        "ℹ️ Auto-mute cancelado: la política, el umbral o la duración cambió."
                    )
                else:
                    consequence_warning = (
                        f"ℹ️ <@{target_id}> ya tenía un mute activo o pendiente; no se re-aplicó."
                    )
            except RuntimeError:
                consequence_warning = (
                    "⚠️ Auto-mute pendiente de reconciliación segura."
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-mute de %s", usuario)
                consequence_warning = (
                    "⚠️ Auto-mute falló: el rol del bot está debajo del rol de mute"
                    " o falta permiso `Gestionar roles`."
                )
            except discord.HTTPException:
                consequence_warning = "⚠️ Auto-mute sin confirmar: no se pudo completar la operación con Discord."

        return consequence_embed, consequence_warning

    @app_commands.command(name="warn", description="Advierte a un usuario (con consecuencias configurables)")
    @app_commands.describe(
        usuario="Usuario a advertir",
        razon="Razón de la advertencia",
        evidencia_url="URL opcional con evidencia",
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str,
        evidencia_url: Optional[str] = None,
        mensaje_url: Optional[str] = None,
        archivo: Optional[discord.Attachment] = None,
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        razon = razon.strip()
        if not razon:
            return await interaction.response.send_message(
                "❌ Escribe el motivo en la opción `razon`. No se ha aplicado ninguna sanción.",
                ephemeral=True,
            )
        err = self._can_moderate(interaction.user, usuario, action_type="WARN")  # type: ignore
        if err:
            return await interaction.response.send_message(_voice(self).line("error", err), ephemeral=True)

        await interaction.response.defer()

        target_id = usuario.id

        async def apply_warn_record():
            current_actor, current_target, auth_error = await self._fresh_moderation_context(
                interaction,
                "moderate_members",
                target_id=target_id,
                action_type="WARN",
            )
            if auth_error or current_actor is None or current_target is None:
                raise PermissionError(auth_error or "No pude verificar la operación.")
            evidence = await capture_manual(self.bot, interaction, mensaje_url, archivo, evidencia_url)
            current_actor, current_target, auth_error = await self._fresh_moderation_context(
                interaction, "moderate_members", target_id=target_id, action_type="WARN",
            )
            if auth_error or current_actor is None or current_target is None:
                raise PermissionError(auth_error or "No pude verificar la operación.")
            current_warns, current_case_id = self.db.add_warn_with_action(
                target_id,
                interaction.guild_id,
                current_actor.id,
                "WARN",
                razon, extra=interaction_metadata(interaction, target_id, current_actor),
                evidence_url=evidencia_url, evidence=evidence,
            )
            return current_actor, current_target, current_warns, current_case_id

        try:
            current_actor, usuario, warns, warn_case_id = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "WARN",
                apply_warn_record,
            )
        except PermissionError as exc:
            return await interaction.followup.send(
                _voice(self).line("error", str(exc)),
                ephemeral=True,
            )

        cfg = self.db.get_config(interaction.guild_id)

        # Embed de warn (configurable)
        warn_embed = build_warn_embed(cfg, usuario, current_actor, razon, warns)
        if evidencia_url:
            warn_embed.add_field(name="Evidencia", value=evidencia_url, inline=False)
        self._add_evidence_status(warn_embed, interaction.guild_id, warn_case_id)
        await interaction.followup.send(embed=warn_embed)
        log_ok = await self._send_log(interaction.guild, warn_embed)
        if not log_ok:
            await self._notify_modlog_issue(interaction)

        if warn_case_id:
            view = AppealUserView(
                self.bot, interaction.guild_id, "WARN", razon, warn_case_id
            )
            await self._dm(usuario, warn_embed, view=view)

        consequence_embed, consequence_warning = await self.apply_warn_consequence(
            interaction, usuario, warn_case_id
        )

        if consequence_embed:
            await interaction.followup.send(embed=consequence_embed)
            log_ok = await self._send_log(interaction.guild, consequence_embed)
            if not log_ok:
                await self._notify_modlog_issue(interaction)

        if consequence_warning:
            try:
                await interaction.followup.send(consequence_warning, ephemeral=True)
            except discord.HTTPException:
                pass

    @warn.error
    async def warn_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /warns
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="warns", description="Consulta los warns de un usuario")
    @app_commands.describe(usuario="Usuario a consultar (por defecto tú mismo)")
    async def warns_cmd(
        self,
        interaction: discord.Interaction,
        usuario: Optional[discord.Member] = None,
    ):
        target = usuario or interaction.user
        record = self.db.get_user(target.id, interaction.guild_id)  # type: ignore
        cfg = self.db.get_config(interaction.guild_id)

        w = record["warns"]
        thresholds = {
            "Mute": (cfg.get("warn_mute_threshold", 3), bool(cfg.get("warn_mute_enabled", 1))),
            "Kick": (cfg.get("warn_kick_threshold", 5), bool(cfg.get("warn_kick_enabled", 0))),
            "Ban":  (cfg.get("warn_ban_threshold", 7),  bool(cfg.get("warn_ban_enabled", 0))),
        }
        max_t = max(v[0] for v in thresholds.values())
        ratio = w / max_t if max_t else 0
        color = (
            discord.Color.green() if ratio == 0
            else discord.Color.yellow() if ratio < 0.5
            else discord.Color.orange() if ratio < 0.8
            else discord.Color.red()
        )

        embed = discord.Embed(
            title=f"Warns de {target.display_name}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="⚠️ Warns actuales", value=f"**{w}**", inline=True)

        next_enabled_thresholds = [t for t, en in thresholds.values() if en and t > w]
        next_threshold = min(next_enabled_thresholds) if next_enabled_thresholds else None

        lines = []
        for name, (thr, enabled) in thresholds.items():
            icon = "✅" if enabled else "❌"
            marker = " ← próximo" if enabled and next_threshold is not None and thr == next_threshold else ""
            lines.append(f"{icon} **{name}** a los {thr} warns{marker}")

        embed.add_field(name="Consecuencias configuradas", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"ID: {target.id}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # /unwarn
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="unwarn", description="Revoca un warn por número de caso")
    @app_commands.describe(case_id="Número de caso o ID interno", razon="Razón de la revocación")
    async def unwarn(
        self,
        interaction: discord.Interaction,
        case_id: int,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        case = self.db.get_case(interaction.guild_id, case_id)
        if not case:
            return await interaction.response.send_message(f"❌ No existe el caso `{case_id}`.", ephemeral=True)
        if (case.get("action_type") or "").upper() not in {"WARN", "AUTO_WARN"}:
            return await interaction.response.send_message("❌ Ese caso no es un warn.", ephemeral=True)
        if (case.get("status") or "active") == "revoked":
            return await interaction.response.send_message("ℹ️ Ese warn ya estaba revocado.", ephemeral=True)

        target_id = int(case["target_id"])
        internal_case_id = int(case["id"])

        async def apply_unwarn():
            current_actor, _, auth_error = await self._fresh_moderation_context(
                interaction,
                "moderate_members",
                target_id=target_id,
            )
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "Autorización no verificable.")
            current_case = self.db.get_case_by_id(
                interaction.guild_id, internal_case_id
            )
            if (
                not current_case
                or str(current_case.get("status") or "active").lower() != "active"
                or str(current_case.get("action_type") or "").upper()
                not in {"WARN", "AUTO_WARN"}
                or int(current_case.get("target_id") or 0) != target_id
            ):
                raise LookupError("warn_not_active")
            new_count = self.db.decrement_warn(target_id, interaction.guild_id)
            updated_case = self.db.update_case_by_id(
                interaction.guild_id,
                internal_case_id,
                status="revoked",
                extra_data=json.dumps(
                    {
                        "revoked_by": current_actor.id,
                        "revoked_reason": razon,
                    },
                    ensure_ascii=False,
                ),
            )
            self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                "UNWARN",
                razon,
                {**interaction_metadata(interaction, target_id, current_actor), **{
                    "case_id": current_case.get("id"),
                    "case_number": current_case.get("case_number"),
                }},
                parent_case_id=internal_case_id,
                status="revoked",
            )
            return current_actor, current_case, updated_case, new_count

        try:
            current_actor, case, updated, new_total = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "UNWARN",
                apply_unwarn,
            )
        except PermissionError as exc:
            return await interaction.response.send_message(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except LookupError:
            return await interaction.response.send_message(
                "ℹ️ Ese warn ya no está activo.", ephemeral=True
            )

        embed = discord.Embed(
            title="Warn revocado",
            description=f"Caso **#{updated.get('case_number', case_id)}** revocado. Warns activos restantes: **{new_total}**.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"<@{case['target_id']}>\n`{case['target_id']}`", inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

    @unwarn.error
    async def unwarn_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /cases y /moderations
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="cases", description="Muestra historial de casos de moderación")
    @app_commands.describe(usuario="Filtrar por usuario", case_id="Mostrar un caso específico")
    async def cases_cmd(
        self,
        interaction: discord.Interaction,
        usuario: Optional[discord.Member] = None,
        case_id: Optional[int] = None,
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        if case_id is not None:
            case = self.db.get_case(interaction.guild_id, case_id)
            if not case:
                return await interaction.response.send_message(f"❌ No existe el caso `{case_id}`.", ephemeral=True)
            embed = self._case_embed(case, title="Detalle de caso")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        rows = self.db.list_cases(interaction.guild_id, usuario.id if usuario else None, limit=10)
        if not rows:
            return await interaction.response.send_message("No hay casos para mostrar.", ephemeral=True)

        embed = discord.Embed(
            title="Casos de moderación" if not usuario else f"Casos de {usuario.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for row in rows[:10]:
            embed.add_field(
                name=f"#{row.get('case_number') or row.get('id')} · {row.get('action_type')} · {row.get('status') or 'active'}",
                value=f"Usuario: <@{row.get('target_id')}> · Mod: <@{row.get('moderator_id')}>\nRazón: {row.get('reason') or '—'}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cases_cmd.error
    async def cases_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    @app_commands.command(name="moderations", description="Lista sanciones activas con expiración")
    async def moderations_cmd(self, interaction: discord.Interaction):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        rows = self.db.get_active_moderations(interaction.guild_id, limit=15)
        pending = self.db.get_pending_moderation_actions(interaction.guild_id, limit=15)
        if not rows and not pending:
            return await interaction.response.send_message("No hay moderaciones activas registradas.", ephemeral=True)
        embed = discord.Embed(title="Moderaciones activas", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
        seen = set()
        for row in rows:
            seen.add(row.get("id"))
            exp = row.get("expires_at")
            exp_txt = "permanente" if not exp else f"<t:{int(datetime.fromisoformat(exp).timestamp())}:R>"
            embed.add_field(
                name=f"#{row.get('case_number') or row.get('id')} · {row.get('action_type')}",
                value=f"Usuario: <@{row.get('target_id')}> · Expira: {exp_txt}\nRazón: {row.get('reason') or '—'}",
                inline=False,
            )
        for job in pending:
            if job.get("case_id") in seen:
                continue
            exp_txt = f"<t:{int(datetime.fromisoformat(job['execute_at']).timestamp())}:R>"
            embed.add_field(
                name=f"Job #{job.get('id')} · {job.get('action_type')}",
                value=f"Usuario: <@{job.get('user_id')}> · Ejecuta: {exp_txt}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _case_embed(self, case: Dict, title: str = "Caso") -> discord.Embed:
        embed = discord.Embed(
            title=f"{title} #{case.get('case_number') or case.get('id')}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Acción", value=str(case.get("action_type") or "—"), inline=True)
        embed.add_field(name="Estado", value=str(case.get("status") or "active"), inline=True)
        embed.add_field(name="Usuario", value=f"<@{case.get('target_id')}>\n`{case.get('target_id')}`", inline=True)
        embed.add_field(name="Moderador", value=f"<@{case.get('moderator_id')}>\n`{case.get('moderator_id')}`", inline=True)
        if case.get("duration_seconds"):
            embed.add_field(name="Duración", value=fmt_duration(int(case["duration_seconds"])), inline=True)
        if case.get("expires_at"):
            try:
                embed.add_field(name="Expira", value=f"<t:{int(datetime.fromisoformat(case['expires_at']).timestamp())}:R>", inline=True)
            except Exception:
                embed.add_field(name="Expira", value=str(case.get("expires_at")), inline=True)
        if case.get("evidence_url"):
            embed.add_field(name="Evidencia", value=str(case.get("evidence_url")), inline=False)
        embed.add_field(name="Razón", value=str(case.get("reason") or "—"), inline=False)
        return embed

    case_group = app_commands.Group(name="case", description="Gestión de casos de moderación")

    @case_group.command(name="evidence", description="Añade archivos o contexto de Discord a un caso, de forma privada")
    async def case_evidence(
        self, interaction: discord.Interaction, case_id: int,
        archivo: Optional[discord.Attachment] = None, mensaje_url: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        case = self.db.get_case(interaction.guild_id, case_id)
        if not case:
            return await interaction.followup.send("Caso no encontrado.", ephemeral=True)
        action = str(case.get("action_type") or "").removeprefix("AUTO_")
        permission = "ban_members" if "BAN" in action else "kick_members" if action == "KICK" else "manage_roles" if "MUTE" in action else "moderate_members"
        actor, _, error = await self._fresh_moderation_context(interaction, permission)
        if error or actor is None:
            return await interaction.followup.send(error or "No pude verificar tus permisos.", ephemeral=True)
        evidence = await capture_manual(self.bot, interaction, mensaje_url, archivo)
        actor, _, error = await self._fresh_moderation_context(interaction, permission)
        if error or actor is None:
            return await interaction.followup.send(error or "Tus permisos cambiaron.", ephemeral=True)
        try:
            self.db.add_case_evidence(interaction.guild_id, int(case["id"]), evidence)
        except ValueError:
            return await interaction.followup.send("La evidencia supera el límite del caso o ya no está disponible.", ephemeral=True)
        summary = self.db.case_evidence_summary(interaction.guild_id, int(case["id"]))
        await interaction.followup.send(f"Evidencia añadida: {summary['evidence_count']} archivos disponibles. Estado: {summary['evidence_status']}. " + ", ".join(summary["evidence_errors"]), ephemeral=True)

    @case_group.command(name="update", description="Actualiza razón/evidencia/estado de un caso")
    @app_commands.describe(
        case_id="Número de caso o ID interno",
        razon="Nueva razón del caso",
        evidencia_url="Nueva URL de evidencia",
        estado="active, expired, revoked o failed",
    )
    async def case_update(
        self,
        interaction: discord.Interaction,
        case_id: int,
        razon: Optional[str] = None,
        evidencia_url: Optional[str] = None,
        estado: Optional[str] = None,
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)
        case = self.db.get_case(interaction.guild_id, case_id)
        if not case:
            return await interaction.response.send_message(f"❌ No existe el caso `{case_id}`.", ephemeral=True)

        payload: Dict = {}
        if razon is not None:
            payload["reason"] = razon
        if evidencia_url is not None:
            payload["evidence_url"] = evidencia_url
        if estado is not None:
            normalized = estado.lower().strip()
            if normalized not in {"active", "expired", "revoked", "failed"}:
                return await interaction.response.send_message("❌ Estado inválido. Usa active, expired, revoked o failed.", ephemeral=True)
            payload["status"] = normalized
        if not payload:
            return await interaction.response.send_message("No hay cambios que aplicar.", ephemeral=True)

        updated = self.db.update_case_by_id(interaction.guild_id, int(case["id"]), **payload)
        self.db.log_action(
            interaction.guild_id, case["target_id"], interaction.user.id,
            "CASE_UPDATE", "Caso actualizado", {**interaction_metadata(interaction, case["target_id"], interaction.user.id), **{"case_id": case.get("id"), "changes": payload}},
            parent_case_id=int(case["id"]),
            status=payload.get("status", case.get("status") or "active"),
        )
        await interaction.response.send_message(embed=self._case_embed(updated or case, title="Caso actualizado"), ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # /clearwarns
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="clearwarns", description="Limpia todos los warns de un usuario")
    @app_commands.describe(usuario="Usuario al que limpiar los warns", razon="Razón del reseteo")
    async def clearwarns(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        user = interaction.user
        guild = interaction.guild
        if (
            not guild
            or not isinstance(user, discord.Member)
            or (user.id != guild.owner_id and not user.guild_permissions.administrator)
        ):
            return await interaction.response.send_message(
                _voice(self).line("error", "Este comando requiere Administrador."),
                ephemeral=True,
            )
        target_id = usuario.id

        async def apply_clear_warns():
            current_actor, auth_error = await self._fresh_owner_or_admin(interaction)
            if auth_error or current_actor is None:
                raise PermissionError(auth_error or "Autorización no verificable.")
            record = self.db.get_user(target_id, interaction.guild_id)
            old_count = int(record["warns"] or 0)
            if old_count <= 0:
                raise LookupError("no_warns")
            self.db.clear_warns(target_id, interaction.guild_id)
            self.db.log_action(
                interaction.guild_id,
                target_id,
                current_actor.id,
                "CLEAR_WARNS",
                razon,
                {**interaction_metadata(interaction, target_id, current_actor), **{"removed": old_count}},
                status="revoked",
            )
            return current_actor, old_count

        try:
            current_actor, old = await run_sanction_locked(
                self.bot,
                interaction.guild_id,
                target_id,
                "CLEAR_WARNS",
                apply_clear_warns,
            )
        except PermissionError as exc:
            return await interaction.response.send_message(
                _voice(self).line("error", str(exc)), ephemeral=True
            )
        except LookupError:
            return await interaction.response.send_message(
                f"ℹ️ {usuario.mention} no tiene warns.", ephemeral=True
            )

        embed = discord.Embed(
            title="Warns limpiados",
            description=f"Se eliminaron **{old}** warn(s) de {usuario.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=usuario.mention, inline=True)
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

    @clearwarns.error
    async def clearwarns_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /purge
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="purgar", description="Elimina mensajes en masa del canal actual")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        cantidad="Número de mensajes recientes a eliminar (2-100)",
        usuario="Eliminar solo mensajes de este usuario (opcional)",
        tipo="Filtro opcional: todos, links, invitaciones, bots o humano",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Todos", value="all"),
        app_commands.Choice(name="Links", value="links"),
        app_commands.Choice(name="Invitaciones", value="invites"),
        app_commands.Choice(name="Bots", value="bots"),
        app_commands.Choice(name="Humanos", value="humans"),
    ])
    async def purge(
        self,
        interaction: discord.Interaction,
        cantidad: app_commands.Range[int, 2, 100],
        usuario: Optional[discord.Member] = None,
        tipo: str = "all",
    ):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message(
                "❌ Este comando solo puede usarse en canales con historial de mensajes.",
                ephemeral=True,
            )
        if not await check_channel_perms(
            interaction,
            channel,
            user_permission="manage_messages",
            bot_permissions=("manage_messages", "read_message_history"),
        ):
            return
        await interaction.response.defer(ephemeral=True)

        tipo = (tipo or "all").lower().strip()

        def check(msg: discord.Message) -> bool:
            if usuario and msg.author.id != usuario.id:
                return False
            if tipo == "all":
                return True
            if tipo == "bots":
                return bool(msg.author.bot)
            if tipo == "humans":
                return not bool(msg.author.bot)
            content = msg.content or ""
            if tipo == "invites":
                return bool(INVITE_RE.search(content))
            if tipo == "links":
                return bool(URL_RE.search(content))
            return True

        current_actor, _, auth_error = await self._fresh_moderation_context(
            interaction, "manage_messages"
        )
        guild = interaction.guild
        if auth_error or current_actor is None or guild is None:
            return await interaction.followup.send(
                _voice(self).line("error", auth_error or "No pude verificar la operación."),
                ephemeral=True,
            )
        current_channel = guild.get_channel_or_thread(channel.id)
        bot_member = guild.me
        if not isinstance(current_channel, (discord.TextChannel, discord.Thread)):
            return await interaction.followup.send(
                "❌ El canal ya no está disponible.", ephemeral=True
            )
        actor_channel_perms = current_channel.permissions_for(current_actor)
        bot_channel_perms = (
            current_channel.permissions_for(bot_member) if bot_member else None
        )
        if not (
            actor_channel_perms.view_channel
            and actor_channel_perms.read_message_history
            and bot_channel_perms
            and bot_channel_perms.manage_messages
            and bot_channel_perms.read_message_history
        ):
            return await interaction.followup.send(
                "❌ Los permisos actuales del canal no permiten completar la purga.",
                ephemeral=True,
            )
        channel = current_channel
        try:
            deleted = await channel.purge(limit=cantidad, check=check, bulk=True)
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo permisos para eliminar mensajes.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ Error al purgar: {exc}", ephemeral=True)

        self.db.log_action(
            interaction.guild_id,
            0,
            current_actor.id,
            "PURGE",
            f"Purge {tipo}",
            {**interaction_metadata(interaction, 0, current_actor.id), **{"deleted": len(deleted), "requested": cantidad, "filter": tipo, "user_id": usuario.id if usuario else None}},
            status="expired",
        )

        embed = discord.Embed(
            title="Mensajes purgados",
            description=f"Se eliminaron **{len(deleted)}** mensajes en {interaction.channel.mention}.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Moderador", value=current_actor.mention, inline=True)
        embed.add_field(name="Filtro", value=tipo, inline=True)
        if usuario:
            embed.add_field(name="Usuario filtrado", value=usuario.mention, inline=True)
        await self._send_log(interaction.guild, embed)

        await interaction.followup.send(
            f"✅ Eliminados **{len(deleted)}** mensajes.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────────
    # /appeals
    # ─────────────────────────────────────────────────────────────────────────

    appeals_group = app_commands.Group(name="appeals", description="Gestión de apelaciones")

    @appeals_group.command(name="list", description="Lista las apelaciones pendientes del servidor")
    @app_commands.describe(
        estado="Filtrar por estado: PENDING (por defecto), ACCEPTED, DENIED",
    )
    async def appeals_list(
        self,
        interaction: discord.Interaction,
        estado: Optional[str] = None,
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message(_voice(self).line("error", "Este comando es solo para mods. El gato te miró feo."), ephemeral=True)

        status_filter = (estado or "PENDING").upper()
        if status_filter not in ("PENDING", "ACCEPTED", "DENIED"):
            return await interaction.response.send_message(
                "❌ Estado inválido. Usa: `PENDING`, `ACCEPTED` o `DENIED`.",
                ephemeral=True,
            )

        appeals = self.db.get_appeals_by_guild(interaction.guild_id, status_filter)

        if not appeals:
            return await interaction.response.send_message(
                f"📭 No hay apelaciones con estado **{status_filter}**.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"Apelaciones • {status_filter}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Total: {len(appeals)}")

        for a in appeals[:10]:
            user = self.bot.get_user(a["user_id"])
            user_name = f"{user}" if user else f"`{a['user_id']}`"
            embed.add_field(
                name=f"#{a['id']} — {user_name}",
                value=(
                    f"**Sanción:** {a['action_type']}\n"
                    f"**Estado:** {a['status']}\n"
                    f"**Razón:** {a['reason'][:100]}\n"
                    f"**Creada:** <t:{int(datetime.fromisoformat(a['created_at']).timestamp())}:R>"
                ),
                inline=False,
            )

        if len(appeals) > 10:
            embed.description = f"Mostrando las 10 más recientes de {len(appeals)} totales."

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # /modconfig — configuración crítica también disponible por Discord
    # ─────────────────────────────────────────────────────────────────────────

    modconfig_group = app_commands.Group(
        name="modconfig",
        description="Configura roles y canales críticos de moderación",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @modconfig_group.command(name="status", description="Muestra la configuración actual de moderación")
    async def modconfig_status(self, interaction: discord.Interaction):
        if not self._has_config_perms(interaction):
            return await interaction.response.send_message("❌ Necesitas Administrador o Gestionar servidor.", ephemeral=True)
        cfg = self.db.get_config(interaction.guild_id)
        srv = self.db.get_server_config(interaction.guild_id)
        embed = discord.Embed(
            title="Configuración de moderación",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Rol mute", value=f"<@&{cfg.get('mute_role_id')}>" if cfg.get("mute_role_id") else "—", inline=True)
        embed.add_field(name="Rol mod", value=f"<@&{srv.get('mod_role_id')}>" if srv.get("mod_role_id") else "—", inline=True)
        staff_id = srv.get("staff_role_id") or cfg.get("staff_role_id")
        embed.add_field(name="Rol staff", value=f"<@&{staff_id}>" if staff_id else "—", inline=True)
        embed.add_field(name="Modlog", value=f"<#{srv.get('modlog_channel')}>" if srv.get("modlog_channel") else "—", inline=True)
        embed.add_field(name="Serverlog", value=f"<#{srv.get('serverlog_channel')}>" if srv.get("serverlog_channel") else "—", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @modconfig_group.command(name="mute_role", description="Asigna el rol que usará /mute")
    @app_commands.describe(rol="Rol que se aplicará a usuarios muteados")
    async def modconfig_mute_role(self, interaction: discord.Interaction, rol: discord.Role):
        live_role, error = await self._fresh_config_role(
            interaction,
            rol.id,
            owner_or_admin_only=False,
        )
        if error or not safe_for_automatic_assignment(
            live_role,
            interaction.guild.me if interaction.guild else None,
            forbidden_role_ids=delegated_bot_role_ids(
                self.db, interaction.guild_id
            ),
        ):
            return await interaction.response.send_message(
                f"❌ {error or 'El rol no es seguro para una asignación automática.'}",
                ephemeral=True,
            )
        changed = await self._apply_mute_overwrites(interaction.guild, live_role)
        live_role = interaction.guild.get_role(live_role.id)
        if not mute_role_has_effective_denies(interaction.guild, live_role):
            return await interaction.response.send_message(
                "❌ No pude aplicar denies de envío y voz en todos los canales relevantes.",
                ephemeral=True,
            )
        self.db.set_config(interaction.guild_id, mute_role_id=live_role.id)
        await interaction.response.send_message(
            f"✅ Rol de mute configurado: {live_role.mention}. Overrides aplicados en `{changed}` canales visibles.",
            ephemeral=True,
        )

    @modconfig_group.command(name="mod_role", description="Asigna el rol con permisos de moderación del bot")
    @app_commands.describe(rol="Rol de moderador")
    async def modconfig_mod_role(self, interaction: discord.Interaction, rol: discord.Role):
        live_role, error = await self._fresh_config_role(
            interaction,
            rol.id,
            owner_or_admin_only=True,
        )
        if error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        self.db.set_server_config(interaction.guild_id, mod_role_id=live_role.id)
        await interaction.response.send_message(f"✅ Rol moderador configurado: {live_role.mention}", ephemeral=True)

    @modconfig_group.command(name="staff_role", description="Asigna el rol staff usado por moderación/tickets/reportes")
    @app_commands.describe(rol="Rol staff")
    async def modconfig_staff_role(self, interaction: discord.Interaction, rol: discord.Role):
        live_role, error = await self._fresh_config_role(
            interaction,
            rol.id,
            owner_or_admin_only=True,
        )
        if error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        self.db.set_config(interaction.guild_id, staff_role_id=live_role.id)
        self.db.set_server_config(interaction.guild_id, staff_role_id=live_role.id)
        await interaction.response.send_message(f"✅ Rol staff configurado: {live_role.mention}", ephemeral=True)

    @modconfig_group.command(name="modlog", description="Asigna el canal de logs de moderación")
    @app_commands.describe(canal="Canal de texto para logs de moderación")
    async def modconfig_modlog(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not self._has_config_perms(interaction):
            return await interaction.response.send_message("❌ Necesitas Administrador o Gestionar servidor.", ephemeral=True)
        self.db.set_server_config(interaction.guild_id, modlog_channel=canal.id, modlog_enabled=1)
        await interaction.response.send_message(f"✅ Canal de modlogs configurado: {canal.mention}", ephemeral=True)

    @modconfig_group.command(name="serverlog", description="Asigna el canal de logs de eventos del servidor")
    @app_commands.describe(canal="Canal de texto para logs del servidor")
    async def modconfig_serverlog(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not self._has_config_perms(interaction):
            return await interaction.response.send_message("❌ Necesitas Administrador o Gestionar servidor.", ephemeral=True)
        self.db.set_server_config(interaction.guild_id, serverlog_channel=canal.id, serverlog_enabled=1)
        await interaction.response.send_message(f"✅ Canal de serverlogs configurado: {canal.mention}", ephemeral=True)

    # ── Manejador de errores de permisos ──────────────────────────────────────

    async def _handle_perm_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        interaction.extras["catsbot.app_command_error_handled"] = True

        if isinstance(error, app_commands.MissingPermissions):
            msg = f"❌ Te faltan permisos: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = f"❌ Al bot le faltan permisos: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.CommandSignatureMismatch):
            msg = (
                "❌ Discord envió una versión antigua o incompleta del comando. "
                "Vuelve a abrirlo y rellena las opciones obligatorias, incluida `razon` "
                "para /warn, /ban y /kick. No se ha aplicado ninguna sanción."
            )
        elif isinstance(error, app_commands.TransformerError):
            command = interaction.command
            command_name = getattr(command, "qualified_name", "desconocido")
            if error.type is discord.AppCommandOptionType.user:
                logger.warning(
                    "No se pudo resolver el usuario de /%s como miembro "
                    "(guild=%s, value_type=%s)",
                    command_name,
                    interaction.guild_id,
                    type(error.value).__name__,
                )
                msg = (
                    "❌ No pude reconocer ese usuario como miembro de este servidor. "
                    "Vuelve a abrir el comando y selecciónalo desde la lista de Discord; "
                    "si aún aparece como texto libre, reinicia Discord para actualizar los comandos."
                )
            else:
                logger.warning(
                    "Valor inválido para /%s (option_type=%s, value_type=%s)",
                    command_name,
                    error.type,
                    type(error.value).__name__,
                )
                msg = (
                    "❌ Uno de los valores del comando no es válido. "
                    "Vuelve a abrirlo e inténtalo de nuevo."
                )
        else:
            logger.error("Error en comando de moderación: %s", error, exc_info=True)
            msg = "❌ Error inesperado. Revisa los logs del bot."

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except discord.NotFound:
            logger.warning("No se pudo responder error de moderación: interacción expirada o desconocida")
        except discord.HTTPException as exc:
            logger.warning("No se pudo responder error de moderación: %s", exc)


# ── Views y Modals para /modconfig ────────────────────────────────────────────
# ELIMINADOS: ModConfigView, MuteRoleSelectView, MuteDurationConfigModal,
# ThresholdsConfigModal, ConsequencesToggleView
# → Configuración migrada al Dashboard Web


# ── Appeals UI ────────────────────────────────────────────────────────────────

class AppealUserModal(discord.ui.Modal, title="Apelar Sanción"):
    appeal_text = discord.ui.TextInput(
        label="¿Por qué deberíamos retirar tu sanción?",
        style=discord.TextStyle.paragraph,
        placeholder="Explica tu situación detalladamente...",
        required=True,
        max_length=1000
    )

    def __init__(
        self,
        bot: commands.Bot,
        guild_id: int,
        action_type: str,
        reason: str,
        case_id: int,
    ):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.action_type = action_type
        self.reason = reason
        self.case_id = int(case_id)

    async def on_submit(self, interaction: discord.Interaction):
        db = getattr(self.bot, 'db')
        appeal_id = db.create_appeal(
            self.guild_id,
            interaction.user.id,
            self.action_type,
            self.reason,
            self.appeal_text.value,
            case_id=self.case_id,
        )
        if not appeal_id:
            return await interaction.response.send_message(
                "❌ La sanción asociada ya no existe o no coincide con esta apelación.",
                ephemeral=True,
            )

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message(
                "⚠️ Tu apelación quedó registrada pero el bot no puede ver el servidor en este momento.",
                ephemeral=True,
            )
            logger.warning("No se pudo publicar apelación %s: guild %s no disponible", appeal_id, self.guild_id)
            return

        embed = discord.Embed(
            title="Nueva Apelación Recibida",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Sanción", value=self.action_type, inline=True)
        embed.add_field(name="Razón Original", value=self.reason, inline=True)
        embed.add_field(name="Defensa del Usuario", value=self.appeal_text.value, inline=False)
        embed.set_footer(text=f"ID Apelación: {appeal_id}")

        cog = self.bot.get_cog("Moderation")
        modlog = await cog._resolve_modlog(guild) if cog else None

        if modlog is None:
            await interaction.response.send_message(
                "✅ Tu apelación quedó registrada. El equipo la revisará desde el dashboard.\n"
                "ℹ️ Aviso al staff: el canal de mod-logs no está configurado o no es accesible.",
                ephemeral=True,
            )
            logger.warning(
                "Apelación %s guardada pero no publicada: modlog inaccesible en guild %s",
                appeal_id, self.guild_id,
            )
            return

        try:
            await modlog.send(
                embed=embed,
                view=AppealModView(self.bot, appeal_id, interaction.user.id, self.action_type),
            )
            await interaction.response.send_message(
                "✅ Tu apelación ha sido enviada al equipo de moderación. Recibirás un DM con la respuesta.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Tu apelación quedó registrada pero el bot no pudo publicarla en el canal de mod-logs (sin permisos).",
                ephemeral=True,
            )
            logger.warning("Sin permisos para publicar apelación %s en modlog", appeal_id)
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                "⚠️ Tu apelación quedó registrada pero hubo un error publicándola en mod-logs.",
                ephemeral=True,
            )
            logger.warning("Error enviando apelación %s a modlog: %s", appeal_id, exc)


class AppealUserView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        guild_id: int,
        action_type: str,
        reason: str,
        case_id: int,
    ):
        super().__init__(timeout=86400)
        self.bot = bot
        self.guild_id = guild_id
        self.action_type = action_type
        self.reason = reason
        self.case_id = int(case_id)

    @discord.ui.button(label="Apelar Sanción", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AppealUserModal(
                self.bot,
                self.guild_id,
                self.action_type,
                self.reason,
                self.case_id,
            )
        )


def _appeal_staff_allowed(
    bot: commands.Bot,
    interaction: discord.Interaction,
    member: Optional[discord.Member] = None,
) -> bool:
    guild = interaction.guild
    user = member or interaction.user
    if (
        not guild
        or not isinstance(user, discord.Member)
        or (
            getattr(user, "guild", None) is not None
            and getattr(user.guild, "id", None) != guild.id
        )
        or interaction.guild_id != guild.id
    ):
        return False
    if user.id == guild.owner_id or user.guild_permissions.administrator:
        return True
    db = getattr(bot, "db", None)
    allowed_ids = delegated_moderation_role_ids(db, guild.id)
    if allowed_ids is None:
        return False
    return any(role.id in allowed_ids for role in user.roles)


async def _fresh_appeal_staff_member(
    bot: commands.Bot,
    interaction: discord.Interaction,
) -> Optional[discord.Member]:
    moderation = bot.get_cog("Moderation")
    if not isinstance(moderation, Moderation):
        return None
    member, _, error = await moderation._fresh_moderation_context(
        interaction,
        "administrator",
    )
    return member if error is None else None


def _pending_appeal(bot: commands.Bot, interaction: discord.Interaction, appeal_id: int):
    if not interaction.guild_id:
        return None
    appeal = getattr(bot, "db").get_appeal(appeal_id)
    if not appeal:
        return None
    if int(appeal.get("guild_id", 0)) != interaction.guild_id:
        return None
    if str(appeal.get("status") or "").upper() != "PENDING":
        return None
    return appeal


class AppealAcceptModal(discord.ui.Modal, title="Aceptar Apelación"):
    mod_reason = discord.ui.TextInput(
        label="Mensaje para el usuario",
        style=discord.TextStyle.paragraph,
        placeholder="Ej: Se retirará tu sanción porque...",
        required=True
    )
    auto_remove = discord.ui.TextInput(
        label="¿Quitar sanción automáticamente? (SI/NO)",
        style=discord.TextStyle.short,
        default="SI",
        required=True
    )

    def __init__(self, bot: commands.Bot, appeal_id: int, user_id: int, action_type: str):
        super().__init__()
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        if not _appeal_staff_allowed(self.bot, interaction):
            return await interaction.response.send_message(
                "❌ Ya no tienes permisos para gestionar apelaciones.", ephemeral=True
            )
        appeal = _pending_appeal(self.bot, interaction, self.appeal_id)
        if not appeal:
            return await interaction.response.send_message(
                "❌ La apelación no existe, no pertenece a este servidor o ya fue resuelta.",
                ephemeral=True,
            )
        self.user_id = int(appeal["user_id"])
        self.action_type = str(appeal["action_type"]).upper()
        await interaction.response.defer(ephemeral=True)
        current_actor = await _fresh_appeal_staff_member(self.bot, interaction)
        appeal = _pending_appeal(self.bot, interaction, self.appeal_id)
        if current_actor is None or not appeal:
            return await interaction.followup.send(
                "❌ Tus permisos cambiaron o la apelación ya no está pendiente.",
                ephemeral=True,
            )
        self.user_id = int(appeal["user_id"])
        self.action_type = str(appeal["action_type"]).upper()
        db = getattr(self.bot, 'db')
        if not db.claim_pending_appeal(self.appeal_id, interaction.guild_id):
            return await interaction.followup.send(
                "❌ La apelación ya está siendo procesada o fue resuelta.",
                ephemeral=True,
            )
        appeal = db.get_appeal(self.appeal_id)
        if (
            not appeal
            or int(appeal.get("guild_id") or 0) != interaction.guild_id
            or str(appeal.get("status") or "").upper() != "PROCESSING"
        ):
            db.release_appeal_claim(self.appeal_id, interaction.guild_id)
            return await interaction.followup.send(
                "❌ No se pudo verificar la apelación reservada.", ephemeral=True
            )
        self.user_id = int(appeal["user_id"])
        self.action_type = str(appeal["action_type"]).upper()
        guild = interaction.guild
        member = guild.get_member(self.user_id) if guild else None
        recipient = member or self.bot.get_user(self.user_id)

        auto_text = self.auto_remove.value.strip().upper()
        auto_remove_error: Optional[str] = None
        appeal_finalized = False
        if auto_text == "SI" and guild:
            sanction_guard = None
            sanction_guard_acquired = False
            try:
                moderation = self.bot.get_cog("Moderation")
                if not isinstance(moderation, Moderation):
                    raise RuntimeError("Moderation cog no disponible")
                try:
                    case_id = int(appeal.get("case_id") or 0)
                except (TypeError, ValueError):
                    case_id = 0
                if not case_id:
                    raise RuntimeError(
                        "la apelación legacy no está ligada a un caso exacto"
                    )
                sanction_guard = sanction_lock(
                    self.bot,
                    guild.id,
                    self.user_id,
                    self.action_type,
                )
                await sanction_guard.acquire()
                sanction_guard_acquired = True
                appeal_case = db.get_appealable_active_case(
                    guild.id,
                    self.user_id,
                    case_id,
                    self.action_type,
                )
                if appeal_case is None:
                    raise RuntimeError(
                        "la sanción apelada ya no es la sanción activa actual"
                    )
                if self.action_type in ("BAN", "TEMPBAN"):
                    effect_state = await moderation._ban_effect_state(
                        guild, self.user_id, appeal_case
                    )
                    if effect_state == "legacy":
                        raise RuntimeError(
                            "el caso apelado no conserva la identidad exacta del ban"
                        )
                    if effect_state == "replaced":
                        raise RuntimeError(
                            "el ban actual fue creado fuera del caso apelado"
                        )
                    if db.get_appealable_active_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                    ) is None:
                        raise RuntimeError(
                            "la sanción cambió durante la retirada automática"
                        )
                    action_actor, _, auth_error = (
                        await moderation._fresh_moderation_context(
                            interaction, "ban_members"
                        )
                    )
                    if auth_error or action_actor is None:
                        raise PermissionError(
                            auth_error or "autorización no verificable"
                        )
                    effect_state = await moderation._ban_effect_state(
                        guild, self.user_id, appeal_case
                    )
                    if effect_state == "legacy":
                        raise RuntimeError(
                            "el caso apelado no conserva la identidad exacta del ban"
                        )
                    if effect_state == "replaced":
                        raise RuntimeError(
                            "el ban actual fue creado fuera del caso apelado"
                        )
                    action_actor, _, auth_error = (
                        await moderation._fresh_moderation_context(
                            interaction, "ban_members"
                        )
                    )
                    if auth_error or action_actor is None:
                        raise PermissionError(
                            auth_error or "autorización no verificable"
                        )
                    if effect_state == "match":
                        try:
                            await guild.unban(
                                discord.Object(id=self.user_id),
                                reason=f"Apelación Aceptada por {action_actor}",
                            )
                        except discord.NotFound:
                            pass
                    if not db.resolve_appealed_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                        self.appeal_id,
                    ):
                        raise RuntimeError(
                            "la sanción cambió durante la retirada automática"
                        )
                    appeal_finalized = True
                elif self.action_type == "MUTE":
                    try:
                        mute_role_id = int(
                            moderation._json_object(
                                appeal_case.get("extra_data")
                            )["role_id"]
                        )
                    except (KeyError, TypeError, ValueError):
                        raise RuntimeError(
                            "el caso apelado no conserva el rol de mute exacto"
                        )
                    if db.get_appealable_active_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                    ) is None:
                        raise RuntimeError(
                            "la sanción cambió durante la retirada automática"
                        )
                    effect_state = await moderation._mute_effect_state(
                        guild,
                        self.user_id,
                        mute_role_id,
                        appeal_case,
                    )
                    if effect_state in {"legacy", "unverified"}:
                        raise RuntimeError(
                            "el caso apelado no conserva una identidad de mute verificable"
                        )
                    if effect_state == "replaced":
                        raise RuntimeError(
                            "el rol de mute actual fue reaplicado fuera del caso apelado"
                        )
                    if db.get_appealable_active_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                    ) is None:
                        raise RuntimeError(
                            "la sanción cambió durante la retirada automática"
                        )
                    action_actor, mem, mute_role, auth_error = (
                        await moderation._fresh_mute_role_context(
                            interaction,
                            self.user_id,
                            mute_role_id,
                            allow_absent_target=True,
                            allow_absent_effect=True,
                        )
                    )
                    if auth_error or action_actor is None:
                        raise PermissionError(
                            auth_error or "autorización no verificable"
                        )
                    effect_state = await moderation._mute_effect_state(
                        guild,
                        self.user_id,
                        mute_role_id,
                        appeal_case,
                    )
                    if effect_state in {"legacy", "unverified"}:
                        raise RuntimeError(
                            "el caso apelado no conserva una identidad de mute verificable"
                        )
                    if effect_state == "replaced":
                        raise RuntimeError(
                            "el rol de mute actual fue reaplicado fuera del caso apelado"
                        )
                    action_actor, mem, mute_role, auth_error = (
                        await moderation._fresh_mute_role_context(
                            interaction,
                            self.user_id,
                            mute_role_id,
                            allow_absent_target=True,
                            allow_absent_effect=True,
                        )
                    )
                    if auth_error or action_actor is None:
                        raise PermissionError(
                            auth_error or "autorización no verificable"
                        )
                    if effect_state == "match" and (mem is None or mute_role is None):
                        raise RuntimeError(
                            "el efecto de mute cambió durante la retirada automática"
                        )
                    if effect_state == "absent" and mute_role is not None:
                        raise RuntimeError(
                            "el efecto de mute cambió durante la retirada automática"
                        )
                    if effect_state == "match" and mem and mute_role and mute_role_id in {
                        int(value) for value in getattr(mem, "_roles", ())
                    }:
                        await mem.remove_roles(
                            mute_role,
                            reason=f"Apelación Aceptada por {action_actor}",
                        )
                    await moderation._restore_mute_roles(
                        guild, self.user_id, appeal_case, actor_id=action_actor.id
                    )
                    if not db.resolve_appealed_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                        self.appeal_id,
                    ):
                        raise RuntimeError(
                            "la sanción cambió durante la retirada automática"
                        )
                    appeal_finalized = True
                elif self.action_type == "WARN":
                    action_actor, _, auth_error = await moderation._fresh_moderation_context(
                        interaction,
                        "manage_messages",
                        target_id=self.user_id,
                        allow_absent_target=True,
                    )
                    if auth_error or action_actor is None:
                        raise PermissionError(auth_error or "autorización no verificable")
                    if not db.resolve_appealed_case(
                        guild.id,
                        self.user_id,
                        case_id,
                        self.action_type,
                        self.appeal_id,
                    ):
                        raise RuntimeError(
                            "el warn apelado ya no estaba activo"
                        )
                    appeal_finalized = True
            except asyncio.CancelledError:
                db.release_appeal_claim(self.appeal_id, interaction.guild_id)
                raise
            except (PermissionError, RuntimeError) as exc:
                logger.warning(
                    "Retirada automática de apelación %s cancelada: %s",
                    self.appeal_id,
                    exc,
                )
                auto_remove_error = "No se pudo autorizar la retirada automática."
            except discord.Forbidden:
                logger.warning("Sin permisos para retirar sanción automáticamente en apelación %s", self.appeal_id)
                auto_remove_error = "El bot ya no tiene permisos para retirar la sanción."
            except discord.HTTPException as exc:
                logger.warning("Error quitando sanción automáticamente en apelación %s: %s", self.appeal_id, exc)
                auto_remove_error = "Discord no confirmó la retirada de la sanción."
            except Exception as exc:
                logger.warning(
                    "Error interno retirando sanción de apelación %s: %s",
                    self.appeal_id,
                    exc,
                )
                auto_remove_error = "No se pudo completar la retirada automática."
            finally:
                if sanction_guard_acquired and sanction_guard is not None:
                    sanction_guard.release()

        if auto_remove_error:
            db.release_appeal_claim(self.appeal_id, interaction.guild_id)
            return await interaction.followup.send(
                f"❌ {auto_remove_error} La apelación sigue pendiente.",
                ephemeral=True,
            )

        if not appeal_finalized:
            try:
                finalized = db.finalize_claimed_appeal(
                    self.appeal_id, interaction.guild_id, "ACCEPTED"
                )
            except Exception as exc:
                db.release_appeal_claim(self.appeal_id, interaction.guild_id)
                logger.warning("No se pudo finalizar apelación %s: %s", self.appeal_id, exc)
                return await interaction.followup.send(
                    "❌ No se pudo finalizar la apelación; vuelve a intentarlo.",
                    ephemeral=True,
                )
            if not finalized:
                db.release_appeal_claim(self.appeal_id, interaction.guild_id)
                return await interaction.followup.send(
                    "❌ La apelación cambió de estado durante el proceso.",
                    ephemeral=True,
                )

        if recipient and guild:
            embed = discord.Embed(
                title="✅ Apelación Aceptada",
                description=f"Tu apelación en **{guild.name}** ha sido aceptada.",
                color=discord.Color.green()
            )
            embed.add_field(name="Sanción Original", value=self.action_type)
            embed.add_field(name="Mensaje del Moderador", value=self.mod_reason.value, inline=False)
            try:
                await recipient.send(embed=embed)
            except discord.Forbidden:
                logger.info("No se pudo notificar por DM la apelación aceptada a %s", self.user_id)
            except discord.HTTPException as exc:
                logger.warning("Error notificando apelación aceptada a %s: %s", self.user_id, exc)

        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0].copy()
            embed.color = discord.Color.green()
            embed.title = "✅ Apelación Aceptada"
            embed.add_field(name="Moderador", value=current_actor.mention, inline=False)
            embed.add_field(name="Motivo de Aceptación", value=self.mod_reason.value, inline=False)
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send("Apelación aceptada.", ephemeral=True)


class AppealDenyModal(discord.ui.Modal, title="Denegar Apelación"):
    mod_reason = discord.ui.TextInput(
        label="Mensaje para el usuario",
        style=discord.TextStyle.paragraph,
        placeholder="Ej: Tu apelación ha sido denegada porque...",
        required=True
    )

    def __init__(self, bot: commands.Bot, appeal_id: int, user_id: int, action_type: str):
        super().__init__()
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        if not _appeal_staff_allowed(self.bot, interaction):
            return await interaction.response.send_message(
                "❌ Ya no tienes permisos para gestionar apelaciones.", ephemeral=True
            )
        appeal = _pending_appeal(self.bot, interaction, self.appeal_id)
        if not appeal:
            return await interaction.response.send_message(
                "❌ La apelación no existe, no pertenece a este servidor o ya fue resuelta.",
                ephemeral=True,
            )
        self.user_id = int(appeal["user_id"])
        self.action_type = str(appeal["action_type"]).upper()
        await interaction.response.defer(ephemeral=True)
        current_actor = await _fresh_appeal_staff_member(self.bot, interaction)
        appeal = _pending_appeal(self.bot, interaction, self.appeal_id)
        if current_actor is None or not appeal:
            return await interaction.followup.send(
                "❌ Tus permisos cambiaron o la apelación ya no está pendiente.",
                ephemeral=True,
            )
        self.user_id = int(appeal["user_id"])
        self.action_type = str(appeal["action_type"]).upper()
        db = getattr(self.bot, 'db')
        if not db.claim_pending_appeal(self.appeal_id, interaction.guild_id):
            return await interaction.followup.send(
                "❌ La apelación ya está siendo procesada o fue resuelta.",
                ephemeral=True,
            )
        try:
            finalized = db.finalize_claimed_appeal(
                self.appeal_id, interaction.guild_id, "DENIED"
            )
        except Exception as exc:
            db.release_appeal_claim(self.appeal_id, interaction.guild_id)
            logger.warning("No se pudo finalizar apelación %s: %s", self.appeal_id, exc)
            return await interaction.followup.send(
                "❌ No se pudo finalizar la apelación; vuelve a intentarlo.",
                ephemeral=True,
            )
        if not finalized:
            db.release_appeal_claim(self.appeal_id, interaction.guild_id)
            return await interaction.followup.send(
                "❌ La apelación cambió de estado durante el proceso.",
                ephemeral=True,
            )
        guild = interaction.guild
        member = guild.get_member(self.user_id) if guild else None
        recipient = member or self.bot.get_user(self.user_id)

        if recipient and guild:
            embed = discord.Embed(
                title="❌ Apelación Denegada",
                description=f"Tu apelación en **{guild.name}** ha sido denegada.",
                color=discord.Color.red()
            )
            embed.add_field(name="Sanción Original", value=self.action_type)
            embed.add_field(name="Mensaje del Moderador", value=self.mod_reason.value, inline=False)
            try:
                await recipient.send(embed=embed)
            except discord.Forbidden:
                logger.info("No se pudo notificar por DM la apelación denegada a %s", self.user_id)
            except discord.HTTPException as exc:
                logger.warning("Error notificando apelación denegada a %s: %s", self.user_id, exc)

        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0].copy()
            embed.color = discord.Color.red()
            embed.title = "❌ Apelación Denegada"
            embed.add_field(name="Moderador", value=current_actor.mention, inline=False)
            embed.add_field(name="Motivo de Denegación", value=self.mod_reason.value, inline=False)
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send("Apelación denegada.", ephemeral=True)


class AppealModView(discord.ui.View):
    def __init__(self, bot: commands.Bot, appeal_id: int = 0, user_id: int = 0, action_type: str = "UNKNOWN"):
        super().__init__(timeout=None)
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if _appeal_staff_allowed(self.bot, interaction):
            return True
        await interaction.response.send_message(
            "❌ No tienes permisos actuales para gestionar apelaciones.", ephemeral=True
        )
        return False

    @staticmethod
    def _parse_embed(interaction: discord.Interaction) -> tuple:
        """Extrae (appeal_id, user_id, action_type) del embed del mensaje."""
        appeal_id, user_id, action_type = 0, 0, "UNKNOWN"
        if not (interaction.message and interaction.message.embeds):
            return appeal_id, user_id, action_type
        embed = interaction.message.embeds[0]
        # Footer: "ID Apelación: N"
        if embed.footer and embed.footer.text:
            try:
                appeal_id = int(embed.footer.text.split("ID Apelación:")[-1].strip())
            except (ValueError, IndexError):
                pass
        for field in embed.fields:
            if field.name == "Sanción":
                action_type = field.value or "UNKNOWN"
            elif field.name == "Usuario" and field.value:
                # Formato: "mención (`ID`)"
                try:
                    user_id = int(field.value.split("`")[1])
                except (IndexError, ValueError):
                    pass
        return appeal_id, user_id, action_type

    @discord.ui.button(label="Aceptar", style=discord.ButtonStyle.success, emoji="✅", custom_id="appeal_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        appeal_id, user_id, action_type = self._parse_embed(interaction)
        if not appeal_id:
            appeal_id, user_id, action_type = self.appeal_id, self.user_id, self.action_type
        await interaction.response.send_modal(AppealAcceptModal(self.bot, appeal_id, user_id, action_type))

    @discord.ui.button(label="Denegar", style=discord.ButtonStyle.danger, emoji="❌", custom_id="appeal_deny")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        appeal_id, user_id, action_type = self._parse_embed(interaction)
        if not appeal_id:
            appeal_id, user_id, action_type = self.appeal_id, self.user_id, self.action_type
        await interaction.response.send_modal(AppealDenyModal(self.bot, appeal_id, user_id, action_type))



async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    # Registrar AppealModView como vista persistente (botones con custom_id fijos)
    # Los datos del appeal se extraen del embed al interactuar
    bot.add_view(AppealModView(bot))
