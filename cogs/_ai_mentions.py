"""Allow mentions only for real, unambiguous members selected by the requester."""
import re

import discord


def _members(message):
    members = {message.author.id: message.author}
    for member in message.mentions[:19]:
        if getattr(member, "guild", message.guild) == message.guild:
            members[member.id] = member
    names = {}
    for member in getattr(message.guild, "members", ()):
        for name in {member.display_name, getattr(member, "name", "")} - {""}:
            names.setdefault(name.casefold(), {})[member.id] = member
    for name, matches in names.items():
        if len(members) < 20 and len(matches) == 1 and len(name) >= 3 and re.search(r"(?<!\w)@?" + re.escape(name) + r"(?!\w)", message.content or "", re.I):
            member = next(iter(matches.values()))
            members[member.id] = member
    return members


def mention_context(message):
    return [{"user_id": str(member.id), "display_name": member.display_name,
             "username": getattr(member, "name", "")} for member in list(_members(message).values())[:20]]


def format_ai_mentions(text, message, *, first_fragment=True, notified_user_ids=None):
    members = _members(message)
    names = {}
    for member in members.values():
        for name in {member.display_name, getattr(member, "name", "")} - {""}:
            names.setdefault(name.casefold(), set()).add(member.id)
    for name in sorted(names, key=len, reverse=True):
        if len(names[name]) == 1:
            text = re.sub(r"(?<!\w)@" + re.escape(name) + r"(?!\w)", f"<@{next(iter(names[name]))}>", text, flags=re.I)
    text = re.sub(r"<@!?(\d+)>", lambda match: match.group() if int(match[1]) in members else "@\u200b" + match[1], text)
    if notified_user_ids is None:
        allowed = list(members) if first_fragment else []
    else:
        if first_fragment:
            notified_user_ids.add(message.author.id)
        allowed = {int(match[1]) for match in re.finditer(r"<@!?(\d+)>", text)} & members.keys() - notified_user_ids
        notified_user_ids.update(allowed)
    return text, discord.AllowedMentions(everyone=False, roles=False,
        users=[discord.Object(id=user_id) for user_id in allowed] if allowed else False,
        replied_user=first_fragment)


def split_ai_text(text, limit=1990):
    if limit < 32:
        raise ValueError("mention_chunk_limit_too_small")
    while text:
        end = min(limit, len(text))
        if end < len(text):
            for match in re.finditer(r"<@!?\d{1,20}>", text[max(0, end - 24):end + 24]):
                start = max(0, end - 24) + match.start()
                stop = max(0, end - 24) + match.end()
                if start < end < stop:
                    end = start
                    break
        yield text[:end]
        text = text[end:]
