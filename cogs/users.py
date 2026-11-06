"""
cogs/users.py
─────────────
Gestión de usuarios.

Comandos slash:
  /addrole      – Añadir rol a usuario
  /removerole   – Quitar rol a usuario
  /roleinfo     – Información detallada de un rol
  /userinfo     – Información súper detallada de un usuario
  /usermessage  – Últimos N mensajes de un usuario (todos los canales)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs._role_safety import (
    safe_for_automatic_assignment,
    self_service_forbidden_role_ids,
)

logger = logging.getLogger("Users")


class Users(commands.Cog):
    """Gestión de usuarios: roles, información y mensajes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    def _member_has_user_perms(
        self,
        guild: discord.Guild,
        member: discord.Member,
        *,
        need_roles: bool = False,
    ) -> bool:
        member_guild = getattr(member, "guild", None)
        if member_guild is not None and getattr(member_guild, "id", None) != guild.id:
            return False
        if member.guild_permissions.administrator:
            return True
        if need_roles and member.guild_permissions.manage_roles:
            return True
        try:
            role_id = int(
                (self.db.get_server_config(guild.id) or {}).get("users_role_id")
                or 0
            )
        except Exception:
            return False
        return bool(role_id and any(role.id == role_id for role in member.roles))

    async def _check_user_perms(self, interaction: discord.Interaction, need_roles: bool = False) -> bool:
        """Verifica permisos del usuario según el módulo."""
        member = interaction.user
        guild = interaction.guild
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Este comando solo puede usarse dentro de un servidor.",
                ephemeral=True,
            )
            return False
        if self._member_has_user_perms(guild, member, need_roles=need_roles):
            return True

        perm = "Gestionar Roles" if need_roles else "el rol de usuarios configurado"
        await interaction.response.send_message(
            f"❌ Necesitas el permiso **{perm}** o ser administrador.",
            ephemeral=True,
        )
        return False

    async def _fresh_user_action_context(
        self,
        interaction: discord.Interaction,
        target_id: int,
        *,
        role_id: Optional[int] = None,
        for_nickname: bool = False,
    ) -> tuple[
        Optional[discord.Member],
        Optional[discord.Member],
        Optional[discord.Role],
        Optional[str],
    ]:
        """Revalida autorización y jerarquías por REST justo antes del efecto."""
        guild = interaction.guild
        if (
            guild is None
            or interaction.guild_id != guild.id
            or self.bot.user is None
        ):
            return None, None, None, "No pude verificar el servidor actual."

        try:
            target, actor, bot_member, live_roles, live_guild = await asyncio.gather(
                guild.fetch_member(int(target_id)),
                guild.fetch_member(interaction.user.id),
                guild.fetch_member(self.bot.user.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except discord.NotFound:
            return None, None, None, "El usuario o rol ya no está disponible."
        except (discord.Forbidden, discord.HTTPException):
            return None, None, None, "No pude verificar permisos y jerarquías actuales."
        if getattr(live_guild, "id", None) != guild.id:
            return None, None, None, "La identidad actual del servidor no coincide."

        roles_by_id = {int(role.id): role for role in live_roles}

        def current_role_state(member: discord.Member):
            role_ids = {guild.id}
            role_ids.update(int(value) for value in getattr(member, "_roles", ()))
            if any(value not in roles_by_id for value in role_ids):
                return None
            roles = [roles_by_id[value] for value in role_ids]
            permissions_value = 0
            for current_role in roles:
                permissions_value |= int(current_role.permissions.value)
            return discord.Permissions(permissions_value), max(roles), role_ids

        actor_state = current_role_state(actor)
        target_state = current_role_state(target)
        bot_state = current_role_state(bot_member)
        if actor_state is None or target_state is None or bot_state is None:
            return None, None, None, "No pude verificar la jerarquía completa de roles."

        actor_permissions, actor_top_role, actor_role_ids = actor_state
        target_permissions, target_top_role, _target_role_ids = target_state
        bot_permissions, bot_top_role, _bot_role_ids = bot_state
        owner_id = int(live_guild.owner_id)

        try:
            configured_role_id = int(
                (self.db.get_server_config(guild.id) or {}).get("users_role_id")
                or 0
            )
        except (AttributeError, TypeError, ValueError):
            return None, None, None, "No pude verificar el rol delegado actual."
        configured_role = roles_by_id.get(configured_role_id)
        delegated_access = bool(
            configured_role_id
            and configured_role_id in actor_role_ids
            and configured_role is not None
            and not configured_role.is_default()
            and not configured_role.managed
            and configured_role < bot_top_role
        )
        native_role_manager = bool(
            actor.id == owner_id
            or actor_permissions.administrator
            or actor_permissions.manage_roles
        )
        if not native_role_manager and not delegated_access:
            return None, None, None, "Tus permisos cambiaron; la operación fue cancelada."

        if target.id == owner_id:
            return None, None, None, "No puedes gestionar al dueño del servidor."
        if target_permissions.administrator and actor.id != owner_id:
            return None, None, None, "No puedes gestionar a un administrador protegido."
        if actor.id != owner_id and actor_top_role <= target_top_role:
            return None, None, None, "Tu rol no es suficientemente alto para gestionar a ese usuario."
        if bot_top_role <= target_top_role:
            return None, None, None, "Mi rol no es suficiente para gestionar a ese usuario."

        if for_nickname:
            if actor.id == target.id:
                return None, None, None, "No puedes cambiar tu propio apodo con este comando."
            if not (
                bot_permissions.administrator
                or bot_permissions.manage_nicknames
            ):
                return None, None, None, "Ya no tengo permiso para gestionar apodos."
            return actor, target, None, None

        role = roles_by_id.get(int(role_id or 0))
        if role is None:
            return None, None, None, "El rol ya no existe."
        if role.is_default():
            return None, None, None, "No puedes gestionar el rol @everyone."
        if role.managed:
            return None, None, None, "Ese rol es gestionado por una integración."
        if not (bot_permissions.administrator or bot_permissions.manage_roles):
            return None, None, None, "Ya no tengo permiso para gestionar roles."
        if role >= bot_top_role:
            return None, None, None, "No puedo gestionar un rol igual o superior al mío."
        if actor.id != owner_id and role >= actor_top_role:
            return None, None, None, "No puedes gestionar un rol igual o superior al tuyo."
        if not native_role_manager:
            forbidden_role_ids = self_service_forbidden_role_ids(self.db, guild.id)
            if forbidden_role_ids is None or not safe_for_automatic_assignment(
                role,
                bot_member,
                forbidden_role_ids=forbidden_role_ids,
            ):
                return None, None, None, "El rol delegado de usuarios no puede gestionar ese rol."
        return actor, target, role, None

    # ─────────────────────────────────────────────────────────────────────────
    # /addrole
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="asignar_rol", description="Añade un rol a un usuario")
    @app_commands.describe(usuario="Usuario al que añadir el rol", rol="Rol a añadir")
    async def addrole(
        self, interaction: discord.Interaction,
        usuario: discord.Member, rol: discord.Role,
    ):
        if not await self._check_user_perms(interaction, need_roles=True):
            return

        actor, current_target, current_role, err = await self._fresh_user_action_context(
            interaction, usuario.id, role_id=rol.id
        )
        if err or actor is None or current_target is None or current_role is None:
            return await interaction.response.send_message(
                f"❌ {err or 'No pude verificar la operación.'}", ephemeral=True
            )

        current_role_ids = {
            int(value) for value in getattr(current_target, "_roles", ())
        }
        if current_role.id in current_role_ids:
            return await interaction.response.send_message(
                f"⚠️ {current_target.mention} ya tiene el rol {current_role.mention}.", ephemeral=True
            )

        try:
            await current_target.add_roles(
                current_role, reason=f"Añadido por {actor}"
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para añadir rol %s a %s en %s", current_role.id, current_target.id, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos para añadir ese rol.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error añadiendo rol %s a %s en %s: %s", current_role.id, current_target.id, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo añadir el rol. Inténtalo de nuevo.",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="✅ Rol añadido",
            description=f"Se añadió {current_role.mention} a {current_target.mention}.",
            color=current_role.color if current_role.color.value else discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Ejecutado por {actor.display_name}")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /removerole
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="quitar_rol", description="Quita un rol de un usuario")
    @app_commands.describe(usuario="Usuario al que quitar el rol", rol="Rol a quitar")
    async def removerole(
        self, interaction: discord.Interaction,
        usuario: discord.Member, rol: discord.Role,
    ):
        if not await self._check_user_perms(interaction, need_roles=True):
            return

        actor, current_target, current_role, err = await self._fresh_user_action_context(
            interaction, usuario.id, role_id=rol.id
        )
        if err or actor is None or current_target is None or current_role is None:
            return await interaction.response.send_message(
                f"❌ {err or 'No pude verificar la operación.'}", ephemeral=True
            )

        current_role_ids = {
            int(value) for value in getattr(current_target, "_roles", ())
        }
        if current_role.id not in current_role_ids:
            return await interaction.response.send_message(
                f"⚠️ {current_target.mention} no tiene el rol {current_role.mention}.", ephemeral=True
            )

        try:
            await current_target.remove_roles(
                current_role, reason=f"Removido por {actor}"
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para quitar rol %s a %s en %s", current_role.id, current_target.id, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos para quitar ese rol.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error quitando rol %s a %s en %s: %s", current_role.id, current_target.id, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo quitar el rol. Inténtalo de nuevo.",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="✅ Rol removido",
            description=f"Se quitó {current_role.mention} de {current_target.mention}.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Ejecutado por {actor.display_name}")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /roleinfo
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="rol_info", description="Muestra información detallada de un rol")
    @app_commands.describe(rol="Rol a consultar")
    async def roleinfo(self, interaction: discord.Interaction, rol: discord.Role):
        members_with = len(rol.members)
        created = int(rol.created_at.timestamp())

        # Clasificar permisos
        admin_perms = []
        mod_perms = []
        general_perms = []
        for perm, value in rol.permissions:
            if not value:
                continue
            if perm in ("administrator", "manage_guild", "manage_roles", "manage_channels"):
                admin_perms.append(perm.replace("_", " ").title())
            elif perm in ("ban_members", "kick_members", "manage_messages",
                          "moderate_members", "mute_members", "manage_nicknames"):
                mod_perms.append(perm.replace("_", " ").title())
            else:
                general_perms.append(perm.replace("_", " ").title())

        embed = discord.Embed(
            title=f"📋 Información del Rol: {rol.name}",
            color=rol.color if rol.color.value else discord.Color.greyple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🆔 ID", value=f"`{rol.id}`", inline=True)
        embed.add_field(name="🎨 Color", value=f"`{rol.color}`", inline=True)
        embed.add_field(name="👥 Miembros", value=f"`{members_with}`", inline=True)
        embed.add_field(name="📊 Posición", value=f"`{rol.position}`", inline=True)
        embed.add_field(name="📢 Mencionable", value="✅" if rol.mentionable else "❌", inline=True)
        embed.add_field(name="🔰 Separado", value="✅" if rol.hoist else "❌", inline=True)
        embed.add_field(name="📅 Creado", value=f"<t:{created}:R>", inline=True)

        if admin_perms:
            embed.add_field(name="🛡️ Permisos Admin", value=", ".join(admin_perms[:10]), inline=False)
        if mod_perms:
            embed.add_field(name="🔨 Permisos Mod", value=", ".join(mod_perms[:10]), inline=False)
        if general_perms:
            # Limitar a 10 para no exceder límites
            text = ", ".join(general_perms[:10])
            if len(general_perms) > 10:
                text += f" +{len(general_perms) - 10} más"
            embed.add_field(name="📝 Permisos Generales", value=text, inline=False)

        if rol.icon:
            embed.set_thumbnail(url=rol.icon.url)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /userinfo
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="usuario_info", description="Información súper detallada de un usuario")
    @app_commands.describe(usuario="Usuario a consultar (por defecto tú mismo)")
    async def userinfo(
        self, interaction: discord.Interaction,
        usuario: Optional[discord.Member] = None,
    ):
        target = usuario or interaction.user
        if interaction.guild is None or not isinstance(target, discord.Member):
            return await interaction.response.send_message("❌ Este comando solo puede usarse en servidores.", ephemeral=True)

        await interaction.response.defer()

        created = int(target.created_at.timestamp())
        joined = int(target.joined_at.timestamp()) if target.joined_at else 0

        embed = discord.Embed(
            title=f"👤 Información de {target.display_name}",
            color=target.color if target.color.value else discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )

        # ── Identidad ─────────────────────────────────────────────────────
        embed.set_thumbnail(url=target.display_avatar.url)
        banner = getattr(target, "banner", None)
        if banner:
            embed.set_image(url=banner.url)

        embed.add_field(name="📛 Usuario", value=f"{target.mention}\n`{target}`", inline=True)
        embed.add_field(name="🆔 ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="🤖 Bot", value="✅" if target.bot else "❌", inline=True)

        # ── Fechas ────────────────────────────────────────────────────────
        embed.add_field(name="📅 Cuenta creada", value=f"<t:{created}:R>", inline=True)
        if joined:
            embed.add_field(name="📥 Se unió", value=f"<t:{joined}:R>", inline=True)

        # ── Boost ─────────────────────────────────────────────────────────
        if target.premium_since:
            boost_ts = int(target.premium_since.timestamp())
            embed.add_field(name="💎 Boost desde", value=f"<t:{boost_ts}:R>", inline=True)

        # ── Roles ─────────────────────────────────────────────────────────
        roles = [r.mention for r in reversed(target.roles) if r != interaction.guild.default_role]
        if roles:
            roles_text = ", ".join(roles[:15])
            if len(roles) > 15:
                roles_text += f" +{len(roles) - 15} más"
            embed.add_field(name=f"🏷️ Roles ({len(roles)})", value=roles_text, inline=False)

        # ── Actividad ─────────────────────────────────────────────────────
        status_map = {
            discord.Status.online: "🟢 En línea",
            discord.Status.idle: "🟡 Ausente",
            discord.Status.dnd: "🔴 No molestar",
            discord.Status.offline: "⚫ Desconectado",
        }
        embed.add_field(
            name="📡 Estado",
            value=status_map.get(target.status, "Desconocido"),
            inline=True,
        )

        if target.activity:
            act = target.activity
            if isinstance(act, discord.Spotify):
                act_text = f"🎵 Escuchando: {act.title} — {act.artist}"
            elif isinstance(act, discord.Game):
                act_text = f"🎮 Jugando: {act.name}"
            elif isinstance(act, discord.Streaming):
                act_text = f"📺 Streaming: {act.name}"
            elif isinstance(act, discord.CustomActivity):
                act_text = f"💬 {act.name or '—'}"
            else:
                act_text = str(act.name) if act.name else "—"
            embed.add_field(name="🎯 Actividad", value=act_text, inline=True)

        # ── Dispositivos ──────────────────────────────────────────────────
        devices = []
        if target.desktop_status != discord.Status.offline:
            devices.append("🖥️ PC")
        if target.mobile_status != discord.Status.offline:
            devices.append("📱 Móvil")
        if target.web_status != discord.Status.offline:
            devices.append("🌐 Web")
        if devices:
            embed.add_field(name="📲 Dispositivos", value=" · ".join(devices), inline=True)

        # ── Moderación (datos de DB) ──────────────────────────────────────
        user_record = self.db.get_user(target.id, interaction.guild_id)
        summary = self.db.get_user_action_summary(target.id, interaction.guild_id)

        mod_lines = [
            f"⚠️ Warns actuales: **{user_record['warns']}**",
            f"🔇 Mutes recibidos: **{summary.get('MUTE', 0)}**",
            f"👢 Kicks recibidos: **{summary.get('KICK', 0)}**",
            f"🔨 Bans recibidos: **{summary.get('BAN', 0)}**",
        ]
        if user_record.get("mute_start"):
            mod_lines.append("🔇 **Actualmente muteado**")

        embed.add_field(name="🛡️ Historial de Moderación", value="\n".join(mod_lines), inline=False)

        # ── Permisos clave ────────────────────────────────────────────────
        key_perms = []
        if target.guild_permissions.administrator:
            key_perms.append("👑 Administrador")
        if target.guild_permissions.manage_guild:
            key_perms.append("⚙️ Gestionar Servidor")
        if target.guild_permissions.ban_members:
            key_perms.append("🔨 Banear")
        if target.guild_permissions.kick_members:
            key_perms.append("👢 Expulsar")
        if target.guild_permissions.manage_messages:
            key_perms.append("📝 Gestionar Msgs")
        if key_perms:
            embed.add_field(name="🔑 Permisos Clave", value=" · ".join(key_perms), inline=False)

        embed.set_footer(text=f"ID: {target.id}")
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /nick
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="apodo", description="Cambia el apodo/nickname de un usuario")
    @app_commands.describe(
        usuario="Usuario al que cambiar el apodo",
        nickname="Nuevo apodo (déjalo vacío para resetear)",
    )
    async def nick(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        nickname: Optional[str] = None,
    ):
        if not await self._check_user_perms(interaction, need_roles=True):
            return

        actor, current_target, _role, err = await self._fresh_user_action_context(
            interaction, usuario.id, for_nickname=True
        )
        if err or actor is None or current_target is None:
            return await interaction.response.send_message(
                f"❌ {err or 'No pude verificar la operación.'}", ephemeral=True
            )

        try:
            await current_target.edit(nick=nickname, reason=f"Nick cambiado por {actor}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ No tengo permisos para cambiar ese apodo.", ephemeral=True
            )
        except discord.HTTPException as exc:
            return await interaction.response.send_message(
                f"❌ Error cambiando el apodo: {exc}", ephemeral=True
            )

        if nickname:
            embed = discord.Embed(
                title="✅ Apodo cambiado",
                description=f"El apodo de {current_target.mention} ahora es **{nickname}**.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="✅ Apodo reseteado",
                description=f"El apodo de {current_target.mention} ha sido reseteado.",
                color=discord.Color.green(),
            )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /usermessage
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="usermessage",
        description="Muestra los últimos N mensajes de un usuario (busca en todos los canales)",
    )
    @app_commands.describe(
        usuario="Usuario a consultar",
        cantidad="Cantidad de mensajes (1-50)",
    )
    async def usermessage(
        self, interaction: discord.Interaction,
        usuario: discord.Member,
        cantidad: app_commands.Range[int, 1, 50] = 10,
    ):
        if not await self._check_user_perms(interaction):
            return

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("❌ Este comando solo puede usarse en servidores.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        all_messages = []
        scan_limit = max(cantidad * 3, 100)
        bot_member = guild.me or guild.get_member(self.bot.user.id)

        if bot_member is None:
            return await interaction.followup.send(
                "❌ No pude verificar mis permisos en este servidor.",
                ephemeral=True,
            )

        for channel in guild.text_channels:
            try:
                bot_perms = channel.permissions_for(bot_member)
                actor_perms = channel.permissions_for(interaction.user)
                if not (
                    bot_perms.view_channel
                    and bot_perms.read_message_history
                    and actor_perms.view_channel
                    and actor_perms.read_message_history
                ):
                    continue

                async for msg in channel.history(limit=scan_limit):
                    if msg.author.id == usuario.id:
                        all_messages.append(msg)
            except discord.Forbidden:
                logger.debug("Sin permisos para leer historial en canal %s", channel.id)
            except discord.HTTPException as exc:
                logger.debug("Error leyendo historial en canal %s: %s", channel.id, exc)

        try:
            current_actor = await guild.fetch_member(interaction.user.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            current_actor = None
        if current_actor is None or not self._member_has_user_perms(guild, current_actor):
            return await interaction.followup.send(
                "❌ Tus permisos cambiaron mientras se consultaba el historial.",
                ephemeral=True,
            )
        all_messages = [
            msg
            for msg in all_messages
            if (
                (perms := msg.channel.permissions_for(current_actor)).view_channel
                and perms.read_message_history
            )
        ]

        if not all_messages:
            return await interaction.followup.send(
                f"❌ No se encontraron mensajes de {usuario.mention}.", ephemeral=True,
            )

        # Ordenar TODOS por fecha descendente y tomar los N más recientes
        all_messages.sort(key=lambda m: m.created_at, reverse=True)
        messages = all_messages[:cantidad]

        # Construir páginas
        pages = []
        page_channel_ids = []
        current_page = []
        current_channel_ids = set()
        current_len = 0

        for msg in messages:
            ts = int(msg.created_at.timestamp())
            content = msg.content or "[Contenido multimedia/embed]"
            if len(content) > 100:
                content = content[:100] + "..."
            line = f"**#{msg.channel.name}** — <t:{ts}:f>\n> {content}\n"

            if current_len + len(line) > 1800:
                pages.append("\n".join(current_page))
                page_channel_ids.append(set(current_channel_ids))
                current_page = [line]
                current_channel_ids = {msg.channel.id}
                current_len = len(line)
            else:
                current_page.append(line)
                current_channel_ids.add(msg.channel.id)
                current_len += len(line)

        if current_page:
            pages.append("\n".join(current_page))
            page_channel_ids.append(set(current_channel_ids))

        if len(pages) == 1:
            embed = discord.Embed(
                title=f"📨 Últimos {len(messages)} mensajes de {usuario.display_name}",
                description=pages[0],
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text=f"Total encontrados: {len(messages)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # Paginación
            view = MessagePaginatorView(
                pages,
                usuario,
                interaction.user.id,
                cog=self,
                guild_id=guild.id,
                page_channel_ids=page_channel_ids,
            )
            embed = view.build_embed(0)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class MessagePaginatorView(discord.ui.View):
    """Paginador para /usermessage."""

    def __init__(
        self,
        pages: list,
        target: discord.Member,
        author_id: int,
        *,
        cog: Optional[Users] = None,
        guild_id: Optional[int] = None,
        page_channel_ids: Optional[list[set[int]]] = None,
    ):
        super().__init__(timeout=120)
        self.pages = pages
        self.target = target
        self.author_id = author_id
        self.cog = cog
        self.guild_id = guild_id
        self.page_channel_ids = page_channel_ids or [set() for _ in pages]
        self.current = 0

    def build_embed(self, page: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"📨 Mensajes de {self.target.display_name}",
            description=self.pages[page],
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Página {page + 1}/{len(self.pages)}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo quien ejecutó el comando puede paginar.", ephemeral=True)
            return False
        if interaction.guild_id != self.guild_id or self.cog is None:
            await interaction.response.send_message("❌ Este paginador ya no es válido.", ephemeral=True)
            return False
        return True

    async def _authorize_page(self, interaction: discord.Interaction, page: int) -> bool:
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id or self.cog is None:
            await interaction.response.send_message("❌ Este paginador ya no es válido.", ephemeral=True)
            return False
        try:
            member = await guild.fetch_member(self.author_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            member = None
        if member is None or not self.cog._member_has_user_perms(guild, member):
            await interaction.response.send_message(
                "❌ Ya no tienes permisos para consultar este historial.", ephemeral=True
            )
            return False
        for channel_id in self.page_channel_ids[page]:
            channel = guild.get_channel(channel_id)
            if channel is None:
                await interaction.response.send_message(
                    "❌ Ya no puedes acceder a uno de los canales de esta página.", ephemeral=True
                )
                return False
            permissions = channel.permissions_for(member)
            if not (permissions.view_channel and permissions.read_message_history):
                await interaction.response.send_message(
                    "❌ Ya no puedes acceder a uno de los canales de esta página.", ephemeral=True
                )
                return False
        return True

    @discord.ui.button(label="◀️ Anterior", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = max(0, self.current - 1)
        if not await self._authorize_page(interaction, page):
            return
        self.current = page
        await interaction.response.edit_message(embed=self.build_embed(self.current), view=self)

    @discord.ui.button(label="▶️ Siguiente", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = min(len(self.pages) - 1, self.current + 1)
        if not await self._authorize_page(interaction, page):
            return
        self.current = page
        await interaction.response.edit_message(embed=self.build_embed(self.current), view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Users(bot))
