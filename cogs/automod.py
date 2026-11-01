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

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from cogs._sanction_locks import (
    ban_reason_matches,
    new_ban_effect_token,
    new_mute_effect_token,
    reason_with_ban_effect,
    reason_with_mute_effect,
    run_sanction_locked,
)

from cogs._role_safety import (
    delegated_bot_role_ids,
    member_is_effectively_muted,
    mute_role_has_effective_denies,
    safe_for_automatic_assignment,
)
from cogs._llm_moderation import LLMReview, fingerprint
from cogs._moderation_history import action_metadata

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
        self._cleanup_task: Optional[asyncio.Task] = None
        self._action_cooldowns: Dict[Tuple[int, int, str, str], float] = {}
        self.llm = LLMReview(self)

    @staticmethod
    def _can_manage(interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        user = interaction.user
        if not guild or not isinstance(user, discord.Member):
            return False
        perms = user.guild_permissions
        return bool(user.id == guild.owner_id or perms.administrator or perms.manage_guild)

    @staticmethod
    def _enabled_flag(value: object, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    async def cog_load(self):
        self._cleanup_task = self.bot.loop.create_task(self._cleanup_loop())
        await self.llm.start()

    async def cog_unload(self):
        await self.llm.close()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

    async def _cleanup_loop(self):
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                next_run = datetime.now(timezone.utc) + timedelta(minutes=5)
                await discord.utils.sleep_until(next_run.replace(microsecond=0))
                self.tracker.cleanup()
                cutoff = time.monotonic() - 600
                self._action_cooldowns = {
                    key: timestamp
                    for key, timestamp in self._action_cooldowns.items()
                    if timestamp >= cutoff
                }
        except asyncio.CancelledError:
            return

    # ── Listener principal ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild:
            return

        cfg = self.db.get_automod_config(message.guild.id)
        if not self._enabled_flag(cfg.get("enabled")):
            self.llm.enqueue(message)
            return

        rules = cfg.get("rules", {}) or {}
        ignored = rules.get("ignored", {}) or {}
        if message.author.bot and self._enabled_flag(
            ignored.get("exempt_bots"), default=True
        ):
            return
        try:
            ignored_channel_ids = {
                int(channel_id) for channel_id in (ignored.get("channels", []) or [])
            }
            ignored_role_ids = {
                int(role_id) for role_id in (ignored.get("roles", []) or [])
            }
        except (TypeError, ValueError):
            return
        if message.channel.id in ignored_channel_ids:
            return

        member = message.author
        if isinstance(member, discord.Member):
            if any(r.id in ignored_role_ids for r in member.roles):
                return
            if member.id == message.guild.owner_id or member.guild_permissions.administrator:
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
            if not self._enabled_flag(rule_cfg.get("enabled")):
                continue
            action = check(member, content, message, rule_cfg)
            if action:
                triggered.append((rule_name, action))

        if not triggered:
            self.llm.enqueue(message)
            return

        # Elige la acción de mayor severidad entre los triggers.
        rule_name, action = max(
            triggered, key=lambda x: AutoModActions.severity(x[1])
        )
        rule_cfg = rules.get(rule_name) or {}
        if not self._action_allowed(message, rule_name, action, rule_cfg):
            # Mantiene el canal limpio, pero no repite warns/sanciones/logs en cada
            # mensaje mientras el usuario siga por encima del mismo umbral.
            if await self._fresh_policy_allows_action(
                message, rule_name, action
            ):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return
        await self._execute_action(message, rule_name, action, rule_cfg)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if not any(field in payload.data for field in ("content", "attachments", "sticker_items")):
            return
        self.llm.enqueue(payload=payload)

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

    def _action_allowed(
        self,
        message: discord.Message,
        rule_name: str,
        action: str,
        rule_cfg: dict,
    ) -> bool:
        """Evita sanciones repetidas mientras una ventana sigue sobre el umbral."""
        configured = rule_cfg.get("action_cooldown_seconds")
        if configured is None:
            if rule_name == "spam":
                windows = [
                    int(rule_cfg.get(key) or 0)
                    for key in ("warn_timeframe", "mute_timeframe", "kick_timeframe", "ban_timeframe")
                ]
                configured = max(windows or [30])
            elif rule_name == "duplicate":
                configured = int(rule_cfg.get("window") or 30)
            else:
                configured = 30
        cooldown = max(1, int(configured or 30))
        key = (message.guild.id, message.author.id, rule_name, action)
        now = time.monotonic()
        last = self._action_cooldowns.get(key, 0.0)
        if now - last < cooldown:
            return False
        self._action_cooldowns[key] = now
        return True

    def _current_policy_allows_action(
        self,
        message: discord.Message,
        live_member: discord.Member,
        live_roles: List[discord.Role],
        owner_id: int,
        rule_name: str,
        expected_action: str,
    ) -> Optional[dict]:
        """Revalida política, exenciones y acción sin awaits antes del sink."""
        if rule_name == "llm":
            return self.llm.current_policy(message, live_member, live_roles, owner_id, expected_action)
        roles_by_id = {int(role.id): role for role in live_roles}
        role_ids = {message.guild.id}
        role_ids.update(
            int(role_id) for role_id in getattr(live_member, "_roles", ())
        )
        if any(role_id not in roles_by_id for role_id in role_ids):
            return None
        permissions_value = 0
        for role_id in role_ids:
            permissions_value |= int(roles_by_id[role_id].permissions.value)
        permissions = discord.Permissions(permissions_value)

        try:
            live_cfg = self.db.get_automod_config(message.guild.id)
            live_rules = live_cfg.get("rules", {}) or {}
            live_rule_cfg = live_rules.get(rule_name) or {}
            live_ignored = live_rules.get("ignored", {}) or {}
            ignored_channels = {
                int(channel_id)
                for channel_id in (live_ignored.get("channels", []) or [])
            }
            ignored_roles = {
                int(role_id)
                for role_id in (live_ignored.get("roles", []) or [])
            }
        except (AttributeError, TypeError, ValueError):
            return None

        live_check = {
            "banned_words": self._check_banned_words,
            "links": self._check_links,
            "mentions": self._check_mentions,
            "caps": self._check_caps,
            "emoji_spam": self._check_emoji_spam,
            "duplicate": self._check_duplicate,
            "spam": self._check_spam,
        }.get(rule_name)
        try:
            current_action = (
                live_check(
                    live_member,
                    message.content or "",
                    message,
                    live_rule_cfg,
                )
                if live_check is not None
                else None
            )
        except (AttributeError, TypeError, ValueError):
            return None

        allowed = bool(
            self._enabled_flag(live_cfg.get("enabled"))
            and self._enabled_flag(live_rule_cfg.get("enabled"))
            and current_action == expected_action
            and message.channel.id not in ignored_channels
            and live_member.id != int(owner_id)
            and not permissions.administrator
            and not any(role_id in ignored_roles for role_id in role_ids)
            and not (
                live_member.bot
                and self._enabled_flag(
                    live_ignored.get("exempt_bots"), default=True
                )
            )
        )
        return live_rule_cfg if allowed else None

    async def _fresh_policy_allows_action(
        self,
        message: discord.Message,
        rule_name: str,
        expected_action: str,
    ) -> bool:
        """Obtiene miembro, roles y propietario actuales antes de borrar."""
        guild = message.guild
        if guild is None:
            return False
        try:
            if rule_name == "llm":
                current_message = await message.channel.fetch_message(message.id)
                if fingerprint(current_message) != fingerprint(message):
                    return False
            live_member, live_roles, live_guild = await asyncio.gather(
                guild.fetch_member(message.author.id),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
        return self._current_policy_allows_action(
            message,
            live_member,
            live_roles,
            int(live_guild.owner_id),
            rule_name,
            expected_action,
        ) is not None

    async def _execute_action(
        self,
        message: discord.Message,
        rule_name: str,
        action: str,
        rule_cfg: dict,
    ) -> None:
        deletion_notices = []
        try:
            if rule_name == "llm" and action == AutoModActions.DELETE:
                async def apply_delete():
                    await self._apply_action(message, rule_name, action, rule_cfg, deletion_notices)
                await run_sanction_locked(self.bot, message.guild.id, message.id, "LLM_MESSAGE_DELETE", apply_delete)
            else:
                await self._apply_action(message, rule_name, action, rule_cfg, deletion_notices)
        finally:
            # Wording generation must not delay a sanction or change its result.
            for decision in deletion_notices:
                await self.llm.notify_deleted(message, decision)

    async def _apply_action(
        self,
        message: discord.Message,
        rule_name: str,
        action: str,
        rule_cfg: dict,
        deletion_notices: list,
    ) -> None:
        member = message.author
        guild = message.guild
        reason = f"AutoMod ({rule_name}): {action}"
        if rule_name == "llm":
            if self.db.has_llm_message_action(guild.id, message.id):
                return
            reason = rule_cfg["reason"]
        elif rule_cfg is not None:
            self.llm.mark_deterministic(message.id)
        metadata = action_metadata(message, self.bot.user, rule_name,
                                   rule_cfg["llm_decision"] if rule_name == "llm" else None)
        case_kwargs = {"evidence_url": message.jump_url, "extra": metadata}

        def persist_action_outcome(outcome: str) -> None:
            if rule_name == "llm":
                self.llm.action_outcomes[message.id] = outcome
            try:
                self.db.log_automod_action(
                    guild.id,
                    rule_name,
                    member.id,
                    (f"message:{message.id} Motivo: {rule_cfg['llm_decision']['reason']} Regla: {rule_cfg['llm_decision']['rule']}"
                     if rule_name == "llm" else message.content or ""),
                    outcome,
                    extra=metadata,
                )
            except Exception as exc:
                logger.warning("No se pudo persistir log_automod_action: %s", type(exc).__name__)

        # Siempre intenta borrar el mensaje (incluso si action=delete).
        message_deleted = False
        if not await self._fresh_policy_allows_action(
            message, rule_name, action
        ):
            logger.warning(
                "Acción AutoMod saltada en %s: la política o exención cambió",
                guild.name,
            )
            return
        delete_case_id = None
        if rule_name == "llm" and action == AutoModActions.DELETE:
            delete_case_id = self.db.log_action(
                guild.id, member.id, self.bot.user.id, "AUTO_DELETE", reason,
                status="applying", **case_kwargs,
            )
            if not delete_case_id:
                raise RuntimeError("delete_intent_not_persisted")
        try:
            await message.delete()
            message_deleted = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        audit_extra = {}
        if rule_name == "llm":
            decision = rule_cfg["llm_decision"]
            audit_extra = {"Motivo": decision["reason"], "Regla aplicada": decision["rule"],
                           "Borrado": "Mensaje eliminado" if message_deleted else "No se pudo eliminar"}
            if message_deleted:
                if action != AutoModActions.DELETE:
                    self.llm.log(guild.id, member.id, message.id, "delete",
                                 f"Motivo: {decision['reason']} Regla: {decision['rule']}", extra=metadata)
                deletion_notices.append(decision)
            elif action != AutoModActions.DELETE:
                self.llm.log(guild.id, member.id, message.id, "delete_failed", decision["reason"])

        if action == AutoModActions.DELETE:
            if delete_case_id is not None:
                self.db.update_case_by_id(
                    guild.id, delete_case_id, status="active" if message_deleted else "failed",
                )
            persist_action_outcome(
                AutoModActions.DELETE if message_deleted else "delete_failed"
            )
            embed_action = "delete_failed" if rule_name == "llm" and not message_deleted else action
            await self._log_to_modlog(guild, self._build_embed(rule_name, embed_action, member, message.content or "", extra=audit_extra))
            return

        if action == AutoModActions.WARN:
            async def persist_auto_warn():
                try:
                    live_member, live_roles, live_guild = await asyncio.gather(
                        guild.fetch_member(member.id),
                        guild.fetch_roles(),
                        self.bot.fetch_guild(guild.id),
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "Auto-warn saltado en %s: no se pudo revalidar el objetivo",
                        guild.name,
                    )
                    return None

                if self._current_policy_allows_action(
                    message,
                    live_member,
                    live_roles,
                    int(live_guild.owner_id),
                    rule_name,
                    AutoModActions.WARN,
                ) is None:
                    logger.warning(
                        "Auto-warn saltado en %s: el objetivo quedó exento o protegido",
                        guild.name,
                    )
                    return None

                warns, _case_id = self.db.add_warn_with_action(
                    live_member.id,
                    guild.id,
                    self.bot.user.id,
                    "AUTO_WARN",
                    reason,
                    **case_kwargs,
                )
                return warns, live_member

            warn_result = await run_sanction_locked(
                self.bot,
                guild.id,
                member.id,
                "AUTO_WARN",
                persist_auto_warn,
            )
            if warn_result is None:
                return
            warns, warned_member = warn_result
            persist_action_outcome(AutoModActions.WARN)
            embed = self._build_embed(
                rule_name,
                action,
                warned_member,
                message.content or "",
                extra={**audit_extra, "Warns totales": str(warns)},
            )
            await self._log_to_modlog(guild, embed)
            return

        if action == AutoModActions.MUTE:
            async def apply_auto_mute():
                try:
                    policy_member, policy_roles, policy_guild = await asyncio.gather(
                        guild.fetch_member(member.id),
                        guild.fetch_roles(),
                        self.bot.fetch_guild(guild.id),
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return None
                if self._current_policy_allows_action(
                    message,
                    policy_member,
                    policy_roles,
                    int(policy_guild.owner_id),
                    rule_name,
                    AutoModActions.MUTE,
                ) is None:
                    return None

                mute_role = await self._resolve_mute_role(guild)
                if mute_role is None:
                    logger.warning(
                        "Auto-mute saltado en %s: no hay rol de mute", guild.name
                    )
                    return None
                try:
                    live_member, live_bot, live_roles, live_guild = await asyncio.gather(
                        guild.fetch_member(member.id),
                        guild.fetch_member(self.bot.user.id),
                        guild.fetch_roles(),
                        self.bot.fetch_guild(guild.id),
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "Auto-mute saltado en %s: no se pudo revalidar miembro, bot y roles",
                        guild.name,
                    )
                    return None

                roles_by_id = {int(role.id): role for role in live_roles}

                def live_role_state(current_member: discord.Member):
                    role_ids = {guild.id}
                    role_ids.update(
                        int(role_id) for role_id in getattr(current_member, "_roles", ())
                    )
                    if any(role_id not in roles_by_id for role_id in role_ids):
                        return None
                    roles = [roles_by_id[role_id] for role_id in role_ids]
                    permissions_value = 0
                    for role in roles:
                        permissions_value |= int(role.permissions.value)
                    return discord.Permissions(permissions_value), max(roles)

                member_state = live_role_state(live_member)
                bot_state = live_role_state(live_bot)
                live_mute_role = roles_by_id.get(int(mute_role.id))
                forbidden_role_ids = delegated_bot_role_ids(self.db, guild.id)
                if (
                    member_state is None
                    or bot_state is None
                    or live_mute_role is None
                    or forbidden_role_ids is None
                ):
                    logger.warning(
                        "Auto-mute saltado en %s: estado de roles incompleto",
                        guild.name,
                    )
                    return None

                member_permissions, member_top_role = member_state
                bot_permissions, bot_top_role = bot_state
                if (
                    live_member.bot
                    or live_member.id == int(live_guild.owner_id)
                    or member_permissions.administrator
                    or member_top_role >= bot_top_role
                    or live_mute_role >= bot_top_role
                    or not (
                        bot_permissions.administrator
                        or bot_permissions.view_audit_log
                    )
                    or not safe_for_automatic_assignment(
                        live_mute_role,
                        live_bot,
                        forbidden_role_ids=forbidden_role_ids,
                    )
                    or not mute_role_has_effective_denies(guild, live_mute_role)
                ):
                    logger.warning(
                        "Auto-mute saltado en %s: objetivo o rol no es gestionable de forma segura",
                        guild.name,
                    )
                    return None

                moderation_cog = self.bot.get_cog("Moderation")
                required_mute_methods = (
                    "_prepare_mute_record",
                    "_confirm_effective_mute",
                    "_confirm_mute_effect_state",
                )
                if not moderation_cog or not all(
                    callable(getattr(moderation_cog, method, None))
                    for method in required_mute_methods
                ):
                    logger.warning(
                        "Auto-mute saltado en %s: Moderation no puede preparar el caso",
                        guild.name,
                    )
                    return None
                current_rule_cfg = self._current_policy_allows_action(
                    message,
                    live_member,
                    live_roles,
                    int(live_guild.owner_id),
                    rule_name,
                    AutoModActions.MUTE,
                )
                if current_rule_cfg is None:
                    logger.warning(
                        "Auto-mute saltado en %s: la política o exención cambió",
                        guild.name,
                    )
                    return None
                live_dur = max(
                    60, int(current_rule_cfg.get("mute_duration") or 3600)
                )
                effect_token = new_mute_effect_token()
                _, case_id = moderation_cog._prepare_mute_record(
                    guild.id,
                    live_member.id,
                    self.bot.user.id,
                    "AUTO_MUTE",
                    reason,
                    live_dur,
                    live_mute_role.id,
                    extra={
                        "source": "automod",
                        "rule": rule_name,
                        "mute_effect_token": effect_token,
                        **({"decision": rule_cfg["llm_decision"], "evidence_url": message.jump_url} if rule_name == "llm" else {}),
                    },
                )
                await live_member.add_roles(
                    live_mute_role,
                    reason=reason_with_mute_effect(reason, effect_token),
                )
                confirmed_member = await moderation_cog._confirm_effective_mute(
                    guild, live_member.id, live_mute_role
                )
                if confirmed_member is None:
                    logger.warning(
                        "Auto-mute no activado en %s: el efecto quedó para reconciliación segura",
                        guild.name,
                    )
                    return None

                prepared_case = self.db.get_case_by_id(guild.id, case_id)
                effect_state = await moderation_cog._confirm_mute_effect_state(
                    guild,
                    live_member.id,
                    live_mute_role.id,
                    prepared_case,
                    member=confirmed_member,
                )
                if effect_state != "match":
                    raise RuntimeError("mute_effect_identity_not_confirmed")
                if not self.db.activate_prepared_mute_case(
                    guild.id, confirmed_member.id, case_id
                ):
                    raise RuntimeError("mute_intent_changed")
                return confirmed_member, live_dur

            try:
                mute_result = await run_sanction_locked(
                    self.bot,
                    guild.id,
                    member.id,
                    "AUTO_MUTE",
                    apply_auto_mute,
                )
                if mute_result is None:
                    return
                confirmed_member, applied_duration = mute_result
                persist_action_outcome(AutoModActions.MUTE)
                embed = self._build_embed(
                    rule_name, action, confirmed_member, message.content or "",
                    extra={**audit_extra, "Duración": f"{applied_duration}s"},
                )
                await self._log_to_modlog(guild, embed)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Sin permisos para auto-mute en %s", guild.name)
            except LookupError:
                logger.warning(
                    "Auto-mute saltado en %s: ya existe un caso de mute activo o pendiente",
                    guild.name,
                )
            except ValueError:
                logger.warning(
                    "Auto-mute saltado en %s: la duración o el rol configurado cambió",
                    guild.name,
                )
            except RuntimeError:
                logger.warning(
                    "Auto-mute en %s pendiente de reconciliación segura",
                    guild.name,
                )
            return

        if action == AutoModActions.KICK:
            async def apply_auto_kick():
                live_member, live_bot, live_roles, live_guild = await asyncio.gather(
                    guild.fetch_member(member.id),
                    guild.fetch_member(self.bot.user.id),
                    guild.fetch_roles(),
                    self.bot.fetch_guild(guild.id),
                )
                roles_by_id = {int(role.id): role for role in live_roles}

                def live_role_state(current_member: discord.Member):
                    role_ids = {guild.id}
                    role_ids.update(
                        int(role_id)
                        for role_id in getattr(current_member, "_roles", ())
                    )
                    if any(role_id not in roles_by_id for role_id in role_ids):
                        return None
                    roles = [roles_by_id[role_id] for role_id in role_ids]
                    permissions_value = 0
                    for current_role in roles:
                        permissions_value |= int(current_role.permissions.value)
                    return discord.Permissions(permissions_value), max(roles)

                member_state = live_role_state(live_member)
                bot_state = live_role_state(live_bot)
                if member_state is None or bot_state is None:
                    return None
                member_permissions, member_top_role = member_state
                bot_permissions, bot_top_role = bot_state
                if (
                    live_member.bot
                    or live_member.id == int(live_guild.owner_id)
                    or member_permissions.administrator
                    or member_top_role >= bot_top_role
                    or not (
                        bot_permissions.administrator
                        or bot_permissions.kick_members
                    )
                ):
                    return None
                if self._current_policy_allows_action(
                    message,
                    live_member,
                    live_roles,
                    int(live_guild.owner_id),
                    rule_name,
                    AutoModActions.KICK,
                ) is None:
                    return None
                await live_member.kick(reason=reason[:512] if rule_name == "llm" else reason)
                self.db.log_action(
                    guild.id,
                    live_member.id,
                    self.bot.user.id,
                    "AUTO_KICK",
                    reason,
                    **case_kwargs,
                )
                return live_member

            try:
                kicked_member = await run_sanction_locked(
                    self.bot,
                    guild.id,
                    member.id,
                    "AUTO_KICK",
                    apply_auto_kick,
                )
                if kicked_member is None:
                    logger.warning(
                        "Auto-kick saltado en %s: objetivo o jerarquía protegidos",
                        guild.name,
                    )
                    return
                persist_action_outcome(AutoModActions.KICK)
                await self._log_to_modlog(
                    guild,
                    self._build_embed(
                        rule_name, action, kicked_member, message.content or "", extra=audit_extra
                    ),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("Sin permisos para auto-kick en %s", guild.name)
            return

        if action == AutoModActions.BAN:
            async def apply_auto_ban():
                live_member, live_bot, live_roles, live_guild = await asyncio.gather(
                    guild.fetch_member(member.id),
                    guild.fetch_member(self.bot.user.id),
                    guild.fetch_roles(),
                    self.bot.fetch_guild(guild.id),
                )
                roles_by_id = {int(role.id): role for role in live_roles}

                def live_role_state(current_member: discord.Member):
                    role_ids = {guild.id}
                    role_ids.update(
                        int(role_id) for role_id in getattr(current_member, "_roles", ())
                    )
                    if any(role_id not in roles_by_id for role_id in role_ids):
                        return None
                    roles = [roles_by_id[role_id] for role_id in role_ids]
                    permissions_value = 0
                    for role in roles:
                        permissions_value |= int(role.permissions.value)
                    return discord.Permissions(permissions_value), max(roles)

                member_state = live_role_state(live_member)
                bot_state = live_role_state(live_bot)
                if member_state is None or bot_state is None:
                    logger.warning(
                        "Auto-ban saltado en %s: estado de roles incompleto",
                        guild.name,
                    )
                    return None
                member_permissions, member_top_role = member_state
                bot_permissions, bot_top_role = bot_state
                if (
                    live_member.bot
                    or live_member.id == int(live_guild.owner_id)
                    or member_permissions.administrator
                    or member_top_role >= bot_top_role
                    or not (bot_permissions.administrator or bot_permissions.ban_members)
                ):
                    logger.warning(
                        "Auto-ban saltado en %s: objetivo o jerarquía no gestionable",
                        guild.name,
                    )
                    return None
                current_rule_cfg = self._current_policy_allows_action(
                    message,
                    live_member,
                    live_roles,
                    int(live_guild.owner_id),
                    rule_name,
                    AutoModActions.BAN,
                )
                if current_rule_cfg is None:
                    logger.warning(
                        "Auto-ban saltado en %s: la política o exención cambió",
                        guild.name,
                    )
                    return None
                effect_token = new_ban_effect_token()
                audit_reason = reason_with_ban_effect(reason, effect_token)
                case_id = self.db.log_action(
                    guild.id,
                    live_member.id,
                    self.bot.user.id,
                    "AUTO_BAN",
                    reason,
                    {
                        "ban_effect_token": effect_token,
                        "source": "automod",
                        "rule": rule_name,
                        **({"decision": rule_cfg["llm_decision"], "evidence_url": message.jump_url} if rule_name == "llm" else {}),
                    },
                    status="applying",
                )
                if not case_id:
                    raise RuntimeError("ban_intent_not_persisted")
                await guild.ban(
                    live_member,
                    reason=audit_reason,
                    delete_message_days=0,
                )
                current_ban = await guild.fetch_ban(discord.Object(id=live_member.id))
                if not ban_reason_matches(current_ban.reason, effect_token):
                    logger.error(
                        "Auto-ban sin identidad verificable en %s para %s; queda para revisión manual",
                        guild.name,
                        live_member.id,
                    )
                    return None
                if not self.db.activate_prepared_ban_case(
                    guild.id,
                    live_member.id,
                    case_id,
                    self.bot.user.id,
                    reason,
                    current_rule_cfg.get("ban_duration") if rule_name == "llm" else None,
                    (datetime.now(timezone.utc) + timedelta(seconds=current_rule_cfg["ban_duration"])).isoformat()
                    if rule_name == "llm" and current_rule_cfg.get("ban_duration") else None,
                ):
                    raise RuntimeError("ban_intent_changed")
                return live_member

            try:
                banned_member = await run_sanction_locked(
                    self.bot,
                    guild.id,
                    member.id,
                    "AUTO_BAN",
                    apply_auto_ban,
                )
                if banned_member is None:
                    return
                persist_action_outcome(AutoModActions.BAN)
                await self._log_to_modlog(
                    guild,
                    self._build_embed(
                        rule_name, action, banned_member, message.content or "", extra=audit_extra
                    ),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("Sin permisos para auto-ban en %s", guild.name)
            except Exception:
                logger.exception(
                    "Auto-ban aplicado en %s pero no se pudo completar su registro; requiere revisión manual",
                    guild.name,
                )
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
        """Las sanciones automáticas solo usan un rol ya configurado."""
        cfg = self.db.get_config(guild.id)
        role_id = cfg.get("mute_role_id") or 0
        role = guild.get_role(int(role_id)) if role_id else None
        forbidden_role_ids = delegated_bot_role_ids(self.db, guild.id)
        return role if safe_for_automatic_assignment(
            role,
            guild.me,
            forbidden_role_ids=forbidden_role_ids,
        ) and mute_role_has_effective_denies(guild, role) else None

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
        if not self._can_manage(interaction):
            return await interaction.response.send_message(
                "❌ Necesitas Gestionar servidor.", ephemeral=True
            )
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
        if not self._can_manage(interaction):
            return await interaction.response.send_message(
                "❌ Necesitas Gestionar servidor.", ephemeral=True
            )
        self.db.set_automod_config(interaction.guild_id, enabled=int(activar))
        msg = "✅ Automoderación activada." if activar else "🛑 Automoderación desactivada."
        await interaction.response.send_message(msg, ephemeral=True)

    @automod_group.command(name="log", description="Últimas acciones de automoderación")
    @app_commands.describe(limite="Cuantos registros mostrar (1-20)")
    async def automod_log(self, interaction: discord.Interaction, limite: int = 10):
        if not self._can_manage(interaction):
            return await interaction.response.send_message(
                "❌ Necesitas Gestionar servidor.", ephemeral=True
            )
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
