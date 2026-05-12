"""
cogs/autoresponses.py
─────────────────────
Sistema de auto-respuestas configurables por canal.
Cuando un usuario escribe un trigger en un canal, el bot responde automáticamente.

Comandos slash:
  /autoresponse add     – Agregar una auto-respuesta
  /autoresponse remove  – Eliminar una auto-respuesta
  /autoresponse list    – Listar todas las auto-respuestas del servidor
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class AutoResponses(commands.Cog):
    """Sistema de auto-respuestas por canal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    # ── Listener ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        rows = self.db.get_autoresponses_by_channel(message.guild.id, message.channel.id)
        if not rows:
            return

        content_lower = message.content.lower()
        for row in rows:
            trigger = row["trigger"].lower()
            if trigger in content_lower:
                try:
                    await message.channel.send(row["response"])
                except (discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning("Error enviando autoresponse en %s: %s", message.guild.id, exc)
                break

    # ── Grupo de comandos ─────────────────────────────────────────────────────

    autoresponse_group = app_commands.Group(
        name="autoresponse",
        description="Gestionar auto-respuestas del servidor",
    )

    @autoresponse_group.command(name="add", description="Agrega una auto-respuesta en un canal")
    @app_commands.describe(
        trigger="Palabra o frase que activa la respuesta",
        response="Texto que responderá el bot",
        canal="Canal donde funcionará (opcional: todos los canales si se omite)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        response: str,
        canal: Optional[discord.TextChannel] = None,
    ):
        ch_id = canal.id if canal else None
        rid = self.db.add_autoresponse(interaction.guild_id, ch_id, trigger, response)

        embed = discord.Embed(
            title="✅ Auto-respuesta agregada",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Trigger", value=f"`{trigger}`", inline=False)
        embed.add_field(name="Respuesta", value=response[:1024], inline=False)
        embed.add_field(name="Canal", value=canal.mention if canal else "🌐 Todos los canales", inline=True)
        embed.set_footer(text=f"ID: {rid}")

        await interaction.response.send_message(embed=embed)

    @autoresponse_group.command(name="remove", description="Elimina una auto-respuesta por su ID")
    @app_commands.describe(id="ID numérico de la auto-respuesta a eliminar")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction, id: int):
        rows = self.db.get_autoresponses(interaction.guild_id)
        matching = [r for r in rows if r["id"] == id]

        if not matching:
            return await interaction.response.send_message(
                f"❌ No existe una auto-respuesta con ID `{id}`.", ephemeral=True
            )

        self.db.remove_autoresponse(id)

        embed = discord.Embed(
            title="🗑️ Auto-respuesta eliminada",
            description=f"Se eliminó la auto-respuesta **ID {id}**.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    @autoresponse_group.command(name="list", description="Lista todas las auto-respuestas del servidor")
    async def list_ar(self, interaction: discord.Interaction):
        rows = self.db.get_autoresponses(interaction.guild_id)

        if not rows:
            return await interaction.response.send_message(
                "📭 No hay auto-respuestas configuradas en este servidor.", ephemeral=True
            )

        embed = discord.Embed(
            title="Auto-respuestas",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Total: {len(rows)}")

        for r in rows[:15]:
            canal = interaction.guild.get_channel(r["channel_id"]) if r["channel_id"] else None
            canal_str = canal.mention if canal else "🌐 Todos"
            embed.add_field(
                name=f"#{r['id']} — `{r['trigger'][:50]}`",
                value=f"→ {r['response'][:100]}\n📌 {canal_str}",
                inline=False,
            )

        if len(rows) > 15:
            embed.description = f"Mostrando 15 de {len(rows)} auto-respuestas."

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoResponses(bot))
