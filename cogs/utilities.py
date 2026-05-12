"""
cogs/utilities.py
────────────────
Utilidades generales: encuestas, recordatorios, anti-raid, starboard y anti-alt.

Comandos slash:
  /poll       – Crear una encuesta con hasta 10 opciones
  /remindme   – Establecer un recordatorio

Listeners / funciones automáticas:
  on_member_join      – Anti-raid + anti-alt (configurables desde Dashboard)
  on_raw_reaction_add – Starboard (publica mensajes con N ⭐)
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("Utilities")

NUMBER_EMOJIS = [
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
]


# ── Modal para /poll ───────────────────────────────────────────────────────────

class PollModal(discord.ui.Modal, title="Nueva encuesta"):
    pregunta = discord.ui.TextInput(
        label="Pregunta",
        placeholder="¿Cuál es tu color favorito?",
        max_length=256,
        required=True,
    )
    opciones = discord.ui.TextInput(
        label="Opciones (separadas por coma)",
        placeholder="Rojo, Azul, Verde, Amarillo",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        items = [o.strip() for o in self.opciones.value.split(",") if o.strip()]
        if len(items) < 2:
            return await interaction.response.send_message(
                "❌ Necesitas al menos **2 opciones**.", ephemeral=True
            )
        if len(items) > 10:
            return await interaction.response.send_message(
                "❌ Máximo **10 opciones**.", ephemeral=True
            )

        embed = discord.Embed(
            title="📊 " + self.pregunta.value,
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        lines = []
        for i, opt in enumerate(items):
            lines.append(f"{NUMBER_EMOJIS[i]} {opt}")
        embed.add_field(name="Opciones", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Creada por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

        msg = await interaction.original_response()
        for i in range(len(items)):
            await msg.add_reaction(NUMBER_EMOJIS[i])


# ── Cog principal ─────────────────────────────────────────────────────────────

class Utilities(commands.Cog):
    """Utilidades generales: encuestas, recordatorios, anti-raid, starboard y anti-alt."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

        # Anti-raid: join timestamps por guild
        self._join_timestamps: dict[int, list[float]] = defaultdict(list)

        # Starboard: {guild_id: {message_id: starboard_message_id}}
        self._starboard_cache: dict[int, dict[int, int]] = defaultdict(dict)

        # Lockdown activo: {guild_id: expiry_timestamp}
        self._lockdowns: dict[int, float] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # /poll
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="poll", description="Crea una encuesta con hasta 10 opciones")
    async def poll(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PollModal())

    # ─────────────────────────────────────────────────────────────────────────
    # /remindme
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="remindme", description="Establece un recordatorio")
    @app_commands.describe(
        tiempo="Tiempo (ej: 30m, 1h, 2d, 5m)",
        mensaje="Mensaje del recordatorio",
    )
    async def remindme(
        self,
        interaction: discord.Interaction,
        tiempo: str,
        mensaje: str,
    ):
        secs = self._parse_duration(tiempo)
        if secs is None:
            return await interaction.response.send_message(
                "❌ Formato inválido. Ejemplos: `30m` · `2h` · `1d`",
                ephemeral=True,
            )
        if secs < 30:
            return await interaction.response.send_message(
                "❌ El tiempo mínimo es 30 segundos.", ephemeral=True,
            )
        if secs > 7_776_000:  # 90 días
            return await interaction.response.send_message(
                "❌ El tiempo máximo es 90 días.", ephemeral=True,
            )

        await interaction.response.send_message(
            f"✅ Te recordaré **{mensaje}** en **{self._fmt_duration(secs)}**.",
            ephemeral=True,
        )

        try:
            await interaction.user.send(
                f"✅ Recordatorio configurado para **{self._fmt_duration(secs)}** "
                f"a partir de ahora.\n**Mensaje:** {mensaje}"
            )
        except discord.Forbidden:
            pass

        asyncio.create_task(self._send_reminder(
            interaction.user.id, mensaje, secs
        ))

    async def _send_reminder(self, user_id: int, mensaje: str, delay: int):
        await asyncio.sleep(delay)
        user = self.bot.get_user(user_id)
        if not user:
            return
        embed = discord.Embed(
            title="⏰ Recordatorio",
            description=mensaje,
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Recordatorio programado")
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            logger.info("No se pudo enviar recordatorio a %s: DMs cerrados", user_id)
        except discord.HTTPException as exc:
            logger.warning("Error enviando recordatorio a %s: %s", user_id, exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Anti-Raid
    # ─────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        cfg = self.db.get_server_config(guild.id)

        # ── Anti-Alt ──────────────────────────────────────────────────────
        min_age_days = cfg.get("anti_alt_min_age", 7)
        if min_age_days > 0:
            age = (datetime.now(timezone.utc) - member.created_at).days
            if age < min_age_days:
                await self._handle_anti_alt(member, cfg, age)

        # ── Anti-Raid ────────────────────────────────────────────────────
        if not cfg.get("anti_raid_enabled", 0):
            return

        now = asyncio.get_event_loop().time()
        self._join_timestamps[guild.id].append(now)

        raid_threshold = cfg.get("anti_raid_threshold", 10)
        raid_window = cfg.get("anti_raid_window", 30)

        window_ago = now - raid_window
        recent = [t for t in self._join_timestamps[guild.id] if t > window_ago]
        self._join_timestamps[guild.id] = recent

        if len(recent) >= raid_threshold and guild.id not in self._lockdowns:
            await self._activate_lockdown(guild, cfg)

    async def _handle_anti_alt(self, member: discord.Member, cfg: dict, age_days: int):
        action = cfg.get("anti_alt_action", "log")
        min_age = cfg.get("anti_alt_min_age", 7)

        embed = discord.Embed(
            title="⚠️ Posible cuenta alternativa",
            description=f"{member.mention} (`{member.id}`)",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Cuenta creada", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Edad", value=f"{age_days} día(s)", inline=True)
        embed.add_field(name="Mínimo requerido", value=f"{min_age} día(s)", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")

        await self._send_log(member.guild, embed)

        if action == "kick":
            try:
                await member.kick(reason=f"Anti-alt: cuenta muy reciente ({age_days} días)")
            except discord.Forbidden:
                logger.warning("Sin permisos para kickear alt %s en %s", member, member.guild)
        elif action == "restrict":
            role_id = cfg.get("anti_alt_role_id")
            if role_id:
                role = member.guild.get_role(int(role_id))
                if role:
                    try:
                        await member.add_roles(role, reason="Anti-alt: cuenta muy reciente")
                    except discord.Forbidden:
                        logger.warning("Sin permisos para asignar rol anti-alt a %s", member)

    async def _activate_lockdown(self, guild: discord.Guild, cfg: dict):
        logger.warning("Anti-raid activado en %s (%s)", guild.name, guild.id)
        self._lockdowns[guild.id] = asyncio.get_event_loop().time() + cfg.get("anti_raid_lockdown_duration", 300)

        embed = discord.Embed(
            title="🔒 Lockdown activado — Anti-Raid",
            description=(
                "Se ha detectado una cantidad anómala de ingresos y se ha activado "
                "el modo lockdown.\n\n"
                "**Medidas aplicadas:**\n"
                "• Nivel de verificación → Alto\n"
                "• Nuevos ingresos bloqueados temporalmente"
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )

        # Cambiar nivel de verificación a HIGH
        try:
            await guild.edit(
                verification_level=discord.VerificationLevel.high,
                reason="Anti-raid: lockdown automático",
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para cambiar verificación en %s", guild.name)
        except discord.HTTPException as exc:
            logger.warning("Error cambiando verificación en %s: %s", guild.name, exc)

        # Notificar al modlog
        await self._send_log(guild, embed)

        # Auto-desactivar después del periodo
        asyncio.create_task(self._disable_lockdown_after(guild, cfg))

    async def _disable_lockdown_after(self, guild: discord.Guild, cfg: dict):
        duration = cfg.get("anti_raid_lockdown_duration", 300)
        await asyncio.sleep(duration)

        self._lockdowns.pop(guild.id, None)
        self._join_timestamps[guild.id].clear()

        try:
            await guild.edit(
                verification_level=discord.VerificationLevel.low,
                reason="Anti-raid: fin del lockdown automático",
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para restaurar verificación en %s", guild.name)
        except discord.HTTPException as exc:
            logger.warning("Error restaurando verificación en %s: %s", guild.name, exc)

        embed = discord.Embed(
            title="🔓 Lockdown desactivado",
            description="El modo lockdown ha sido desactivado automáticamente.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        await self._send_log(guild, embed)
        logger.info("Lockdown desactivado en %s", guild.name)

    # ─────────────────────────────────────────────────────────────────────────
    # Starboard
    # ─────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or not payload.emoji.is_unicode_emoji():
            return
        if payload.emoji.name != "⭐":
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        cfg = self.db.get_server_config(payload.guild_id)
        channel_id = cfg.get("starboard_channel_id")
        threshold = cfg.get("starboard_threshold", 3)
        if not channel_id:
            return

        starboard_channel = guild.get_channel(int(channel_id))
        if not isinstance(starboard_channel, discord.TextChannel):
            return

        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        if message.author.bot:
            return

        star_count = sum(
            1 for r in message.reactions if r.emoji == "⭐"
        )

        if star_count < threshold:
            return

        star_cache = self._starboard_cache[payload.guild_id]
        existing_id = star_cache.get(payload.message_id)

        if existing_id:
            try:
                existing_msg = await starboard_channel.fetch_message(existing_id)
                embed = existing_msg.embeds[0] if existing_msg.embeds else None
                if embed:
                    embed.description = embed.description or ""
                    lines = embed.description.split("\n")
                    if lines and lines[0].startswith("⭐"):
                        lines[0] = f"⭐ **{star_count}**"
                    embed.description = "\n".join(lines)
                    await existing_msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                star_cache.pop(payload.message_id, None)

        content = message.content or ""
        embed = discord.Embed(
            description=f"⭐ **{star_count}**\n{content[:2000]}",
            color=discord.Color.gold(),
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(name="🔗 Enlace", value=f"[Ir al mensaje]({message.jump_url})", inline=False)

        if message.attachments:
            first = message.attachments[0]
            if first.content_type and first.content_type.startswith("image"):
                embed.set_image(url=first.url)

        try:
            star_msg = await starboard_channel.send(embed=embed)
            star_cache[payload.message_id] = star_msg.id
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Error enviando starboard en %s: %s", guild.name, exc)

    # ─────────────────────────────────────────────────────────────────────────
    # /starboard
    # ─────────────────────────────────────────────────────────────────────────

    starboard_group = app_commands.Group(
        name="starboard", description="Configurar el sistema de starboard (⭐)",
    )

    @starboard_group.command(name="channel", description="Establece el canal de starboard")
    @app_commands.describe(canal="Canal donde se publicarán los mensajes destacados")
    @app_commands.checks.has_permissions(administrator=True)
    async def starboard_channel(self, interaction: discord.Interaction, canal: discord.TextChannel):
        self.db.set_server_config(interaction.guild_id, starboard_channel_id=canal.id)
        await interaction.response.send_message(
            f"✅ Canal de starboard establecido a {canal.mention}.", ephemeral=True
        )

    @starboard_group.command(name="threshold", description="Define cuántas ⭐ se necesitan para destacar")
    @app_commands.describe(cantidad="Número mínimo de estrellas (1-50)")
    @app_commands.checks.has_permissions(administrator=True)
    async def starboard_threshold(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 50]):
        self.db.set_server_config(interaction.guild_id, starboard_threshold=cantidad)
        await interaction.response.send_message(
            f"✅ Umbral de starboard establecido a **{cantidad}** ⭐.", ephemeral=True
        )

    @starboard_group.command(name="config", description="Muestra la configuración actual del starboard")
    async def starboard_config(self, interaction: discord.Interaction):
        cfg = self.db.get_server_config(interaction.guild_id)
        ch_id = cfg.get("starboard_channel_id")
        threshold = cfg.get("starboard_threshold", 3)
        channel = interaction.guild.get_channel(int(ch_id)) if ch_id else None

        embed = discord.Embed(
            title="⭐ Configuración de Starboard",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Canal", value=channel.mention if channel else "❌ No configurado", inline=True)
        embed.add_field(name="Umbral", value=f"{threshold} ⭐", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers privados
    # ─────────────────────────────────────────────────────────────────────────

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        cfg = self.db.get_server_config(guild.id)
        ch_id = cfg.get("modlog_channel")
        if not ch_id:
            return

        channel = guild.get_channel(ch_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar logs en %s", guild.name)
        except discord.HTTPException as exc:
            logger.warning("No se pudo enviar log en %s: %s", guild.name, exc)

    @staticmethod
    def _parse_duration(raw: str) -> Optional[int]:
        if not raw:
            return None
        raw = raw.strip().lower()
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        try:
            if raw[-1] in units:
                return int(raw[:-1]) * units[raw[-1]]
            return int(raw) * 60
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        parts = []
        for label, unit in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
            if seconds >= unit:
                parts.append(f"{seconds // unit}{label}")
                seconds %= unit
        return " ".join(parts) if parts else "0s"


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))
