"""Private, bounded evidence captured from Discord before a moderation action."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
from copy import copy
from datetime import datetime, timezone
from urllib.parse import urlsplit

import aiohttp
import discord
from cogs._mute_roles import fresh_members

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
MAX_FILES = 6
MAX_CASE_BYTES = 64 * 1024 * 1024
LIMITS = {"max_file_bytes": MAX_FILE_BYTES, "max_upload_bytes": MAX_UPLOAD_BYTES, "max_files": MAX_FILES}
_CAPTURE_SLOT = asyncio.Semaphore(1)
MESSAGE_URL = re.compile(r"https://(?:canary\.|ptb\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)(?:[?#].*)?$")


def media_type(data: bytes) -> str:
    """Sniff supported inert image/audio/video containers; never trust client MIME."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    raise ValueError("unsupported_media")


def artifact(filename, data=None, *, kind="attachment", source="upload", uploader_id=None,
             source_message_id=None, source_channel_id=None, error=None, content_type=None):
    if data is not None and len(data) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    name = re.sub(r"[^\w. ()-]", "_", str(filename or "evidence"))[:160].strip(". ") or "evidence"
    return {"filename": name, "kind": kind, "source": source,
        "uploader_id": str(uploader_id) if uploader_id is not None else None,
        "source_message_id": str(source_message_id) if source_message_id is not None else None,
        "source_channel_id": str(source_channel_id) if source_channel_id is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if error else "available", "error": error,
        "content_type": content_type or (media_type(data) if data is not None else None),
        "size": len(data) if data is not None else 0,
        "sha256": hashlib.sha256(data).hexdigest() if data is not None else None,
        "content": data}


async def preserve_attachment(attachment, *, source, uploader_id=None, message=None):
    provenance = dict(source=source, uploader_id=uploader_id,
        source_message_id=getattr(message, "id", None),
        source_channel_id=getattr(getattr(message, "channel", None), "id", None))
    try:
        if int(attachment.size) > MAX_FILE_BYTES:
            raise ValueError("file_too_large")
        url = urlsplit(attachment.url)
        if (url.scheme != "https" or url.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}
            or url.username or url.password or url.port not in (None, 443)
            or not url.path.startswith("/attachments/")):
            raise ValueError("invalid_attachment_url")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5), trust_env=False) as session:
            async with session.get(attachment.url, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError("attachment_unavailable")
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > MAX_FILE_BYTES:
                        raise ValueError("file_too_large")
        return artifact(attachment.filename, bytes(data), **provenance)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "attachment_unavailable"
        return artifact(attachment.filename, error=code, **provenance)


async def render_snapshot(document: dict) -> bytes:
    """Offline Chrome rendering of escaped Discord data; no web page or remote assets."""
    from playwright.async_api import async_playwright
    escape = lambda value: html.escape(str(value))
    blocks = []
    for message in document["messages"]:
        attachments = "\n".join(a["filename"] for a in message["attachments"])
        blocks.append(f'<article><b>{escape(message["author"])}</b> <small>ID {escape(message["author_id"])} · {escape(message["created_at"])}</small><pre>{escape(message["content"])}</pre><small>Mensaje {escape(message["id"])}\n{escape(attachments)}</small></article>')
    markup = '<!doctype html><meta charset="utf-8"><style>body{background:#313338;color:#f2f3f5;font:16px Arial;padding:24px;width:1050px}article{border-top:1px solid #555;padding:14px 0}small{color:#bbb;white-space:pre-wrap}pre{font:16px Arial;white-space:pre-wrap;overflow-wrap:anywhere}h2{font-size:20px}</style>'
    markup += f'<h2>Registro del bot · contexto de Discord</h2><p>{escape(document["guild_name"])} · #{escape(document["channel_name"])} · canal {escape(document["channel_id"])}</p><small>Capturado {escape(document["captured_at"])} · fuente {escape(document["source"])}</small>' + ''.join(blocks)
    async with _CAPTURE_SLOT:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True, chromium_sandbox=True,
                executable_path=os.environ.get("CATBOT_CHROME_EXECUTABLE") or None)
            try:
                page = await browser.new_page(viewport={"width": 1150, "height": 900}, java_script_enabled=False)
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(markup, wait_until="domcontentloaded", timeout=4000)
                return await page.screenshot(type="png", full_page=True, timeout=4000)
            finally:
                await browser.close()


async def _authorized_channel(bot, guild, channel, actor_id=None):
    if getattr(getattr(channel, "guild", None), "id", None) != guild.id:
        raise ValueError("source_wrong_guild")
    # fresh_members binds roles/channels to one REST permission snapshot.
    members = await fresh_members(bot, guild, bot.user.id, actor_id)
    live_bot, _, *actor = members
    view = live_bot.guild
    if getattr(channel.guild, "id", None) != guild.id:
        raise ValueError("source_wrong_guild")
    live_channel = view.get_channel(channel.id)
    if live_channel is None and isinstance(channel, discord.Thread):
        live_channel = copy(channel)
        live_channel.guild = view
    if live_channel is None:
        raise ValueError("channel_unavailable")
    for member in (live_bot, *(actor if actor_id is not None else ())):
        permissions = live_channel.permissions_for(member)
        if not (permissions.view_channel and permissions.read_message_history):
            raise ValueError("channel_access_denied")
        if isinstance(live_channel, discord.Thread) and live_channel.is_private() and not permissions.manage_threads:
            try:
                await channel.fetch_member(member.id)
            except discord.HTTPException:
                raise ValueError("private_thread_access_denied") from None
    return live_channel


