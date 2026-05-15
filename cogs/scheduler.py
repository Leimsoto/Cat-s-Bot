"""
cogs/scheduler.py
─────────────────
Sistema de mensajes programados (cron).

Comandos:
  /schedule create   — Abre modal: nombre, canal, mensaje, intervalo
  /schedule list     — Lista schedules del servidor
  /schedule delete   — Elimina un schedule
  /schedule toggle   — Activa/desactiva
  /schedule test     — Envía el mensaje una vez ahora

Restricciones:
  - Solo administradores
  - Intervalo mínimo: 10 minutos
  - Máximo 10 schedules por servidor
"""

import json
import logging
import asyncio
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo  # stdlib desde Python 3.9
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs._message_payload import render_message_payload

logger = logging.getLogger("Scheduler")

MIN_INTERVAL = 600       # 10 minutos en segundos
MAX_INTERVAL = 2_592_000 # 30 días en segundos
MAX_SCHEDULES = 10


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_interval(text: str) -> int:
    """Convierte '1h', '30m', '2d', '1w' a segundos. Devuelve -1 si inválido."""
    text = text.strip().lower()
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    if len(text) < 2:
        return -1
    unit = text[-1]
    if unit not in units:
        return -1
    try:
        n = float(text[:-1])
        return int(n * units[unit])
    except ValueError:
        return -1


def _fmt_interval(seconds: int) -> str:
    """Formatea segundos como '2h 30m'."""
    parts = []
    for unit, label in [(604800, "sem"), (86400, "d"), (3600, "h"), (60, "min")]:
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    return " ".join(parts) if parts else f"{seconds}s"


async def _schedule_autocomplete(interaction: discord.Interaction, current: str):
    schedules = interaction.client.db.get_schedules(interaction.guild_id)
    return [
        app_commands.Choice(name=s["name"], value=s["name"])
        for s in schedules if current.lower() in s["name"].lower()
    ][:25]


# ── Modal ─────────────────────────────────────────────────────────────────────

