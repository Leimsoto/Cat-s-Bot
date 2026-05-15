"""
cogs/autoresponses.py
─────────────────────
Sistema de auto-respuestas configurables por canal con matching avanzado y
respuestas en formato MessageEditor (texto plano + embed).

Tipos de match soportados (columna ``match_type``):
  • contains     – substring (default).
  • exact        – mensaje completo igual al trigger.
  • word         – palabra completa (regex ``\\btrigger\\b``).
  • starts_with  – mensaje comienza con el trigger.
  • regex        – patrón regex completo.

Comandos slash legacy (toda la creación/edición se hace desde el dashboard):
  /autoresponse list    – lista las auto-respuestas del servidor.
  /autoresponse remove  – elimina una auto-respuesta por ID.
"""

import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs._message_payload import render_message_payload

logger = logging.getLogger("AutoResponses")


def _match(content: str, trigger: str, match_type: str, case_sensitive: bool) -> bool:
    if not trigger:
        return False
    haystack = content if case_sensitive else content.lower()
    needle = trigger if case_sensitive else trigger.lower()
    mt = (match_type or "contains").lower()

    if mt == "exact":
        return haystack.strip() == needle.strip()
    if mt == "starts_with":
        return haystack.lstrip().startswith(needle)
    if mt == "word":
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.search(r"\b" + re.escape(trigger) + r"\b", content, flags))
    if mt == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return bool(re.search(trigger, content, flags))
        except re.error:
            return False
    return needle in haystack


class AutoResponses(commands.Cog):
    """Auto-respuestas con matching avanzado y respuestas con embed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        rows = self.db.get_autoresponses_by_channel(message.guild.id, message.channel.id)
        if not rows:
            return

        for row in rows:
            if not row.get("enabled", 1):
                continue
            if not _match(
                message.content,
                row["trigger"],
                row.get("match_type") or "contains",
                bool(row.get("case_sensitive")),
            ):
                continue

            variables = {
                "user": message.author.mention,
                "username": message.author.display_name,
                "server": message.guild.name,
                "channel": message.channel.mention,
            }
            try:
                if row.get("response_data"):
                    payload = render_message_payload(
                        row["response_data"], variables, member=message.author,
                    )
                    await message.channel.send(
                        content=payload["content"],
                        embed=payload["embed"],
                    )
                else:
                    text = (row.get("response") or "")
                    for k, v in variables.items():
                        text = text.replace("{" + k + "}", str(v))
                    if text:
                        await message.channel.send(text)
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.warning("Error enviando autoresponse en %s: %s", message.guild.id, exc)
            break

    autoresponse_group = app_commands.Group(
        name="autoresponse",
        description="Inspeccionar auto-respuestas (configuración en dashboard)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @autoresponse_group.command(name="list", description="Lista todas las auto-respuestas del servidor")
    async def list_ar(self, interaction: discord.Interaction):
        rows = self.db.get_autoresponses(interaction.guild_id)
        if not rows:
            return await interaction.response.send_message(
                "📭 No hay auto-respuestas configuradas. Crea desde el dashboard.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Auto-respuestas",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Total: {len(rows)} · Edita desde el dashboard")
        for r in rows[:15]:
            canal = interaction.guild.get_channel(r["channel_id"]) if r["channel_id"] else None
            canal_str = canal.mention if canal else "🌐 Todos"
            state = "✅" if r.get("enabled", 1) else "⏸️"
            mt = r.get("match_type") or "contains"
            embed.add_field(
                name=f"{state} #{r['id']} · [{mt}] `{r['trigger'][:40]}`",
                value=f"📌 {canal_str}",
                inline=False,
            )
        if len(rows) > 15:
            embed.description = f"Mostrando 15 de {len(rows)} auto-respuestas."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autoresponse_group.command(name="remove", description="Elimina una auto-respuesta por su ID")
    @app_commands.describe(id="ID numérico de la auto-respuesta a eliminar")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction, id: int):
        rows = self.db.get_autoresponses(interaction.guild_id)
        if not any(r["id"] == id for r in rows):
            return await interaction.response.send_message(
                f"❌ No existe una auto-respuesta con ID `{id}`.", ephemeral=True
            )
        self.db.remove_autoresponse(id)
        await interaction.response.send_message(
            f"🗑️ Auto-respuesta ID `{id}` eliminada.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoResponses(bot))
