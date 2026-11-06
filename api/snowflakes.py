"""Helpers para IDs Discord snowflake en API/dashboard.

JavaScript pierde precisión con snowflakes si los recibe como números JSON.
Regla: aceptar string/int en entrada, convertir a int solo internamente, y serializar
IDs Discord como string en respuestas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

from fastapi import HTTPException


def serialize_snowflake(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def coerce_snowflake(value: Any, field_name: str = "id") -> int:
    coerced = coerce_optional_snowflake(value, field_name)
    if coerced is None:
        raise HTTPException(400, f"{field_name} requerido")
    return coerced


def coerce_optional_snowflake(value: Any, field_name: str = "id") -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field_name} inválido")


def stringify_fields(row: Any, fields: Iterable[str]) -> Any:
    if row is None:
        return None
    out = dict(row)
    for field in fields:
        if field in out:
            out[field] = serialize_snowflake(out.get(field))
    return out


def stringify_rows(rows: Iterable[Any], fields: Iterable[str]) -> list[dict]:
    return [stringify_fields(row, fields) for row in (rows or [])]


def stringify_json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item not in (None, "")]


def int_json_list(value: Any, field_name: str = "ids") -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise HTTPException(400, f"{field_name} debe ser una lista")
    return [coerce_snowflake(item, field_name) for item in value]


def is_messageable_channel(channel: Any) -> bool:
    return channel is not None and callable(getattr(channel, "send", None))


def is_voice_or_stage_channel(channel: Any) -> bool:
    kind = channel.__class__.__name__ if channel is not None else ""
    return kind in {"VoiceChannel", "StageChannel"}


def is_guild_channel(channel: Any) -> bool:
    return channel is not None and hasattr(channel, "id")


def is_role(role: Any) -> bool:
    return role is not None and hasattr(role, "id") and hasattr(role, "name")


def repair_rounded_snowflake(
    bot: Any,
    guild_id: int,
    value: int | None,
    *,
    kind: str,
    is_valid: Callable[[Any], bool],
    get_existing: Callable[[Any, int], Any],
    iter_candidates: Callable[[Any], Iterable[Any]],
    logger: logging.Logger | None = None,
    max_delta: int = 4096,
) -> int | None:
    """Repara un snowflake redondeado por JS si hay un único candidato cercano."""
    if bot is None or not hasattr(bot, "get_guild") or value is None:
        return value
    guild = bot.get_guild(guild_id)
    if guild is None:
        return value
    existing = get_existing(guild, value)
    if is_valid(existing):
        return value
    candidates = [
        int(getattr(item, "id"))
        for item in iter_candidates(guild)
        if is_valid(item) and abs(int(getattr(item, "id")) - int(value)) <= max_delta
    ]
    if len(candidates) == 1:
        fixed = int(candidates[0])
        if logger:
            logger.warning("%s redondeado reparado para guild %s: %s -> %s", kind, guild_id, value, fixed)
        return fixed
    return value
