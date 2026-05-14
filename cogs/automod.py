import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.(?:com|gg)"
    r"|discord\.me|discordservers\.com)"
    r"(?:\/invite)?\/([a-zA-Z0-9\-_]+)"
)

URL_RE = re.compile(r"https?://\S+")


class AutoModActions:
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"

    ALL = (WARN, MUTE, KICK, BAN)

    @classmethod
    def parse(cls, action: str) -> Optional[str]:
        a = action.strip().lower()
        return a if a in cls.ALL else None


class SpamTracker:
    def __init__(self):
        self._data: Dict[tuple, list] = defaultdict(list)

    def record(self, guild_id: int, user_id: int) -> None:
        key = (guild_id, user_id)
        now = time.monotonic()
        self._data[key].append(now)

    def count_in_window(self, guild_id: int, user_id: int, window: int) -> int:
        key = (guild_id, user_id)
        now = time.monotonic()
        cutoff = now - window
        messages = [t for t in self._data[key] if t > cutoff]
        self._data[key] = messages
        return len(messages)

    def cleanup(self) -> None:
        now = time.monotonic()
        for key in list(self._data.keys()):
            self._data[key] = [t for t in self._data[key] if t > now - 120]
            if not self._data[key]:
                del self._data[key]


class AutoMod(commands.Cog):
    """Sistema de automoderación con reglas configurables por servidor.

    Reglas:
      • spam       → control de frecuencia de mensajes
      • mentions   → límite de menciones por mensaje
      • caps       → bloqueo de mayúsculas excesivas
      • links      → bloqueo de enlaces (con lista blanca)
      • banned_words → bloqueo de palabras prohibidas
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self.spam_tracker = SpamTracker()

    async def cog_load(self):
        self.bot.loop.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await discord.utils.sleep_until(
                datetime.now(timezone.utc).replace(second=0) + __import__("datetime").timedelta(minutes=5)
            )
            self.spam_tracker.cleanup()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        cfg = self.db.get_automod_config(guild_id)
        if not cfg.get("enabled"):
            return

        rules = cfg.get("rules", {})
        ignored_channels = set(rules.get("ignored", {}).get("channels", []))
        if message.channel.id in ignored_channels:
            return

        member = message.author
        ignored_roles = set(rules.get("ignored", {}).get("roles", []))
        if any(r.id in ignored_roles for r in member.roles):
            return

        content = message.content or ""
        actions: List[str] = []

        for rule_name, check in [
            ("banned_words", self._check_banned_words),
            ("links", self._check_links),
            ("mentions", self._check_mentions),
            ("caps", self._check_caps),
            ("spam", self._check_spam),
        ]:
            rule_cfg = rules.get(rule_name, {})
            if not rule_cfg.get("enabled", False):
                continue
            result = check(member, content, message, rule_cfg)
            if result:
                actions.append(result)

        if not actions:
            return

        action = actions[0]
        await self._execute_action(message, action, rules)

    def _check_spam(self, member: discord.Member, content: str,
                    message: discord.Message, cfg: dict) -> Optional[str]:
        self.spam_tracker.record(message.guild.id, member.id)

        for threshold_key, timeframe_key, action in [
            ("ban_threshold", "ban_timeframe", AutoModActions.BAN),
            ("kick_threshold", "kick_timeframe", AutoModActions.KICK),
            ("mute_threshold", "mute_timeframe", AutoModActions.MUTE),
            ("warn_threshold", "warn_timeframe", AutoModActions.WARN),
        ]:
            threshold = int(cfg.get(threshold_key, 0))
            if not threshold:
                continue
            window = int(cfg.get(timeframe_key, 10))
            count = self.spam_tracker.count_in_window(
                message.guild.id, member.id, window
            )
            if count >= threshold:
                return action
        return None

    def _check_mentions(self, member: discord.Member, content: str,
                        message: discord.Message, cfg: dict) -> Optional[str]:
        max_m = int(cfg.get("max_mentions", 5))
        total = len(message.mentions) + len(message.role_mentions)
        if total > max_m:
            return AutoModActions.parse(cfg.get("action", "warn"))
        return None

    def _check_caps(self, member: discord.Member, content: str,
                    message: discord.Message, cfg: dict) -> Optional[str]:
        min_len = int(cfg.get("min_length", 15))
        if len(content) < min_len:
            return None
        letters = [c for c in content if c.isalpha()]
        if not letters:
            return None
        pct = sum(1 for c in letters if c.isupper()) / len(letters) * 100
        if pct >= int(cfg.get("min_percent", 70)):
            return AutoModActions.parse(cfg.get("action", "warn"))
        return None

    def _check_links(self, member: discord.Member, content: str,
                     message: discord.Message, cfg: dict) -> Optional[str]:
        whitelist: List[str] = cfg.get("whitelist", [])
        if whitelist and any(d in content for d in whitelist):
            return None
        if cfg.get("block_invites", True) and INVITE_RE.search(content):
            return AutoModActions.parse(cfg.get("action", "warn"))
        if URL_RE.search(content):
            return AutoModActions.parse(cfg.get("action", "warn"))
        return None

    def _check_banned_words(self, member: discord.Member, content: str,
                            message: discord.Message, cfg: dict) -> Optional[str]:
        # Bug fix: substring matching causaba falsos positivos (ej. "ass"
        # disparaba en "pass", "class"). Ahora hace match por palabra completa
        # con regex word-boundary, case-insensitive.
        words: List[str] = cfg.get("words", [])
        if not words:
            return None
        for w in words:
            w_clean = w.strip()
            if not w_clean:
                continue
            pattern = r"\b" + re.escape(w_clean) + r"\b"
            if re.search(pattern, content, re.IGNORECASE):
                return AutoModActions.parse(cfg.get("action", "warn"))
        return None

    async def _execute_action(self, message: discord.Message, action: str, rules: dict) -> None:
        member = message.author
        guild = message.guild
        reason = f"AutoMod: {action} automático"

        self.db.log_automod_action(guild.id, action, member.id, message.content or "", action)

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if action == AutoModActions.WARN:
            warns = self.db.add_warn(member.id, guild.id)
            self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_WARN", reason)
            embed = discord.Embed(
                title="Advertencia automática",
                description=f"{member.mention} — {reason}",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Warns actuales", value=str(warns), inline=True)
            await self._send_to_channel(guild, embed)

        elif action == AutoModActions.MUTE:
            cfg = self.db.get_config(guild.id)
            mute_role = guild.get_role(cfg.get("mute_role_id") or 0)
            if not mute_role:
                return
            dur = int(rules.get("spam", {}).get("mute_duration", 3600))
            self.db.set_mute(member.id, guild.id, dur)
            self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_MUTE", reason)
            try:
                await member.add_roles(mute_role, reason=reason)
            except discord.Forbidden:
                pass

        elif action == AutoModActions.KICK:
            self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_KICK", reason)
            try:
                await member.kick(reason=reason)
            except discord.Forbidden:
                pass

        elif action == AutoModActions.BAN:
            self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_BAN", reason)
            try:
                await member.ban(reason=reason, delete_message_days=0)
            except discord.Forbidden:
                pass

    async def _send_to_channel(self, guild: discord.Guild, embed: discord.Embed) -> None:
        srv = self.db.get_server_config(guild.id)
        ch_id = srv.get("modlog_channel")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch and isinstance(ch, discord.TextChannel):
            try:
                await ch.send(embed=embed)
            except discord.Forbidden:
                pass

    automod_group = app_commands.Group(
        name="automod",
        description="Configuración del sistema de automoderación",
        default_permissions=discord.Permissions(administrator=True),
    )

    @automod_group.command(name="status", description="Muestra el estado actual de la automoderación")
    async def automod_status(self, interaction: discord.Interaction):
        cfg = self.db.get_automod_config(interaction.guild_id)
        rules = cfg.get("rules", {})

        embed = discord.Embed(
            title="Automoderación",
            description=f"Estado: {'**Activada**' if cfg.get('enabled') else '**Desactivada**'}",
            color=discord.Color.green() if cfg.get("enabled") else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )

        labels = {
            "spam": "Anti-Spam",
            "mentions": "Límite de Menciones",
            "caps": "Anti-Mayúsculas",
            "links": "Bloqueo de Enlaces",
            "banned_words": "Palabras Prohibidas",
        }

        for key, label in labels.items():
            rule = rules.get(key, {})
            status = "✅" if rule.get("enabled") else "❌"
            action = rule.get("action", "warn")
            embed.add_field(
                name=f"{status} {label}",
                value=f"Acción: `{action}`" if rule.get("enabled") else "Desactivado",
                inline=True,
            )

        try:
            logs = self.db.get_automod_log(interaction.guild_id, limit=5)
        except Exception:
            logs = []
        if logs:
            lines = []
            for log in logs[:3]:
                action = log["action_taken"]
                uid = log["user_id"]
                lines.append(f"`{action}` → <@{uid}>")
            embed.add_field(
                name="Últimas acciones",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="Últimas acciones", value="Ninguna aún", inline=False)

        embed.set_footer(text="Usa el Dashboard Web para configurar las reglas")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="toggle", description="Activa o desactiva la automoderación")
    @app_commands.describe(activar="True = activar, False = desactivar")
    async def automod_toggle(self, interaction: discord.Interaction, activar: bool):
        self.db.set_automod_config(interaction.guild_id, enabled=int(activar))
        voice = getattr(self.bot, "catbot_voice", None)
        if activar:
            msg = (
                voice.line("success", "Automod activado. El gato vigila el chat.")
                if voice else "✅ Activada la automoderación."
            )
        else:
            msg = (
                voice.line("afk", "Automod desactivado. El gato se va a dormir.")
                if voice else "❌ Desactivada la automoderación."
            )
        await interaction.response.send_message(msg, ephemeral=True)

    @automod_group.command(name="log", description="Muestra el registro de acciones de automoderación")
    @app_commands.describe(limite="Cuantos registros mostrar (máx 20)")
    async def automod_log(self, interaction: discord.Interaction, limite: int = 10):
        limite = max(1, min(20, limite))
        logs = self.db.get_automod_log(interaction.guild_id, limit=limite)
        if not logs:
            voice = getattr(self.bot, "catbot_voice", None)
            msg = (
                voice.line("info", "El gato no ha tenido que actuar todavía. Sin registros.")
                if voice else "📭 No hay registros de automoderación."
            )
            return await interaction.response.send_message(msg, ephemeral=True)

        embed = discord.Embed(
            title="Registro de Automoderación",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for log in logs[:limite]:
            action = log["action_taken"]
            uid = log["user_id"]
            rule = log["rule"]
            ts = (log.get("created_at") or "")[:16].replace("T", " ")
            embed.add_field(
                name=f"{ts} — {rule}",
                value=f"`{action}` → <@{uid}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
