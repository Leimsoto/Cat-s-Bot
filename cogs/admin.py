"""
cogs/admin.py
─────────────
Comandos de administración del bot (solo owner del servidor y developers).
"""

import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def _get_bot_owners() -> list[int]:
    raw = os.getenv("BOT_OWNERS", "")
    if not raw:
        return []
    owners = []
    for part in raw.split(","):
        part = part.strip()
        try:
            owners.append(int(part))
        except ValueError:
            continue
    return owners


class Admin(commands.Cog):
    """Comandos de administración del bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bot_owners = _get_bot_owners()

    def _can_use(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        if not isinstance(user, discord.Member):
            return False
        if user.id in self._bot_owners:
            return True
        if user.id == interaction.guild.owner_id:
            return True
        return False

    @app_commands.command(name="resetbot", description="Reinicia el bot (solo owner del server y developers)")
    async def resetbot(self, interaction: discord.Interaction):
        if not self._can_use(interaction):
            return await interaction.response.send_message(
                "❌ Solo el dueño del servidor o los developers del bot pueden usar este comando.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "🔄 Reiniciando el bot...",
            ephemeral=True,
        )

        logger.warning(
            "ResetBot ejecutado por %s (%s) en guild %s (%s)",
            interaction.user, interaction.user.id,
            interaction.guild, interaction.guild_id,
        )

        try:
            await self.bot.close()
        except Exception:
            pass

        os._exit(0)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
