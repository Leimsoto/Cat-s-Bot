"""Serialización efímera de sanciones que comparten un efecto Discord."""

from __future__ import annotations

import asyncio
import secrets
import weakref
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_BAN_REASON_LIMIT = 512
_BAN_MARKER_PREFIX = "[catbot-ban:"
_MUTE_MARKER_PREFIX = "[catbot-mute:"


def sanction_family(action_type: str) -> str:
    action = str(action_type or "").upper()
    if action in {
        "BAN", "TEMPBAN", "FORCEBAN", "AUTO_BAN", "SOFTBAN",
        "UNBAN", "TEMPBAN_EXPIRE",
    }:
        return "BAN"
    if action in {
        "MUTE", "AUTO_MUTE", "HARDMUTE", "UNMUTE",
        "MUTE_EXPIRE", "HARDMUTE_EXPIRE",
    }:
        return "MUTE"
    if action in {"WARN", "AUTO_WARN", "UNWARN", "CLEAR_WARNS"}:
        return "WARN"
    return action or "UNKNOWN"


def new_ban_effect_token() -> str:
    """Crea una identidad impredecible para un efecto de ban concreto."""
    return secrets.token_hex(16)


def new_mute_effect_token() -> str:
    return secrets.token_hex(16)


def ban_effect_marker(token: str) -> str:
    clean = str(token or "").strip()
    if not clean:
        raise ValueError("missing_ban_effect_token")
    return f"{_BAN_MARKER_PREFIX}{clean}]"


def reason_with_ban_effect(reason: str, token: str) -> str:
    """Conserva el marcador aunque Discord limite el audit-log reason."""
    marker = ban_effect_marker(token)
    text = " ".join(str(reason or "").split())
    available = _BAN_REASON_LIMIT - len(marker) - 1
    return f"{marker} {text[:max(0, available)]}".rstrip()


def ban_reason_matches(reason: object, token: str) -> bool:
    """Comprueba que el ban actual todavía sea el efecto creado por el caso."""
    if not reason or not token:
        return False
    try:
        marker = ban_effect_marker(token)
    except ValueError:
        return False
    return str(reason).startswith(f"{marker} ") or str(reason) == marker


def mute_effect_marker(token: str) -> str:
    clean = str(token or "").strip()
    if not clean:
        raise ValueError("missing_mute_effect_token")
    return f"{_MUTE_MARKER_PREFIX}{clean}]"


def reason_with_mute_effect(reason: str, token: str) -> str:
    marker = mute_effect_marker(token)
    text = " ".join(str(reason or "").split())
    available = _BAN_REASON_LIMIT - len(marker) - 1
    return f"{marker} {text[:max(0, available)]}".rstrip()


def mute_reason_matches(reason: object, token: str) -> bool:
    if not reason or not token:
        return False
    try:
        marker = mute_effect_marker(token)
    except ValueError:
        return False
    return str(reason).startswith(f"{marker} ") or str(reason) == marker


def sanction_lock(
    bot: Any,
    guild_id: int,
    user_id: int,
    action_type: str,
) -> asyncio.Lock:
    """Devuelve el lock compartido del bot para usuario y familia de sanción."""
    locks = getattr(bot, "_security_sanction_locks", None)
    if locks is None:
        locks = weakref.WeakValueDictionary()
        setattr(bot, "_security_sanction_locks", locks)
    key = (int(guild_id), int(user_id), sanction_family(action_type))
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


async def run_sanction_locked(
    bot: Any,
    guild_id: int,
    user_id: int,
    action_type: str,
    operation: Callable[[], Awaitable[T]],
) -> T:
    async with sanction_lock(bot, guild_id, user_id, action_type):
        return await operation()


async def run_sanctions_locked(
    bot: Any,
    guild_id: int,
    user_id: int,
    action_types: tuple[str, ...],
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Adquiere varias familias en orden estable para evitar interbloqueos."""
    families = sorted({sanction_family(action_type) for action_type in action_types})
    locks = [sanction_lock(bot, guild_id, user_id, family) for family in families]
    acquired: list[asyncio.Lock] = []
    try:
        for lock in locks:
            await lock.acquire()
            acquired.append(lock)
        return await operation()
    finally:
        for lock in reversed(acquired):
            lock.release()
