"""
cogs/logging.py
────────────────
Server event logging system.

Logs configurable Discord events to a designated channel.
Configuration is managed via the dashboard web panel.
"""

import json
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class Logging(commands.Cog):
    """Logs server events to a configurable channel."""

    EVENT_ALIASES = {
        "bulk_message_delete": ("bulk_message_delete", "message_delete"),
        "member_update": ("member_update", "role_change", "nickname_changes", "role_changes"),
        "voice_state_update": ("voice_state_update", "voice_join", "voice_leave", "voice_join_leave"),
        "member_unban": ("member_unban", "member_ban"),
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self._last_log: dict[int, float] = {}

    @classmethod
    def _event_enabled(cls, raw, event_name: str) -> bool:
        aliases = cls.EVENT_ALIASES.get(event_name, (event_name,))
        if raw is None:
            return True
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return True
        if isinstance(raw, dict):
            if not raw:
                return True
            return any(bool(raw.get(key)) for key in aliases)
        if isinstance(raw, list):
            return any(key in raw for key in aliases)
        return True

    def _nearby_messageable_channel(self, guild: discord.Guild, channel_id: int):
        candidates = [
            ch
            for ch in getattr(guild, "channels", [])
            if callable(getattr(ch, "send", None)) and abs(int(ch.id) - int(channel_id)) <= 4096
        ]
        return candidates[0] if len(candidates) == 1 else None

    async def _resolve_serverlog_channel(self, guild: discord.Guild, raw_channel_id):
        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            return None, raw_channel_id, "invalid_channel_id"

        channel = guild.get_channel(channel_id)
        if callable(getattr(channel, "send", None)):
            return channel, channel.id, None

        repaired = self._nearby_messageable_channel(guild, channel_id)
        if repaired is not None:
            logger.warning(
                "serverlog channel_id redondeado reparado en %s: %s -> %s",
                guild.name,
                channel_id,
                repaired.id,
            )
            try:
                self.db.set_server_config(guild.id, serverlog_channel=repaired.id)
            except Exception:
                logger.debug("No se pudo persistir serverlog_channel reparado", exc_info=True)
            return repaired, repaired.id, None

        try:
            fetched = await guild.fetch_channel(channel_id)
            if callable(getattr(fetched, "send", None)):
                return fetched, fetched.id, None
            return fetched, channel_id, "target_is_not_messageable"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            return None, channel_id, str(exc)

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed, event_name: str) -> None:
        srv_cfg = self.db.get_server_config(guild.id)
        if not srv_cfg.get("serverlog_enabled", 1):
            return

        raw = srv_cfg.get("log_events", "[]")
        if not self._event_enabled(raw, event_name):
            return

        ch_id = srv_cfg.get("serverlog_channel")
        if not ch_id:
            return

        channel, resolved_ch_id, resolve_error = await self._resolve_serverlog_channel(guild, ch_id)
        if channel is None or not callable(getattr(channel, "send", None)):
            logger.warning("serverlog channel no accesible en %s (%s): %s", guild.name, ch_id, resolve_error)
            self._enqueue_serverlog_outbox(guild, embed, event_name, resolved_ch_id or ch_id, resolve_error or "channel_unavailable")
            return

        now = time.time()
        last = self._last_log.get(guild.id, 0.0)
        if now - last < 2.0:
            self._enqueue_serverlog_outbox(guild, embed, event_name, resolved_ch_id, "rate_limited")
            return
        self._last_log[guild.id] = now

        try:
            from cogs._managed_messages import send_managed
            await send_managed(self.bot, guild.id, "serverutils", channel.send, embed=embed)
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar serverlog en %s", guild.name)
            self._enqueue_serverlog_outbox(guild, embed, event_name, resolved_ch_id, "missing_send_messages")
        except discord.HTTPException as exc:
            logger.warning("Error enviando serverlog en %s: %s", guild.name, exc)
            self._enqueue_serverlog_outbox(guild, embed, event_name, resolved_ch_id, str(exc))

    def _enqueue_serverlog_outbox(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        event_name: str,
        channel_id,
        error: str,
    ) -> None:
        try:
            self.db.enqueue_log_outbox(
                guild.id,
                event_name,
                {
                    "embed": embed.to_dict(),
                    "source": "logging_cog",
                    "event": event_name,
                    "last_error": (error or "")[:500],
                },
                channel_id=int(channel_id),
            )
        except Exception as exc:
            logger.warning("No se pudo encolar serverlog fallido en %s: %s", guild.name, exc)

    # ── Message events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not after.guild:
            return
        if before.content == after.content:
            return

        embed = discord.Embed(
            title="✏️ Mensaje editado",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=after.author.display_name, icon_url=after.author.display_avatar.url)
        embed.add_field(name="Canal", value=after.channel.mention, inline=True)
        embed.add_field(name="Autor", value=after.author.mention, inline=True)
        if before.content:
            embed.add_field(name="Antes", value=before.content[:1024], inline=False)
        embed.add_field(name="Después", value=after.content[:1024], inline=False)
        embed.add_field(name="Enlace", value=f"[Ir al mensaje]({after.jump_url})", inline=False)
        embed.set_footer(text=f"ID: {after.id}")

        await self._send_log(after.guild, embed, "message_edit")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        embed = discord.Embed(
            title="🗑️ Mensaje eliminado",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Canal", value=message.channel.mention, inline=True)
        embed.add_field(name="Autor", value=message.author.mention, inline=True)
        if message.content:
            embed.add_field(name="Contenido", value=message.content[:1024], inline=False)
        embed.set_footer(text=f"ID: {message.id}")

        await self._send_log(message.guild, embed, "message_delete")

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        guild = messages[0].guild
        if not guild:
            return

        embed = discord.Embed(
            title="🗑️ Mensajes eliminados en lote",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Cantidad", value=str(len(messages)), inline=True)
        embed.add_field(name="Canal", value=messages[0].channel.mention, inline=True)
        embed.set_footer(text=f"Canal ID: {messages[0].channel.id}")

        await self._send_log(guild, embed, "bulk_message_delete")

    # ── Member events ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        nick_changed = before.nick != after.nick
        added = [r for r in after.roles if r not in before.roles and r.is_assignable()]
        removed = [r for r in before.roles if r not in after.roles and r.is_assignable()]

        if not nick_changed and not added and not removed:
            return

        embed = discord.Embed(
            title="📝 Miembro actualizado",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=after.display_name, icon_url=after.display_avatar.url)
        embed.add_field(name="Usuario", value=after.mention, inline=True)

        if nick_changed:
            embed.add_field(name="Apodo anterior", value=before.nick or "Ninguno", inline=True)
            embed.add_field(name="Apodo nuevo", value=after.nick or "Ninguno", inline=True)

        if added:
            embed.add_field(name="Roles añadidos", value=", ".join(r.mention for r in added), inline=False)

        if removed:
            embed.add_field(name="Roles quitados", value=", ".join(r.mention for r in removed), inline=False)

        await self._send_log(guild, embed, "member_update")

    # ── Channel events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        guild = channel.guild

        embed = discord.Embed(
            title="📢 Canal creado",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Nombre", value=channel.mention, inline=True)
        embed.add_field(name="Tipo", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Categoría", value=channel.category.name if channel.category else "Ninguna", inline=True)
        embed.set_footer(text=f"ID: {channel.id}")

        await self._send_log(guild, embed, "channel_create")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild

        embed = discord.Embed(
            title="❌ Canal eliminado",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Nombre", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Tipo", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Categoría", value=channel.category.name if channel.category else "Ninguna", inline=True)
        embed.set_footer(text=f"ID: {channel.id}")

        await self._send_log(guild, embed, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        guild = after.guild

        name_changed = before.name != after.name
        topic_changed = getattr(before, "topic", None) != getattr(after, "topic", None)

        if not name_changed and not topic_changed:
            return

        embed = discord.Embed(
            title="✏️ Canal actualizado",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Canal", value=after.mention, inline=True)

        if name_changed:
            embed.add_field(name="Nombre anterior", value=f"#{before.name}", inline=True)
            embed.add_field(name="Nombre nuevo", value=f"#{after.name}", inline=True)

        if topic_changed:
            embed.add_field(name="Tópico anterior", value=before.topic or "Ninguno", inline=False)
            embed.add_field(name="Tópico nuevo", value=after.topic or "Ninguno", inline=False)

        await self._send_log(guild, embed, "channel_update")

    # ── Voice events ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild

        if before.channel == after.channel:
            return

        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊 Se unió a un canal de voz",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=after.channel.mention, inline=True)

        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 Salió del canal de voz",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=before.channel.mention, inline=True)

        else:
            embed = discord.Embed(
                title="🔁 Se movió de canal de voz",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="De", value=before.channel.mention, inline=True)
            embed.add_field(name="A", value=after.channel.mention, inline=True)

        await self._send_log(guild, embed, "voice_state_update")

    # ── Ban events ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        embed = discord.Embed(
            title="🔨 Usuario baneado",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)", inline=True)

        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    embed.add_field(name="Moderador", value=entry.user.mention if entry.user else "Desconocido", inline=True)
                    embed.add_field(name="Razón", value=entry.reason or "Sin razón", inline=False)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        embed.set_footer(text=f"ID: {user.id}")
        await self._send_log(guild, embed, "member_ban")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(
            title="✅ Usuario desbaneado",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)", inline=True)

        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    embed.add_field(name="Moderador", value=entry.user.mention if entry.user else "Desconocido", inline=True)
                    embed.add_field(name="Razón", value=entry.reason or "Sin razón", inline=False)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        embed.set_footer(text=f"ID: {user.id}")
        await self._send_log(guild, embed, "member_unban")


async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))
