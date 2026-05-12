"""
cogs/translate.py
────────────────
Traducción de texto usando Google Translate.

Comandos slash:
  /translate <texto> [idioma] – Traduce texto al idioma deseado
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands
from googletrans import Translator

logger = logging.getLogger(__name__)

LANGUAGES = {
    "es": "Español", "en": "Inglés", "fr": "Francés", "de": "Alemán",
    "it": "Italiano", "pt": "Portugués", "ja": "Japonés", "ko": "Coreano",
    "zh-cn": "Chino Simplificado", "zh-tw": "Chino Tradicional",
    "ru": "Ruso", "ar": "Árabe", "nl": "Holandés", "pl": "Polaco",
    "sv": "Sueco", "da": "Danés", "fi": "Finlandés", "no": "Noruego",
    "tr": "Turco", "hi": "Hindi", "th": "Tailandés", "vi": "Vietnamita",
    "el": "Griego", "he": "Hebreo", "ro": "Rumano", "hu": "Húngaro",
    "cs": "Checo", "sk": "Eslovaco", "bg": "Búlgaro", "uk": "Ucraniano",
}


class Translate(commands.Cog):
    """Traducción de texto entre idiomas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._translator = Translator()

    @app_commands.command(name="translate", description="Traduce texto a otro idioma")
    @app_commands.describe(
        texto="Texto a traducir",
        destino="Idioma de destino (ej: en, fr, pt, ja...)",
    )
    async def translate(
        self,
        interaction: discord.Interaction,
        texto: str,
        destino: str = "es",
    ):
        await interaction.response.defer()

        destino = destino.lower().strip()

        try:
            result = await self._translator.translate(texto, dest=destino)
        except Exception as exc:
            logger.warning("Error en traducción: %s", exc)
            return await interaction.followup.send(
                "❌ Error al traducir. Verifica que el código de idioma sea válido.\n"
                "Ejemplos: `en`, `fr`, `pt`, `ja`, `de`, `it`",
                ephemeral=True,
            )

        src_lang = LANGUAGES.get(result.src[:5], result.src.upper())
        dest_lang = LANGUAGES.get(destino, destino.upper())

        embed = discord.Embed(
            title="🌍 Traducción",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="📝 Original", value=texto[:1024], inline=False)
        embed.add_field(name=f"🔤 Traducido ({src_lang} → {dest_lang})", value=result.text[:1024], inline=False)
        embed.set_footer(text="Google Translate")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Translate(bot))
