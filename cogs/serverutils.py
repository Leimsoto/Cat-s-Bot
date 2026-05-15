"""
cogs/serverutils.py
───────────────────
Utilidades de servidor: información y logs en tiempo real.

Comandos slash:
  /ping        – Latencia del bot
  /botinfo     – Información general del bot
  /avatar      – Avatar de un usuario
  /servericon  – Icono del servidor
  /serverinfo  – Información detallada del servidor
  /serverlogs  – Configuración de captura de logs en tiempo real

Nota: la configuración global de roles/canales (antes /config) vive en el
panel web (Moderación + páginas por módulo).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("ServerUtils")

DEFAULT_LOG_EVENTS = {
    "message_delete": True,
    "message_edit": True,
    "member_join": True,
    "member_leave": True,
    "voice_join_leave": True,
    "role_changes": True,
    "nickname_changes": True,
    "channel_updates": True,
    "message_send": False,
    "reactions": False,
}


class ServerUtils(commands.Cog):
    """Información del servidor, configuración global y sistema de logs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    def _get_log_events(self, guild_id: int) -> dict:
        cfg = self.db.get_server_config(guild_id)
        events = dict(DEFAULT_LOG_EVENTS)
        if cfg.get("log_events"):
            try:
                raw_events = json.loads(cfg["log_events"])
                if isinstance(raw_events, dict):
                    events.update({key: bool(value) for key, value in raw_events.items() if key in DEFAULT_LOG_EVENTS})
                else:
                    logger.warning("log_events inválido en guild %s: no es un objeto JSON", guild_id)
            except json.JSONDecodeError:
                logger.warning("log_events contiene JSON inválido en guild %s", guild_id)
        return events

    async def _send_server_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        cfg = self.db.get_server_config(guild.id)
        if not cfg.get("serverlog_enabled", 1):
            return

        ch_id = cfg.get("serverlog_channel")
        if not ch_id:
            return

        channel = guild.get_channel(ch_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Canal de serverlog inválido o no accesible en %s (%s)", guild.name, ch_id)
            return

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar serverlogs en %s", guild.name)
        except discord.HTTPException as exc:
            logger.warning("No se pudo enviar serverlog en %s: %s", guild.name, exc)

    # ─────────────────────────────────────────────────────────────────────
    # /ping, /botinfo, /avatar, /servericon
    # ─────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="Latencia del bot")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latencia API: `{ms}ms`")

    @app_commands.command(name="bot_info", description="Información general del bot")
    async def botinfo(self, interaction: discord.Interaction):
        delta = discord.utils.utcnow() - self.bot.start_time
        total_sec = int(delta.total_seconds())
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        uptime = f"{h}h {m}m {s}s"

        servers = len(self.bot.guilds)
        users = sum(g.member_count or 0 for g in self.bot.guilds)
        
        embed = discord.Embed(title="🤖 Info del Bot", color=discord.Color.blurple())
        embed.add_field(name="Latencia", value=f"`{round(self.bot.latency * 1000)} ms`")
        embed.add_field(name="Uptime", value=f"`{uptime}`")
        embed.add_field(name="Servidores", value=f"`{servers}`")
        embed.add_field(name="Usuarios", value=f"`{users}`")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Ver el avatar de un usuario")
    async def avatar(self, interaction: discord.Interaction, usuario: discord.User = None):
        target = usuario or interaction.user
        embed = discord.Embed(title=f"Avatar de {target.display_name}", color=discord.Color.blurple())
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="icono_servidor", description="Ver el icono del servidor")
    async def servericon(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.guild.icon:
            return await interaction.response.send_message("❌ Este servidor no tiene icono.", ephemeral=True)
        embed = discord.Embed(title=f"Icono de {interaction.guild.name}", color=discord.Color.blurple())
        embed.set_image(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────
    # /serverinfo
    # ─────────────────────────────────────────────────────────────────────

    @app_commands.command(name="servidor_info", description="Información detallada del servidor")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        if g is None:
            return await interaction.response.send_message("❌ Este comando solo puede usarse en servidores.", ephemeral=True)

        await interaction.response.defer()

        created = int(g.created_at.timestamp())
        online = sum(1 for m in g.members if m.status != discord.Status.offline)
        bots = sum(1 for m in g.members if m.bot)
        text_ch = len(g.text_channels)
        voice_ch = len(g.voice_channels)
        cats = len(g.categories)

        embed = discord.Embed(
            title=f"🏠 {g.name}",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)

        embed.add_field(name="🆔 ID", value=f"`{g.id}`", inline=True)
        embed.add_field(name="👑 Dueño", value=f"{g.owner.mention}" if g.owner else "—", inline=True)
        embed.add_field(name="📅 Creado", value=f"<t:{created}:R>", inline=True)
        embed.add_field(
            name=f"👥 Miembros ({g.member_count})",
            value=f"🟢 {online} en línea · 🤖 {bots} bots",
            inline=False,
        )
        embed.add_field(
            name=f"📺 Canales ({text_ch + voice_ch})",
            value=f"💬 {text_ch} texto · 🔊 {voice_ch} voz · 📁 {cats} categorías",
            inline=False,
        )
        embed.add_field(name="🏷️ Roles", value=f"`{len(g.roles) - 1}`", inline=True)
        embed.add_field(name="😀 Emojis", value=f"`{len(g.emojis)}`", inline=True)
        embed.add_field(name="🔒 Verificación", value=f"`{g.verification_level}`", inline=True)

        if g.premium_subscription_count:
            embed.add_field(
                name="💎 Boosts",
                value=f"`{g.premium_subscription_count}` (Nivel {g.premium_tier})",
                inline=True,
            )

        features = g.features[:8] if g.features else []
        if features:
            embed.add_field(
                name="✨ Características",
                value=", ".join(f.replace("_", " ").title() for f in features),
                inline=False,
            )

        embed.set_footer(text=f"Servidor ID: {g.id}")
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────
    # /serverlogs — Configuración de eventos
    # ─────────────────────────────────────────────────────────────────────

    @app_commands.command(name="servidor_logs", description="Configura los logs del servidor en tiempo real")
    @app_commands.checks.has_permissions(administrator=True)
    async def serverlogs(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Este comando solo puede usarse en servidores.", ephemeral=True)

        events = self._get_log_events(interaction.guild_id)
        srv = self.db.get_server_config(interaction.guild_id)
        embed = self._build_logs_embed(interaction.guild, srv, events)
        view = ServerLogsView(self, interaction.user.id, events)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _build_logs_embed(self, guild, srv, events):
        ch_id = srv.get("serverlog_channel")
        ch = guild.get_channel(ch_id) if ch_id else None

        embed = discord.Embed(
            title="📡 Configuración de Server Logs",
            description=f"Canal: {ch.mention if ch else '❌ No configurado'}",
            color=discord.Color.dark_gold(),
            timestamp=datetime.now(timezone.utc),
        )

        event_labels = {
            "message_delete": "🗑️ Mensajes eliminados",
            "message_edit": "✏️ Mensajes editados",
            "member_join": "📥 Miembros: unión",
            "member_leave": "📤 Miembros: salida",
            "voice_join_leave": "🔊 Voz: unión/salida",
            "role_changes": "🏷️ Cambios de roles",
            "nickname_changes": "📛 Cambios de nickname",
            "channel_updates": "📝 Cambios en canales",
            "message_send": "💬 Cada mensaje enviado",
            "reactions": "😀 Reacciones",
        }
        lines = []
        for key, label in event_labels.items():
            icon = "✅" if events.get(key, False) else "❌"
            lines.append(f"{icon} {label}")
        embed.add_field(name="Eventos activos", value="\n".join(lines), inline=False)
        embed.set_footer(text="Usa los botones para cambiar eventos")
        return embed

    # ─────────────────────────────────────────────────────────────────────
    # Listeners de logs en tiempo real
    # ─────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        events = self._get_log_events(message.guild.id)
        if not events.get("message_delete"):
            return
        embed = discord.Embed(
            title="🗑️ Mensaje eliminado",
            description=(
                f"**Canal:** {message.channel.mention} (`{message.channel.id}`)\n"
                f"**Autor:** {message.author.mention} (`{message.author.id}`)"
            ),
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        content = message.content or "[Sin contenido de texto]"
        if len(content) > 1024:
            content = content[:1021] + "..."
        embed.add_field(name="📝 Contenido", value=content, inline=False)

        # ── Multimedia / Archivos adjuntos ────────────────────────────
        if message.attachments:
            att_lines = []
            image_set = False
            for att in message.attachments:
                att_lines.append(f"[{att.filename}]({att.url}) ({att.content_type or 'desconocido'})")
                # Mostrar la primera imagen como imagen del embed
                if not image_set and att.content_type and att.content_type.startswith("image"):
                    embed.set_image(url=att.url)
                    image_set = True
            attachments_text = "\n".join(att_lines[:5])
            if len(attachments_text) > 1024:
                attachments_text = attachments_text[:1021] + "..."
            embed.add_field(
                name=f"📎 Archivos adjuntos ({len(message.attachments)})",
                value=attachments_text,
                inline=False,
            )

        # ── Embeds del mensaje ────────────────────────────────────────
        if message.embeds:
            embed.add_field(
                name="📋 Embeds",
                value=f"`{len(message.embeds)}` embed(s) incluido(s)",
                inline=True,
            )

        embed.set_footer(text=f"ID Mensaje: {message.id}")
        embed.set_thumbnail(url=message.author.display_avatar.url)
        await self._send_server_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        events = self._get_log_events(before.guild.id)
        if not events.get("message_edit"):
            return
        embed = discord.Embed(
            title="✏️ Mensaje editado",
            description=f"**Canal:** {before.channel.mention}\n**Autor:** {before.author.mention}\n[Ir al mensaje]({after.jump_url})",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        old = (before.content or "—")[:500]
        new = (after.content or "—")[:500]
        embed.add_field(name="Antes", value=old, inline=False)
        embed.add_field(name="Después", value=new, inline=False)
        embed.set_footer(text=f"ID: {before.id}")
        await self._send_server_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        events = self._get_log_events(member.guild.id)
        if not events.get("member_join"):
            return
        created = int(member.created_at.timestamp())
        embed = discord.Embed(
            title="📥 Miembro se unió",
            description=f"{member.mention} (`{member}`)",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Cuenta creada", value=f"<t:{created}:R>", inline=True)
        embed.add_field(name="Miembros totales", value=f"`{member.guild.member_count}`", inline=True)
        embed.set_footer(text=f"ID: {member.id}")
        await self._send_server_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        events = self._get_log_events(member.guild.id)
        if not events.get("member_leave"):
            return
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        embed = discord.Embed(
            title="📤 Miembro salió",
            description=f"{member.mention} (`{member}`)",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if roles:
            roles_text = ", ".join(roles[:10])
            if len(roles_text) > 1024:
                roles_text = roles_text[:1021] + "..."
            embed.add_field(name="Roles", value=roles_text, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        await self._send_server_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        events = self._get_log_events(member.guild.id)
        if not events.get("voice_join_leave"):
            return
        if before.channel == after.channel:
            return
        if after.channel and not before.channel:
            embed = discord.Embed(
                title="🔊 Unión a canal de voz",
                description=(
                    f"**Usuario:** {member.mention} (`{member.id}`)\n"
                    f"**Canal:** {after.channel.mention} (`{after.channel.id}`)"
                ),
                color=discord.Color.green(), timestamp=datetime.now(timezone.utc),
            )
        elif before.channel and not after.channel:
            embed = discord.Embed(
                title="🔇 Salida de canal de voz",
                description=(
                    f"**Usuario:** {member.mention} (`{member.id}`)\n"
                    f"**Canal:** {before.channel.mention} (`{before.channel.id}`)"
                ),
                color=discord.Color.orange(), timestamp=datetime.now(timezone.utc),
            )
        else:
            embed = discord.Embed(
                title="🔀 Cambio de canal de voz",
                description=(
                    f"**Usuario:** {member.mention} (`{member.id}`)\n"
                    f"**De:** {before.channel.mention} (`{before.channel.id}`)\n"
                    f"**A:** {after.channel.mention} (`{after.channel.id}`)"
                ),
                color=discord.Color.blue(), timestamp=datetime.now(timezone.utc),
            )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID Usuario: {member.id}")
        await self._send_server_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        events = self._get_log_events(before.guild.id)

        # Cambio de roles
        if events.get("role_changes") and before.roles != after.roles:
            added = set(after.roles) - set(before.roles)
            removed = set(before.roles) - set(after.roles)
            if added or removed:
                embed = discord.Embed(
                    title="🏷️ Cambio de roles",
                    description=f"**Usuario:** {after.mention} (`{after.id}`)",
                    color=discord.Color.purple(), timestamp=datetime.now(timezone.utc),
                )
                if added:
                    added_text = ", ".join(r.mention for r in added)
                    if len(added_text) > 1024:
                        added_text = added_text[:1021] + "..."
                    embed.add_field(name="➕ Añadidos", value=added_text, inline=False)
                if removed:
                    removed_text = ", ".join(r.mention for r in removed)
                    if len(removed_text) > 1024:
                        removed_text = removed_text[:1021] + "..."
                    embed.add_field(name="➖ Removidos", value=removed_text, inline=False)
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=f"ID Usuario: {after.id}")
                await self._send_server_log(before.guild, embed)

        # Cambio de nickname
        if events.get("nickname_changes") and before.nick != after.nick:
            embed = discord.Embed(
                title="📛 Cambio de nickname",
                description=f"**Usuario:** {after.mention} (`{after.id}`)",
                color=discord.Color.teal(), timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Antes", value=before.nick or before.name, inline=True)
            embed.add_field(name="Después", value=after.nick or after.name, inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text=f"ID Usuario: {after.id}")
            await self._send_server_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        """Detecta cambios de permisos, nombre o categoría en canales."""
        events = self._get_log_events(before.guild.id)
        if not events.get("channel_updates", True):
            return

        # Cambio de nombre
        if before.name != after.name:
            embed = discord.Embed(
                title="📝 Canal renombrado",
                description=(
                    f"**Canal:** {after.mention} (`{after.id}`)\n"
                    f"**Antes:** `#{before.name}`\n**Después:** `#{after.name}`"
                ),
                color=discord.Color.blue(), timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text=f"ID Canal: {after.id}")
            await self._send_server_log(before.guild, embed)

        # Cambio de permisos (overwrites)
        if before.overwrites != after.overwrites:
            embed = discord.Embed(
                title="🔐 Permisos de canal modificados",
                description=f"**Canal:** {after.mention} (`{after.id}`)",
                color=discord.Color.dark_gold(), timestamp=datetime.now(timezone.utc),
            )
            # Detectar qué target cambió
            all_targets = set(list(before.overwrites.keys()) + list(after.overwrites.keys()))
            changes = []
            for target in all_targets:
                old_ow = before.overwrites.get(target)
                new_ow = after.overwrites.get(target)
                if old_ow != new_ow:
                    target_name = target.mention if hasattr(target, 'mention') else str(target)
                    if not old_ow:
                        changes.append(f"➕ Permisos añadidos para {target_name}")
                    elif not new_ow:
                        changes.append(f"➖ Permisos removidos para {target_name}")
                    else:
                        changes.append(f"✏️ Permisos modificados para {target_name}")
            if changes:
                embed.add_field(name="Cambios", value="\n".join(changes[:10]), inline=False)
            embed.set_footer(text=f"ID Canal: {after.id}")
            await self._send_server_log(before.guild, embed)


# ── View para /serverlogs ─────────────────────────────────────────────────────

class ServerLogsView(discord.ui.View):
    def __init__(self, cog: ServerUtils, author_id: int, events: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.events = events
        self._add_toggles()

    def _add_toggles(self):
        """Crea un StringSelect con todos los eventos como opciones."""
        labels = {
            "message_delete": "🗑️ Mensajes eliminados",
            "message_edit": "✏️ Mensajes editados",
            "member_join": "📥 Miembros: unión",
            "member_leave": "📤 Miembros: salida",
            "voice_join_leave": "🔊 Voz: unión/salida",
            "role_changes": "🏷️ Cambios de roles",
            "nickname_changes": "📛 Cambios de nickname",
            "channel_updates": "📝 Cambios en canales",
            "message_send": "💬 Cada mensaje enviado",
            "reactions": "😀 Reacciones",
        }
        options = []
        for key, label in labels.items():
            is_on = self.events.get(key, False)
            options.append(discord.SelectOption(
                label=label, value=key,
                description="Activado" if is_on else "Desactivado",
                default=is_on,
            ))
        select = discord.ui.Select(
            placeholder="Selecciona los eventos a activar",
            min_values=0, max_values=len(options), options=options,
        )
        select.callback = self._toggle_callback
        self.add_item(select)

    async def _toggle_callback(self, interaction: discord.Interaction):
        selected = set(interaction.data.get("values", []))
        for key in self.events:
            self.events[key] = key in selected
        self.cog.db.set_server_config(
            interaction.guild_id,
            log_events=json.dumps(self.events),
        )
        srv = self.cog.db.get_server_config(interaction.guild_id)
        embed = self.cog._build_logs_embed(interaction.guild, srv, self.events)

        self.clear_items()
        self._add_toggles()
        close_btn = discord.ui.Button(label="Cerrar", emoji="❌", style=discord.ButtonStyle.danger)
        close_btn.callback = self._close
        self.add_item(close_btn)

        await interaction.response.edit_message(embed=embed, view=self)

    async def _close(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="✅ Panel cerrado.", embed=None, view=None)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo quien abrió el panel.", ephemeral=True)
            return False
        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerUtils(bot))
