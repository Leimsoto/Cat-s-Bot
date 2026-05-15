"""
cogs/_message_payload.py
────────────────────────
Helper compartido para renderizar payloads guardados por ``MessageEditor`` del
dashboard.

El JSON canónico (forma nueva) es::

    {
      "content": str,
      "enabled": bool,
      "embed": {
        "title": str, "description": str, "color": str (#hex),
        "footer": str, "footer_icon": str,
        "image": str, "thumbnail": str,
        "author": str, "author_icon": str, "author_url": str
      }
    }

También se aceptan los formatos legacy (top-level title/description/color/
image_url/thumbnail_url/footer_text/footer_icon) para no romper instalaciones
que aún no hayan editado el embed desde el dashboard nuevo.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import discord

logger = logging.getLogger("MessagePayload")


def _color_from(raw: Any, fallback: int = 0x5865F2) -> discord.Color:
    if raw is None:
        return discord.Color(fallback)
    if isinstance(raw, int):
        try:
            return discord.Color(raw)
        except (ValueError, TypeError):
            return discord.Color(fallback)
    text = str(raw).strip().lstrip("#")
    if not text:
        return discord.Color(fallback)
    try:
        return discord.Color(int(text, 16))
    except ValueError:
        return discord.Color(fallback)


def _sub(text: Optional[str], variables: Dict[str, str]) -> str:
    if not text:
        return ""
    out = text
    for k, v in variables.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def parse_message_data(raw: Any) -> Optional[Dict[str, Any]]:
    """Devuelve un dict normalizado o None si el contenido es inválido."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        return None

    if not isinstance(data, dict):
        return None

    # Detectar formato nuevo (tiene "embed" anidado).
    if "embed" in data and isinstance(data["embed"], dict):
        return {
            "content": data.get("content") or "",
            "enabled": bool(data.get("enabled", True)),
            "embed": data["embed"],
        }

    # Formato legacy: campos en el top-level. Mapear a la forma nueva.
    return {
        "content": data.get("content") or "",
        "enabled": True,
        "embed": {
            "title": data.get("title") or "",
            "description": data.get("description") or "",
            "color": data.get("color"),
            "footer": data.get("footer_text") or data.get("footer") or "",
            "footer_icon": data.get("footer_icon") or "",
            "image": data.get("image_url") or data.get("image") or "",
            "thumbnail": data.get("thumbnail_url") or data.get("thumbnail") or "",
            "author": data.get("author") or "",
            "author_icon": data.get("author_icon") or "",
            "author_url": data.get("author_url") or "",
        },
    }


def render_message_payload(
    raw: Any,
    variables: Optional[Dict[str, str]] = None,
    member: Optional[discord.Member] = None,
    default_color: int = 0x5865F2,
) -> Dict[str, Any]:
    """Convierte el JSON serializado en ``{content, embed}``.

    Args:
        raw: string JSON, dict ya parseado o ``None``.
        variables: mapeo de placeholders soportados (``{user}``, ``{server}``…).
            Se aplica a title, description, footer, author y content.
        member: si se pasa y la regla pide ``thumbnail`` sin url específica,
            usa el avatar del miembro.
        default_color: color por defecto si el JSON no especifica uno válido.

    Returns:
        ``{"content": str|None, "embed": discord.Embed|None}``.
    """
    variables = variables or {}
    parsed = parse_message_data(raw)
    if parsed is None:
        return {"content": None, "embed": None}

    content = _sub(parsed["content"], variables) or None

    if not parsed.get("enabled", True):
        return {"content": content, "embed": None}

    emb = parsed["embed"] or {}
    title = _sub(emb.get("title"), variables) or None
    description = _sub(emb.get("description"), variables) or None

    if not title and not description and not emb.get("image"):
        # Embed vacío: no enviar.
        return {"content": content, "embed": None}

    embed = discord.Embed(
        title=title,
        description=description,
        color=_color_from(emb.get("color"), fallback=default_color),
    )

    author_name = _sub(emb.get("author"), variables)
    if author_name:
        embed.set_author(
            name=author_name,
            icon_url=emb.get("author_icon") or None,
            url=emb.get("author_url") or None,
        )

    if emb.get("image"):
        embed.set_image(url=emb["image"])

    thumb = emb.get("thumbnail")
    if thumb == "{avatar}" and member is not None:
        embed.set_thumbnail(url=member.display_avatar.url)
    elif thumb:
        embed.set_thumbnail(url=thumb)

    footer_text = _sub(emb.get("footer"), variables)
    footer_icon = emb.get("footer_icon") or None
    if footer_text or footer_icon:
        embed.set_footer(text=footer_text or None, icon_url=footer_icon)

    return {"content": content, "embed": embed}
