"""Reglas locales deterministas; las reglas globales siguen siendo independientes."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

import discord

logger = logging.getLogger("ChannelSettings")
LINK_RE = re.compile(r"(?:https?://|www\.|discord\.gg/)[^\s]+", re.IGNORECASE)
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".mp4", ".webm", ".mov", ".mp3", ".ogg", ".wav", ".flac", ".m4a"}


def policy_active(config, now=None):
    if not config or not config.get("enabled", True):
        return False
    schedule = config.get("schedule", {})
    if not schedule.get("enabled"):
        return True
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(schedule["timezone"]))
    minute = local.hour * 60 + local.minute
    day = local.weekday()
    for window in schedule["windows"]:
        start = sum(int(value) * factor for value, factor in zip(window["start"].split(":"), (60, 1)))
        end = sum(int(value) * factor for value, factor in zip(window["end"].split(":"), (60, 1)))
        if start < end and day in window["days"] and start <= minute < end:
            return True
        if start > end and ((day in window["days"] and minute >= start) or ((day - 1) % 7 in window["days"] and minute < end)):
            return True
    return False


def has_media(message):
    for source in (message, *getattr(message, "message_snapshots", ())):
        if any(
            (getattr(attachment, "content_type", "") or "").split("/")[0] in {"image", "video", "audio"}
            or PurePosixPath(getattr(attachment, "filename", "")).suffix.lower() in MEDIA_SUFFIXES
            for attachment in getattr(source, "attachments", ())
        ) or any(getattr(embed, "type", "") in {"image", "video", "gifv"} for embed in getattr(source, "embeds", ())):
            return True
    return False


def local_actions(message, member, config):
    """Devuelve acciones de reglas locales; nunca omite el requisito global."""
    roles = {str(role.id) for role in member.roles}
    whitelist = config["whitelist"]
    if str(member.id) in whitelist["user_ids"] or roles.intersection(whitelist["role_ids"]):
        return []
    actions = []
    role = config["role"]
    if role["mode"] in {"additional", "override"} and not roles.intersection(role["role_ids"]):
        actions.append({"id": "role", "name": "Rol requerido", "delete": True, "response": role["notice"], "notify_staff": False})
    restriction = config["restrictions"]
    content = "\n".join(getattr(source, "content", "") or "" for source in (message, *getattr(message, "message_snapshots", ()))).casefold()
    media = has_media(message)
    link = bool(LINK_RE.search(content))
    if (restriction["media_only"] and not media) or (restriction["block_links"] and link) or any(word.casefold() in content for word in restriction["blocked_words"]):
        actions.append({"id": "content", "name": "Restricción de contenido", "delete": True, "response": restriction["notice"], "notify_staff": False})
    for trigger in config["triggers"]:
        condition, values = trigger["condition"], trigger["values"]
        matched = (condition == "any_message"
                   or condition == "contains_text" and any(value.casefold() in content for value in values)
                   or condition == "has_link" and link
                   or condition == "no_media" and not media
                   or condition == "missing_role" and not roles.intersection(values))
        if matched:
            actions.append(trigger)
    return actions


async def apply_local_actions(bot, message, config, actions):
    rejected = any(action["delete"] for action in actions)
    if rejected:
        try:
            await message.delete()
        except discord.NotFound:
            return False
        except discord.HTTPException as exc:
            logger.warning("No se pudo borrar mensaje %s: %s", message.id, exc)
            return False
    policy_channel_id = getattr(message.channel, "parent_id", None) if isinstance(message.channel, discord.Thread) else message.channel.id
    responded = False
    staff_notified = False
    for action in actions:
        key = (message.guild.id, policy_channel_id, message.author.id, action["id"])
        if key in bot._channel_policy_notices:
            continue
        bot._channel_policy_notices.add(key)
        asyncio.get_running_loop().call_later(10, bot._channel_policy_notices.discard, key)
        if action["response"] and not responded:
            responded = True
            try:
                await message.channel.send(
                    f"<@{message.author.id}> {action['response']}",
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[discord.Object(id=message.author.id)], replied_user=False),
                )
            except discord.HTTPException as exc:
                logger.warning("No se pudo responder en canal %s: %s", message.channel.id, exc)
        if action["notify_staff"] and not staff_notified:
            staff_notified = True
            channel = message.guild.get_channel(int(config["staff_channel_id"]))
            if channel is not None:
                try:
                    # Sin copiar contenido del usuario ni activar menciones de staff.
                    await channel.send(
                        f"Regla «{action['name']}» activada por <@{message.author.id}> en <#{message.channel.id}>. Mensaje: {message.id}. {'Borrado.' if rejected else message.jump_url}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException as exc:
                    logger.warning("No se pudo notificar al staff en canal %s: %s", channel.id, exc)
    return not rejected
