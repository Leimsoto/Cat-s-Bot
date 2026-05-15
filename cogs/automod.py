"""
cogs/automod.py
───────────────
Cog de automoderación.

Vigila los mensajes en tiempo real y aplica acciones automáticas según las
reglas configuradas desde el dashboard. Las reglas son por servidor y se
guardan como JSON en ``automod_settings.rules``.

Reglas soportadas
─────────────────
  • spam          → frecuencia de mensajes en una ventana temporal.
  • mentions      → límite de menciones (usuarios + roles) por mensaje.
  • caps          → porcentaje de mayúsculas.
  • links         → bloqueo de enlaces y/o invitaciones de Discord.
  • banned_words  → palabras prohibidas (match por palabra completa).
  • duplicate     → repetición del mismo mensaje en ventana corta.
  • emoji_spam    → demasiados emojis por mensaje.

Cada regla soporta:
  • enabled:   bool
  • action:    warn | mute | kick | ban
  • mute_duration: segundos (solo si action=mute)
  • parámetros propios de la regla

Reglas comunes (clave ``ignored``):
  • channels:        list[int]
  • roles:           list[int]
  • exempt_admins:   bool (default True)
  • exempt_bots:     bool (default True)

Comandos slash
──────────────
  /automod status   – ver estado y últimas acciones.
  /automod toggle   – activar/desactivar globalmente.
  /automod log      – historial reciente.

La configuración detallada vive en el dashboard.
"""

import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("AutoMod")

# Invitaciones de Discord (todos los hosts comunes).
INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.(?:com|gg)"
    r"|discord\.me|discordservers\.com)"
    r"(?:/invite)?/([a-zA-Z0-9\-_]+)",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)

# Rango Unicode aproximado para emojis (incluye símbolos pictográficos).
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF]"
)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


class AutoModActions:
    """Acciones disponibles, ordenadas de menor a mayor severidad."""

    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"
    DELETE = "delete"  # solo borra, sin sanción.

    ORDER = (DELETE, WARN, MUTE, KICK, BAN)
    ALL = ORDER

    @classmethod
    def parse(cls, action: Optional[str]) -> str:
        a = (action or "").strip().lower()
        return a if a in cls.ALL else cls.WARN

    @classmethod
    def severity(cls, action: str) -> int:
        try:
            return cls.ORDER.index(action)
        except ValueError:
            return -1


class WindowTracker:
    """Tracker en memoria por (guild, user) con expiración automática."""

    def __init__(self, max_window_seconds: int = 600):
        self._timestamps: Dict[Tuple[int, int], Deque[float]] = defaultdict(deque)
        self._content: Dict[Tuple[int, int], Deque[Tuple[float, str]]] = defaultdict(deque)
        self._max_window = max_window_seconds

    def record_message(self, guild_id: int, user_id: int, content: str) -> None:
        key = (guild_id, user_id)
        now = time.monotonic()
        self._timestamps[key].append(now)
        self._content[key].append((now, content[:120]))
        # Evita crecimiento ilimitado.
        cutoff = now - self._max_window
        self._prune(self._timestamps[key], cutoff)
        self._prune_content(self._content[key], cutoff)

    @staticmethod
    def _prune(dq: Deque[float], cutoff: float) -> None:
        while dq and dq[0] < cutoff:
            dq.popleft()

    @staticmethod
    def _prune_content(dq: Deque[Tuple[float, str]], cutoff: float) -> None:
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def messages_in(self, guild_id: int, user_id: int, window: int) -> int:
        key = (guild_id, user_id)
        cutoff = time.monotonic() - window
        return sum(1 for t in self._timestamps[key] if t >= cutoff)

    def duplicates_in(self, guild_id: int, user_id: int, window: int, content: str) -> int:
        key = (guild_id, user_id)
        cutoff = time.monotonic() - window
        snippet = content[:120]
        return sum(1 for t, c in self._content[key] if t >= cutoff and c == snippet)

    def cleanup(self) -> None:
        cutoff = time.monotonic() - self._max_window
        for key in list(self._timestamps.keys()):
            self._prune(self._timestamps[key], cutoff)
            if not self._timestamps[key]:
                del self._timestamps[key]
        for key in list(self._content.keys()):
            self._prune_content(self._content[key], cutoff)
            if not self._content[key]:
                del self._content[key]


