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

import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("Users")


class Users(commands.Cog):
    """Gestión de usuarios: roles, información y mensajes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    def _validate_role_action(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        rol: discord.Role,
    ) -> Optional[str]:
        guild = interaction.guild
        actor = interaction.user

        if guild is None or not isinstance(actor, discord.Member):
            return "Este comando solo puede usarse dentro de un servidor."
        if rol == guild.default_role:
            return "No puedes gestionar el rol @everyone."
        if rol.managed:
            return "Ese rol es gestionado por una integración y no puede modificarse manualmente."

        bot_member = guild.me or guild.get_member(self.bot.user.id)
        if bot_member is None:
            return "No pude verificar mi jerarquía de roles."
        if rol >= bot_member.top_role:
            return "No puedo gestionar un rol igual o superior al mío."
        if bot_member.top_role <= usuario.top_role:
            return "Mi rol no es suficiente para gestionar a ese usuario."

        if actor.id != guild.owner_id and rol >= actor.top_role:
            return "No puedes gestionar un rol igual o superior al tuyo."
        if actor.id != guild.owner_id and actor.top_role <= usuario.top_role:
            return "Tu rol no es suficientemente alto para gestionar a ese usuario."

        return None

    async def _check_user_perms(self, interaction: discord.Interaction, need_roles: bool = False) -> bool:
        """Verifica permisos del usuario según el módulo."""
        member = interaction.user
        if interaction.guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Este comando solo puede usarse dentro de un servidor.",
                ephemeral=True,
            )
            return False

        if member.guild_permissions.administrator:
            return True
        if need_roles and member.guild_permissions.manage_roles:
            return True

        srv_cfg = self.db.get_server_config(interaction.guild_id)
        role_id = srv_cfg.get("users_role_id")
        if role_id and any(r.id == role_id for r in member.roles):
            return True

        perm = "Gestionar Roles" if need_roles else "el rol de usuarios configurado"
        await interaction.response.send_message(
            f"❌ Necesitas el permiso **{perm}** o ser administrador.",
            ephemeral=True,
        )
        return False

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

        if rol in usuario.roles:
            return await interaction.response.send_message(
                f"⚠️ {usuario.mention} ya tiene el rol {rol.mention}.", ephemeral=True
            )

        err = self._validate_role_action(interaction, usuario, rol)
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        try:
            await usuario.add_roles(rol, reason=f"Añadido por {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para añadir rol %s a %s en %s", rol.id, usuario.id, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos para añadir ese rol.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error añadiendo rol %s a %s en %s: %s", rol.id, usuario.id, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo añadir el rol. Inténtalo de nuevo.",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="✅ Rol añadido",
            description=f"Se añadió {rol.mention} a {usuario.mention}.",
            color=rol.color if rol.color.value else discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Ejecutado por {interaction.user.display_name}")
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

        if rol not in usuario.roles:
            return await interaction.response.send_message(
                f"⚠️ {usuario.mention} no tiene el rol {rol.mention}.", ephemeral=True
            )

        err = self._validate_role_action(interaction, usuario, rol)
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        try:
            await usuario.remove_roles(rol, reason=f"Removido por {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para quitar rol %s a %s en %s", rol.id, usuario.id, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos para quitar ese rol.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error quitando rol %s a %s en %s: %s", rol.id, usuario.id, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo quitar el rol. Inténtalo de nuevo.",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="✅ Rol removido",
            description=f"Se quitó {rol.mention} de {usuario.mention}.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Ejecutado por {interaction.user.display_name}")
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

        if not interaction.guild.me.guild_permissions.manage_nicknames:
            return await interaction.response.send_message(
                "❌ No tengo permisos para gestionar apodos.", ephemeral=True
            )

        if usuario.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "❌ No puedo cambiar el apodo a alguien con un rol igual o superior al mío.",
                ephemeral=True,
            )

        if usuario.id != interaction.guild.owner_id and usuario.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                "❌ No puedes cambiar el apodo a alguien con un rol igual o superior al tuyo.",
                ephemeral=True,
            )

        try:
            await usuario.edit(nick=nickname, reason=f"Nick cambiado por {interaction.user}")
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
                description=f"El apodo de {usuario.mention} ahora es **{nickname}**.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="✅ Apodo reseteado",
                description=f"El apodo de {usuario.mention} ha sido reseteado.",
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
                perms = channel.permissions_for(bot_member)
                if not perms.view_channel or not perms.read_message_history:
                    continue

                async for msg in channel.history(limit=scan_limit):
                    if msg.author.id == usuario.id:
                        all_messages.append(msg)
            except discord.Forbidden:
                logger.debug("Sin permisos para leer historial en canal %s", channel.id)
            except discord.HTTPException as exc:
                logger.debug("Error leyendo historial en canal %s: %s", channel.id, exc)

        if not all_messages:
            return await interaction.followup.send(
                f"❌ No se encontraron mensajes de {usuario.mention}.", ephemeral=True,
            )

        # Ordenar TODOS por fecha descendente y tomar los N más recientes
        all_messages.sort(key=lambda m: m.created_at, reverse=True)
        messages = all_messages[:cantidad]

        # Construir páginas
        pages = []
        current_page = []
        current_len = 0

        for msg in messages:
            ts = int(msg.created_at.timestamp())
            content = msg.content or "[Contenido multimedia/embed]"
            if len(content) > 100:
                content = content[:100] + "..."
            line = f"**#{msg.channel.name}** — <t:{ts}:f>\n> {content}\n"

            if current_len + len(line) > 1800:
                pages.append("\n".join(current_page))
                current_page = [line]
                current_len = len(line)
            else:
                current_page.append(line)
                current_len += len(line)

        if current_page:
            pages.append("\n".join(current_page))

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
            view = MessagePaginatorView(pages, usuario, interaction.user.id)
            embed = view.build_embed(0)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class MessagePaginatorView(discord.ui.View):
    """Paginador para /usermessage."""

    def __init__(self, pages: list, target: discord.Member, author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.target = target
        self.author_id = author_id
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
        return True

    @discord.ui.button(label="◀️ Anterior", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current > 0:
            self.current -= 1
        await interaction.response.edit_message(embed=self.build_embed(self.current), view=self)

    @discord.ui.button(label="▶️ Siguiente", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current < len(self.pages) - 1:
            self.current += 1
        await interaction.response.edit_message(embed=self.build_embed(self.current), view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Users(bot))
