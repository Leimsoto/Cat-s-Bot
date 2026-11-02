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

from cogs.logging import Logging

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
    "audit_events": True,
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
        raw = cfg.get("log_events")
        try:
            raw = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            raw = None
        aliases = {"role_changes": "role_change", "channel_updates": "channel_update",
                   "voice_join_leave": "voice_state_update"}
        events = {key: Logging._event_enabled(raw, aliases.get(key, key))
                  for key in DEFAULT_LOG_EVENTS}
        if raw is None or raw == {}:
            events.update(DEFAULT_LOG_EVENTS)
        return events

    def _nearby_messageable_channel(self, guild: discord.Guild, channel_id: int):
        """Encuentra un único canal enviable cercano a un snowflake redondeado por JS."""
        candidates = []
        for channel in getattr(guild, "channels", []):
            try:
                candidate_id = int(getattr(channel, "id"))
            except (TypeError, ValueError):
                continue
            if callable(getattr(channel, "send", None)) and abs(candidate_id - int(channel_id)) <= 4096:
                candidates.append(channel)
        return candidates[0] if len(candidates) == 1 else None

    async def _resolve_serverlog_channel(self, guild: discord.Guild, raw_channel_id):
        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            return None, raw_channel_id, "invalid_channel_id"

        channel = guild.get_channel(channel_id)
        if callable(getattr(channel, "send", None)):
            return channel, int(channel.id), None

        repaired = self._nearby_messageable_channel(guild, channel_id)
        if repaired is not None:
            logger.warning(
                "serverlog_channel redondeado reparado en %s: %s -> %s",
                guild.name,
                channel_id,
                repaired.id,
            )
            try:
                self.db.set_server_config(guild.id, serverlog_channel=int(repaired.id))
            except Exception:
                logger.debug("No se pudo persistir serverlog_channel reparado", exc_info=True)
            return repaired, int(repaired.id), None

        try:
            fetched = await guild.fetch_channel(channel_id)
            if callable(getattr(fetched, "send", None)):
                return fetched, int(getattr(fetched, "id", channel_id)), None
            return fetched, channel_id, "target_is_not_messageable"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            return None, channel_id, str(exc)

    async def _send_server_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        cfg = self.db.get_server_config(guild.id)
        if not cfg.get("serverlog_enabled", 1):
            return

        ch_id = cfg.get("serverlog_channel")
        if not ch_id:
            return

        channel, resolved_ch_id, resolve_error = await self._resolve_serverlog_channel(guild, ch_id)
        send = getattr(channel, "send", None)
        if channel is None or not callable(send):
            logger.warning("Canal de serverlog inválido o no accesible en %s (%s): %s", guild.name, ch_id, resolve_error)
            self._enqueue_serverlog_outbox(guild, embed, resolve_error or "channel_unavailable", resolved_ch_id or ch_id)
            return

        try:
            from cogs._managed_messages import send_managed
            await send_managed(self.bot, guild.id, "serverutils", send, embed=embed)
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar serverlogs en %s", guild.name)
            self._enqueue_serverlog_outbox(guild, embed, "missing_send_messages", resolved_ch_id)
        except discord.HTTPException as exc:
            logger.warning("No se pudo enviar serverlog en %s: %s", guild.name, exc)
            self._enqueue_serverlog_outbox(guild, embed, str(exc), resolved_ch_id)

    def _enqueue_serverlog_outbox(self, guild: discord.Guild, embed: discord.Embed, error: str, channel_id=None) -> None:
        try:
            ch_id = channel_id
            if ch_id is None:
                cfg = self.db.get_server_config(guild.id)
                ch_id = cfg.get("serverlog_channel")
            if not ch_id or not hasattr(self.db, "enqueue_log_outbox"):
                return
            self.db.enqueue_log_outbox(
                guild.id,
                "serverlog",
                {
                    "embed": embed.to_dict(),
                    "source": "serverutils_cog",
                    "last_error": (error or "")[:500],
                },
                channel_id=int(ch_id),
            )
        except Exception as exc:
            logger.warning("No se pudo encolar serverlog fallido en %s: %s", guild.name, exc)

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
        view = ServerLogsView(self, interaction.user.id, interaction.guild_id, events)
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
            "role_changes": "🏷️ Roles: miembros y definición",
            "nickname_changes": "📛 Cambios de apodo",
            "channel_updates": "📝 Canales y categorías (ajustes y permisos)",
            "audit_events": "📋 Auditoría administrativa adicional",
            "message_send": "💬 Cada mensaje enviado",
            "reactions": "😀 Reacciones",
        }
        lines = []
        for key, label in event_labels.items():
            icon = "✅" if events.get(key, False) else "❌"
            lines.append(f"{icon} {label}")
        embed.add_field(name="Eventos activos", value="\n".join(lines), inline=False)
        embed.set_footer(text="Auditoría: requiere Ver registro de auditoría. Sin historial offline; contenido anterior sin caché no disponible.")
        return embed

    # ─────────────────────────────────────────────────────────────────────
    # Listeners de logs en tiempo real
    # ─────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        # `cogs.logging` es el dueño único de logs de mensajes. Mantener este
        # listener como no-op evita duplicados con distinto formato.
        return

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # `cogs.logging` es el dueño único de logs de mensajes. Mantener este
        # listener como no-op evita duplicados con distinto formato.
        return

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
        # `cogs.logging` es el dueño único de logs de voz.
        return

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # `cogs.logging` es el dueño único de cambios de roles/nickname.
        return

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        # `cogs.logging` es el dueño único de cambios de canales.
        return


# ── View para /serverlogs ─────────────────────────────────────────────────────

class ServerLogsView(discord.ui.View):
    def __init__(self, cog: ServerUtils, author_id: int, guild_id: int, events: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.events = events
        self._add_toggles()

    async def _authorized(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("❌ Solo quien abrió el panel.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Debes seguir siendo administrador para configurar los logs.", ephemeral=True
            )
            return False
        return True

    def _add_toggles(self):
        """Crea un StringSelect con todos los eventos como opciones."""
        labels = {
            "message_delete": "🗑️ Mensajes eliminados",
            "message_edit": "✏️ Mensajes editados",
            "member_join": "📥 Miembros: unión",
            "member_leave": "📤 Miembros: salida",
            "voice_join_leave": "🔊 Voz: unión/salida",
            "role_changes": "🏷️ Roles: miembros y definición",
            "nickname_changes": "📛 Cambios de apodo",
            "channel_updates": "📝 Canales y categorías (ajustes y permisos)",
            "audit_events": "📋 Auditoría administrativa adicional",
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
        if not await self._authorized(interaction):
            return
        selected = set(interaction.data.get("values", []))
        for key in self.events:
            self.events[key] = key in selected
        raw = self.cog.db.get_server_config(interaction.guild_id).get("log_events")
        try:
            saved = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            saved = {}
        if isinstance(saved, list):
            saved = {key: True for key in saved if isinstance(key, str)}
        saved = dict(saved) if isinstance(saved, dict) else {}
        saved.update(self.events)
        saved["role_change"] = self.events["role_changes"]
        saved["channel_update"] = self.events["channel_updates"]
        saved["voice_join"] = saved["voice_leave"] = self.events["voice_join_leave"]
        if "voice_state_update" in saved:
            saved["voice_state_update"] = self.events["voice_join_leave"]
        self.cog.db.set_server_config(
            interaction.guild_id,
            log_events=json.dumps(saved),
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
        if not await self._authorized(interaction):
            return
        await interaction.response.edit_message(content="✅ Panel cerrado.", embed=None, view=None)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self._authorized(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerUtils(bot))
