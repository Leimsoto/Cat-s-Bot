"""Módulo RAG/Scraper pasivo para capturar conocimiento del servidor.

No responde preguntas ni sintetiza todavía. Su responsabilidad es:
- crear workspace aislado por guild;
- capturar mensajes nuevos/editados/borrados;
- hacer backfill reanudable de canales/hilos;
- persistir datos crudos normalizados en ``workspaces/<guild_id>/raw.sqlite``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from rag import RAGWorkspaceManager
from rag.workspace import (
    DEFAULT_EXPORT_LIMIT,
    MAX_ARCHIVED_THREADS_PER_CHANNEL,
    MAX_EXPORT_ROWS,
    MAX_HISTORY_BATCH_SIZE,
    MAX_SOURCES_PER_CYCLE,
    RAW_MAINTENANCE_INTERVAL_SECONDS,
    RAW_MESSAGE_RETENTION_DAYS,
    utc_now_iso,
)

logger = logging.getLogger("RAG")

MAX_PENDING_WORKSPACE_OPS_PER_GUILD = 64
MAX_PENDING_DELETIONS_PER_GUILD = 4_096
PENDING_DELETION_TTL_SECONDS = 10 * 60
_IO_DROPPED = object()
_IO_UNAUTHORIZED = object()
_SAVE_STORED = "stored"
_SAVE_SKIPPED = "skipped"
_SAVE_DROPPED = "dropped"


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _sid(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _safe_to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "to_dict"):
        try:
            data = obj.to_dict()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _channel_kind(channel: Any) -> str:
    return channel.__class__.__name__


class RAGScraper(commands.Cog):
    """Infraestructura pasiva de captura para RAG futuro."""

    rag_group = app_commands.Group(
        name="rag",
        description="Control del scraper/RAG pasivo del servidor",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.workspace: RAGWorkspaceManager = getattr(bot, "rag_workspace", RAGWorkspaceManager())
        setattr(bot, "rag_workspace", self.workspace)
        self._guild_locks: dict[int, asyncio.Lock] = {}
        self._io_locks: dict[int, asyncio.Lock] = {}
        self._io_pending: dict[int, int] = {}
        self._io_capacity: dict[int, asyncio.Event] = {}
        self._pending_deletions: dict[int, dict[int, float]] = {}
        self._manual_tasks: dict[int, asyncio.Task] = {}
        self._last_backfill_run: dict[int, float] = {}
        self._last_maintenance_run: dict[int, float] = {}
        self._backfill_loop.start()

    def cog_unload(self) -> None:
        self._backfill_loop.cancel()
        for task in list(self._manual_tasks.values()):
            task.cancel()
        self._pending_deletions.clear()

    def _lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._guild_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._guild_locks[guild_id] = lock
        return lock

    def _io_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._io_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._io_locks[guild_id] = lock
        return lock

    def _capacity_event(self, guild_id: int) -> asyncio.Event:
        event = self._io_capacity.get(guild_id)
        if event is None:
            event = asyncio.Event()
            event.set()
            self._io_capacity[guild_id] = event
        return event

    async def _workspace_call(
        self,
        guild_id: int,
        func: Callable[..., Any],
        *args: Any,
        drop_if_full: bool = False,
        prepare: Callable[[], None] | None = None,
        authorize: Callable[[], Awaitable[bool]] | None = None,
        **kwargs: Any,
    ) -> Any:
        guild_id = int(guild_id)
        while self._io_pending.get(guild_id, 0) >= MAX_PENDING_WORKSPACE_OPS_PER_GUILD:
            if drop_if_full:
                return _IO_DROPPED
            capacity = self._capacity_event(guild_id)
            capacity.clear()
            await capacity.wait()

        self._io_pending[guild_id] = self._io_pending.get(guild_id, 0) + 1
        try:
            async with self._io_lock(guild_id):
                if authorize is not None and not await authorize():
                    return _IO_UNAUTHORIZED
                if prepare is not None:
                    prepare()
                worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
                try:
                    return await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
        finally:
            remaining = self._io_pending.get(guild_id, 1) - 1
            if remaining > 0:
                self._io_pending[guild_id] = remaining
            else:
                self._io_pending.pop(guild_id, None)
            self._capacity_event(guild_id).set()

    def _prune_pending_deletions(self, guild_id: int, now: float) -> dict[int, float]:
        pending = self._pending_deletions.get(guild_id)
        if pending is None:
            return {}
        for message_id, expires_at in list(pending.items()):
            if expires_at <= now:
                pending.pop(message_id, None)
        if not pending:
            self._pending_deletions.pop(guild_id, None)
        return pending

    def _remember_deleted(self, guild_id: int, message_id: int) -> None:
        now = asyncio.get_running_loop().time()
        pending = self._prune_pending_deletions(guild_id, now)
        if not pending:
            pending = {}
            self._pending_deletions[guild_id] = pending
        if message_id not in pending and len(pending) >= MAX_PENDING_DELETIONS_PER_GUILD:
            oldest = min(pending, key=pending.get)
            pending.pop(oldest, None)
        pending[message_id] = now + PENDING_DELETION_TTL_SECONDS

    def _is_pending_deleted(self, guild_id: int, message_id: int) -> bool:
        now = asyncio.get_running_loop().time()
        return message_id in self._prune_pending_deletions(guild_id, now)

    def _forget_pending_deleted(self, guild_id: int, message_id: int) -> None:
        pending = self._pending_deletions.get(guild_id)
        if pending is None:
            return
        pending.pop(message_id, None)
        if not pending:
            self._pending_deletions.pop(guild_id, None)

    async def _authorized(
        self,
        interaction: discord.Interaction,
        *,
        admin_only: bool = False,
    ) -> bool:
        """Revalida membresía, roles y dueño actuales antes de una operación RAG."""
        guild = interaction.guild
        if guild is None or interaction.guild_id != guild.id:
            return False
        return await self._authorized_user(
            guild,
            interaction.user.id,
            admin_only=admin_only,
        )

    async def _authorized_user(
        self,
        guild: discord.Guild,
        user_id: int,
        *,
        admin_only: bool = False,
    ) -> bool:
        """Versión reutilizable por Discord y la API, siempre con datos REST."""
        try:
            member, roles, live_guild = await asyncio.gather(
                guild.fetch_member(int(user_id)),
                guild.fetch_roles(),
                self.bot.fetch_guild(guild.id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
        if (
            member.id != int(user_id)
            or getattr(live_guild, "id", None) != guild.id
        ):
            return False

        roles_by_id = {int(role.id): role for role in roles}
        role_ids = {guild.id}
        role_ids.update(int(role_id) for role_id in getattr(member, "_roles", ()))
        if any(role_id not in roles_by_id for role_id in role_ids):
            return False

        permissions_value = 0
        for role_id in role_ids:
            permissions_value |= int(roles_by_id[role_id].permissions.value)
        permissions = discord.Permissions(permissions_value)
        if member.id == int(live_guild.owner_id) or permissions.administrator:
            return True
        return bool(not admin_only and permissions.manage_guild)

    def _config(self, guild_id: int) -> dict[str, Any]:
        self.workspace.ensure_workspace(guild_id)
        return self.workspace.load_config(guild_id)

    def _is_enabled(self, guild_id: int) -> bool:
        return bool(self._config(guild_id).get("enabled", True))

    def _excluded(self, cfg: dict[str, Any]) -> set[str]:
        return {str(x) for x in cfg.get("excluded_channel_ids") or []}

    def _can_read_history(self, channel: Any) -> bool:
        guild = getattr(channel, "guild", None)
        me = getattr(guild, "me", None)
        if guild is None or me is None or not hasattr(channel, "permissions_for"):
            return False
        try:
            perms = channel.permissions_for(me)
            return bool(perms.view_channel and perms.read_message_history)
        except Exception:
            logger.debug(
                "[rag] No se pudieron comprobar permisos del bot para channel=%s",
                getattr(channel, "id", None),
                exc_info=True,
            )
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Serialización normalizada
    # ──────────────────────────────────────────────────────────────────────

    def _channel_payload(self, channel: Any) -> dict[str, Any]:
        guild = getattr(channel, "guild", None)
        category = getattr(channel, "category", None)
        parent = getattr(channel, "parent", None)
        return {
            "channel_id": _sid(getattr(channel, "id", None)),
            "guild_id": _sid(getattr(guild, "id", None)),
            "name": getattr(channel, "name", None),
            "type": _channel_kind(channel),
            "category_id": _sid(getattr(category, "id", None)),
            "parent_id": _sid(getattr(parent, "id", None)),
            "position": getattr(channel, "position", None),
            "nsfw": bool(getattr(channel, "nsfw", False)),
            "archived": bool(getattr(channel, "archived", False)),
            "raw": {
                "id": _sid(getattr(channel, "id", None)),
                "name": getattr(channel, "name", None),
                "type": _channel_kind(channel),
                "jump_url": getattr(channel, "jump_url", None),
            },
        }

    def _thread_payload(self, thread: discord.Thread) -> dict[str, Any]:
        guild = getattr(thread, "guild", None)
        parent = getattr(thread, "parent", None)
        return {
            "thread_id": _sid(thread.id),
            "guild_id": _sid(getattr(guild, "id", None)),
            "parent_channel_id": _sid(getattr(parent, "id", None)),
            "name": thread.name,
            "owner_id": _sid(getattr(thread, "owner_id", None)),
            "archived": bool(getattr(thread, "archived", False)),
            "locked": bool(getattr(thread, "locked", False)),
            "type": _channel_kind(thread),
            "created_at": _iso(getattr(thread, "created_at", None)),
            "archived_at": _iso(getattr(thread, "archive_timestamp", None)),
            "raw": {
                "id": _sid(thread.id),
                "name": thread.name,
                "parent_id": _sid(getattr(parent, "id", None)),
                "jump_url": getattr(thread, "jump_url", None),
            },
        }

    def _message_payload(self, message: discord.Message) -> dict[str, Any]:
        guild = message.guild
        channel = message.channel
        parent = getattr(channel, "parent", None)
        thread_id = message.channel.id if isinstance(channel, discord.Thread) else None
        author = message.author
        return {
            "message_id": _sid(message.id),
            "guild_id": _sid(getattr(guild, "id", None)),
            "channel_id": _sid(getattr(parent, "id", None) if isinstance(channel, discord.Thread) and parent else getattr(channel, "id", None)),
            "thread_id": _sid(thread_id),
            "author_id": _sid(getattr(author, "id", None)),
            "author_name": str(author) if author else None,
            "author_bot": bool(getattr(author, "bot", False)),
            "content": message.content,
            "clean_content": getattr(message, "clean_content", message.content),
            "attachments": [
                {
                    "id": _sid(a.id),
                    "filename": a.filename,
                    "url": a.url,
                    "proxy_url": a.proxy_url,
                    "content_type": a.content_type,
                    "size": a.size,
                    "description": a.description,
                }
                for a in message.attachments
            ],
            "embeds": [_safe_to_dict(e) for e in message.embeds],
            "mentions": {
                "users": [_sid(u.id) for u in message.mentions],
                "roles": [_sid(r.id) for r in message.role_mentions],
                "channels": [_sid(c.id) for c in message.channel_mentions],
            },
            "reactions": [
                {"emoji": str(r.emoji), "count": r.count, "me": bool(r.me)}
                for r in message.reactions
            ],
            "reference_message_id": _sid(getattr(getattr(message, "reference", None), "message_id", None)),
            "message_type": str(message.type),
            "is_pinned": bool(message.pinned),
            "jump_url": message.jump_url,
            "created_at": _iso(message.created_at),
            "edited_at": _iso(message.edited_at),
            "captured_at": utc_now_iso(),
            "raw": {
                "id": _sid(message.id),
                "channel_id": _sid(getattr(channel, "id", None)),
                "guild_id": _sid(getattr(guild, "id", None)),
                "author_id": _sid(getattr(author, "id", None)),
                "system_content": getattr(message, "system_content", None),
                "flags": getattr(getattr(message, "flags", None), "value", None),
                "stickers": [
                    {
                        "id": _sid(getattr(sticker, "id", None)),
                        "name": getattr(sticker, "name", None),
                        "format_type": str(getattr(sticker, "format", getattr(sticker, "format_type", ""))),
                        "url": getattr(sticker, "url", None),
                    }
                    for sticker in getattr(message, "stickers", [])
                ],
                "components": [_safe_to_dict(component) for component in getattr(message, "components", [])],
                "webhook_id": _sid(getattr(message, "webhook_id", None)),
                "application_id": _sid(getattr(message, "application_id", None)),
            },
        }

    def _persist_message(
        self,
        guild_id: int,
        channel_payload: Mapping[str, Any],
        thread_payload: Mapping[str, Any] | None,
        message_payload: Mapping[str, Any],
    ) -> bool:
        self.workspace.upsert_channel(guild_id, channel_payload)
        if thread_payload is not None:
            self.workspace.upsert_thread(guild_id, thread_payload)
        return self.workspace.upsert_message(guild_id, message_payload)

    async def _save_message(
        self,
        message: discord.Message,
        *,
        cfg: dict[str, Any] | None = None,
    ) -> str:
        if not message.guild:
            return _SAVE_SKIPPED
        if cfg is None:
            loaded = await self._workspace_call(
                message.guild.id,
                self._config,
                message.guild.id,
                drop_if_full=True,
            )
            if loaded is _IO_DROPPED:
                return _SAVE_DROPPED
            cfg = loaded
        if not cfg.get("enabled", True) or not cfg.get("capture_live_messages", True):
            return _SAVE_SKIPPED
        if getattr(message.author, "bot", False) and not cfg.get("include_bots", False):
            return _SAVE_SKIPPED
        channel_id = str(getattr(message.channel, "id", ""))
        parent_id = str(getattr(getattr(message.channel, "parent", None), "id", ""))
        if channel_id in self._excluded(cfg) or parent_id in self._excluded(cfg):
            return _SAVE_SKIPPED

        channel_payload = self._channel_payload(message.channel)
        thread_payload = (
            self._thread_payload(message.channel)
            if isinstance(message.channel, discord.Thread)
            else None
        )
        message_payload = self._message_payload(message)

        was_pending_deleted = False

        def apply_pending_deletion() -> None:
            nonlocal was_pending_deleted
            if self._is_pending_deleted(message.guild.id, message.id):
                was_pending_deleted = True
                message_payload["is_deleted"] = True
                message_payload["deleted_at"] = utc_now_iso()

        stored = await self._workspace_call(
            message.guild.id,
            self._persist_message,
            message.guild.id,
            channel_payload,
            thread_payload,
            message_payload,
            drop_if_full=True,
            prepare=apply_pending_deletion,
        )
        if stored is _IO_DROPPED:
            return _SAVE_DROPPED
        if stored and was_pending_deleted:
            self._forget_pending_deleted(message.guild.id, message.id)
        return _SAVE_STORED if stored else _SAVE_SKIPPED

    async def _mark_deleted(
        self,
        guild_id: int,
        message_id: int,
        channel_id: int | None = None,
    ) -> bool:
        self._remember_deleted(guild_id, message_id)
        result = await self._workspace_call(
            guild_id,
            self.workspace.mark_message_deleted,
            guild_id,
            message_id,
            channel_id,
            drop_if_full=True,
        )
        if result is _IO_DROPPED:
            return False
        if result:
            self._forget_pending_deleted(guild_id, message_id)
        return bool(result)

    def _mark_deleted_batch_sync(
        self, guild_id: int, message_ids: Iterable[int]
    ) -> tuple[int, ...]:
        return tuple(
            message_id
            for message_id in message_ids
            if self.workspace.mark_message_deleted(guild_id, message_id)
        )

    async def _mark_deleted_batch(
        self,
        guild_id: int,
        message_ids: Iterable[int],
        *,
        drop_if_full: bool = True,
        remember: bool = True,
    ) -> int:
        ids = tuple(int(message_id) for message_id in message_ids)
        if remember:
            for message_id in ids:
                self._remember_deleted(guild_id, message_id)
        result = await self._workspace_call(
            guild_id,
            self._mark_deleted_batch_sync,
            guild_id,
            ids,
            drop_if_full=drop_if_full,
        )
        if result is _IO_DROPPED:
            return 0
        for message_id in result:
            self._forget_pending_deleted(guild_id, message_id)
        return len(result)

    # ──────────────────────────────────────────────────────────────────────
    # Listeners pasivos
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._workspace_call(guild.id, self.workspace.ensure_workspace, guild.id)
        logger.info("[rag] workspace inicializado para guild=%s", guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._workspace_call(guild.id, self.workspace.ensure_workspace, guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self._save_message(message)
        except Exception as exc:
            logger.warning("[rag] no se pudo capturar mensaje %s: %s", getattr(message, "id", None), exc)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        try:
            await self._save_message(after)
        except Exception as exc:
            logger.warning("[rag] no se pudo actualizar mensaje editado %s: %s", getattr(after, "id", None), exc)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        try:
            await self._mark_deleted(
                message.guild.id,
                message.id,
                getattr(message.channel, "id", None),
            )
        except Exception as exc:
            logger.warning("[rag] no se pudo marcar mensaje borrado %s: %s", getattr(message, "id", None), exc)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        try:
            await self._mark_deleted(payload.guild_id, payload.message_id, payload.channel_id)
        except Exception as exc:
            logger.warning("[rag] no se pudo marcar borrado raw %s: %s", payload.message_id, exc)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        try:
            await self._mark_deleted_batch(payload.guild_id, payload.message_ids)
        except Exception as exc:
            logger.warning("[rag] no se pudo marcar borrado bulk raw: %s", exc)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.guild_id is None or getattr(payload, "cached_message", None) is not None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel_or_thread(payload.channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(payload.channel_id)
            except discord.NotFound:
                await self._mark_deleted(payload.guild_id, payload.message_id, payload.channel_id)
                return
            except discord.Forbidden:
                return
            except discord.HTTPException as exc:
                logger.warning("[rag] no se pudo resolver canal para edit raw %s: %s", payload.message_id, exc)
                return
        if not hasattr(channel, "fetch_message") or not self._can_read_history(channel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            await self._mark_deleted(payload.guild_id, payload.message_id, payload.channel_id)
            return
        except discord.Forbidden:
            return
        except discord.HTTPException as exc:
            logger.warning("[rag] no se pudo obtener edit raw %s: %s", payload.message_id, exc)
            return
        try:
            await self._save_message(message)
        except Exception as exc:
            logger.warning("[rag] no se pudo actualizar mensaje raw %s: %s", payload.message_id, exc)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if not thread.guild:
            return
        enabled = await self._workspace_call(
            thread.guild.id,
            self._is_enabled,
            thread.guild.id,
            drop_if_full=True,
        )
        if enabled in (False, _IO_DROPPED):
            return
        payload = self._thread_payload(thread)
        await self._workspace_call(
            thread.guild.id,
            self.workspace.upsert_thread,
            thread.guild.id,
            payload,
            drop_if_full=True,
        )

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if not after.guild:
            return
        enabled = await self._workspace_call(
            after.guild.id,
            self._is_enabled,
            after.guild.id,
            drop_if_full=True,
        )
        if enabled in (False, _IO_DROPPED):
            return
        payload = self._thread_payload(after)
        await self._workspace_call(
            after.guild.id,
            self.workspace.upsert_thread,
            after.guild.id,
            payload,
            drop_if_full=True,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Backfill reanudable
    # ──────────────────────────────────────────────────────────────────────

    def _iter_sources(self, guild: discord.Guild, cfg: dict[str, Any]) -> Iterable[Any]:
        excluded = self._excluded(cfg)
        for channel in guild.channels:
            if str(channel.id) in excluded:
                continue
            if isinstance(channel, (discord.TextChannel, discord.Thread)) and self._can_read_history(channel):
                yield channel
        if cfg.get("capture_threads", True):
            for thread in guild.threads:
                parent_id = _sid(getattr(getattr(thread, "parent", None), "id", None))
                if str(thread.id) in excluded or (parent_id and parent_id in excluded):
                    continue
                if self._can_read_history(thread):
                    yield thread

    async def _iter_archived_threads(self, channel: Any, limit: int):
        if not hasattr(channel, "archived_threads"):
            return
        count = 0
        try:
            async for thread in channel.archived_threads(limit=limit):
                yield thread
                count += 1
                if count >= limit:
                    break
        except (discord.Forbidden, discord.HTTPException):
            return

    async def _backfill_source(self, guild: discord.Guild, source: Any, cfg: dict[str, Any]) -> Optional[int]:
        """Procesa una fuente.

        Returns:
            ``None`` si la fuente ya estaba completa y no debe consumir el
            límite del ciclo; ``int`` para intentos reales, incluso si capturan
            0 mensajes.
        """
        if not hasattr(source, "history") or not self._can_read_history(source):
            return 0
        source_id = getattr(source, "id", None)
        if source_id is None:
            return 0
        if isinstance(source, discord.Thread):
            source_payload = self._thread_payload(source)
            await self._workspace_call(
                guild.id,
                self.workspace.upsert_thread,
                guild.id,
                source_payload,
            )
        else:
            source_payload = self._channel_payload(source)
            await self._workspace_call(
                guild.id,
                self.workspace.upsert_channel,
                guild.id,
                source_payload,
            )
        scope = f"messages:{source_id}"
        checkpoint = await self._workspace_call(
            guild.id,
            self.workspace.get_checkpoint,
            guild.id,
            scope,
        ) or {}
        meta = {}
        if checkpoint.get("meta_json"):
            try:
                meta = json.loads(checkpoint["meta_json"])
            except json.JSONDecodeError:
                meta = {}
        if checkpoint.get("status") == "completed":
            return None

        before_id = meta.get("before_message_id")
        before_obj = discord.Object(id=int(before_id)) if before_id else None
        batch_size = min(
            MAX_HISTORY_BATCH_SIZE,
            max(1, int(cfg.get("history_batch_size", 200))),
        )
        messages: list[discord.Message] = []
        reached_retention = False
        retention_cutoff = datetime.now(timezone.utc) - timedelta(
            days=RAW_MESSAGE_RETENTION_DAYS
        )
        try:
            async for msg in source.history(limit=batch_size, before=before_obj):
                if msg.created_at < retention_cutoff:
                    reached_retention = True
                    break
                if getattr(msg.author, "bot", False) and not cfg.get("include_bots", False):
                    continue
                messages.append(msg)
        except discord.Forbidden:
            await self._workspace_call(
                guild.id,
                self.workspace.set_checkpoint,
                guild.id,
                scope,
                channel_id=source_id,
                status="forbidden",
                meta={"error": "missing_read_history"},
            )
            return 0
        except discord.HTTPException as exc:
            await self._workspace_call(
                guild.id,
                self.workspace.set_checkpoint,
                guild.id,
                scope,
                channel_id=source_id,
                status="http_error",
                meta={"error": str(exc)[:300]},
            )
            return 0

        if not messages:
            await self._workspace_call(
                guild.id,
                self.workspace.set_checkpoint,
                guild.id,
                scope,
                channel_id=source_id,
                status="completed",
                meta=meta,
            )
            return 0

        stored_count = 0
        for msg in reversed(messages):
            if await self._save_message(msg, cfg=cfg) == _SAVE_STORED:
                stored_count += 1
        oldest = min(messages, key=lambda m: int(m.id))
        newest = max(messages, key=lambda m: int(m.id))
        meta["before_message_id"] = str(oldest.id)
        await self._workspace_call(
            guild.id,
            self.workspace.set_checkpoint,
            guild.id,
            scope,
            channel_id=source_id,
            thread_id=source_id if isinstance(source, discord.Thread) else None,
            last_message_id=newest.id,
            last_message_created_at=_iso(newest.created_at),
            status="completed" if reached_retention else "running",
            meta=meta,
        )
        return stored_count

    async def backfill_guild(
        self,
        guild: discord.Guild,
        *,
        manual: bool = False,
        max_sources: Optional[int] = None,
        authorize: Callable[[], Awaitable[bool]] | None = None,
    ) -> dict[str, Any]:
        async with self._lock(guild.id):
            cfg = await self._workspace_call(guild.id, self._config, guild.id)
            if not cfg.get("enabled", True):
                return {"guild_id": str(guild.id), "captured": 0, "sources": 0, "skipped": "disabled"}
            if not manual and not cfg.get("backfill_enabled", True):
                return {"guild_id": str(guild.id), "captured": 0, "sources": 0, "skipped": "backfill_disabled"}
            requested_limit = (
                max_sources
                if max_sources is not None
                else cfg.get("max_sources_per_cycle", 20)
            )
            try:
                limit = min(MAX_SOURCES_PER_CYCLE, max(1, int(requested_limit)))
            except (TypeError, ValueError):
                limit = 20
            if manual and authorize is None:
                return {
                    "guild_id": str(guild.id),
                    "captured": 0,
                    "sources": 0,
                    "skipped": "unauthorized",
                }
            if authorize is not None and not await authorize():
                return {
                    "guild_id": str(guild.id),
                    "captured": 0,
                    "sources": 0,
                    "skipped": "unauthorized",
                }
            captured = 0
            processed = 0

            sources = list(self._iter_sources(guild, cfg))
            if cfg.get("capture_archived_threads", True):
                try:
                    archived_limit = min(
                        MAX_ARCHIVED_THREADS_PER_CHANNEL,
                        max(1, int(cfg.get("archived_threads_limit_per_channel", 50))),
                    )
                except (TypeError, ValueError):
                    archived_limit = 50
                archived_added = 0
                for channel in guild.channels:
                    if archived_added >= limit:
                        break
                    async for thread in self._iter_archived_threads(channel, archived_limit):
                        if archived_added >= limit:
                            break
                        if self._can_read_history(thread):
                            sources.append(thread)
                            archived_added += 1

            for source in sources:
                if processed >= limit:
                    break
                source_captured = await self._backfill_source(guild, source, cfg)
                if source_captured is None:
                    continue
                captured += source_captured
                processed += 1
                await asyncio.sleep(0)
            logger.info("[rag] backfill guild=%s sources=%s captured=%s", guild.id, processed, captured)
            return {"guild_id": str(guild.id), "captured": captured, "sources": processed}

    async def run_manual_backfill(
        self,
        guild: discord.Guild,
        *,
        max_sources: Optional[int],
        authorize: Callable[[], Awaitable[bool]],
    ) -> dict[str, Any]:
        """Admite una sola pasada manual por guild y reautoriza dentro del lock."""
        guild_id = guild.id
        existing = self._manual_tasks.get(guild_id)
        if existing is not None and not existing.done():
            return {
                "guild_id": str(guild_id),
                "captured": 0,
                "sources": 0,
                "skipped": "already_running",
            }
        task = asyncio.create_task(
            self.backfill_guild(
                guild,
                manual=True,
                max_sources=max_sources,
                authorize=authorize,
            )
        )
        self._manual_tasks[guild_id] = task
        try:
            return await task
        finally:
            if self._manual_tasks.get(guild_id) is task:
                self._manual_tasks.pop(guild_id, None)

    @tasks.loop(seconds=60)
    async def _backfill_loop(self):
        now = asyncio.get_running_loop().time()
        workspace_ids = {guild.id for guild in list(self.bot.guilds)}
        for workspace_path in self.workspace.list_workspaces():
            if workspace_path.name.isdecimal() and int(workspace_path.name) > 0:
                workspace_ids.add(int(workspace_path.name))

        for guild_id in workspace_ids:
            try:
                pending_deletions = tuple(
                    self._prune_pending_deletions(guild_id, now)
                )
                if pending_deletions:
                    await self._mark_deleted_batch(
                        guild_id,
                        pending_deletions,
                        drop_if_full=False,
                        remember=False,
                    )
                last_maintenance = self._last_maintenance_run.get(guild_id, 0.0)
                if now - last_maintenance < RAW_MAINTENANCE_INTERVAL_SECONDS:
                    continue
                maintenance = await self._workspace_call(
                    guild_id,
                    self.workspace.prune_corpus,
                    guild_id,
                )
                self._last_maintenance_run[guild_id] = now
                if (
                    maintenance["oversized_deleted"]
                    or maintenance["expired_deleted"]
                    or maintenance["quota_deleted"]
                    or maintenance["metadata_expired_deleted"]
                    or maintenance["metadata_quota_deleted"]
                ):
                    logger.info(
                        "[rag] retención guild=%s oversized=%s expired=%s quota=%s metadata_expired=%s metadata_quota=%s rows=%s bytes=%s",
                        guild_id,
                        maintenance["oversized_deleted"],
                        maintenance["expired_deleted"],
                        maintenance["quota_deleted"],
                        maintenance["metadata_expired_deleted"],
                        maintenance["metadata_quota_deleted"],
                        maintenance["message_count"],
                        maintenance["payload_bytes"],
                    )
            except Exception as exc:
                logger.warning("[rag] mantenimiento falló guild=%s: %s", guild_id, exc)

        for guild in list(self.bot.guilds):
            try:
                cfg = await self._workspace_call(guild.id, self._config, guild.id)
                if not cfg.get("enabled", True) or not cfg.get("backfill_enabled", True):
                    continue
                interval = max(60, int(cfg.get("backfill_interval_seconds", 300)))
                last = self._last_backfill_run.get(guild.id, 0)
                if now - last < interval:
                    continue
                self._last_backfill_run[guild.id] = now
                await self.backfill_guild(guild)
            except Exception as exc:
                logger.warning("[rag] backfill falló guild=%s: %s", getattr(guild, "id", None), exc)

    @_backfill_loop.before_loop
    async def _before_backfill_loop(self):
        await self.bot.wait_until_ready()
        # Crear workspaces pronto, pero dejar respirar al arranque/sync de comandos.
        await asyncio.sleep(15)

    # ──────────────────────────────────────────────────────────────────────
    # Slash commands admin
    # ──────────────────────────────────────────────────────────────────────

    @rag_group.command(name="status", description="Muestra estado local del scraper/RAG")
    async def rag_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Solo disponible en servidores.", ephemeral=True)
        if not await self._authorized(interaction):
            return await interaction.response.send_message(
                "❌ Necesitas Gestionar servidor.", ephemeral=True
            )
        cfg = await self._workspace_call(
            interaction.guild.id,
            self._config,
            interaction.guild.id,
        )
        stats = await self._workspace_call(
            interaction.guild.id,
            self.workspace.stats,
            interaction.guild.id,
        )
        counts = stats["counts"]
        embed = discord.Embed(
            title="🧠 RAG/Scraper",
            description="Captura pasiva de conocimiento del servidor.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Estado", value="Activo" if cfg.get("enabled") else "Desactivado", inline=True)
        embed.add_field(name="Backfill", value="Activo" if cfg.get("backfill_enabled") else "Desactivado", inline=True)
        embed.add_field(name="Mensajes", value=str(counts.get("messages", 0)), inline=True)
        embed.add_field(name="Canales", value=str(counts.get("channels", 0)), inline=True)
        embed.add_field(name="Hilos", value=str(counts.get("threads", 0)), inline=True)
        embed.add_field(name="Checkpoints", value=str(counts.get("checkpoints", 0)), inline=True)
        embed.add_field(name="Workspace", value=f"`{stats['workspace']}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rag_group.command(name="config", description="Activa/desactiva captura RAG del servidor")
    @app_commands.describe(
        enabled="Activa/desactiva todo el módulo",
        backfill="Activa/desactiva lectura histórica reanudable",
        include_bots="Incluye mensajes de bots en la captura",
    )
    async def rag_config(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        backfill: Optional[bool] = None,
        include_bots: Optional[bool] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Solo disponible en servidores.", ephemeral=True)
        if not await self._authorized(interaction):
            return await interaction.response.send_message(
                "❌ Necesitas Gestionar servidor.", ephemeral=True
            )
        updates: dict[str, Any] = {}
        if enabled is not None:
            updates["enabled"] = enabled
        if backfill is not None:
            updates["backfill_enabled"] = backfill
        if include_bots is not None:
            updates["include_bots"] = include_bots
        if updates:
            cfg = await self._workspace_call(
                interaction.guild.id,
                self.workspace.save_config,
                interaction.guild.id,
                updates,
                drop_if_full=True,
                authorize=lambda: self._authorized(interaction),
            )
            if cfg is _IO_UNAUTHORIZED:
                return await interaction.response.send_message(
                    "❌ Tus permisos cambiaron; no se modificó la configuración.",
                    ephemeral=True,
                )
            if cfg is _IO_DROPPED:
                return await interaction.response.send_message(
                    "❌ El workspace RAG está ocupado; inténtalo de nuevo.",
                    ephemeral=True,
                )
        else:
            cfg = await self._workspace_call(
                interaction.guild.id,
                self._config,
                interaction.guild.id,
            )
        await interaction.response.send_message(
            "✅ Config RAG actualizada: "
            f"enabled={cfg['enabled']} · backfill={cfg['backfill_enabled']} · include_bots={cfg['include_bots']}",
            ephemeral=True,
        )

    @rag_group.command(name="backfill", description="Lanza una pasada manual de captura histórica")
    @app_commands.describe(max_sources="Máximo de canales/hilos a procesar en esta pasada")
    async def rag_backfill(self, interaction: discord.Interaction, max_sources: Optional[int] = None):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Solo disponible en servidores.", ephemeral=True)
        if not await self._authorized(interaction, admin_only=True):
            return await interaction.response.send_message(
                "❌ El backfill histórico requiere Administrador.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.run_manual_backfill(
            interaction.guild,
            max_sources=max_sources,
            authorize=lambda: self._authorized(interaction, admin_only=True),
        )
        if result.get("skipped") == "already_running":
            return await interaction.followup.send(
                "❌ Ya hay un backfill manual en curso para este servidor.",
                ephemeral=True,
            )
        if result.get("skipped") == "unauthorized":
            return await interaction.followup.send(
                "❌ Tus permisos cambiaron; el backfill fue cancelado.",
                ephemeral=True,
            )
        await interaction.followup.send(
            f"✅ Backfill RAG: fuentes={result.get('sources', 0)} · mensajes={result.get('captured', 0)}",
            ephemeral=True,
        )

    @rag_group.command(name="export", description="Exporta mensajes capturados a texto legible")
    @app_commands.describe(
        formato="Formato del archivo",
        canal="Opcional: exportar solo un canal de texto",
        incluir_borrados="Incluye mensajes marcados como borrados",
        limite=f"Exporta los últimos N mensajes; vacío = {DEFAULT_EXPORT_LIMIT}",
        todo=f"Exporta hasta el límite seguro de {MAX_EXPORT_ROWS} mensajes",
    )
    @app_commands.choices(
        formato=[
            app_commands.Choice(name="Markdown", value="markdown"),
            app_commands.Choice(name="Texto plano", value="txt"),
            app_commands.Choice(name="JSON Lines", value="jsonl"),
        ]
    )
    async def rag_export(
        self,
        interaction: discord.Interaction,
        formato: str = "markdown",
        canal: Optional[discord.TextChannel] = None,
        incluir_borrados: bool = False,
        limite: Optional[int] = None,
        todo: bool = False,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Solo disponible en servidores.", ephemeral=True)
        if not await self._authorized(interaction, admin_only=True):
            return await interaction.response.send_message(
                "❌ Exportar el corpus RAG requiere Administrador.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self._workspace_call(
                interaction.guild.id,
                self.workspace.export_messages,
                interaction.guild.id,
                format=formato,
                channel_id=canal.id if canal else None,
                include_deleted=incluir_borrados,
                limit=limite,
                export_all=todo,
            )
        except (ValueError, RuntimeError) as exc:
            return await interaction.followup.send(f"❌ {exc}", ephemeral=True)

        path = Path(result["path"])
        if not await self._authorized(interaction, admin_only=True):
            return await interaction.followup.send(
                "❌ Tus permisos cambiaron; el archivo no se enviará.",
                ephemeral=True,
            )
        message = (
            f"✅ Export RAG generado: `{result['filename']}`\n"
            f"Selección: **{result['selection']}** · Mensajes: **{result['count']}** · Tamaño: **{result['bytes']} bytes**\n"
            f"Truncado por límites seguros: **{bool(result.get('truncated'))}**\n"
            f"Ruta local: `{result['path']}`"
        )
        # Evitar fallos por límites de upload. El archivo siempre queda en disco.
        if path.is_file() and result["bytes"] <= 7_500_000:
            await interaction.followup.send(message, file=discord.File(str(path)), ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RAGScraper(bot))
