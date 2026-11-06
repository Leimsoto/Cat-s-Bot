"""Shared, read-only presentation of current and legacy moderation records."""
from __future__ import annotations

import json
import re

import discord



RULE_LABELS = {
    "llm": "Reglas del servidor (IA)", "spam": "Mensajes demasiado frecuentes",
    "duplicate": "Mensajes repetidos", "caps": "Exceso de mayúsculas",
    "mentions": "Exceso de menciones", "emoji_spam": "Exceso de emojis",
    "links": "Enlaces o invitaciones no permitidos", "banned_words": "Palabras no permitidas",
}
ACTION_LABELS = {
    "DELETE": "Mensaje eliminado", "WARN": "Advertencia", "MUTE": "Silenciado",
    "TIMEOUT": "Aislamiento temporal", "KICK": "Expulsión", "BAN": "Veto",
    "TEMPBAN": "Veto temporal", "UNBAN": "Veto retirado", "UNMUTE": "Silencio retirado",
    "UNTIMEOUT": "Aislamiento retirado", "WARN_REMOVE": "Advertencia retirada",
    "WARN_RESET": "Advertencias retiradas", "DELETE_FAILED": "Borrado fallido",
}


def record_extra(row):
    value = row.get("extra_data") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def moderation_details(row, *, automod=False):
    """Expose only explanation fields, never classifier prompts or arbitrary extra data."""
    extra = record_extra(row)
    decision = extra.get("decision") or {}
    if not isinstance(decision, dict):
        decision = {}
    action = str(row.get("action_taken") or row.get("action_type") or row.get("action") or "")
    action_key = action.upper().removeprefix("AUTO_")
    raw = str(row.get("content") if automod else row.get("reason") or "")
    rule_key = str(row.get("rule") or extra.get("rule_key") or "")
    source = str(extra.get("source") or ("llm" if raw.startswith("LLM message:") else "automod" if automod or action.startswith("AUTO_") else "moderation"))
    reason = decision.get("reason") or extra.get("reason")
    rule = decision.get("rule") or extra.get("rule")
    message_id = extra.get("message_id") or decision.get("message_id")
    marker = re.match(r"(?:LLM )?message:(\d+)\s*(.*)", raw, re.S)
    if marker:
        message_id = message_id or marker[1]
        body = marker[2]
        if body.startswith("Motivo: "):
            legacy_reason, separator, legacy_rule = body[8:].partition(" Regla: ")
            reason = reason or legacy_reason
            rule = rule or (legacy_rule if separator else None)
        elif body:
            legacy_rule, separator, legacy_reason = body.partition(": ")
            reason = reason or (legacy_reason if separator else "Motivo no disponible en el registro antiguo")
            rule = rule or legacy_rule
        rule_key = rule_key or "llm"
        source = "llm"
    deterministic = re.fullmatch(r"AutoMod \(([^)]+)\): \w+", raw)
    if deterministic:
        rule_key = deterministic[1]
    if not reason:
        reason = RULE_LABELS.get(rule_key) if (automod or deterministic) and rule_key != "llm" else (None if automod else raw)
    label = ACTION_LABELS.get(action_key, action.replace("_", " ").capitalize())
    status = row.get("status")
    if status == "failed":
        label = f"Intento fallido: {label}"
    elif status in {"applying", "pending"}:
        label = f"Sin confirmar: {label}"
    return {
        "action_label": label,
        "rule_label": RULE_LABELS.get(rule_key, "Regla del servidor" if rule else None),
        "reason_display": str(reason or "Sin motivo registrado"),
        "rule_text": str(rule) if rule else None,
        "source": source,
        "message_id": str(message_id) if message_id not in (None, "") else None,
        "channel_id": str(extra["channel_id"]) if extra.get("channel_id") not in (None, "") else None,
        "evidence_url": row.get("evidence_url") or extra.get("evidence_url"),
    }


def identity_payload(user_id, user=None):
    sid = str(user_id) if user_id not in (None, "") else None
    if user is None:
        return {"id": sid, "display": f"Usuario desconocido ({sid})" if sid else "Usuario desconocido",
                "tag": None, "name": None, "avatar_url": None, "resolved": False}
    display = getattr(user, "display_name", None) or getattr(user, "global_name", None) or getattr(user, "name", None)
    name = getattr(user, "name", None) or display
    discriminator = getattr(user, "discriminator", None)
    tag = f"{name}#{discriminator}" if discriminator and discriminator != "0" and name else name
    avatar = getattr(user, "display_avatar", None) or getattr(user, "avatar", None)
    return {"id": sid, "display": display or tag or f"Usuario desconocido ({sid})", "tag": tag, "name": name,
            "avatar_url": str(getattr(avatar, "url", "") or "") or None, "resolved": bool(display or name)}


def public_channel(channel, guild):
    if not isinstance(channel, discord.TextChannel):
        return False
    permissions = channel.permissions_for(guild.default_role)
    return bool(permissions.view_channel and permissions.read_message_history)


def action_metadata(message, moderator, rule_key, decision=None):
    extra = {"source": "llm" if rule_key == "llm" else "automod", "rule_key": rule_key,
             "message_id": str(message.id), "channel_id": str(message.channel.id),
             "public_at_capture": public_channel(message.channel, message.guild),
             "evidence_url": message.jump_url,
             "target_user": identity_payload(message.author.id, message.author),
             "moderator_user": identity_payload(moderator.id, moderator)}
    if decision is not None:
        extra.update(reason=decision["reason"], rule=decision["rule"], decision=decision)
    return extra


def interaction_metadata(interaction, target, moderator_id):
    guild = interaction.guild
    channel = getattr(interaction, "channel", None)
    def cached_identity(value):
        uid = getattr(value, "id", value)
        user = value if hasattr(value, "id") else None
        if user is None and str(uid) == str(interaction.user.id):
            user = interaction.user
        if user is None and hasattr(guild, "get_member"):
            user = guild.get_member(int(uid))
        return identity_payload(uid, user)
    return {"source": "moderation", "channel_id": str(getattr(interaction, "channel_id", None) or getattr(channel, "id", "")),
            "public_at_capture": public_channel(channel, guild), "target_user": cached_identity(target),
            "moderator_user": cached_identity(moderator_id)}


class IdentityResolver:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild = bot.get_guild(int(guild_id)) if bot is not None and hasattr(bot, "get_guild") else None
        self._cache = {}

    async def resolve(self, user_id, snapshot=None):
        sid = str(user_id) if user_id not in (None, "") else None
        if sid not in self._cache:
            user = None
            try:
                uid = int(sid)
                if self.guild is not None:
                    user = self.guild.get_member(uid)
                if user is None and self.bot is not None and hasattr(self.bot, "get_user"):
                    user = self.bot.get_user(uid)
            except (TypeError, ValueError, AttributeError):
                pass
            self._cache[sid] = identity_payload(sid, user)
        result = self._cache[sid]
        if not result["resolved"] and isinstance(snapshot, dict) and str(snapshot.get("id")) == sid:
            result = {key: snapshot.get(key) for key in ("display", "tag", "name", "avatar_url")}
            result.update(id=sid, resolved=bool(result["name"] or result["display"]))
            result["display"] = result["display"] or result["name"] or self._cache[sid]["display"]
        return dict(result)
