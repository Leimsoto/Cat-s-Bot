"""Workspace multi-servidor para el módulo RAG/Scraper.

El módulo RAG guarda datos crudos por servidor en::

    workspaces/<guild_id>/
      config.yaml
      raw.sqlite
      checkpoints/
      exports/
      logs/
      synthesis/
      vectorstore/
      tmp/

Este archivo evita depender de la base principal del bot: cada guild tiene su
SQLite aislado y sus checkpoints propios. Las funciones aceptan/serializan IDs
como strings para no perder precisión de snowflakes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


DEFAULT_RAG_CONFIG: dict[str, Any] = {
    "enabled": True,
    "backfill_enabled": True,
    "capture_live_messages": True,
    "capture_threads": True,
    "capture_forums": True,
    "capture_archived_threads": True,
    "include_bots": False,
    "history_batch_size": 200,
    "max_sources_per_cycle": 20,
    "archived_threads_limit_per_channel": 50,
    "backfill_interval_seconds": 300,
    "excluded_channel_ids": [],
}

DEFAULT_EXPORT_LIMIT = 5_000
MAX_EXPORT_ROWS = 20_000
MAX_EXPORT_BYTES = 25 * 1024 * 1024
MAX_EXPORT_STORAGE_BYTES = 100 * 1024 * 1024
MAX_EXPORT_FILES_PER_GUILD = 20
MIN_EXPORT_INTERVAL_SECONDS = 10.0

MAX_HISTORY_BATCH_SIZE = 500
MAX_SOURCES_PER_CYCLE = 50
MAX_ARCHIVED_THREADS_PER_CHANNEL = 50
MIN_BACKFILL_INTERVAL_SECONDS = 60
MAX_BACKFILL_INTERVAL_SECONDS = 86_400
MAX_EXCLUDED_CHANNELS = 500

MAX_RAW_MESSAGE_BYTES = 256 * 1024
MAX_RAW_MESSAGES_PER_GUILD = 100_000
MAX_RAW_PAYLOAD_BYTES_PER_GUILD = 256 * 1024 * 1024
MAX_RAW_THREADS_PER_GUILD = 50_000
MAX_RAW_CHECKPOINTS_PER_GUILD = 50_000
RAW_MESSAGE_RETENTION_DAYS = 180
RAW_PRUNE_BATCH_ROWS = 500
RAW_MAINTENANCE_INTERVAL_SECONDS = 300.0

RAG_INT_CONFIG_BOUNDS: dict[str, tuple[int, int]] = {
    "history_batch_size": (1, MAX_HISTORY_BATCH_SIZE),
    "max_sources_per_cycle": (1, MAX_SOURCES_PER_CYCLE),
    "archived_threads_limit_per_channel": (1, MAX_ARCHIVED_THREADS_PER_CHANNEL),
    "backfill_interval_seconds": (
        MIN_BACKFILL_INTERVAL_SECONDS,
        MAX_BACKFILL_INTERVAL_SECONDS,
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sid(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _canonical_snowflake(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text.isdecimal() or int(text) <= 0 or str(int(text)) != text:
        raise ValueError(f"{field} debe ser un ID numérico positivo de Discord.")
    return text


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "si", "sí"}
    return bool(value)


def _json_or(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if text.startswith("[") or text.startswith("{") or text.startswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text.strip('"')
    try:
        return int(text)
    except ValueError:
        return text.strip('"')


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


class RAGWorkspaceManager:
    """Administra workspaces, config, SQLite crudo y checkpoints por guild."""

    def __init__(self, base_dir: str | Path = "workspaces"):
        self.base_dir = Path(base_dir)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._initialized_workspaces: set[str] = set()
        self._init_guard = threading.Lock()
        self._last_export_at: dict[str, float] = {}
        self._exports_guard = threading.Lock()

    # ──────────────────────────────────────────────────────────────────────
    # Workspace / config
    # ──────────────────────────────────────────────────────────────────────

    def guild_dir(self, guild_id: int | str) -> Path:
        return self.base_dir / _canonical_snowflake(guild_id, "guild_id")

    def raw_db_path(self, guild_id: int | str) -> Path:
        return self.guild_dir(guild_id) / "raw.sqlite"

    def config_path(self, guild_id: int | str) -> Path:
        return self.guild_dir(guild_id) / "config.yaml"

    def _lock(self, guild_id: int | str) -> threading.RLock:
        key = _canonical_snowflake(guild_id, "guild_id")
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def ensure_workspace(self, guild_id: int | str) -> Path:
        key = _canonical_snowflake(guild_id, "guild_id")
        root = self.guild_dir(guild_id)
        if (
            key in self._initialized_workspaces
            and self.raw_db_path(guild_id).exists()
            and self.config_path(guild_id).exists()
        ):
            return root
        with self._init_guard:
            if (
                key in self._initialized_workspaces
                and self.raw_db_path(guild_id).exists()
                and self.config_path(guild_id).exists()
            ):
                return root
            for subdir in ("checkpoints", "exports", "logs", "synthesis", "vectorstore", "tmp"):
                (root / subdir).mkdir(parents=True, exist_ok=True)
            if not self.config_path(guild_id).exists():
                self.save_config(guild_id, DEFAULT_RAG_CONFIG)
            self.init_schema(guild_id)
            self._initialized_workspaces.add(key)
        return root

    def load_config(self, guild_id: int | str) -> dict[str, Any]:
        self.guild_dir(guild_id).mkdir(parents=True, exist_ok=True)
        cfg = dict(DEFAULT_RAG_CONFIG)
        path = self.config_path(guild_id)
        if path.exists():
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key in cfg:
                    cfg[key] = _parse_scalar(value)
        # Normalización defensiva
        cfg["enabled"] = _as_bool(cfg.get("enabled", True))
        cfg["backfill_enabled"] = _as_bool(cfg.get("backfill_enabled", True))
        cfg["capture_live_messages"] = _as_bool(cfg.get("capture_live_messages", True))
        cfg["capture_threads"] = _as_bool(cfg.get("capture_threads", True))
        cfg["capture_forums"] = _as_bool(cfg.get("capture_forums", True))
        cfg["capture_archived_threads"] = _as_bool(cfg.get("capture_archived_threads", True))
        cfg["include_bots"] = _as_bool(cfg.get("include_bots", False))
        for int_key, (minimum, maximum) in RAG_INT_CONFIG_BOUNDS.items():
            try:
                cfg[int_key] = min(
                    maximum,
                    max(minimum, int(cfg.get(int_key, DEFAULT_RAG_CONFIG[int_key]))),
                )
            except (TypeError, ValueError):
                cfg[int_key] = DEFAULT_RAG_CONFIG[int_key]
        excluded = cfg.get("excluded_channel_ids") or []
        if not isinstance(excluded, list):
            excluded = []
        cfg["excluded_channel_ids"] = [
            str(x)
            for x in excluded[:MAX_EXCLUDED_CHANNELS]
            if x not in (None, "")
        ]
        return cfg

    def save_config(self, guild_id: int | str, updates: Mapping[str, Any]) -> dict[str, Any]:
        root = self.guild_dir(guild_id)
        root.mkdir(parents=True, exist_ok=True)
        cfg = dict(DEFAULT_RAG_CONFIG)
        if self.config_path(guild_id).exists():
            cfg.update(self.load_config(guild_id))
        for key, value in updates.items():
            if key in DEFAULT_RAG_CONFIG:
                cfg[key] = value
        for int_key, (minimum, maximum) in RAG_INT_CONFIG_BOUNDS.items():
            try:
                cfg[int_key] = min(maximum, max(minimum, int(cfg[int_key])))
            except (TypeError, ValueError, KeyError):
                cfg[int_key] = DEFAULT_RAG_CONFIG[int_key]
        # Reusar load_config para normalizar después de escribir no es posible aún,
        # así que normalizamos la lista principal aquí.
        if "excluded_channel_ids" in cfg and isinstance(cfg["excluded_channel_ids"], list):
            cfg["excluded_channel_ids"] = [
                str(x)
                for x in cfg["excluded_channel_ids"][:MAX_EXCLUDED_CHANNELS]
                if x not in (None, "")
            ]
        lines = [
            "# Configuración local del módulo RAG/Scraper.",
            "# Este archivo pertenece únicamente a este guild.",
        ]
        for key in DEFAULT_RAG_CONFIG:
            lines.append(f"{key}: {_format_scalar(cfg[key])}")
        self.config_path(guild_id).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.load_config(guild_id)

    # ──────────────────────────────────────────────────────────────────────
    # SQLite
    # ──────────────────────────────────────────────────────────────────────

    def _connect(self, guild_id: int | str) -> sqlite3.Connection:
        root = self.guild_dir(guild_id)
        root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.raw_db_path(guild_id)))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.execute("PRAGMA journal_size_limit=16777216")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self, guild_id: int | str) -> None:
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS channels (
                        channel_id TEXT PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        name TEXT,
                        type TEXT,
                        category_id TEXT,
                        parent_id TEXT,
                        position INTEGER,
                        nsfw INTEGER DEFAULT 0,
                        archived INTEGER DEFAULT 0,
                        raw_json TEXT,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS threads (
                        thread_id TEXT PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        parent_channel_id TEXT,
                        name TEXT,
                        owner_id TEXT,
                        archived INTEGER DEFAULT 0,
                        locked INTEGER DEFAULT 0,
                        type TEXT,
                        created_at TEXT,
                        archived_at TEXT,
                        raw_json TEXT,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        message_id TEXT PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        thread_id TEXT,
                        author_id TEXT,
                        author_name TEXT,
                        author_bot INTEGER DEFAULT 0,
                        content TEXT,
                        clean_content TEXT,
                        attachments_json TEXT,
                        embeds_json TEXT,
                        mentions_json TEXT,
                        reactions_json TEXT,
                        reference_message_id TEXT,
                        message_type TEXT,
                        is_pinned INTEGER DEFAULT 0,
                        is_deleted INTEGER DEFAULT 0,
                        jump_url TEXT,
                        created_at TEXT,
                        edited_at TEXT,
                        captured_at TEXT NOT NULL,
                        deleted_at TEXT,
                        raw_json TEXT,
                        payload_bytes INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS checkpoints (
                        scope_key TEXT PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        channel_id TEXT,
                        thread_id TEXT,
                        last_message_id TEXT,
                        last_message_created_at TEXT,
                        status TEXT,
                        meta_json TEXT,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS corpus_usage (
                        guild_id TEXT PRIMARY KEY,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        payload_bytes INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_guild_channel ON messages(guild_id, channel_id);
                    CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(guild_id, thread_id);
                    CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(guild_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_messages_captured ON messages(guild_id, captured_at);
                    CREATE INDEX IF NOT EXISTS idx_checkpoints_guild ON checkpoints(guild_id);
                    """
                )
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(messages)").fetchall()
                }
                if "payload_bytes" not in columns:
                    conn.execute(
                        "ALTER TABLE messages ADD COLUMN payload_bytes INTEGER NOT NULL DEFAULT 0"
                    )
                conn.execute(
                    """
                    UPDATE messages SET payload_bytes =
                        length(CAST(COALESCE(message_id, '') AS BLOB)) +
                        length(CAST(COALESCE(guild_id, '') AS BLOB)) +
                        length(CAST(COALESCE(channel_id, '') AS BLOB)) +
                        length(CAST(COALESCE(thread_id, '') AS BLOB)) +
                        length(CAST(COALESCE(author_id, '') AS BLOB)) +
                        length(CAST(COALESCE(author_name, '') AS BLOB)) +
                        length(CAST(COALESCE(content, '') AS BLOB)) +
                        length(CAST(COALESCE(clean_content, '') AS BLOB)) +
                        length(CAST(COALESCE(attachments_json, '') AS BLOB)) +
                        length(CAST(COALESCE(embeds_json, '') AS BLOB)) +
                        length(CAST(COALESCE(mentions_json, '') AS BLOB)) +
                        length(CAST(COALESCE(reactions_json, '') AS BLOB)) +
                        length(CAST(COALESCE(reference_message_id, '') AS BLOB)) +
                        length(CAST(COALESCE(message_type, '') AS BLOB)) +
                        length(CAST(COALESCE(jump_url, '') AS BLOB)) +
                        length(CAST(COALESCE(created_at, '') AS BLOB)) +
                        length(CAST(COALESCE(edited_at, '') AS BLOB)) +
                        length(CAST(COALESCE(captured_at, '') AS BLOB)) +
                        length(CAST(COALESCE(deleted_at, '') AS BLOB)) +
                        length(CAST(COALESCE(raw_json, '') AS BLOB))
                    WHERE payload_bytes <= 0
                    """
                )
                guild_key = _canonical_snowflake(guild_id, "guild_id")
                conn.execute(
                    """
                    INSERT INTO corpus_usage(guild_id, message_count, payload_bytes, updated_at)
                    VALUES(
                        ?,
                        (SELECT COUNT(*) FROM messages WHERE guild_id=?),
                        (SELECT COALESCE(SUM(payload_bytes), 0) FROM messages WHERE guild_id=?),
                        ?
                    )
                    ON CONFLICT(guild_id) DO UPDATE SET
                      message_count=excluded.message_count,
                      payload_bytes=excluded.payload_bytes,
                      updated_at=excluded.updated_at
                    """,
                    (guild_key, guild_key, guild_key, utc_now_iso()),
                )

    def upsert_channel(self, guild_id: int | str, data: Mapping[str, Any]) -> None:
        self.ensure_workspace(guild_id)
        now = utc_now_iso()
        row = {
            "channel_id": _sid(data.get("channel_id")),
            "guild_id": str(guild_id),
            "name": data.get("name"),
            "type": data.get("type"),
            "category_id": _sid(data.get("category_id")),
            "parent_id": _sid(data.get("parent_id")),
            "position": data.get("position"),
            "nsfw": 1 if data.get("nsfw") else 0,
            "archived": 1 if data.get("archived") else 0,
            "raw_json": json.dumps(data.get("raw") or {}, ensure_ascii=False),
            "first_seen_at": now,
            "last_seen_at": now,
        }
        if not row["channel_id"]:
            return
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO channels(channel_id, guild_id, name, type, category_id, parent_id,
                                         position, nsfw, archived, raw_json, first_seen_at, last_seen_at)
                    VALUES(:channel_id, :guild_id, :name, :type, :category_id, :parent_id,
                           :position, :nsfw, :archived, :raw_json, :first_seen_at, :last_seen_at)
                    ON CONFLICT(channel_id) DO UPDATE SET
                      name=excluded.name, type=excluded.type, category_id=excluded.category_id,
                      parent_id=excluded.parent_id, position=excluded.position, nsfw=excluded.nsfw,
                      archived=excluded.archived, raw_json=excluded.raw_json,
                      last_seen_at=excluded.last_seen_at
                    """,
                    row,
                )

    def upsert_thread(self, guild_id: int | str, data: Mapping[str, Any]) -> None:
        self.ensure_workspace(guild_id)
        now = utc_now_iso()
        row = {
            "thread_id": _sid(data.get("thread_id")),
            "guild_id": str(guild_id),
            "parent_channel_id": _sid(data.get("parent_channel_id")),
            "name": data.get("name"),
            "owner_id": _sid(data.get("owner_id")),
            "archived": 1 if data.get("archived") else 0,
            "locked": 1 if data.get("locked") else 0,
            "type": data.get("type"),
            "created_at": data.get("created_at"),
            "archived_at": data.get("archived_at"),
            "raw_json": json.dumps(data.get("raw") or {}, ensure_ascii=False),
            "first_seen_at": now,
            "last_seen_at": now,
        }
        if not row["thread_id"]:
            return
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO threads(thread_id, guild_id, parent_channel_id, name, owner_id,
                                        archived, locked, type, created_at, archived_at, raw_json,
                                        first_seen_at, last_seen_at)
                    VALUES(:thread_id, :guild_id, :parent_channel_id, :name, :owner_id,
                           :archived, :locked, :type, :created_at, :archived_at, :raw_json,
                           :first_seen_at, :last_seen_at)
                    ON CONFLICT(thread_id) DO UPDATE SET
                      parent_channel_id=excluded.parent_channel_id, name=excluded.name,
                      owner_id=excluded.owner_id, archived=excluded.archived, locked=excluded.locked,
                      type=excluded.type, archived_at=excluded.archived_at, raw_json=excluded.raw_json,
                      last_seen_at=excluded.last_seen_at
                    """,
                    row,
                )

    @staticmethod
    def _message_payload_bytes(row: Mapping[str, Any]) -> int:
        fields = (
            "message_id",
            "guild_id",
            "channel_id",
            "thread_id",
            "author_id",
            "author_name",
            "content",
            "clean_content",
            "attachments_json",
            "embeds_json",
            "mentions_json",
            "reactions_json",
            "reference_message_id",
            "message_type",
            "jump_url",
            "created_at",
            "edited_at",
            "captured_at",
            "deleted_at",
            "raw_json",
        )
        return sum(
            len(str(row.get(field) or "").encode("utf-8", errors="replace"))
            for field in fields
        )

    @staticmethod
    def _usage_locked(conn: sqlite3.Connection, guild_key: str) -> tuple[int, int]:
        usage = conn.execute(
            "SELECT message_count, payload_bytes FROM corpus_usage WHERE guild_id=?",
            (guild_key,),
        ).fetchone()
        if usage is not None:
            return int(usage[0] or 0), int(usage[1] or 0)
        count, payload_bytes = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0) FROM messages WHERE guild_id=?",
            (guild_key,),
        ).fetchone()
        conn.execute(
            "INSERT INTO corpus_usage(guild_id, message_count, payload_bytes, updated_at) VALUES(?, ?, ?, ?)",
            (guild_key, int(count or 0), int(payload_bytes or 0), utc_now_iso()),
        )
        return int(count or 0), int(payload_bytes or 0)

    @staticmethod
    def _set_usage_locked(
        conn: sqlite3.Connection,
        guild_key: str,
        message_count: int,
        payload_bytes: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO corpus_usage(guild_id, message_count, payload_bytes, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              message_count=excluded.message_count,
              payload_bytes=excluded.payload_bytes,
              updated_at=excluded.updated_at
            """,
            (
                guild_key,
                max(0, int(message_count)),
                max(0, int(payload_bytes)),
                utc_now_iso(),
            ),
        )

    @classmethod
    def _prune_for_limits_locked(
        cls,
        conn: sqlite3.Connection,
        guild_key: str,
        projected_count: int,
        projected_bytes: int,
    ) -> tuple[int, int, int]:
        deleted = 0
        while (
            projected_count > MAX_RAW_MESSAGES_PER_GUILD
            or projected_bytes > MAX_RAW_PAYLOAD_BYTES_PER_GUILD
        ):
            rows = conn.execute(
                """
                SELECT message_id, COALESCE(payload_bytes, 0) AS payload_bytes
                FROM messages
                WHERE guild_id=?
                ORDER BY COALESCE(NULLIF(created_at, ''), captured_at, '') ASC,
                         CAST(message_id AS INTEGER) ASC
                LIMIT ?
                """,
                (guild_key, RAW_PRUNE_BATCH_ROWS),
            ).fetchall()
            if not rows:
                break

            needed_count = max(0, projected_count - MAX_RAW_MESSAGES_PER_GUILD)
            needed_bytes = max(0, projected_bytes - MAX_RAW_PAYLOAD_BYTES_PER_GUILD)
            victims: list[str] = []
            freed_bytes = 0
            for old_row in rows:
                victims.append(str(old_row[0]))
                freed_bytes += int(old_row[1] or 0)
                if len(victims) >= needed_count and freed_bytes >= needed_bytes:
                    break
            placeholders = ",".join("?" for _ in victims)
            conn.execute(
                f"DELETE FROM messages WHERE guild_id=? AND message_id IN ({placeholders})",
                [guild_key, *victims],
            )
            projected_count -= len(victims)
            projected_bytes -= freed_bytes
            deleted += len(victims)
        return max(0, projected_count), max(0, projected_bytes), deleted

    def upsert_message(self, guild_id: int | str, data: Mapping[str, Any]) -> bool:
        self.ensure_workspace(guild_id)
        guild_key = _canonical_snowflake(guild_id, "guild_id")
        row = {
            "message_id": _sid(data.get("message_id")),
            "guild_id": guild_key,
            "channel_id": _sid(data.get("channel_id")),
            "thread_id": _sid(data.get("thread_id")),
            "author_id": _sid(data.get("author_id")),
            "author_name": data.get("author_name"),
            "author_bot": 1 if data.get("author_bot") else 0,
            "content": data.get("content"),
            "clean_content": data.get("clean_content"),
            "attachments_json": json.dumps(data.get("attachments") or [], ensure_ascii=False),
            "embeds_json": json.dumps(data.get("embeds") or [], ensure_ascii=False),
            "mentions_json": json.dumps(data.get("mentions") or {}, ensure_ascii=False),
            "reactions_json": json.dumps(data.get("reactions") or [], ensure_ascii=False),
            "reference_message_id": _sid(data.get("reference_message_id")),
            "message_type": data.get("message_type"),
            "is_pinned": 1 if data.get("is_pinned") else 0,
            "is_deleted": 1 if data.get("is_deleted") else 0,
            "jump_url": data.get("jump_url"),
            "created_at": data.get("created_at"),
            "edited_at": data.get("edited_at"),
            "captured_at": data.get("captured_at") or utc_now_iso(),
            "deleted_at": data.get("deleted_at"),
            "raw_json": json.dumps(data.get("raw") or {}, ensure_ascii=False),
        }
        if not row["message_id"] or not row["channel_id"]:
            return False
        created_at = _parse_utc_datetime(row["created_at"])
        if row["created_at"] not in (None, "") and created_at is None:
            return False
        if created_at is not None and created_at < (
            datetime.now(timezone.utc) - timedelta(days=RAW_MESSAGE_RETENTION_DAYS)
        ):
            return False
        if created_at is not None:
            row["created_at"] = created_at.isoformat()
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                existing = conn.execute(
                    """
                    SELECT guild_id, COALESCE(payload_bytes, 0) AS payload_bytes,
                           COALESCE(is_deleted, 0) AS is_deleted, deleted_at, created_at
                    FROM messages WHERE message_id=?
                    """,
                    (row["message_id"],),
                ).fetchone()
                if existing is not None and str(existing[0]) != guild_key:
                    return False
                if existing is not None:
                    row["created_at"] = existing["created_at"] or row["created_at"]
                    if bool(existing["is_deleted"]):
                        row["is_deleted"] = 1
                        row["deleted_at"] = (
                            existing["deleted_at"] or row["deleted_at"] or utc_now_iso()
                        )
                if row["is_deleted"] and not row["deleted_at"]:
                    row["deleted_at"] = utc_now_iso()
                row["payload_bytes"] = self._message_payload_bytes(row)
                if row["payload_bytes"] > MAX_RAW_MESSAGE_BYTES:
                    return False

                old_bytes = int(existing["payload_bytes"] or 0) if existing is not None else 0
                message_count, payload_bytes = self._usage_locked(conn, guild_key)
                projected_count = message_count + (0 if existing is not None else 1)
                projected_bytes = payload_bytes - old_bytes + int(row["payload_bytes"])
                conn.execute(
                    """
                    INSERT INTO messages(message_id, guild_id, channel_id, thread_id, author_id,
                                         author_name, author_bot, content, clean_content,
                                         attachments_json, embeds_json, mentions_json, reactions_json,
                                         reference_message_id, message_type, is_pinned, is_deleted,
                                         jump_url, created_at, edited_at, captured_at, deleted_at,
                                         raw_json, payload_bytes)
                    VALUES(:message_id, :guild_id, :channel_id, :thread_id, :author_id,
                           :author_name, :author_bot, :content, :clean_content,
                           :attachments_json, :embeds_json, :mentions_json, :reactions_json,
                           :reference_message_id, :message_type, :is_pinned, :is_deleted,
                           :jump_url, :created_at, :edited_at, :captured_at, :deleted_at,
                           :raw_json, :payload_bytes)
                    ON CONFLICT(message_id) DO UPDATE SET
                      channel_id=excluded.channel_id, thread_id=excluded.thread_id,
                      author_id=excluded.author_id, author_name=excluded.author_name,
                      author_bot=excluded.author_bot, content=excluded.content,
                      clean_content=excluded.clean_content, attachments_json=excluded.attachments_json,
                      embeds_json=excluded.embeds_json, mentions_json=excluded.mentions_json,
                      reactions_json=excluded.reactions_json,
                      reference_message_id=excluded.reference_message_id,
                      message_type=excluded.message_type, is_pinned=excluded.is_pinned,
                      is_deleted=MAX(
                          COALESCE(messages.is_deleted, 0),
                          COALESCE(excluded.is_deleted, 0)
                      ),
                      jump_url=excluded.jump_url,
                      created_at=COALESCE(messages.created_at, excluded.created_at),
                      edited_at=excluded.edited_at, captured_at=excluded.captured_at,
                      deleted_at=COALESCE(messages.deleted_at, excluded.deleted_at),
                      raw_json=excluded.raw_json, payload_bytes=excluded.payload_bytes
                    """,
                    row,
                )
                projected_count, projected_bytes, _deleted = self._prune_for_limits_locked(
                    conn,
                    guild_key,
                    projected_count,
                    projected_bytes,
                )
                self._set_usage_locked(conn, guild_key, projected_count, projected_bytes)
                retained = conn.execute(
                    "SELECT 1 FROM messages WHERE message_id=? AND guild_id=?",
                    (row["message_id"], guild_key),
                ).fetchone()
                return retained is not None

    def mark_message_deleted(
        self,
        guild_id: int | str,
        message_id: int | str,
        channel_id: int | str | None = None,
    ) -> bool:
        self.ensure_workspace(guild_id)
        deleted_at = utc_now_iso()
        guild_key = _canonical_snowflake(guild_id, "guild_id")
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                existing = conn.execute(
                    """
                    SELECT COALESCE(payload_bytes, 0), COALESCE(deleted_at, '')
                    FROM messages WHERE message_id=? AND guild_id=?
                    """,
                    (str(message_id), guild_key),
                ).fetchone()
                if existing is None:
                    return False
                stored_deleted_at = str(existing[1] or "") or deleted_at
                deleted_delta = len(stored_deleted_at.encode("utf-8")) - len(
                    str(existing[1] or "").encode("utf-8")
                )
                cur = conn.execute(
                    """
                    UPDATE messages
                    SET is_deleted=1, deleted_at=?, payload_bytes=payload_bytes+?
                    WHERE message_id=? AND guild_id=?
                    """,
                    (
                        stored_deleted_at,
                        deleted_delta,
                        str(message_id),
                        guild_key,
                    ),
                )
                message_count, payload_bytes = self._usage_locked(conn, guild_key)
                message_count, payload_bytes, _deleted = self._prune_for_limits_locked(
                    conn,
                    guild_key,
                    message_count,
                    payload_bytes + deleted_delta,
                )
                self._set_usage_locked(conn, guild_key, message_count, payload_bytes)
                return cur.rowcount > 0

    def prune_corpus(self, guild_id: int | str) -> dict[str, int]:
        """Aplica retención y reconcilia las cuotas lógicas del corpus del guild."""
        self.ensure_workspace(guild_id)
        guild_key = _canonical_snowflake(guild_id, "guild_id")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RAW_MESSAGE_RETENTION_DAYS)).isoformat()
        oversized_deleted = 0
        expired_deleted = 0
        quota_deleted = 0
        metadata_expired_deleted = 0
        metadata_quota_deleted = 0

        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn:
                with conn:
                    while True:
                        oversized = conn.execute(
                            """
                            SELECT message_id FROM messages
                            WHERE guild_id=? AND payload_bytes>?
                            ORDER BY payload_bytes DESC
                            LIMIT ?
                            """,
                            (guild_key, MAX_RAW_MESSAGE_BYTES, RAW_PRUNE_BATCH_ROWS),
                        ).fetchall()
                        if not oversized:
                            break
                        ids = [str(row[0]) for row in oversized]
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(
                            f"DELETE FROM messages WHERE guild_id=? AND message_id IN ({placeholders})",
                            [guild_key, *ids],
                        )
                        oversized_deleted += len(ids)

                    while True:
                        expired = conn.execute(
                            """
                            SELECT message_id
                            FROM messages
                            WHERE guild_id=?
                              AND COALESCE(NULLIF(created_at, ''), captured_at, '') < ?
                            ORDER BY COALESCE(NULLIF(created_at, ''), captured_at, '') ASC
                            LIMIT ?
                            """,
                            (guild_key, cutoff, RAW_PRUNE_BATCH_ROWS),
                        ).fetchall()
                        if not expired:
                            break
                        ids = [str(row[0]) for row in expired]
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(
                            f"DELETE FROM messages WHERE guild_id=? AND message_id IN ({placeholders})",
                            [guild_key, *ids],
                        )
                        expired_deleted += len(ids)

                    message_count, payload_bytes = conn.execute(
                        """
                        SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0)
                        FROM messages WHERE guild_id=?
                        """,
                        (guild_key,),
                    ).fetchone()
                    message_count, payload_bytes, quota_deleted = self._prune_for_limits_locked(
                        conn,
                        guild_key,
                        int(message_count or 0),
                        int(payload_bytes or 0),
                    )

                    while True:
                        stale_threads = conn.execute(
                            """
                            SELECT thread_id FROM threads
                            WHERE guild_id=? AND COALESCE(archived, 0)=1
                              AND COALESCE(NULLIF(archived_at, ''), last_seen_at, '') < ?
                            ORDER BY COALESCE(NULLIF(archived_at, ''), last_seen_at, '') ASC
                            LIMIT ?
                            """,
                            (guild_key, cutoff, RAW_PRUNE_BATCH_ROWS),
                        ).fetchall()
                        if not stale_threads:
                            break
                        ids = [str(row[0]) for row in stale_threads]
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(
                            f"DELETE FROM threads WHERE guild_id=? AND thread_id IN ({placeholders})",
                            [guild_key, *ids],
                        )
                        metadata_expired_deleted += len(ids)

                    metadata_caps = (
                        (
                            "threads",
                            "thread_id",
                            "COALESCE(NULLIF(archived_at, ''), NULLIF(created_at, ''), last_seen_at, '')",
                            MAX_RAW_THREADS_PER_GUILD,
                        ),
                        (
                            "checkpoints",
                            "scope_key",
                            "COALESCE(updated_at, '')",
                            MAX_RAW_CHECKPOINTS_PER_GUILD,
                        ),
                    )
                    for table, id_column, order_column, maximum in metadata_caps:
                        count = int(
                            conn.execute(
                                f"SELECT COUNT(*) FROM {table} WHERE guild_id=?",
                                (guild_key,),
                            ).fetchone()[0]
                            or 0
                        )
                        excess = max(0, count - maximum)
                        while excess > 0:
                            batch = conn.execute(
                                f"""
                                SELECT {id_column} FROM {table}
                                WHERE guild_id=?
                                ORDER BY {order_column} ASC
                                LIMIT ?
                                """,
                                (guild_key, min(excess, RAW_PRUNE_BATCH_ROWS)),
                            ).fetchall()
                            if not batch:
                                break
                            ids = [str(row[0]) for row in batch]
                            placeholders = ",".join("?" for _ in ids)
                            conn.execute(
                                f"DELETE FROM {table} WHERE guild_id=? AND {id_column} IN ({placeholders})",
                                [guild_key, *ids],
                            )
                            excess -= len(ids)
                            metadata_quota_deleted += len(ids)

                    self._set_usage_locked(
                        conn,
                        guild_key,
                        message_count,
                        payload_bytes,
                    )
                try:
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    conn.execute("PRAGMA optimize")
                except sqlite3.DatabaseError:
                    pass

        return {
            "message_count": message_count,
            "payload_bytes": payload_bytes,
            "oversized_deleted": oversized_deleted,
            "expired_deleted": expired_deleted,
            "quota_deleted": quota_deleted,
            "metadata_expired_deleted": metadata_expired_deleted,
            "metadata_quota_deleted": metadata_quota_deleted,
        }

    def get_checkpoint(self, guild_id: int | str, scope_key: str) -> Optional[dict[str, Any]]:
        self.ensure_workspace(guild_id)
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                row = conn.execute(
                    "SELECT * FROM checkpoints WHERE scope_key=?",
                    (scope_key,),
                ).fetchone()
                return dict(row) if row else None

    def set_checkpoint(
        self,
        guild_id: int | str,
        scope_key: str,
        *,
        channel_id: int | str | None = None,
        thread_id: int | str | None = None,
        last_message_id: int | str | None = None,
        last_message_created_at: str | None = None,
        status: str = "ok",
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.ensure_workspace(guild_id)
        row = {
            "scope_key": scope_key,
            "guild_id": str(guild_id),
            "channel_id": _sid(channel_id),
            "thread_id": _sid(thread_id),
            "last_message_id": _sid(last_message_id),
            "last_message_created_at": last_message_created_at,
            "status": status,
            "meta_json": json.dumps(meta or {}, ensure_ascii=False),
            "updated_at": utc_now_iso(),
        }
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO checkpoints(scope_key, guild_id, channel_id, thread_id,
                                            last_message_id, last_message_created_at,
                                            status, meta_json, updated_at)
                    VALUES(:scope_key, :guild_id, :channel_id, :thread_id,
                           :last_message_id, :last_message_created_at,
                           :status, :meta_json, :updated_at)
                    ON CONFLICT(scope_key) DO UPDATE SET
                      channel_id=excluded.channel_id, thread_id=excluded.thread_id,
                      last_message_id=COALESCE(excluded.last_message_id, checkpoints.last_message_id),
                      last_message_created_at=COALESCE(excluded.last_message_created_at, checkpoints.last_message_created_at),
                      status=excluded.status, meta_json=excluded.meta_json,
                      updated_at=excluded.updated_at
                    """,
                    row,
                )

    def stats(self, guild_id: int | str) -> dict[str, Any]:
        self.ensure_workspace(guild_id)
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                counts = {}
                for table in ("channels", "threads", "messages", "checkpoints"):
                    counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                deleted = conn.execute("SELECT COUNT(*) FROM messages WHERE is_deleted=1").fetchone()[0]
                last = conn.execute("SELECT MAX(captured_at) FROM messages").fetchone()[0]
                checkpoint_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT scope_key, status, updated_at, last_message_id FROM checkpoints ORDER BY updated_at DESC LIMIT 10"
                    ).fetchall()
                ]
        return {
            "guild_id": str(guild_id),
            "workspace": str(self.guild_dir(guild_id)),
            "raw_db": str(self.raw_db_path(guild_id)),
            "counts": counts,
            "deleted_messages": deleted,
            "last_capture_at": last,
            "recent_checkpoints": checkpoint_rows,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Exports legibles
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _effective_export_limit(limit: int | None, export_all: bool) -> int:
        if export_all:
            return MAX_EXPORT_ROWS
        if limit is None:
            return DEFAULT_EXPORT_LIMIT
        try:
            requested = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit debe ser un entero positivo.") from exc
        if requested <= 0:
            raise ValueError("limit debe ser mayor que cero.")
        return min(requested, MAX_EXPORT_ROWS)

    def _claim_export_slot(self, guild_id: int | str) -> None:
        key = _canonical_snowflake(guild_id, "guild_id")
        now = time.monotonic()
        with self._exports_guard:
            last_export = self._last_export_at.get(key)
            if last_export is not None:
                remaining = MIN_EXPORT_INTERVAL_SECONDS - (now - last_export)
                if remaining > 0:
                    raise RuntimeError(
                        f"Espera {int(remaining) + 1} segundos antes de crear otro export de este servidor."
                    )
            self._last_export_at[key] = now

    @staticmethod
    def _estimated_row_bytes(row: Mapping[str, Any]) -> int:
        total = 0
        for value in row.values():
            if value is None:
                continue
            if isinstance(value, bytes):
                total += len(value)
            else:
                total += len(str(value).encode("utf-8", errors="replace"))
        return total

    @staticmethod
    def _prune_exports(exports_dir: Path, incoming_bytes: int) -> None:
        if incoming_bytes > MAX_EXPORT_STORAGE_BYTES:
            raise ValueError("El export excede la cuota de almacenamiento permitida.")

        files: list[tuple[Path, int, float]] = []
        for candidate in exports_dir.glob("rag-export-*"):
            try:
                if candidate.is_file():
                    stat = candidate.stat()
                    files.append((candidate, stat.st_size, stat.st_mtime))
            except OSError:
                continue
        files.sort(key=lambda item: item[2])
        current_bytes = sum(item[1] for item in files)
        while files and (
            len(files) >= MAX_EXPORT_FILES_PER_GUILD
            or current_bytes + incoming_bytes > MAX_EXPORT_STORAGE_BYTES
        ):
            victim, size, _mtime = files.pop(0)
            try:
                victim.unlink()
                current_bytes -= size
            except OSError:
                break
        if (
            len(files) >= MAX_EXPORT_FILES_PER_GUILD
            or current_bytes + incoming_bytes > MAX_EXPORT_STORAGE_BYTES
        ):
            raise ValueError("No hay espacio disponible dentro de la cuota de exports.")

    def _export_rows(
        self,
        guild_id: int | str,
        *,
        channel_id: int | str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        export_all: bool = False,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        self.ensure_workspace(guild_id)
        guild_key = _canonical_snowflake(guild_id, "guild_id")
        channel_key = (
            _canonical_snowflake(channel_id, "channel_id")
            if channel_id not in (None, "")
            else None
        )
        effective_limit = self._effective_export_limit(limit, export_all)
        clauses = ["m.guild_id = ?"]
        params: list[Any] = [guild_key]
        if not include_deleted:
            clauses.append("COALESCE(m.is_deleted, 0) = 0")
        if channel_key is not None:
            clauses.append("(m.channel_id = ? OR m.thread_id = ?)")
            params.extend([channel_key, channel_key])
        sql = f"""
            SELECT m.*, c.name AS channel_name, t.name AS thread_name,
                   COALESCE(m.created_at, m.captured_at, '') AS _sort_ts,
                   CAST(m.message_id AS INTEGER) AS _sort_id
            FROM messages m
            LEFT JOIN channels c ON c.channel_id = m.channel_id
            LEFT JOIN threads t ON t.thread_id = m.thread_id
            WHERE {' AND '.join(clauses)}
        """
        sql = f"""
            SELECT * FROM (
                {sql}
                ORDER BY _sort_ts DESC, _sort_id DESC
                LIMIT ?
            )
            ORDER BY _sort_ts ASC, _sort_id ASC
        """
        params.append(effective_limit + 1)
        with self._lock(guild_id):
            with closing(self._connect(guild_id)) as conn, conn:
                rows: list[dict[str, Any]] = []
                estimated_bytes = 0
                truncated = False
                for sqlite_row in conn.execute(sql, params):
                    row = dict(sqlite_row)
                    estimated_bytes += self._estimated_row_bytes(row)
                    if estimated_bytes > MAX_EXPORT_BYTES:
                        truncated = True
                        break
                    rows.append(row)
                if len(rows) > effective_limit:
                    rows = rows[-effective_limit:]
                    truncated = True
                return rows, effective_limit, truncated

    def _record_for_export(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "message_id": _sid(row.get("message_id")),
            "guild_id": _sid(row.get("guild_id")),
            "channel_id": _sid(row.get("channel_id")),
            "channel_name": row.get("channel_name"),
            "thread_id": _sid(row.get("thread_id")),
            "thread_name": row.get("thread_name"),
            "author_id": _sid(row.get("author_id")),
            "author_name": row.get("author_name"),
            "author_bot": bool(row.get("author_bot")),
            "content": row.get("content") or "",
            "clean_content": row.get("clean_content") or row.get("content") or "",
            "attachments": _json_or(row.get("attachments_json"), []),
            "embeds": _json_or(row.get("embeds_json"), []),
            "mentions": _json_or(row.get("mentions_json"), {}),
            "reactions": _json_or(row.get("reactions_json"), []),
            "raw": _json_or(row.get("raw_json"), {}),
            "reference_message_id": _sid(row.get("reference_message_id")),
            "message_type": row.get("message_type"),
            "is_pinned": bool(row.get("is_pinned")),
            "is_deleted": bool(row.get("is_deleted")),
            "jump_url": row.get("jump_url"),
            "created_at": row.get("created_at"),
            "edited_at": row.get("edited_at"),
            "captured_at": row.get("captured_at"),
            "deleted_at": row.get("deleted_at"),
        }

    def _message_text(self, record: Mapping[str, Any]) -> str:
        raw = record.get("raw") if isinstance(record.get("raw"), Mapping) else {}
        return (
            record.get("clean_content")
            or record.get("content")
            or raw.get("system_content")
            or ""
        ).strip()

    def _format_embed_markdown(self, embed: Mapping[str, Any], index: int) -> list[str]:
        lines = [f"**Embed {index}:**"]
        author = embed.get("author") if isinstance(embed.get("author"), Mapping) else {}
        if author.get("name"):
            lines.append(f"- Autor embed: {author['name']}")
        if embed.get("title"):
            title = str(embed["title"])
            if embed.get("url"):
                title = f"[{title}]({embed['url']})"
            lines.append(f"- Título: {title}")
        if embed.get("description"):
            lines.append("- Descripción:")
            lines.append(str(embed["description"]))
        for field in embed.get("fields") or []:
            if not isinstance(field, Mapping):
                continue
            name = field.get("name") or "Campo"
            value = field.get("value") or ""
            lines.append(f"- {name}: {value}")
        footer = embed.get("footer") if isinstance(embed.get("footer"), Mapping) else {}
        if footer.get("text"):
            lines.append(f"- Footer: {footer['text']}")
        for key in ("image", "thumbnail"):
            data = embed.get(key) if isinstance(embed.get(key), Mapping) else {}
            if data.get("url"):
                lines.append(f"- {key}: {data['url']}")
        if embed.get("timestamp"):
            lines.append(f"- Timestamp: {embed['timestamp']}")
        return lines

    def _format_embed_text(self, embed: Mapping[str, Any], index: int) -> list[str]:
        lines = [f"[embed {index}]"]
        author = embed.get("author") if isinstance(embed.get("author"), Mapping) else {}
        if author.get("name"):
            lines.append(f"embed_author={author['name']}")
        if embed.get("title"):
            lines.append(f"title={embed['title']}")
        if embed.get("description"):
            lines.append(f"description={embed['description']}")
        for field in embed.get("fields") or []:
            if isinstance(field, Mapping):
                lines.append(f"field[{field.get('name') or 'Campo'}]={field.get('value') or ''}")
        footer = embed.get("footer") if isinstance(embed.get("footer"), Mapping) else {}
        if footer.get("text"):
            lines.append(f"footer={footer['text']}")
        for key in ("image", "thumbnail"):
            data = embed.get(key) if isinstance(embed.get(key), Mapping) else {}
            if data.get("url"):
                lines.append(f"{key}={data['url']}")
        return lines

    def _raw_list(self, record: Mapping[str, Any], key: str) -> list[Any]:
        raw = record.get("raw") if isinstance(record.get("raw"), Mapping) else {}
        value = raw.get(key)
        return value if isinstance(value, list) else []

    def _format_message_markdown(self, record: Mapping[str, Any]) -> str:
        channel = record.get("channel_name") or record.get("channel_id") or "canal-desconocido"
        thread = record.get("thread_name")
        author = record.get("author_name") or record.get("author_id") or "usuario-desconocido"
        timestamp = record.get("created_at") or record.get("captured_at") or "sin-fecha"
        deleted = " [BORRADO]" if record.get("is_deleted") else ""
        edited = f" · editado {record['edited_at']}" if record.get("edited_at") else ""
        where = f"#{channel}" + (f" / 🧵 {thread}" if thread else "")
        lines = [f"### {timestamp}{deleted}", f"- **Canal:** {where}", f"- **Autor:** {author} (`{record.get('author_id')}`){edited}"]
        content = self._message_text(record)
        has_rich_payload = bool(record.get("attachments") or record.get("embeds") or self._raw_list(record, "stickers") or self._raw_list(record, "components"))
        if content:
            lines.append("")
            lines.append("**Contenido:**")
            lines.append(content)
        elif not has_rich_payload:
            lines.append("")
            lines.append(
                "_[Sin contenido textual capturado. Si esperabas texto aquí, revisa que el "
                "Message Content Intent esté activado en el Developer Portal y que el bot tenga permisos de lectura/historial.]_"
            )
        if record.get("attachments"):
            lines.append("")
            lines.append("**Adjuntos:**")
            for attachment in record["attachments"]:
                name = attachment.get("filename") or attachment.get("id") or "archivo"
                url = attachment.get("url") or ""
                lines.append(f"- {name}: {url}")
        if record.get("embeds"):
            lines.append("")
            lines.append(f"**Embeds:** {len(record['embeds'])}")
            for index, embed in enumerate(record["embeds"], start=1):
                if isinstance(embed, Mapping):
                    lines.extend(self._format_embed_markdown(embed, index))
                else:
                    lines.append(f"- Embed {index}: {embed}")
        stickers = self._raw_list(record, "stickers")
        if stickers:
            lines.append("")
            lines.append("**Stickers:**")
            for sticker in stickers:
                if isinstance(sticker, Mapping):
                    lines.append(f"- {sticker.get('name') or sticker.get('id') or 'sticker'} ({sticker.get('id') or 'sin-id'})")
                else:
                    lines.append(f"- {sticker}")
        components = self._raw_list(record, "components")
        if components:
            lines.append("")
            lines.append(f"**Componentes/interacciones:** {len(components)}")
        if record.get("jump_url"):
            lines.append(f"\nReferencia Discord: [Ir al mensaje]({record['jump_url']})")
        return "\n".join(lines)

    def _format_message_text(self, record: Mapping[str, Any]) -> str:
        channel = record.get("channel_name") or record.get("channel_id") or "canal-desconocido"
        thread = f" / {record['thread_name']}" if record.get("thread_name") else ""
        author = record.get("author_name") or record.get("author_id") or "usuario-desconocido"
        timestamp = record.get("created_at") or record.get("captured_at") or "sin-fecha"
        deleted = " [BORRADO]" if record.get("is_deleted") else ""
        content = self._message_text(record).replace("\r\n", "\n")
        has_rich_payload = bool(record.get("attachments") or record.get("embeds") or self._raw_list(record, "stickers") or self._raw_list(record, "components"))
        lines = [f"[{timestamp}]{deleted} #{channel}{thread} | {author} ({record.get('author_id')})"]
        if content:
            lines.extend(["[contenido]", content])
        elif not has_rich_payload:
            lines.append("[sin contenido textual capturado: revisar Message Content Intent/permisos si esperabas texto]")
        for attachment in record.get("attachments") or []:
            lines.append(f"[adjunto] {attachment.get('filename') or attachment.get('id')}: {attachment.get('url') or ''}")
        for index, embed in enumerate(record.get("embeds") or [], start=1):
            if isinstance(embed, Mapping):
                lines.extend(self._format_embed_text(embed, index))
        for sticker in self._raw_list(record, "stickers"):
            if isinstance(sticker, Mapping):
                lines.append(f"[sticker] {sticker.get('name') or sticker.get('id')}: {sticker.get('url') or ''}")
        components = self._raw_list(record, "components")
        if components:
            lines.append(f"[componentes] {len(components)}")
        if record.get("jump_url"):
            lines.append(f"[referencia_discord] {record['jump_url']}")
        return "\n".join(line for line in lines if line is not None)

    def export_messages(
        self,
        guild_id: int | str,
        *,
        format: str = "markdown",
        channel_id: int | str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        export_all: bool = False,
    ) -> dict[str, Any]:
        """Exporta mensajes capturados a un archivo legible.

        Formats soportados: ``markdown``/``md``, ``txt`` y ``jsonl``.
        """
        fmt = (format or "markdown").strip().lower()
        if fmt == "md":
            fmt = "markdown"
        if fmt not in {"markdown", "txt", "jsonl"}:
            raise ValueError("Formato inválido. Usa markdown, txt o jsonl.")

        guild_key = _canonical_snowflake(guild_id, "guild_id")
        channel_key = (
            _canonical_snowflake(channel_id, "channel_id")
            if channel_id not in (None, "")
            else None
        )
        self._claim_export_slot(guild_key)

        rows, effective_limit, truncated = self._export_rows(
            guild_key,
            channel_id=channel_key,
            include_deleted=include_deleted,
            limit=limit,
            export_all=export_all,
        )
        exports_dir = self.guild_dir(guild_key) / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        guild_root = self.guild_dir(guild_key).resolve()
        exports_root = exports_dir.resolve()
        if exports_root.parent != guild_root:
            raise ValueError("El directorio de exports no pertenece al workspace del servidor.")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        scope = f"channel-{channel_key}" if channel_key is not None else "all"
        suffix = "md" if fmt == "markdown" else fmt
        path = (exports_dir / f"rag-export-{scope}-{stamp}.{suffix}").resolve()
        if path.parent != exports_root:
            raise ValueError("La ruta del export sale del workspace del servidor.")
        selection_label = (
            f"hasta {effective_limit}"
            if export_all
            else f"últimos {effective_limit}"
        )

        content_budget = MAX_EXPORT_BYTES - (16 * 1024)
        parts: list[str] = []
        content_bytes = 0
        exported_count = 0

        def append_part(value: str) -> bool:
            nonlocal content_bytes
            size = len(value.encode("utf-8"))
            if content_bytes + size > content_budget:
                return False
            parts.append(value)
            content_bytes += size
            return True

        if fmt == "jsonl":
            for row in rows:
                record = self._record_for_export(row)
                if not append_part(json.dumps(record, ensure_ascii=False) + "\n"):
                    truncated = True
                    break
                exported_count += 1
            body = "".join(parts)
        elif fmt == "txt":
            for row in rows:
                record = self._record_for_export(row)
                separator = "" if exported_count == 0 else "\n\n---\n\n"
                if not append_part(separator + self._format_message_text(record)):
                    truncated = True
                    break
                exported_count += 1
            header = [
                f"RAG Export guild={guild_key}",
                f"Generado={utc_now_iso()}",
                f"Mensajes={exported_count}",
                f"Selección={selection_label}",
                f"Truncado={bool(truncated)}",
                "",
            ]
            body = "\n".join(header) + "\n" + "".join(parts)
        else:
            for row in rows:
                record = self._record_for_export(row)
                separator = "" if exported_count == 0 else "\n---\n"
                if not append_part(separator + self._format_message_markdown(record)):
                    truncated = True
                    break
                exported_count += 1
            header = [
                f"# RAG Export — Guild `{guild_key}`",
                "",
                f"- Generado: `{utc_now_iso()}`",
                f"- Mensajes: `{exported_count}`",
                f"- Selección: `{selection_label}`",
                f"- Canal/hilo filtrado: `{channel_key}`" if channel_key is not None else "- Canal/hilo filtrado: `todos`",
                f"- Incluye borrados: `{bool(include_deleted)}`",
                f"- Truncado por límites seguros: `{bool(truncated)}`",
                "",
            ]
            body = "\n".join(header) + "\n" + "".join(parts)

        body_bytes = len(body.encode("utf-8"))
        if body_bytes > MAX_EXPORT_BYTES:
            raise ValueError("El export excede el tamaño máximo permitido.")
        self._prune_exports(exports_dir, body_bytes)
        path.write_text(body, encoding="utf-8")
        return {
            "guild_id": guild_key,
            "format": fmt,
            "channel_id": channel_key,
            "include_deleted": bool(include_deleted),
            "limit": effective_limit,
            "export_all": bool(export_all),
            "selection": selection_label,
            "count": exported_count,
            "truncated": bool(truncated),
            "path": str(path),
            "filename": path.name,
            "bytes": body_bytes,
        }

    def list_workspaces(self) -> Iterable[Path]:
        if not self.base_dir.exists():
            return []
        return [p for p in self.base_dir.iterdir() if p.is_dir()]
