"""
cogs/info.py
────────────
Comandos de información general del bot.

  /ping    – Latencia del bot
  /botinfo – Información del bot: uptime, CPU, RAM, servidores
"""

import platform
from datetime import datetime, timezone

import discord
import psutil
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    """Comandos informativos: ping y estado del sistema."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._start_time = datetime.now(timezone.utc)

    # ─────────────────────────────────────────────────────────────────────────
    # /ping
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="Muestra la latencia del bot con el servidor de Discord")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)

        if ms < 100:
            color, label = discord.Color.green(), "Excelente"
        elif ms < 200:
            color, label = discord.Color.yellow(), "Normal"
        else:
            color, label = discord.Color.red(), "Alta"

        embed = discord.Embed(title="Pong", color=color)
        embed.add_field(name="Latencia API", value=f"`{ms} ms`", inline=True)
        embed.add_field(name="Estado", value=label, inline=True)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /botinfo
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="botinfo",
        description="Información del bot: latencia, uptime, uso de CPU y RAM",
    )
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Uptime
        delta = datetime.now(timezone.utc) - self._start_time
        total_sec = int(delta.total_seconds())
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

        # Sistema (sin bloquear el event loop con interval breve)
        cpu_pct = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        ram_used = ram.used // 1024 ** 2
        ram_total = ram.total // 1024 ** 2

        embed = discord.Embed(
            title=self.bot.user.name,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name="Latencia",
            value=f"`{round(self.bot.latency * 1000)} ms`",
            inline=True,
        )
        embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(
            name="Servidores",
            value=f"`{len(self.bot.guilds)}`",
            inline=True,
        )
        embed.add_field(name="CPU", value=f"`{cpu_pct:.1f}%`", inline=True)
        embed.add_field(
            name="RAM",
            value=f"`{ram_used} MB / {ram_total} MB ({ram.percent:.1f}%)`",
            inline=True,
        )
        embed.add_field(
            name="Python",
            value=f"`{platform.python_version()}`",
            inline=True,
        )

        # Info del servidor donde se ejecutó el comando
        guild = interaction.guild
        embed.add_field(name="Servidor", value=guild.name, inline=True)
        embed.add_field(
            name="Miembros",
            value=f"`{guild.member_count}`",
            inline=True,
        )

        embed.set_footer(text=f"Bot ID: {self.bot.user.id}")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
