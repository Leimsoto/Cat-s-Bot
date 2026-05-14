"""
cogs/_catbot.py
───────────────
Identidad de marca de Cat's Bot.

Carga los Application Emojis personalizados (catbot01–catbot39) una sola vez
al arrancar y los expone como `bot.catbot` (dict name → str).

Helpers de voz/marca:
    bot.catbot_voice.say(key, fallback="...") → str con emoji + texto
    bot.catbot_voice.embed(title, description, kind="info") → discord.Embed

Roles semánticos → emoji por defecto:
    success   → catbot01  (XO, todo bien)
    error     → catbot38  (señal de advertencia)
    warning   → catbot31  (BAN amarillo)
    ban       → catbot39  (martillo BAN!)
    info      → catbot22  (tablet)
    loading   → catbot28  (destellos en espera)
    tip       → catbot08  (bombilla)
    help      → catbot21  (HELP)
    log       → catbot23  (documento)
    stats     → catbot18  (gráfica)
    money     → catbot34  (monedas)
    gift      → catbot12  (regalo)
    star      → catbot15  (estrella dorada)
    boss      → catbot24  (BOSS, admin)
    afk       → catbot11  (zzz)
    night     → catbot10  (luna)
    paw       → catbot37  (huella, marca del bot)
    magic     → catbot20  (destellos)
    code      → catbot35  (laptop)
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

logger = logging.getLogger("Bot.catbot")

# ── Colores de marca (DESIGN.md) ─────────────────────────────────────────────
BRAND_ACCENT = 0xA855F7   # morado principal
BRAND_SUCCESS = 0x10B981  # verde éxito
BRAND_WARNING = 0xF59E0B  # ámbar aviso
BRAND_DANGER = 0xF43F5E   # rojo peligro
BRAND_INFO = 0x06B6D4     # cyan info
BRAND_NEUTRAL = 0x18141F  # mantel (panel)

# ── Mapeo rol semántico → nombre de emoji ────────────────────────────────────
ROLE_TO_EMOJI = {
    "success": "catbot01",
    "error": "catbot38",
    "warning": "catbot31",
    "ban": "catbot39",
    "info": "catbot22",
    "loading": "catbot28",
    "tip": "catbot08",
    "help": "catbot21",
    "log": "catbot23",
    "stats": "catbot18",
    "money": "catbot34",
    "gift": "catbot12",
    "star": "catbot15",
    "boss": "catbot24",
    "afk": "catbot11",
    "night": "catbot10",
    "paw": "catbot37",
    "magic": "catbot20",
    "code": "catbot35",
    "trophy": "catbot07",
    "hype": "catbot17",
    "love": "catbot09",
    "treat": "catbot05",
    "fish": "catbot25",
    "game": "catbot13",
    "stream": "catbot02",
    "idea": "catbot08",
}

# ── Fallbacks Unicode si el bot aún no cargó los app emojis ──────────────────
ROLE_FALLBACK = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "ban": "🔨",
    "info": "ℹ️",
    "loading": "⏳",
    "tip": "💡",
    "help": "❓",
    "log": "📄",
    "stats": "📊",
    "money": "💰",
    "gift": "🎁",
    "star": "⭐",
    "boss": "🛡️",
    "afk": "💤",
    "night": "🌙",
    "paw": "🐾",
    "magic": "✨",
    "code": "💻",
    "trophy": "🏆",
    "hype": "🎉",
    "love": "💜",
    "treat": "🍪",
    "fish": "🐟",
    "game": "🎮",
    "stream": "🍿",
    "idea": "💡",
}


class CatbotVoice:
    """
    Voz de marca de Cat's Bot.

    Uso típico:
        v = bot.catbot_voice
        await ctx.send(v.line("success", "Cambios guardados"))
        await ctx.send(embed=v.embed("Ban aplicado", "Razón: spam", kind="ban"))
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Acceso a un emoji por nombre o rol ────────────────────────────────
    def get(self, name_or_role: str) -> str:
        """Devuelve la string del emoji por nombre exacto (catbot07) o rol (success).
        Si no está cargado todavía o no existe, devuelve un fallback Unicode."""
        catbot = getattr(self.bot, "catbot", None) or {}

        # ¿es un rol?
        if name_or_role in ROLE_TO_EMOJI:
            key = ROLE_TO_EMOJI[name_or_role]
            return catbot.get(key) or ROLE_FALLBACK.get(name_or_role, "")

        # ¿es un nombre exacto catbotNN?
        return catbot.get(name_or_role, "")

    # ── Línea con prefijo de emoji ────────────────────────────────────────
    def line(self, role: str, text: str) -> str:
        emoji = self.get(role)
        return f"{emoji} {text}".strip()

    # ── Embed de marca ────────────────────────────────────────────────────
    def embed(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        kind: str = "info",
        url: Optional[str] = None,
    ) -> discord.Embed:
        color_map = {
            "success": BRAND_SUCCESS,
            "error": BRAND_DANGER,
            "warning": BRAND_WARNING,
            "ban": BRAND_DANGER,
            "info": BRAND_INFO,
            "loading": BRAND_NEUTRAL,
            "tip": BRAND_ACCENT,
            "help": BRAND_ACCENT,
            "log": BRAND_NEUTRAL,
            "stats": BRAND_ACCENT,
            "money": BRAND_WARNING,
            "gift": BRAND_ACCENT,
            "star": BRAND_WARNING,
            "boss": BRAND_ACCENT,
            "trophy": BRAND_WARNING,
            "hype": BRAND_ACCENT,
            "love": BRAND_ACCENT,
        }
        color = color_map.get(kind, BRAND_ACCENT)

        emoji = self.get(kind)
        full_title = f"{emoji} {title}".strip() if title else None

        embed = discord.Embed(
            title=full_title,
            description=description,
            color=color,
            url=url,
        )
        # Firma sutil con la pata morada (catbot37) si existe
        paw = self.get("paw")
        if paw:
            embed.set_footer(text=f"Cat's Bot · {paw}".strip())
        else:
            embed.set_footer(text="Cat's Bot")
        return embed


class Catbot(commands.Cog):
    """Cog que monta la identidad de Cat's Bot en `bot.catbot` y `bot.catbot_voice`."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Inicializa estructuras vacías inmediatamente para que cualquier cog
        # pueda usarlas antes de que llegue on_ready (devolverá fallbacks).
        if not hasattr(bot, "catbot"):
            bot.catbot = {}
        if not hasattr(bot, "catbot_voice"):
            bot.catbot_voice = CatbotVoice(bot)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            app_emojis = await self.bot.fetch_application_emojis()
        except Exception as exc:
            logger.warning("No se pudieron cargar los Application Emojis: %s", exc)
            return

        self.bot.catbot = {e.name: str(e) for e in app_emojis}
        logger.info(
            "Cat's Bot emojis cargados: %d (%s)",
            len(self.bot.catbot),
            ", ".join(sorted(self.bot.catbot.keys())[:5]) + " …",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Catbot(bot))