class AutoMod(commands.Cog):
    """Sistema de automoderación profesional con reglas modulares."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self.tracker = WindowTracker()
        self._cleanup_task: Optional[discord.utils._MissingSentinel] = None

    async def cog_load(self):
        self._cleanup_task = self.bot.loop.create_task(self._cleanup_loop())

    async def cog_unload(self):
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

    async def _cleanup_loop(self):
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                next_run = datetime.now(timezone.utc) + timedelta(minutes=5)
                await discord.utils.sleep_until(next_run.replace(microsecond=0))
                self.tracker.cleanup()
        except discord.utils._MissingSentinel:
            return

    # ── Listener principal ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        cfg = self.db.get_automod_config(message.guild.id)
        if not cfg.get("enabled"):
            return

        rules = cfg.get("rules", {}) or {}
        ignored = rules.get("ignored", {}) or {}
        if message.channel.id in set(ignored.get("channels", []) or []):
            return

        member = message.author
        if isinstance(member, discord.Member):
            ignored_role_ids = set(ignored.get("roles", []) or [])
            if any(r.id in ignored_role_ids for r in member.roles):
                return
            if ignored.get("exempt_admins", True) and member.guild_permissions.administrator:
                return

        content = message.content or ""
        self.tracker.record_message(message.guild.id, member.id, content)

        triggered: List[Tuple[str, str]] = []  # (rule, action)
        for rule_name, check in (
            ("banned_words", self._check_banned_words),
            ("links", self._check_links),
            ("mentions", self._check_mentions),
            ("caps", self._check_caps),
            ("emoji_spam", self._check_emoji_spam),
            ("duplicate", self._check_duplicate),
            ("spam", self._check_spam),
        ):
            rule_cfg = rules.get(rule_name) or {}
            if not rule_cfg.get("enabled"):
                continue
            action = check(member, content, message, rule_cfg)
            if action:
                triggered.append((rule_name, action))

        if not triggered:
            return

        # Elige la acción de mayor severidad entre los triggers.
        rule_name, action = max(
            triggered, key=lambda x: AutoModActions.severity(x[1])
        )
        await self._execute_action(message, rule_name, action, rules.get(rule_name) or {})

    # ── Checks ──────────────────────────────────────────────────────────────

    def _check_spam(self, member, content, message, cfg) -> Optional[str]:
        for threshold_key, window_key, action in (
            ("ban_threshold", "ban_timeframe", AutoModActions.BAN),
            ("kick_threshold", "kick_timeframe", AutoModActions.KICK),
            ("mute_threshold", "mute_timeframe", AutoModActions.MUTE),
            ("warn_threshold", "warn_timeframe", AutoModActions.WARN),
        ):
            threshold = int(cfg.get(threshold_key) or 0)
            if threshold <= 0:
                continue
            window = max(1, int(cfg.get(window_key) or 10))
            count = self.tracker.messages_in(message.guild.id, member.id, window)
            if count >= threshold:
                return action
        return None

    def _check_duplicate(self, member, content, message, cfg) -> Optional[str]:
        if not content.strip():
            return None
        threshold = max(2, int(cfg.get("threshold") or 3))
        window = max(2, int(cfg.get("window") or 30))
        repeats = self.tracker.duplicates_in(message.guild.id, member.id, window, content)
        if repeats >= threshold:
            return AutoModActions.parse(cfg.get("action"))
        return None

    def _check_mentions(self, member, content, message, cfg) -> Optional[str]:
        max_m = int(cfg.get("max_mentions") or 5)
        total = len(message.mentions) + len(message.role_mentions)
        if total > max_m:
            return AutoModActions.parse(cfg.get("action"))
        return None

    def _check_caps(self, member, content, message, cfg) -> Optional[str]:
        min_len = int(cfg.get("min_length") or 15)
        if len(content) < min_len:
            return None
        letters = [c for c in content if c.isalpha()]
        if len(letters) < 3:
            return None
        pct = sum(1 for c in letters if c.isupper()) / len(letters) * 100
        if pct >= int(cfg.get("min_percent") or 70):
            return AutoModActions.parse(cfg.get("action"))
        return None

    def _check_links(self, member, content, message, cfg) -> Optional[str]:
        block_invites = bool(cfg.get("block_invites", True))
        block_all = bool(cfg.get("block_all_urls", False))
        whitelist = {d.lower().strip() for d in cfg.get("whitelist") or [] if d}

        if block_invites and INVITE_RE.search(content):
            return AutoModActions.parse(cfg.get("action"))

        if not block_all:
            return None

        for match in URL_RE.finditer(content):
            host = match.group(1).lower()
            # Coincide con el whitelist por sufijo (ej. "youtube.com" cubre "m.youtube.com").
            if any(host == w or host.endswith("." + w) for w in whitelist):
                continue
            return AutoModActions.parse(cfg.get("action"))
        return None

    def _check_banned_words(self, member, content, message, cfg) -> Optional[str]:
        words: List[str] = cfg.get("words") or []
        if not words:
            return None
        for raw in words:
            w = (raw or "").strip()
            if not w:
                continue
            pattern = r"\b" + re.escape(w) + r"\b"
            if re.search(pattern, content, re.IGNORECASE):
                return AutoModActions.parse(cfg.get("action"))
        return None

    def _check_emoji_spam(self, member, content, message, cfg) -> Optional[str]:
        threshold = int(cfg.get("max_emojis") or 10)
        unicode_count = len(EMOJI_RE.findall(content))
        custom_count = len(CUSTOM_EMOJI_RE.findall(content))
        if unicode_count + custom_count > threshold:
            return AutoModActions.parse(cfg.get("action"))
        return None

    # ── Ejecución de acciones ───────────────────────────────────────────────

    async def _execute_action(
        self,
        message: discord.Message,
        rule_name: str,
        action: str,
        rule_cfg: dict,
    ) -> None:
        member = message.author
        guild = message.guild
        reason = f"AutoMod ({rule_name}): {action}"

        # Log persistente (orden correcto: rule, action_taken).
        try:
            self.db.log_automod_action(
                guild.id, rule_name, member.id, message.content or "", action
            )
        except Exception as exc:
            logger.warning("No se pudo persistir log_automod_action: %s", exc)

        # Siempre intenta borrar el mensaje (incluso si action=delete).
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if action == AutoModActions.DELETE:
            await self._log_to_modlog(guild, self._build_embed(rule_name, action, member, message.content or ""))
            return

        if action == AutoModActions.WARN:
            warns = self.db.add_warn(member.id, guild.id)
            self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_WARN", reason)
            embed = self._build_embed(rule_name, action, member, message.content or "", extra={"Warns totales": str(warns)})
            await self._log_to_modlog(guild, embed)
            return

        if action == AutoModActions.MUTE:
            mute_role = await self._resolve_mute_role(guild)
            if mute_role is None:
                logger.warning("Auto-mute saltado en %s: no hay rol de mute", guild.name)
                return
            dur = max(60, int(rule_cfg.get("mute_duration") or 3600))
            try:
                await member.add_roles(mute_role, reason=reason)
                self.db.set_mute(member.id, guild.id, dur)
                self.db.log_action(
                    guild.id, member.id, self.bot.user.id,
                    "AUTO_MUTE", reason, {"duration_secs": dur},
                )
                embed = self._build_embed(
                    rule_name, action, member, message.content or "",
                    extra={"Duración": f"{dur}s"},
                )
                await self._log_to_modlog(guild, embed)
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-mute en %s", guild.name)
            return

        if action == AutoModActions.KICK:
            try:
                await member.kick(reason=reason)
                self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_KICK", reason)
                await self._log_to_modlog(
                    guild, self._build_embed(rule_name, action, member, message.content or "")
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-kick en %s", guild.name)
            return

        if action == AutoModActions.BAN:
            try:
                await member.ban(reason=reason, delete_message_days=0)
                self.db.log_action(guild.id, member.id, self.bot.user.id, "AUTO_BAN", reason)
                await self._log_to_modlog(
                    guild, self._build_embed(rule_name, action, member, message.content or "")
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-ban en %s", guild.name)
            return

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _build_embed(
        self,
        rule_name: str,
        action: str,
        member: discord.abc.User,
        content: str,
        extra: Optional[Dict[str, str]] = None,
    ) -> discord.Embed:
        colors = {
            AutoModActions.DELETE: discord.Color.greyple(),
            AutoModActions.WARN: discord.Color.orange(),
            AutoModActions.MUTE: discord.Color.red(),
            AutoModActions.KICK: discord.Color.dark_orange(),
            AutoModActions.BAN: discord.Color.dark_red(),
        }
        embed = discord.Embed(
            title=f"AutoMod · {action.upper()}",
            description=f"Regla: **{rule_name}**\nUsuario: {member.mention} (`{member.id}`)",
            color=colors.get(action, discord.Color.blurple()),
            timestamp=datetime.now(timezone.utc),
        )
        if content:
            snippet = content if len(content) <= 500 else content[:497] + "…"
            embed.add_field(name="Mensaje", value=snippet, inline=False)
        for k, v in (extra or {}).items():
            embed.add_field(name=k, value=v, inline=True)
        return embed

    async def _resolve_mute_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Reutiliza el helper del cog Moderation si está disponible."""
        moderation_cog = self.bot.get_cog("Moderation")
        if moderation_cog and hasattr(moderation_cog, "_ensure_mute_role"):
            return await moderation_cog._ensure_mute_role(guild)
        # Fallback: lectura directa.
        cfg = self.db.get_config(guild.id)
        role_id = cfg.get("mute_role_id") or 0
        return guild.get_role(role_id) if role_id else None

    async def _log_to_modlog(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Envía el embed al canal de modlog, reutilizando el helper de Moderation."""
        moderation_cog = self.bot.get_cog("Moderation")
        if moderation_cog and hasattr(moderation_cog, "_send_log"):
            await moderation_cog._send_log(guild, embed)
            return
        # Fallback: sin helper, lectura directa con fetch como backup.
        srv = self.db.get_server_config(guild.id)
        if not srv.get("modlog_enabled", 1):
            return
        ch_id = srv.get("modlog_channel")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch is None:
            try:
                ch = await guild.fetch_channel(int(ch_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ── Slash commands ──────────────────────────────────────────────────────

    automod_group = app_commands.Group(
        name="automod",
        description="Estado y log de la automoderación (configuración en el dashboard)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @automod_group.command(name="status", description="Muestra el estado de la automoderación")
    async def automod_status(self, interaction: discord.Interaction):
        cfg = self.db.get_automod_config(interaction.guild_id)
        rules = cfg.get("rules", {}) or {}

        enabled = bool(cfg.get("enabled"))
        embed = discord.Embed(
            title="AutoMod",
            description=f"Estado global: {'**Activado**' if enabled else '**Desactivado**'}",
            color=discord.Color.green() if enabled else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        labels = {
            "spam": "Anti-Spam",
            "duplicate": "Mensajes Repetidos",
            "mentions": "Límite de Menciones",
            "caps": "Anti-Mayúsculas",
            "links": "Enlaces",
            "banned_words": "Palabras Prohibidas",
            "emoji_spam": "Spam de Emojis",
        }
        for key, label in labels.items():
            rule = rules.get(key) or {}
            on = bool(rule.get("enabled"))
            mark = "✅" if on else "❌"
            value = f"Acción: `{rule.get('action', '—')}`" if on else "Desactivado"
            embed.add_field(name=f"{mark} {label}", value=value, inline=True)

        try:
            logs = self.db.get_automod_log(interaction.guild_id, limit=3)
        except Exception:
            logs = []
        if logs:
            recent = "\n".join(
                f"`{log['action_taken']}` · {log['rule']} → <@{log['user_id']}>"
                for log in logs
            )
            embed.add_field(name="Últimas acciones", value=recent, inline=False)

        embed.set_footer(text="Configura las reglas desde el Dashboard Web.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="toggle", description="Activa o desactiva la automoderación globalmente")
    @app_commands.describe(activar="True = activar, False = desactivar")
    async def automod_toggle(self, interaction: discord.Interaction, activar: bool):
        self.db.set_automod_config(interaction.guild_id, enabled=int(activar))
        msg = "✅ Automoderación activada." if activar else "🛑 Automoderación desactivada."
        await interaction.response.send_message(msg, ephemeral=True)

    @automod_group.command(name="log", description="Últimas acciones de automoderación")
    @app_commands.describe(limite="Cuantos registros mostrar (1-20)")
    async def automod_log(self, interaction: discord.Interaction, limite: int = 10):
        limite = max(1, min(20, limite))
        logs = self.db.get_automod_log(interaction.guild_id, limit=limite)
        if not logs:
            return await interaction.response.send_message(
                "📭 No hay registros de automoderación.", ephemeral=True
            )

        embed = discord.Embed(
            title="Registro de Automoderación",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for log in logs[:limite]:
            ts = (log.get("created_at") or "")[:16].replace("T", " ")
            embed.add_field(
                name=f"{ts} · {log.get('rule', '?')}",
                value=f"`{log.get('action_taken', '?')}` → <@{log.get('user_id')}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
