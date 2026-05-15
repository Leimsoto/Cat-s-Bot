"""
cogs/levels.py
──────────────
Sistema de Niveles / XP.

Comandos de uso:
  /rank [@usuario]         — Tarjeta de rango
  /leaderboard             — Top 10 del servidor
  /xp give @usuario N      — [admin] Dar XP manualmente
  /xp reset @usuario       — [admin] Resetear XP

Configuración: Panel Web → Módulo Niveles
  (XP min/max, cooldown, canal anuncios, recompensas de nivel, roles apilados)

Fórmula: xp_para_nivel_N = 5N² + 50N + 100 (acumulado MEE6)
"""

import json
import logging
import random
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

MEDALS = ["🥇", "🥈", "🥉"]


def _xp_to_next_level(current_level: int) -> int:
    n = current_level + 1
    return 5 * n * n + 50 * n + 100


def _xp_in_current_level(total_xp: int, current_level: int) -> int:
    from database.manager import DatabaseManager
    base = DatabaseManager._xp_for_level(current_level)
    return total_xp - base


def _progress_bar(current: int, total: int, length: int = 12) -> str:
    filled = int(length * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (length - filled)
    return f"`[{bar}]`"


# ── Cog ───────────────────────────────────────────────────────────────────────

class Levels(commands.Cog):
    """Sistema de niveles y XP con recompensas de roles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self._xp_cooldown: dict = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cfg = self.db.get_xp_config(message.guild.id)
        if not cfg.get("enabled"):
            return

        try:
            ignored = json.loads(cfg.get("ignored_channels") or "[]")
        except Exception:
            ignored = []
        if message.channel.id in ignored:
            return

        key = (message.guild.id, message.author.id)
        now_ts = datetime.now(timezone.utc).timestamp()
        cooldown = int(cfg.get("cooldown_seconds", 60))
        last_ts = self._xp_cooldown.get(key, 0)
        if now_ts - last_ts < cooldown:
            return

        self._xp_cooldown[key] = now_ts

        xp_min = int(cfg.get("xp_min", 15))
        xp_max = int(cfg.get("xp_max", 25))
        try:
            multipliers = json.loads(cfg.get("channel_multipliers") or "{}")
        except Exception:
            multipliers = {}
        multiplier = float(multipliers.get(str(message.channel.id), 1.0))
        xp_gained = int(random.randint(xp_min, xp_max) * multiplier)

        result = self.db.add_xp(message.author.id, message.guild.id, xp_gained)

        if result["leveled_up"]:
            await self._announce_levelup(message, result["level"], cfg)
            await self._assign_reward(message.author, message.guild, result["level"], cfg)

    async def _announce_levelup(self, message: discord.Message, new_level: int, cfg: dict):
        """
        Anuncia subida de nivel respetando las opciones de configuración:
          • announcement_mode ("same"|"channel")  → dónde anunciar.
              "same"    = canal donde el usuario subió de nivel.
              "channel" = canal predeterminado (announcement_channel_id).
              Sin configurar: si hay announcement_channel_id → "channel", si no → "same".
          • levelup_persist (1)            → no autoeliminar.
          • levelup_autodelete (0)         → si 1, aplica delete_after.
          • levelup_delete_after_seconds   → segundos antes de borrar.
          • levelup_embed_config (JSON)    → forma MessageEditor (content + embed)
            o legacy (campos sueltos). Si está vacío → texto plano legacy.
        """
        from cogs._message_payload import render_message_payload

        voice = getattr(self.bot, "catbot_voice", None)
        star = voice.get("star") if voice else "⭐"
        default_msg = f"{star} ¡{{user}} acaba de subir al **nivel {{level}}**! El gato está orgulloso."

        variables = {
            "user": message.author.mention,
            "username": message.author.display_name,
            "level": str(new_level),
            "server": message.guild.name,
        }

        embed = None
        content = None
        embed_raw = cfg.get("levelup_embed_config")
        if embed_raw:
            payload = render_message_payload(
                embed_raw, variables, member=message.author,
                default_color=int(discord.Color.gold()),
            )
            content = payload["content"]
            embed = payload["embed"]

        if embed is None and not content:
            # Fallback: texto plano configurable.
            custom_msg = cfg.get("announcement_message") or default_msg
            content = (
                custom_msg
                .replace("{user}", message.author.mention)
                .replace("{level}", str(new_level))
                .replace("{username}", message.author.display_name)
            )

        # Calcular delete_after a partir de las flags.
        persist = int(cfg.get("levelup_persist", 1) or 0)
        autodel = int(cfg.get("levelup_autodelete", 0) or 0)
        ttl = int(cfg.get("levelup_delete_after_seconds", 30) or 30)
        delete_after = None
        if not persist or autodel:
            delete_after = max(1, ttl)

        send_kwargs = {}
        if embed is not None:
            send_kwargs["embed"] = embed
        if content:
            send_kwargs["content"] = content
        if delete_after is not None:
            send_kwargs["delete_after"] = delete_after

        mode = (cfg.get("announcement_mode") or "").strip().lower()
        ann_ch_id = cfg.get("announcement_channel_id")
        if not mode:
            mode = "channel" if ann_ch_id else "same"

        if mode == "channel" and ann_ch_id:
            channel = message.guild.get_channel(int(ann_ch_id))
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(**send_kwargs)
                    return
                except discord.Forbidden:
                    pass

        try:
            await message.channel.send(**send_kwargs)
        except discord.Forbidden:
            pass

    async def _assign_reward(self, member: discord.Member, guild: discord.Guild,
                              level: int, cfg: dict):
        reward = self.db.get_level_reward(guild.id, level)
        if not reward:
            return

        role = guild.get_role(int(reward["role_id"]))
        if not role:
            return

        stack = bool(cfg.get("stack_rewards", 1))
        try:
            if not stack:
                all_rewards = self.db.get_level_rewards(guild.id)
                reward_role_ids = {int(r["role_id"]) for r in all_rewards if int(r["level"]) < level}
                roles_to_remove = [r for r in member.roles if r.id in reward_role_ids]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason=f"Nivel {level} — reemplazo de rol")
            await member.add_roles(role, reason=f"Recompensa nivel {level}")
        except discord.Forbidden:
            logger.warning(f"Sin permisos para asignar rol de nivel {level} en {guild.name}")

    # ── Slash Commands de uso ─────────────────────────────────────────────────
    # Nota: /xp config, /xp setannouncechannel, /xp ignorechannel y
    #       /xp reward add/remove/list han sido eliminados.
    #       Usa el Dashboard Web → Módulo Niveles para configurar el sistema.

    @app_commands.command(name="rango", description="Muestra tu rango o el de otro usuario")
    @app_commands.describe(usuario="Usuario del que ver el rango (opcional)")
    async def rank(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        data = self.db.get_user_level(target.id, interaction.guild_id)

        total_xp = int(data["xp"])
        level = int(data["level"])
        xp_in_level = _xp_in_current_level(total_xp, level)
        xp_needed = _xp_to_next_level(level)
        bar = _progress_bar(xp_in_level, xp_needed)

        leaderboard = self.db.get_leaderboard(interaction.guild_id, limit=9999)
        position = next((i + 1 for i, r in enumerate(leaderboard) if int(r["user_id"]) == target.id), "—")

        embed = discord.Embed(title=f"🏅 Rango de {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Nivel", value=f"**{level}**", inline=True)
        embed.add_field(name="XP Total", value=f"**{total_xp:,}**", inline=True)
        embed.add_field(name="Posición", value=f"**#{position}**", inline=True)
        embed.add_field(
            name=f"Progreso → Nivel {level + 1}",
            value=f"{bar} `{xp_in_level:,} / {xp_needed:,} XP`",
            inline=False,
        )
        embed.set_footer(text=f"Mensajes totales: {data['message_count']:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clasificacion", description="Top 10 del servidor por XP")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = self.db.get_leaderboard(interaction.guild_id, limit=10)
        if not rows:
            return await interaction.followup.send("📭 Nadie tiene XP en este servidor todavía.")

        embed = discord.Embed(
            title=f"🏆 Tabla de Clasificación — {interaction.guild.name}",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        lines = []
        for i, row in enumerate(rows):
            member = interaction.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else f"ID:{row['user_id']}"
            medal = MEDALS[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{medal} **{name}** — Nivel {row['level']} · {int(row['xp']):,} XP")

        embed.description = "\n".join(lines)
        embed.set_footer(text="Actualizado al momento de ejecutar el comando")
        await interaction.followup.send(embed=embed)

    xp_group = app_commands.Group(
        name="xp",
        description="Gestión del sistema XP",
        default_permissions=discord.Permissions(administrator=True),
    )

    @xp_group.command(name="give", description="[Admin] Regala XP a un usuario")
    @app_commands.describe(usuario="Usuario al que dar XP", cantidad="Cantidad de XP a dar")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_give(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        voice = getattr(self.bot, "catbot_voice", None)
        if cantidad <= 0:
            msg = (
                voice.line("error", "El gato no acepta cantidades de cero o negativas.")
                if voice
                else "❌ La cantidad debe ser mayor que 0."
            )
            return await interaction.response.send_message(msg, ephemeral=True)
        result = self.db.add_xp(usuario.id, interaction.guild_id, cantidad)
        treat = voice.get("treat") if voice else "🍪"
        await interaction.response.send_message(
            f"{treat} **+{cantidad} XP** para {usuario.mention}. Ahora lleva **{result['xp']:,} XP** (Nivel {result['level']}).",
            ephemeral=True,
        )
        if result["leveled_up"]:
            cfg = self.db.get_xp_config(interaction.guild_id)
            await self._assign_reward(usuario, interaction.guild, result["level"], cfg)

    @xp_group.command(name="reset", description="[Admin] Resetea el XP de un usuario")
    @app_commands.describe(usuario="Usuario a resetear")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_reset(self, interaction: discord.Interaction, usuario: discord.Member):
        self.db.reset_user_level(usuario.id, interaction.guild_id)
        voice = getattr(self.bot, "catbot_voice", None)
        success = voice.get("success") if voice else "✅"
        await interaction.response.send_message(
            f"{success} El gato borró todo el XP de {usuario.mention}. Vuelta a empezar.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