class ScheduleCreateModal(discord.ui.Modal, title="Crear Mensaje Programado"):
    name_input = discord.ui.TextInput(
        label="Nombre identificador",
        placeholder="recordatorio-semanal",
        max_length=50,
        min_length=1,
    )
    content_input = discord.ui.TextInput(
        label="Mensaje a enviar",
        style=discord.TextStyle.paragraph,
        placeholder="@everyone ¡Recuerden...",
        max_length=2000,
        min_length=1,
    )
    interval_input = discord.ui.TextInput(
        label="Intervalo (ej: 30m, 1h, 2d, 1w)",
        placeholder="1h",
        max_length=10,
    )

    def __init__(self, cog, channel: discord.TextChannel):
        super().__init__()
        self.cog = cog
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        content = self.content_input.value.strip()
        interval_str = self.interval_input.value.strip()

        interval_secs = _parse_interval(interval_str)
        if interval_secs < MIN_INTERVAL:
            return await interaction.response.send_message(
                f"❌ El intervalo mínimo es **10 minutos** (`10m`). Ingresaste: `{interval_str}`.", ephemeral=True
            )
        if interval_secs > MAX_INTERVAL:
            return await interaction.response.send_message(
                f"❌ El intervalo máximo es **30 días** (`30d`).", ephemeral=True
            )

        existing = self.cog.db.get_schedules(interaction.guild_id)
        if len(existing) >= MAX_SCHEDULES:
            return await interaction.response.send_message(
                f"❌ Ya tienes el máximo de {MAX_SCHEDULES} mensajes programados.", ephemeral=True
            )
        if any(s["name"] == name for s in existing):
            return await interaction.response.send_message(
                f"❌ Ya existe un schedule llamado **{name}**.", ephemeral=True
            )

        self.cog.db.create_schedule(
            interaction.guild_id, name, self.channel.id,
            content, interval_secs, interaction.user.id
        )
        await interaction.response.send_message(
            f"✅ Mensaje programado **{name}** creado.\n"
            f"📍 Canal: {self.channel.mention} | ⏱️ Intervalo: `{_fmt_interval(interval_secs)}`",
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Scheduler(commands.Cog):
    """Mensajes programados periódicos (tipo cron)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self.cron_runner.start()

    def cog_unload(self):
        self.cron_runner.cancel()

    @tasks.loop(seconds=60)
    async def cron_runner(self):
        now_utc = datetime.now(timezone.utc)
        try:
            schedules = self.db.get_all_active_schedules()
        except Exception as e:
            logger.warning(f"Error leyendo schedules: {e}")
            return

        for sched in schedules:
            try:
                mode = (sched.get("schedule_mode") or "interval").lower()
                should_send = self._should_send(sched, now_utc, mode)
                if not should_send:
                    continue

                guild = self.bot.get_guild(int(sched["guild_id"]))
                if not guild:
                    continue
                channel = guild.get_channel(int(sched["channel_id"]))
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue

                await self._send_scheduled_message(channel, sched, guild)
                self.db.update_schedule(int(sched["id"]), last_sent=now_utc.isoformat())
                logger.info(
                    "Schedule '%s' enviado en %s#%s (modo %s)",
                    sched["name"], guild.name, channel.name, mode,
                )
            except Exception as e:
                logger.warning(f"Error en schedule '{sched.get('name', '?')}': {e}")

    def _should_send(self, sched: dict, now_utc: datetime, mode: str) -> bool:
        """Decide si toca enviar este schedule en este tick."""
        last_sent_str = sched.get("last_sent")
        last_sent = None
        if last_sent_str:
            try:
                last_sent = datetime.fromisoformat(last_sent_str)
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                last_sent = None

        if mode == "cron":
            tz_name = sched.get("timezone") or "UTC"
            tz = ZoneInfo(tz_name) if ZoneInfo else timezone.utc
            try:
                local_now = now_utc.astimezone(tz) if ZoneInfo else now_utc
            except Exception:
                local_now = now_utc
            target_h = sched.get("cron_hour")
            target_m = sched.get("cron_minute")
            if target_h is None or target_m is None:
                return False
            if local_now.hour != int(target_h) or local_now.minute != int(target_m):
                return False
            # Weekdays opcional (0=lunes según ISO weekday-1).
            weekdays_raw = sched.get("cron_weekdays")
            if weekdays_raw:
                try:
                    allowed = json.loads(weekdays_raw) if isinstance(weekdays_raw, str) else weekdays_raw
                    if isinstance(allowed, list) and allowed:
                        # ISO: Monday=1..Sunday=7; almacenamos 0=Monday..6=Sunday.
                        today = local_now.isoweekday() - 1
                        if today not in [int(x) for x in allowed]:
                            return False
                except (json.JSONDecodeError, ValueError):
                    pass
            # Evita enviar dos veces en el mismo minuto.
            if last_sent and (now_utc - last_sent).total_seconds() < 90:
                return False
            return True

        # Modo interval (legacy).
        interval = int(sched.get("interval_seconds") or 0)
        if interval <= 0:
            return False
        if last_sent is None:
            return True
        return (now_utc - last_sent).total_seconds() >= interval

    async def _send_scheduled_message(
        self,
        channel: discord.TextChannel,
        sched: dict,
        guild: discord.Guild,
    ) -> None:
        """Envía el mensaje del schedule. Prefiere `message_data` (embed)."""
        message_data = sched.get("message_data")
        variables = {
            "server": guild.name,
            "channel": channel.mention,
        }
        if message_data:
            try:
                payload = render_message_payload(message_data, variables)
                if payload["content"] or payload["embed"] is not None:
                    await channel.send(content=payload["content"], embed=payload["embed"])
                    return
            except Exception as exc:
                logger.warning("message_data inválido para schedule %s: %s", sched.get("name"), exc)
        content = sched.get("content") or ""
        for k, v in variables.items():
            content = content.replace("{" + k + "}", str(v))
        if content:
            await channel.send(content)

    @cron_runner.before_loop
    async def before_cron(self):
        await self.bot.wait_until_ready()

    # ── Comandos ──────────────────────────────────────────────────────────────

    schedule_group = app_commands.Group(
        name="schedule",
        description="Mensajes programados periódicos",
        default_permissions=discord.Permissions(administrator=True),
    )

    @schedule_group.command(name="create", description="Crea un mensaje programado que se enviará automáticamente")
    @app_commands.describe(canal="Canal donde se enviará el mensaje")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_create(self, interaction: discord.Interaction, canal: discord.TextChannel):
        await interaction.response.send_modal(ScheduleCreateModal(self, canal))

    @schedule_group.command(name="list", description="Lista todos los mensajes programados del servidor")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_list(self, interaction: discord.Interaction):
        schedules = self.db.get_schedules(interaction.guild_id)
        if not schedules:
            return await interaction.response.send_message(
                "📭 No hay mensajes programados. Crea uno con `/schedule create`.", ephemeral=True
            )

        embed = discord.Embed(
            title="⏱️ Mensajes Programados",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        for s in schedules:
            ch = interaction.guild.get_channel(int(s["channel_id"]))
            ch_text = ch.mention if ch else f"ID:{s['channel_id']}"
            status = "🟢" if s["enabled"] else "🔴"
            last = s["last_sent"][:16].replace("T", " ") if s["last_sent"] else "Nunca"
            embed.add_field(
                name=f"{status} {s['name']}",
                value=f"Canal: {ch_text}\nIntervalo: `{_fmt_interval(int(s['interval_seconds']))}`\nÚltimo envío: `{last}`",
                inline=True,
            )
        embed.set_footer(text=f"{len(schedules)}/{MAX_SCHEDULES} schedules")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @schedule_group.command(name="delete", description="Elimina un mensaje programado")
    @app_commands.describe(nombre="Nombre del schedule a eliminar")
    @app_commands.autocomplete(nombre=_schedule_autocomplete)
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_delete(self, interaction: discord.Interaction, nombre: str):
        sched = self.db.get_schedule_by_name(interaction.guild_id, nombre)
        if not sched:
            return await interaction.response.send_message(f"❌ No existe ningún schedule llamado **{nombre}**.", ephemeral=True)
        self.db.delete_schedule(interaction.guild_id, nombre)
        await interaction.response.send_message(f"✅ Schedule **{nombre}** eliminado.", ephemeral=True)

    @schedule_group.command(name="toggle", description="Activa o desactiva un mensaje programado")
    @app_commands.describe(nombre="Nombre del schedule")
    @app_commands.autocomplete(nombre=_schedule_autocomplete)
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_toggle(self, interaction: discord.Interaction, nombre: str):
        sched = self.db.get_schedule_by_name(interaction.guild_id, nombre)
        if not sched:
            return await interaction.response.send_message(f"❌ No existe ningún schedule llamado **{nombre}**.", ephemeral=True)
        new_state = 0 if sched["enabled"] else 1
        self.db.update_schedule(int(sched["id"]), enabled=new_state)
        state_text = "✅ Activado" if new_state else "🔴 Desactivado"
        await interaction.response.send_message(f"{state_text} — Schedule **{nombre}**.", ephemeral=True)

    @schedule_group.command(name="test", description="Envía el mensaje programado una vez ahora mismo")
    @app_commands.describe(nombre="Nombre del schedule")
    @app_commands.autocomplete(nombre=_schedule_autocomplete)
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_test(self, interaction: discord.Interaction, nombre: str):
        sched = self.db.get_schedule_by_name(interaction.guild_id, nombre)
        if not sched:
            return await interaction.response.send_message(f"❌ No existe ningún schedule llamado **{nombre}**.", ephemeral=True)
        channel = interaction.guild.get_channel(int(sched["channel_id"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Canal no encontrado.", ephemeral=True)
        try:
            await self._send_scheduled_message(channel, sched, interaction.guild)
            await interaction.response.send_message(
                f"✅ Mensaje de prueba enviado a {channel.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Sin permisos para enviar en ese canal.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Scheduler(bot))