async def capture_context(bot, guild, *, message=None, channel=None, actor_id=None, message_url=None, attachment=None):
    """Return captured bytes or explicit failure records; evidence never blocks a sanction."""
    records = []
    try:
        async with asyncio.timeout(10):
            if message_url:
                match = MESSAGE_URL.fullmatch(message_url.strip())
                if not match or int(match[1]) != guild.id:
                    raise ValueError("invalid_message_source")
                channel = await bot.fetch_channel(int(match[2]))
                await _authorized_channel(bot, guild, channel, actor_id)
                message = await channel.fetch_message(int(match[3]))
            else:
                channel = message.channel if message is not None else channel
            if channel is None:
                raise ValueError("channel_unavailable")
            await _authorized_channel(bot, guild, channel, actor_id)
            history = []
            async for previous in channel.history(limit=4, before=message):
                history.append(previous)
            history.reverse()
            if message is not None:
                history.append(message)
            document = {"source": "discord_message" if message is not None else "current_channel",
                "guild_id": str(guild.id), "guild_name": guild.name,
                "channel_id": str(channel.id), "channel_name": str(getattr(channel, "name", channel.id)),
                "captured_at": datetime.now(timezone.utc).isoformat(), "messages": []}
            for entry in history:
                document["messages"].append({"id": str(entry.id), "author_id": str(entry.author.id),
                    "author": str(entry.author), "content": entry.content or "",
                    "created_at": str(getattr(entry, "created_at", "")), "edited_at": str(getattr(entry, "edited_at", "") or ""),
                    "attachments": [{"id": str(a.id), "filename": a.filename, "size": a.size} for a in entry.attachments]})
            provenance = dict(source=document["source"], uploader_id=actor_id or bot.user.id,
                source_message_id=getattr(message, "id", None), source_channel_id=channel.id)
            records.append(artifact("context.json", json.dumps(document, ensure_ascii=False).encode(), kind="context", content_type="application/json", **provenance))
            try:
                png = await asyncio.wait_for(render_snapshot(document), timeout=6)
                records.append(artifact("context.png", png, kind="snapshot", content_type="image/png", **provenance))
            except Exception:
                records.append(artifact("context.png", kind="snapshot", error="snapshot_unavailable", **provenance))
            attachments = [(a, entry) for entry in reversed(history) for a in entry.attachments]
            attachment_limit = MAX_FILES - int(attachment is not None)
            if len(attachments) > attachment_limit:
                records.append(artifact("attachments", error="too_many_files", **provenance))
            total = sum(item["size"] for item in records)
            for item, entry in attachments[:attachment_limit]:
                if total + int(item.size) > MAX_UPLOAD_BYTES:
                    records.append(artifact(item.filename, error="capture_budget_exceeded", **provenance))
                    continue
                record = await preserve_attachment(item, source="discord_attachment", uploader_id=actor_id or bot.user.id, message=entry)
                if total + record["size"] > MAX_UPLOAD_BYTES:
                    record = artifact(item.filename, error="capture_budget_exceeded", **provenance)
                records.append(record)
                total += record["size"]
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "capture_timeout" if isinstance(exc, TimeoutError) else "context_unavailable"
        records.append(artifact("context", kind="context", source="discord", uploader_id=actor_id or bot.user.id, error=code))
    if attachment is not None:
        record = await preserve_attachment(attachment, source="moderator_attachment", uploader_id=actor_id or bot.user.id)
    if any(record.get("content") is not None for record in records):
        try:
            await asyncio.wait_for(_authorized_channel(bot, guild, channel, actor_id), timeout=3)
        except Exception:
            records = [artifact("context", kind="context", source="discord", uploader_id=actor_id or bot.user.id,
                error="source_access_changed")]
    if attachment is not None:
        if sum(item["size"] for item in records) + record["size"] > MAX_UPLOAD_BYTES:
            record = artifact(attachment.filename, source="moderator_attachment", uploader_id=actor_id or bot.user.id, error="capture_budget_exceeded")
        records.append(record)
    return records


async def capture_manual(bot, interaction, message_url=None, attachment=None, evidence_url=None):
    source = message_url or (evidence_url if MESSAGE_URL.fullmatch(evidence_url or "") else None)
    return await capture_context(bot, interaction.guild, channel=getattr(interaction, "channel", None),
        actor_id=interaction.user.id, message_url=source, attachment=attachment)
