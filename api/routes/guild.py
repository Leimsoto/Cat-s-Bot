"""
api/routes/guild.py
───────────────────
Endpoints de configuración y dashboard del servidor.

GET  /api/guilds                            → lista guilds del usuario (con bot)
GET  /api/guilds/{id}/overview              → métricas y actividad
GET  /api/guilds/{id}/config                → config general
PATCH/api/guilds/{id}/config               → actualizar config general
GET  /api/guilds/{id}/ia                    → config IA
PATCH/api/guilds/{id}/ia                   → actualizar IA
GET  /api/guilds/{id}/moderation            → config moderación
PATCH/api/guilds/{id}/moderation           → actualizar moderación
GET  /api/guilds/{id}/levels                → config XP/niveles
PATCH/api/guilds/{id}/levels               → actualizar XP
GET  /api/guilds/{id}/levels/rewards        → recompensas de nivel
POST /api/guilds/{id}/levels/rewards        → añadir recompensa
DELETE/api/guilds/{id}/levels/rewards/{lv} → eliminar recompensa
GET  /api/guilds/{id}/tickets               → config tickets
PATCH/api/guilds/{id}/tickets              → actualizar tickets
GET  /api/guilds/{id}/tickets/categories    → categorías de tickets
POST /api/guilds/{id}/tickets/categories    → añadir categoría
DELETE/api/guilds/{id}/tickets/categories/{id} → eliminar categoría
GET  /api/guilds/{id}/radio                 → config radio
PATCH/api/guilds/{id}/radio                → actualizar radio
GET  /api/guilds/{id}/channels              → lista canales (filtros: search, type, limit)
GET  /api/guilds/{id}/categories            → atajo: solo categorías (search, limit)
GET  /api/guilds/{id}/roles                 → lista roles (search, limit, include_managed)
GET  /api/guilds/{id}/members               → autocomplete de miembros (search, limit)
GET  /api/guilds/{id}/music                 → estado reproducción
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import (
    get_bot,
    get_current_user,
    get_db,
    get_guild_admin_status,
    get_live_guild_member,
    require_guild_admin,
)
from api.snowflakes import coerce_snowflake, stringify_fields, stringify_rows
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.routes.radio import RadioConfigUpdate, patch_radio_config as apply_radio_config
from llm_moderation_config import (
    EndpointConfirmationRequired, allowed_endpoint_hosts, parse_endpoint_url,
    ENDPOINT_CONFIG_FIELDS, public_automod_config, resolve_endpoint_addresses, validate_llm_config,
)
from cogs._conversation import provider_for, current_channel_members
from cogs._managed_messages import CATEGORIES, category_settings
from cogs._moderation_history import IdentityResolver, moderation_details, record_extra
from cogs._role_safety import (
    delegated_moderation_role_ids,
    safe_for_automatic_assignment,
)

logger = logging.getLogger("API.guild")


def _serialize_snowflake(value):
    if value in (None, ""):
        return None
    return str(value)


def _coerce_optional_snowflake(value, field_name: str) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field_name} inválido")


def _normalize_role_id_list(value, field_name: str) -> list[int]:
    if value in (None, ""):
        raw_values = []
    elif isinstance(value, str):
        try:
            raw_values = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{field_name} debe ser una lista JSON") from exc
    else:
        raw_values = value
    if not isinstance(raw_values, list):
        raise HTTPException(400, f"{field_name} debe ser una lista")

    role_ids = []
    for index, raw_role_id in enumerate(raw_values):
        role_id = _coerce_optional_snowflake(
            raw_role_id,
            f"{field_name}[{index}]",
        )
        if role_id is None:
            raise HTTPException(400, f"{field_name}[{index}] inválido")
        role_ids.append(role_id)
    return role_ids


async def _validate_privileged_role_updates(
    request: Request,
    guild_id: int,
    updates: dict,
    bot,
    user: dict,
    current_values: dict | None = None,
) -> dict:
    """Normaliza cambios delegados y descarta valores sensibles sin cambios."""
    role_updates = {}
    for key in (
        "mod_role_id",
        "staff_role_id",
        "users_role_id",
        "channels_role_id",
        "embed_role_id",
        "ai_role_id",
    ):
        if key not in updates:
            continue
        role_id = _coerce_optional_snowflake(updates[key], key)
        if current_values is not None:
            try:
                current_role_id = _coerce_optional_snowflake(
                    current_values.get(key),
                    key,
                )
            except HTTPException:
                current_role_id = object()
            if role_id == current_role_id:
                updates.pop(key, None)
                continue
        role_updates[key] = role_id
    await _authorize_delegated_role_updates(
        request,
        guild_id,
        role_updates,
        bot,
        user,
    )
    return role_updates


async def _authorize_delegated_role_updates(
    request: Request,
    guild_id: int,
    role_updates: dict,
    bot,
    user: dict,
) -> None:
    """Exige owner/admin y comprueba contra roles y miembro del bot actuales."""
    if not role_updates:
        return

    guild = bot.get_guild(guild_id) if bot is not None else None
    if guild is None or getattr(bot, "user", None) is None:
        raise HTTPException(503, "No se pudo verificar la jerarquía de roles")

    actor = None
    if not user.get("is_master_admin"):
        resolved = await get_live_guild_member(request, guild_id, user)
        actor = resolved.get("member")
        if actor is None:
            raise HTTPException(403, "No se pudieron verificar tus permisos actuales")

    async def fetch_current_context():
        return await asyncio.gather(
            guild.fetch_member(bot.user.id),
            guild.fetch_roles(),
            bot.fetch_guild(guild_id),
        )

    try:
        bot_member, fresh_roles, live_guild = await run_on_bot_loop(
            bot,
            fetch_current_context,
            timeout=10,
        )
    except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(409, "No se pudo verificar la jerarquía actual") from exc

    if (
        getattr(bot_member, "id", None) != int(bot.user.id)
        or getattr(getattr(bot_member, "guild", None), "id", None) != guild_id
        or getattr(live_guild, "id", None) != guild_id
    ):
        raise HTTPException(409, "La identidad actual del bot no coincide")
    owner_id = int(live_guild.owner_id)

    roles_by_id = {int(role.id): role for role in fresh_roles}

    def current_role_state(member):
        role_ids = {guild_id}
        role_ids.update(int(role_id) for role_id in getattr(member, "_roles", ()))
        if any(role_id not in roles_by_id for role_id in role_ids):
            raise HTTPException(409, "No se pudo verificar la jerarquía completa")
        roles = [roles_by_id[role_id] for role_id in role_ids]
        permissions_value = 0
        for role in roles:
            permissions_value |= int(role.permissions.value)
        return discord.Permissions(permissions_value), max(roles)

    _, bot_top_role = current_role_state(bot_member)
    if actor is not None:
        actor_permissions, actor_top_role = current_role_state(actor)
        if actor.id != owner_id and not actor_permissions.administrator:
            raise HTTPException(
                403,
                "Solo el dueño o un administrador puede cambiar roles delegados.",
            )
    else:
        actor_top_role = None

    for key, raw_role_ids in role_updates.items():
        role_ids = raw_role_ids if isinstance(raw_role_ids, list) else [raw_role_ids]
        for role_id in role_ids:
            if role_id is None:
                continue
            role = roles_by_id.get(int(role_id))
            if role is None or role.is_default() or role.managed:
                raise HTTPException(400, f"{key} debe referirse a un rol asignable")
            if role >= bot_top_role:
                raise HTTPException(400, f"{key} debe estar debajo del rol del bot")
            if (
                actor is not None
                and actor.id != owner_id
                and role >= actor_top_role
            ):
                raise HTTPException(403, f"{key} debe estar debajo de tu rol")


def _is_messageable_log_channel(channel) -> bool:
    return channel is not None and callable(getattr(channel, "send", None))


def _repair_rounded_log_channel_id(bot, guild_id: int, channel_id: int | None) -> int | None:
    """Repara IDs de canal redondeados por JS si hay un único canal cercano."""
    if bot is None or not hasattr(bot, "get_guild") or channel_id is None:
        return channel_id
    guild = bot.get_guild(guild_id)
    if guild is None:
        return channel_id
    if _is_messageable_log_channel(guild.get_channel(channel_id)):
        return channel_id

    candidates = [
        ch.id
        for ch in getattr(guild, "channels", [])
        if _is_messageable_log_channel(ch) and abs(int(ch.id) - int(channel_id)) <= 4096
    ]
    if len(candidates) == 1:
        fixed = int(candidates[0])
        logger.warning(
            "serverlog_channel redondeado reparado para guild %s: %s -> %s",
            guild_id,
            channel_id,
            fixed,
        )
        return fixed
    return channel_id

# ── Router legacy (prefijo singular) ──────────────────────────────────────────
router_legacy = APIRouter(prefix="/api/guild/{guild_id}", tags=["guild"])

# ── Router nuevo (prefijo plural, para el dashboard) ──────────────────────────
router = APIRouter(prefix="/api/guilds", tags=["guilds"])


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds
# ─────────────────────────────────────────────────────────────────────────────


@router.get("")
async def list_guilds(
    request: Request, db=Depends(get_db), user=Depends(get_current_user)
):
    """Lista los servidores donde el usuario es admin Y el bot está presente.
    Usa el cache en memoria del bot para evitar 404s de la API de Discord.
    """
    user_guilds = user.get("guilds", [])

    # Obtener el bot del state (puede ser None si aún no conectó)
    bot = getattr(request.app.state, "bot", None)

    # Master admin → devuelve todos los guilds del bot en memoria
    if user.get("is_master_admin") or user.get("is_dev_mode"):
        if bot is not None:
            bot_guilds = [
                {
                    "id": str(g.id),
                    "name": g.name,
                    "icon": str(g.icon.url) if g.icon else None,
                    "has_bot": True,
                    "memberCount": g.member_count,
                    "onlineCount": None,
                }
                for g in bot.guilds
            ]
        else:
            bot_guilds = []
        return {
            "guilds": bot_guilds,
            "user": {"id": "0", "username": "MasterAdmin", "avatar": ""},
        }

    if not user_guilds:
        return {"guilds": [], "user": _format_user(user)}

    # El JWT solo sirve como índice. La autorización real se confirma contra el
    # miembro actual para que una revocación sea efectiva también en esta lista.
    result = []
    for g in user_guilds:
        guild_id = int(g["id"])
        if bot is not None:
            live_status = await get_guild_admin_status(request, guild_id, user)
            discord_guild = bot.get_guild(guild_id)
            if discord_guild is not None and live_status.get("allowed"):
                result.append(
                    {
                        "id": str(guild_id),
                        "name": g["name"],
                        "icon": _icon_url(str(guild_id), g.get("icon")),
                        "has_bot": True,
                        "memberCount": discord_guild.member_count,
                        "onlineCount": None,
                    }
                )
        # Sin bot no existe una fuente viva para confirmar una autorización
        # posiblemente revocada; el guild se omite en vez de confiar en el JWT.

    return {"guilds": result, "user": _format_user(user)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/channels  — lista desde bot en memoria
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/channels")
async def get_guild_channels(
    request: Request,
    guild_id: int,
    search: str = "",
    type: str = "",
    limit: int = 200,
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """
    Lista canales del servidor leyendo directamente del bot.

    Parámetros:
      search: substring para filtrar por nombre (case-insensitive).
      type:   filtra por tipo. Acepta uno o varios separados por coma.
              Valores: text, voice, category, stage_voice, forum, news, announcement.
      limit:  máximo de canales a devolver (default 200, max 500).
    """
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    member = None
    if not user.get("is_master_admin"):
        resolved = await get_live_guild_member(request, guild_id, user)
        member = resolved.get("member")
        if member is None:
            raise HTTPException(403, "No se pudieron verificar tus permisos actuales")

    limit = max(1, min(int(limit), 500))
    type_filter = {t.strip() for t in type.split(",") if t.strip()} if type else set()
    search_lower = search.strip().lower()

    channels = []
    for ch in sorted(
        guild.channels, key=lambda c: c.position if hasattr(c, "position") else 0
    ):
        if member is not None and not getattr(
            ch.permissions_for(member), "view_channel", False
        ):
            continue
        ch_type = str(ch.type).split(".")[-1]
        if type_filter and ch_type not in type_filter:
            continue
        if search_lower and search_lower not in ch.name.lower():
            continue
        channels.append(
            {
                "id": str(ch.id),
                "name": ch.name,
                "type": ch_type,
                "position": getattr(ch, "position", 0),
                "category": ch.category.name if ch.category else None,
            }
        )
        if len(channels) >= limit:
            break
    return {"guild_id": str(guild_id), "channels": channels, "total": len(channels)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/categories  — atajo: solo categorías
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/categories")
async def get_guild_categories(
    request: Request,
    guild_id: int,
    search: str = "",
    limit: int = 200,
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """Atajo: lista solo las categorías del servidor (CategoryChannel)."""
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    member = None
    if not user.get("is_master_admin"):
        resolved = await get_live_guild_member(request, guild_id, user)
        member = resolved.get("member")
        if member is None:
            raise HTTPException(403, "No se pudieron verificar tus permisos actuales")

    limit = max(1, min(int(limit), 500))
    search_lower = search.strip().lower()

    categories = []
    for cat in sorted(guild.categories, key=lambda c: c.position):
        if member is not None and not getattr(
            cat.permissions_for(member), "view_channel", False
        ):
            continue
        if search_lower and search_lower not in cat.name.lower():
            continue
        categories.append(
            {
                "id": str(cat.id),
                "name": cat.name,
                "position": cat.position,
                "channel_count": len(cat.channels),
            }
        )
        if len(categories) >= limit:
            break
    return {"guild_id": str(guild_id), "categories": categories, "total": len(categories)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/members  — autocomplete sobre el cache del bot
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/members")
async def get_guild_members(
    guild_id: int,
    search: str = "",
    limit: int = 50,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """
    Autocomplete de miembros del servidor.

    Lee del cache (`guild.members`) — requiere `members` intent (ya está activo).
    Para guilds grandes se recomienda enviar siempre `search`.
    """
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    limit = max(1, min(int(limit), 200))
    search_lower = search.strip().lower()

    members = []
    for m in guild.members:
        if m.bot:
            continue
        if search_lower:
            display = (m.display_name or "").lower()
            uname = (m.name or "").lower()
            if search_lower not in display and search_lower not in uname:
                continue
        members.append(
            {
                "id": str(m.id),
                "name": m.name,
                "display_name": m.display_name,
                "avatar": m.display_avatar.url if m.display_avatar else None,
            }
        )
        if len(members) >= limit:
            break
    return {"guild_id": str(guild_id), "members": members, "total": len(members)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/roles — lista desde bot en memoria
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/roles")
async def get_guild_roles(
    guild_id: int,
    search: str = "",
    limit: int = 200,
    include_managed: bool = False,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """
    Lista roles del servidor leyendo directamente del bot.

    Parámetros:
      search:          substring para filtrar por nombre.
      limit:           máximo de roles (default 200, max 500).
      include_managed: si True incluye roles gestionados por bots/integraciones
                       (default False — los oculta porque no son asignables).
    """
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    limit = max(1, min(int(limit), 500))
    search_lower = search.strip().lower()

    roles = []
    for r in sorted(guild.roles, key=lambda r: -r.position):
        if r.name == "@everyone":
            continue
        if not include_managed and r.managed:
            continue
        if search_lower and search_lower not in r.name.lower():
            continue
        roles.append(
            {
                "id": str(r.id),
                "name": r.name,
                "color": f"#{r.color.value:06x}" if r.color.value else None,
                "position": r.position,
                "managed": r.managed,
            }
        )
        if len(roles) >= limit:
            break
    return {"guild_id": str(guild_id), "roles": roles, "total": len(roles)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/overview
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/overview")
async def get_guild_overview(
    request: Request,
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    try:
        # Nombre correcto del método en DatabaseManager
        mod_cases = (
            db.get_mod_actions(guild_id, limit=100)
            if hasattr(db, "get_mod_actions")
            else []
        )
        open_ticket_count = db.count_open_tickets_by_guild(guild_id)
        members = 0

        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        charts = []
        for i in range(7):
            day_start = now - timedelta(days=6 - i)
            day_end = day_start + timedelta(days=1)
            day_cases = [
                c
                for c in mod_cases
                if c.get("created_at")
                and day_start.timestamp() <= _ts(c["created_at"]) < day_end.timestamp()
            ]
            charts.append(
                {
                    "label": day_start.strftime("%a"),
                    "commands": 0,
                    "automod": 0,
                    "security": 0,
                    "moderation": len(day_cases),
                }
            )

        recent_cases_raw = sorted(
            mod_cases, key=lambda c: _ts(c.get("created_at", 0)), reverse=True
        )[:12]
        recent_cases = [
            {
                "caseId": c.get("id"),
                "action": c.get("action_type", ""),
                "userId": str(c.get("target_id", "")),
                "date": c.get("created_at", ""),
            }
            for c in recent_cases_raw
        ]

        # Obtener datos reales del servidor desde el bot en memoria
        bot = getattr(request.app.state, "bot", None)
        discord_guild = bot.get_guild(guild_id) if bot else None

        member_count = discord_guild.member_count if discord_guild else members
        online_count = (
            sum(1 for m in discord_guild.members if m.status != discord.Status.offline)
            if discord_guild and discord_guild.members
            else 0
        )
        boost_level = discord_guild.premium_tier if discord_guild else 0
        boost_count = (
            discord_guild.premium_subscription_count or 0 if discord_guild else 0
        )
        active_voice = (
            sum(1 for vc in discord_guild.voice_channels if len(vc.members) > 0)
            if discord_guild
            else 0
        )

        return {
            "guild": {"id": str(guild_id)},
            "server": {
                "memberCount": member_count,
                "onlineCount": online_count,
                "boostLevel": boost_level,
                "boostCount": boost_count,
                "activeVoice": active_voice,
            },
            "metrics": {
                "totalCommands": 0,
                "automodTriggers": 0,
                "securityAlerts": 0,
                "moderationActions": len(mod_cases),
                "openTickets": open_ticket_count,
                "memberCount": member_count,
            },
            "charts": charts,
            "recentEvents": [],
            "recentCases": recent_cases,
        }
    except Exception as e:
        logger.error(f"overview error: {e}")
        return {
            "guild": {},
            "metrics": {},
            "charts": [],
            "recentEvents": [],
            "recentCases": [],
        }


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/config
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/config")
async def get_guild_config_new(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    cfg = db.get_config(guild_id) or {}
    return {"guild": cfg, "antiNuke": {}}


@router.patch("/{guild_id}/config")
async def patch_guild_config(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    if "guild" in body:
        payload = body["guild"]
        if not isinstance(payload, dict):
            raise HTTPException(400, "guild must be an object")
        payload = dict(payload)
        if "guild_id" in payload:
            raise HTTPException(400, "guild_id is not editable")
        payload.update(
            await _validate_privileged_role_updates(
                request,
                guild_id,
                payload,
                bot,
                user,
                db.get_config(guild_id) or {},
            )
        )
        try:
            db.set_config(guild_id, **payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/ia
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/ia")
async def get_ia_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    return _public_ia_config(db, guild_id)


@router.get("/{guild_id}/ai-messages")
async def get_ai_message_settings(guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)):
    settings = category_settings(db, guild_id)
    return {"categories": {key: settings.get(key, False) for key in CATEGORIES}, "labels": CATEGORIES}


@router.patch("/{guild_id}/ai-messages")
async def patch_ai_message_settings(guild_id: int, body: dict, db=Depends(get_db), _user=Depends(require_guild_admin)):
    values = body.get("categories")
    if set(body) != {"categories"} or not isinstance(values, dict):
        raise HTTPException(400, "categories debe ser un objeto de booleanos")
    if set(values) - set(CATEGORIES) or any(type(value) is not bool for value in values.values()):
        raise HTTPException(400, "Categoría desconocida o valor no booleano")
    settings = {**category_settings(db, guild_id), **values}
    db.set_server_config(guild_id, ai_message_categories=json.dumps(settings))
    return {"categories": settings, "labels": CATEGORIES}


def _public_ia_config(db, guild_id):
    cfg = db.get_ai_config(guild_id) or {}
    llm = db.get_automod_config(guild_id).get("rules", {}).get("llm", {}) if hasattr(db, "get_automod_config") else {}
    provider = provider_for(db, guild_id, cfg) if hasattr(db, "get_automod_config") else "gemini"
    return stringify_fields({**cfg, "provider": provider,
        "endpoint_configured": bool(llm.get("endpoint_url") and llm.get("model")),
        "effective_model": llm.get("model", "") if provider == "strata" else cfg.get("ai_model", "")},
        ("guild_id", "ai_channel_id", "ai_role_id"))


@router.patch("/{guild_id}/ia")
async def patch_ia_config(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    payload = dict(body or {})
    if "guild_id" in payload:
        raise HTTPException(400, "guild_id is not editable")
    for field in ("ai_channel_id", "ai_role_id"):
        if field in payload:
            payload[field] = _coerce_optional_snowflake(payload[field], field)
    payload.update(
        await _validate_privileged_role_updates(
            request,
            guild_id,
            payload,
            bot,
            user,
            db.get_ai_config(guild_id) or {},
        )
    )
    try:
        db.set_ai_config(guild_id, **payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public_ia_config(db, guild_id)


async def _ai_memory_target(request, guild_id, scope, channel_id, bot, user):
    if scope not in {"global", "chat"}:
        raise HTTPException(400, "scope debe ser global o chat")
    if not user.get("is_master_admin"):
        status = await get_guild_admin_status(request, guild_id, user)
        if not (status.get("is_owner") or status.get("administrator")):
            raise HTTPException(403, "Los recuerdos compartidos requieren Administrator o ser dueño del servidor")
    if scope == "global":
        return 0
    channel_id = coerce_snowflake(channel_id, "channel_id")
    guild = bot.get_guild(guild_id) if bot else None
    if guild is None:
        raise HTTPException(503, "Servidor no disponible")
    try:
        async def current_target():
            return await current_channel_members(guild, channel_id, () if user.get("is_master_admin") else (int(user["user_id"]),))
        channel, members = await run_on_bot_loop(bot, current_target, timeout=10)
    except Exception as exc:
        raise HTTPException(400, "No se pudo verificar el canal de este servidor") from exc
    if not isinstance(channel, (discord.TextChannel, discord.Thread)) or channel.guild.id != guild_id:
        raise HTTPException(400, "Selecciona un canal de texto o hilo de este servidor")
    if members:
        permissions = channel.permissions_for(members[0])
        if not permissions.view_channel or not permissions.read_message_history:
            raise HTTPException(403, "No tienes acceso al historial de este canal")
    return channel_id


@router.get("/{guild_id}/ia/memory")
async def get_ia_memory(guild_id: int, request: Request, scope: str = "global", channel_id: str | None = None,
                        db=Depends(get_db), bot=Depends(get_bot), user=Depends(require_guild_admin)):
    owner = await _ai_memory_target(request, guild_id, scope, channel_id, bot, user)
    rows = db.get_ai_memories(guild_id, scope, owner)
    return {"scope": scope, "channel_id": str(owner) if scope == "chat" else None,
            "content": rows[0]["content"] if rows else ""}


@router.put("/{guild_id}/ia/memory")
async def put_ia_memory(guild_id: int, request: Request, body: dict, scope: str = "global", channel_id: str | None = None,
                        db=Depends(get_db), bot=Depends(get_bot), user=Depends(require_guild_admin)):
    owner = await _ai_memory_target(request, guild_id, scope, channel_id, bot, user)
    if set(body) != {"content"} or not isinstance(body.get("content"), str) or len(body["content"]) > 2000:
        raise HTTPException(400, "content debe ser texto de hasta 2000 caracteres")
    db.set_ai_memory(guild_id, scope, owner, owner, body["content"])
    return {"scope": scope, "channel_id": str(owner) if scope == "chat" else None, "content": body["content"].strip()}


@router.delete("/{guild_id}/ia/memory")
async def delete_ia_memory(guild_id: int, request: Request, scope: str = "global", channel_id: str | None = None,
                           db=Depends(get_db), bot=Depends(get_bot), user=Depends(require_guild_admin)):
    owner = await _ai_memory_target(request, guild_id, scope, channel_id, bot, user)
    db.clear_ai_memory(guild_id, scope, owner)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/moderation  — configuración de moderación
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/moderation")
async def get_moderation_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    """Devuelve la configuración completa de moderación para el dashboard."""
    cfg = db.get_config(guild_id) or {}
    srv_cfg = db.get_server_config(guild_id) if hasattr(db, "get_server_config") else {}
    # No usar un merge plano: server_config contiene staff_role_id por legado y
    # su valor por defecto None puede pisar el staff_role_id real de guild_config.
    return {
        "mute_role_id": _serialize_snowflake(cfg.get("mute_role_id")),
        "mod_role_id": _serialize_snowflake(srv_cfg.get("mod_role_id")),
        "staff_role_id": _serialize_snowflake(srv_cfg.get("staff_role_id") or cfg.get("staff_role_id")),
        "modlog_channel": _serialize_snowflake(srv_cfg.get("modlog_channel")),
        "modlog_enabled": srv_cfg.get("modlog_enabled", 1),
        "warn_ban_threshold": cfg.get("warn_ban_threshold", 7),
        "warn_kick_threshold": cfg.get("warn_kick_threshold", 5),
        "warn_mute_threshold": cfg.get("warn_mute_threshold", 3),
        "warn_ban_enabled": cfg.get("warn_ban_enabled", 0),
        "warn_kick_enabled": cfg.get("warn_kick_enabled", 0),
        "warn_mute_enabled": cfg.get("warn_mute_enabled", 1),
        "warn_mute_duration": cfg.get("warn_mute_duration", 600),
        "warn_embed_config": cfg.get("warn_embed_config"),
        "message_role_enabled": cfg.get("message_role_enabled", 0),
        "message_role_id": _serialize_snowflake(cfg.get("message_role_id")),
        "message_role_notice": cfg.get("message_role_notice", "Necesitas el rol requerido para hablar en este servidor."),
    }


@router.patch("/{guild_id}/moderation")
async def patch_moderation_config(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """
    Actualiza la configuración de moderación desde el dashboard.

    Las opciones se reparten entre dos tablas:
      • guild_config  → warns, mute_role, staff_role, warn_embed_config.
      • server_config → mod_role, modlog_channel, modlog_enabled.

    Antes este endpoint enviaba todo a set_config y rompía con
    `ValueError: Columnas inválidas` para las claves de server_config.
    """
    # Columnas válidas de cada tabla.
    config_keys = {
        "mute_role_id",
        "staff_role_id",
        "warn_ban_threshold",
        "warn_kick_threshold",
        "warn_mute_threshold",
        "warn_ban_enabled",
        "warn_kick_enabled",
        "warn_mute_enabled",
        "warn_mute_duration",
        "warn_embed_config",
        "message_role_enabled",
        "message_role_id",
        "message_role_notice",
    }
    server_keys = {
        "mod_role_id",
        "modlog_channel",
        "modlog_enabled",
    }

    id_keys = {"mute_role_id", "staff_role_id", "mod_role_id", "modlog_channel", "message_role_id"}

    def normalize_value(key, value):
        if key == "message_role_id":
            return _coerce_optional_snowflake(value, key)
        if key in id_keys:
            if value in (None, "", 0, "0"):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{key} debe ser un ID numérico")
        return value

    config_payload = {
        k: normalize_value(k, v)
        for k, v in body.items()
        if k in config_keys
    }
    server_payload = {
        k: normalize_value(k, v)
        for k, v in body.items()
        if k in server_keys
    }

    if {"message_role_enabled", "message_role_id", "message_role_notice"} & config_payload.keys():
        current_gate = db.get_config(guild_id) or {}
        gate = {**current_gate, **config_payload}
        enabled = gate.get("message_role_enabled", 0)
        if not isinstance(enabled, (bool, int)) or enabled not in (0, 1):
            raise HTTPException(400, "message_role_enabled debe ser 0 o 1")
        if "message_role_enabled" in config_payload:
            config_payload["message_role_enabled"] = int(enabled)
        notice = gate.get("message_role_notice", "Necesitas el rol requerido para hablar en este servidor.")
        if not isinstance(notice, str):
            raise HTTPException(400, "El texto del aviso debe ser texto")
        try:
            notice_length = len(notice.encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            raise HTTPException(400, "El texto del aviso contiene caracteres inválidos")
        if notice_length > 1975 or (enabled and not notice.strip()):
            raise HTTPException(400, "El aviso debe tener texto y un máximo de 1975 caracteres")
        role_id = gate.get("message_role_id")
        if enabled and not role_id:
            raise HTTPException(400, "Selecciona un rol requerido para hablar")
        if role_id is not None and (enabled or role_id != current_gate.get("message_role_id")):
            if bot is None:
                raise HTTPException(503, "Bot no disponible para comprobar el rol")
            guild = bot.get_guild(guild_id)
            if guild is None:
                raise HTTPException(404, "Servidor no encontrado en el bot")
            role = guild.get_role(role_id)
            if role is None or role_id == guild_id:
                raise HTTPException(400, "El rol requerido debe existir en este servidor y no puede ser @everyone")

    # staff_role_id existía en ambas tablas; los cogs lo leen desde
    # server_config, así que lo persistimos también ahí para que el dashboard
    # se aplique inmediatamente al bot.
    if "staff_role_id" in config_payload:
        server_payload["staff_role_id"] = config_payload["staff_role_id"]

    privileged_role_keys = {
        key for key in ("mod_role_id", "staff_role_id") if key in body
    }
    if privileged_role_keys:
        current_config = db.get_config(guild_id) or {}
        current_server = db.get_server_config(guild_id) or {}
        current_roles = {
            "mod_role_id": current_server.get("mod_role_id"),
            "staff_role_id": current_server.get("staff_role_id")
            or current_config.get("staff_role_id"),
        }
        role_updates = {
            key: (
                config_payload.get(key)
                if key == "staff_role_id"
                else server_payload.get(key)
            )
            for key in privileged_role_keys
        }
        normalized_roles = await _validate_privileged_role_updates(
            request,
            guild_id,
            role_updates,
            bot,
            user,
            current_roles,
        )
        unchanged_roles = privileged_role_keys - set(normalized_roles)
        if "mod_role_id" in unchanged_roles:
            server_payload.pop("mod_role_id", None)
        if "staff_role_id" in unchanged_roles:
            config_payload.pop("staff_role_id", None)
            server_payload.pop("staff_role_id", None)
        if "mod_role_id" in normalized_roles:
            server_payload["mod_role_id"] = normalized_roles["mod_role_id"]
        if "staff_role_id" in normalized_roles:
            config_payload["staff_role_id"] = normalized_roles["staff_role_id"]
            server_payload["staff_role_id"] = normalized_roles["staff_role_id"]

    if config_payload:
        db.set_config(guild_id, **config_payload)
    if server_payload and hasattr(db, "set_server_config"):
        db.set_server_config(guild_id, **server_payload)

    updated = sorted(set(config_payload.keys()) | set(server_payload.keys()))
    cfg = db.get_config(guild_id) or {}
    srv_cfg = db.get_server_config(guild_id) if hasattr(db, "get_server_config") else {}
    return {
        "status": "ok",
        "updated_keys": updated,
        "config": {
            "mute_role_id": _serialize_snowflake(cfg.get("mute_role_id")),
            "mod_role_id": _serialize_snowflake(srv_cfg.get("mod_role_id")),
            "staff_role_id": _serialize_snowflake(srv_cfg.get("staff_role_id") or cfg.get("staff_role_id")),
            "modlog_channel": _serialize_snowflake(srv_cfg.get("modlog_channel")),
            "modlog_enabled": srv_cfg.get("modlog_enabled", 1),
            "warn_ban_threshold": cfg.get("warn_ban_threshold", 7),
            "warn_kick_threshold": cfg.get("warn_kick_threshold", 5),
            "warn_mute_threshold": cfg.get("warn_mute_threshold", 3),
            "warn_ban_enabled": cfg.get("warn_ban_enabled", 0),
            "warn_kick_enabled": cfg.get("warn_kick_enabled", 0),
            "warn_mute_enabled": cfg.get("warn_mute_enabled", 1),
            "warn_mute_duration": cfg.get("warn_mute_duration", 600),
            "warn_embed_config": cfg.get("warn_embed_config"),
            "message_role_enabled": cfg.get("message_role_enabled", 0),
            "message_role_id": _serialize_snowflake(cfg.get("message_role_id")),
            "message_role_notice": cfg.get("message_role_notice", "Necesitas el rol requerido para hablar en este servidor."),
        },
    }


@router.post("/{guild_id}/moderation/mute-role")
async def create_mute_role(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """Crea (o adopta) un rol de mute para el servidor.

    Si ya existe un rol llamado ``Muted``/``Silenciado`` lo reutiliza.
    Si no, crea uno nuevo y aplica overrides ``deny send_messages`` en cada
    canal donde el bot pueda gestionar permisos.
    """
    if bot is None:
        raise HTTPException(503, "Bot no conectado")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado")

    cog = bot.get_cog("Moderation")
    if cog is None or not hasattr(cog, "_ensure_mute_role"):
        raise HTTPException(503, "Cog de moderación no disponible")

    if not user.get("is_master_admin"):
        live_status = user.get("_live_guild_admin_status") or {}
        if not live_status.get("allowed"):
            raise HTTPException(403, "No se pudieron verificar tus permisos actuales")
        if not (
            live_status.get("is_owner")
            or live_status.get("administrator")
            or live_status.get("manage_roles")
        ):
            raise HTTPException(403, "Necesitas Gestionar roles para crear el rol de mute")

    try:
        role = await run_on_bot_loop(bot, lambda: cog._ensure_mute_role(guild), timeout=30)
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    if role is None:
        raise HTTPException(
            403,
            "No se pudo crear el rol. Verifica que el bot tenga el permiso "
            "`Gestionar roles` y que su rol esté arriba del nuevo rol Muted.",
        )

    return {
        "id": str(role.id),
        "name": role.name,
        "created": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/automod — config automoderación
# ─────────────────────────────────────────────────────────────────────────────


async def _validated_llm_update(db, guild_id, value):
    try:
        if not isinstance(value, dict):
            raise ValueError("llm debe ser un objeto")
        current = db.get_automod_config(guild_id)["rules"].get("llm") or {}
        endpoint = value.get("endpoint_url", current.get("endpoint_url", ""))
        addresses = None
        if endpoint:
            parsed = parse_endpoint_url(endpoint)
            changed = endpoint.strip() != (current.get("endpoint_url") or "").strip()
            approval_changed = ("private_endpoint_confirmed_url" in value
                                and value["private_endpoint_confirmed_url"] != current.get("private_endpoint_confirmed_url", ""))
            if (changed or approval_changed) and parsed.hostname.lower() not in allowed_endpoint_hosts():
                addresses = await resolve_endpoint_addresses(endpoint.strip())
        validated = validate_llm_config(value, current, resolved_addresses=addresses)
        if value.get("api_key_clear"):
            validated["api_key_clear"] = True
        return validated
    except EndpointConfirmationRequired as exc:
        raise HTTPException(409, {"code": exc.code, "endpoint_url": exc.endpoint_url,
                                  "required_confirmations": exc.required_confirmations, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{guild_id}/endpoints")
async def get_endpoints_config(guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)):
    llm = public_automod_config(db.get_automod_config(guild_id))["rules"]["llm"]
    return {"llm": {key: value for key, value in llm.items()
                    if key in ENDPOINT_CONFIG_FIELDS or key == "api_key_configured"},
            "integrations": [
                {"id": "gemini", "label": "Gemini", "managed_by": "ia/key"},
                {"id": "discord_webhook", "label": "Webhook de respuestas Discord", "managed_by": "ia"}]}


@router.patch("/{guild_id}/endpoints")
async def patch_endpoints_config(guild_id: int, body: dict, db=Depends(get_db), _user=Depends(require_guild_admin)):
    if set(body) != {"llm"} or not isinstance(body["llm"], dict):
        raise HTTPException(400, "llm debe ser el único objeto de configuración")
    if set(body["llm"]) - (ENDPOINT_CONFIG_FIELDS | {"api_key_configured", "api_key_clear"}):
        raise HTTPException(400, "Campo de conexión desconocido")
    validated = await _validated_llm_update(db, guild_id, body["llm"])
    connection = {key: validated[key] for key in body["llm"] if key in ENDPOINT_CONFIG_FIELDS}
    for field in ("insecure_http_confirmed_url", "private_endpoint_confirmed_url"):
        connection[field] = validated[field]
    if body["llm"].get("api_key") in (None, ""):
        connection.pop("api_key", None)
    if body["llm"].get("api_key_clear"):
        connection["api_key_clear"] = True
    db.set_automod_config(guild_id, rules={"llm": connection})
    return await get_endpoints_config(guild_id, db, _user)


@router.get("/{guild_id}/automod")
async def get_automod_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    """Devuelve la configuración completa de automoderación."""
    return public_automod_config(db.get_automod_config(guild_id))


@router.patch("/{guild_id}/automod")
async def patch_automod_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    enabled = body.get("enabled")
    rules = body.get("rules")
    if rules is not None and not isinstance(rules, dict):
        raise HTTPException(400, "rules debe ser un objeto")
    if rules is not None and "llm" in rules:
        rules = {**rules, "llm": await _validated_llm_update(db, guild_id, rules["llm"])}
    db.set_automod_config(guild_id, enabled=enabled, rules=rules)
    return {"status": "ok", "config": public_automod_config(db.get_automod_config(guild_id))}


@router.get("/{guild_id}/automod/log")
async def get_automod_log(
    guild_id: int,
    limit: int = 50,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
    bot=Depends(get_bot),
):
    rows = db.get_automod_log(guild_id, limit=max(1, min(limit, 200)))
    resolver = IdentityResolver(bot, guild_id)
    result = []
    for row in rows:
        item = stringify_fields(row, ("guild_id", "user_id"))
        item.update(moderation_details(row, automod=True))
        target = await resolver.resolve(item.get("user_id"), record_extra(row).get("target_user"))
        item.update(target_user=target, target_display=target["display"],
                    target_tag=target["tag"], target_avatar_url=target["avatar_url"])
        result.append(item)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/levels — config XP/niveles
# ─────────────────────────────────────────────────────────────────────────────


def _level_rewards_payload(rows: list[dict], guild_id: int, bot) -> list[dict]:
    """Añade identidad legible del rol sin dejar de exponer el snowflake seguro."""
    payload = stringify_rows(rows or [], ("guild_id", "role_id"))
    guild = bot.get_guild(guild_id) if bot is not None and hasattr(bot, "get_guild") else None
    for item in payload:
        role = None
        role_id = item.get("role_id")
        if guild is not None and role_id:
            try:
                role = guild.get_role(int(role_id))
            except (TypeError, ValueError):
                role = None
        item["role_name"] = getattr(role, "name", None)
        color = getattr(role, "color", None)
        color_value = getattr(color, "value", 0) if color is not None else 0
        item["role_color"] = f"#{int(color_value):06x}" if color_value else None
        item["role_exists"] = role is not None if guild is not None else None
    return payload


@router.get("/{guild_id}/levels")
async def get_levels_config(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    cfg = db.get_xp_config(guild_id) or {}
    cfg = stringify_fields(cfg, ("guild_id", "announcement_channel_id"))
    rewards = db.get_level_rewards(guild_id) or []
    return {"config": cfg, "rewards": _level_rewards_payload(rewards, guild_id, bot)}


@router.patch("/{guild_id}/levels")
async def patch_levels_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """
    Actualiza la configuración de niveles. En Fase 9 se añaden las claves de
    comportamiento del mensaje de subida (`levelup_*`) — antes el dashboard
    podía mostrarlas pero no se persistían.
    """
    allowed = {
        "enabled",
        "xp_min",
        "xp_max",
        "cooldown_seconds",
        "announcement_channel_id",
        "announcement_message",
        "stack_rewards",
        "ignored_channels",
        "channel_multipliers",
        "levelup_persist",
        "levelup_autodelete",
        "levelup_delete_after_seconds",
        "levelup_embed_config",
        "announcement_mode",
    }
    filtered = {k: v for k, v in body.items() if k in allowed}
    if "announcement_channel_id" in filtered:
        filtered["announcement_channel_id"] = _coerce_optional_snowflake(
            filtered["announcement_channel_id"], "announcement_channel_id"
        )
    if filtered:
        db.set_xp_config(guild_id, **filtered)
    return {
        "status": "ok",
        "updated": list(filtered.keys()),
        "config": stringify_fields(db.get_xp_config(guild_id), ("guild_id", "announcement_channel_id")),
    }


@router.get("/{guild_id}/levels/rewards")
async def get_level_rewards(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    return {"rewards": _level_rewards_payload(db.get_level_rewards(guild_id) or [], guild_id, bot)}


@router.post("/{guild_id}/levels/rewards")
async def add_level_reward(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    nivel = int(body.get("level", 0))
    role_id = coerce_snowflake(body.get("role_id"), "role_id")
    if nivel < 1 or role_id < 1:
        raise HTTPException(400, "nivel y role_id son requeridos y deben ser > 0")
    guild = bot.get_guild(guild_id) if bot is not None else None
    role = guild.get_role(role_id) if guild is not None else None
    forbidden_role_ids = delegated_moderation_role_ids(db, guild_id)
    if guild is None or not safe_for_automatic_assignment(
        role,
        guild.me,
        forbidden_role_ids=forbidden_role_ids,
    ):
        raise HTTPException(
            400,
            "El rol de recompensa debe estar bajo el bot y no conceder permisos administrativos.",
        )
    db.set_level_reward(guild_id, nivel, role_id)
    return {"status": "ok", "level": nivel, "role_id": str(role_id)}


@router.delete("/{guild_id}/levels/rewards/{level}")
async def delete_level_reward(
    guild_id: int,
    level: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    db.delete_level_reward(guild_id, level)
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/tickets — config tickets + categorías
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/tickets")
async def get_tickets_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    cfg = db.get_ticket_config(guild_id) or {}
    categories = db.get_ticket_categories(guild_id) or []
    return {
        "config": stringify_fields(cfg, ("guild_id", "panel_channel_id", "category_id", "log_channel_id")),
        "categories": stringify_rows(categories, ("guild_id", "staff_role_id")),
    }


@router.patch("/{guild_id}/tickets")
async def patch_tickets_config(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    """
    Actualiza la configuración de tickets.

    `panel_channel_id` y las claves de plantilla (`*_template`) faltaban en el
    allow-set previo, por lo que el dashboard nunca podía persistir esos campos.
    `max_tickets_per_user` y `ticket_cooldown_seconds` además no existían como
    columnas; ahora sí (Fase 7).
    """
    allowed = {
        "panel_channel_id",
        "category_id",
        "log_channel_id",
        "allowed_roles",
        "immune_roles",
        "channel_name_template",
        "max_tickets_per_user",
        "ticket_cooldown_seconds",
        "panel_embed_data",
        "panel_select_template",
        "panel_inside_template",
        "msg_open_template",
        "msg_close_template",
    }
    filtered = {k: v for k, v in body.items() if k in allowed}
    for field in ("panel_channel_id", "category_id", "log_channel_id"):
        if field in filtered:
            filtered[field] = _coerce_optional_snowflake(filtered[field], field)
    delegated_roles = {}
    current_ticket_config = db.get_ticket_config(guild_id) or {}
    for field in ("allowed_roles", "immune_roles"):
        if field in filtered:
            role_ids = _normalize_role_id_list(filtered[field], field)
            try:
                current_role_ids = _normalize_role_id_list(
                    current_ticket_config.get(field),
                    field,
                )
            except HTTPException:
                current_role_ids = None
            if role_ids == current_role_ids:
                filtered.pop(field)
            else:
                delegated_roles[field] = role_ids
                filtered[field] = json.dumps(role_ids)
    await _authorize_delegated_role_updates(
        request,
        guild_id,
        delegated_roles,
        bot,
        user,
    )
    if filtered:
        db.set_ticket_config(guild_id, **filtered)
    return {
        "status": "ok",
        "updated": list(filtered.keys()),
        "config": stringify_fields(db.get_ticket_config(guild_id), ("guild_id", "panel_channel_id", "category_id", "log_channel_id")),
    }


@router.post("/{guild_id}/tickets/send-panel")
async def send_ticket_panel(
    guild_id: int,
    body: dict,
    request: Request,
    bot=Depends(get_bot),
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    """Envía el panel de tickets a un canal usando el bot."""
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    channel_id = coerce_snowflake(body.get("channel_id"), "channel_id")
    if not channel_id:
        raise HTTPException(400, "channel_id requerido")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado")
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise HTTPException(400, "El panel solo puede enviarse a un canal de texto")

    if not user.get("is_master_admin"):
        resolved = await get_live_guild_member(request, guild_id, user)
        member = resolved.get("member")
        if member is None:
            raise HTTPException(403, "No se pudieron verificar tus permisos actuales")
        caller_permissions = channel.permissions_for(member)
        if not all(
            getattr(caller_permissions, permission, False)
            for permission in ("view_channel", "send_messages", "embed_links")
        ):
            raise HTTPException(403, "No tienes permisos suficientes en ese canal")

    bot_member = guild.me
    if bot_member is None:
        raise HTTPException(503, "No se pudieron verificar los permisos del bot")
    bot_permissions = channel.permissions_for(bot_member)
    if not all(
        getattr(bot_permissions, permission, False)
        for permission in ("view_channel", "send_messages", "embed_links")
    ):
        raise HTTPException(403, "El bot no tiene permisos suficientes en ese canal")

    tickets_cog = bot.get_cog("Tickets")
    if tickets_cog is None:
        raise HTTPException(503, "Módulo de tickets no disponible")
    try:
        ok, msg = await run_on_bot_loop(
            bot,
            lambda: tickets_cog.send_panel_to_channel(guild, channel_id),
            timeout=30,
        )
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    if not ok:
        raise HTTPException(400, msg)
    return {"status": "ok", "message": msg}


@router.post("/{guild_id}/tickets/categories")
async def add_ticket_category(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    nombre = body.get("name", "").strip()
    emoji = body.get("emoji", "")
    preguntas = body.get("questions", ["¿En qué podemos ayudarte?"])
    if not nombre:
        raise HTTPException(400, "name es requerido")

    welcome_data = body.get("welcome_embed_json") or body.get("welcome_embed_data")
    if isinstance(welcome_data, dict):
        welcome_data = json.dumps(welcome_data, ensure_ascii=False)

    staff_role_id = _coerce_optional_snowflake(
        body.get("staff_role_id"),
        "staff_role_id",
    )
    if staff_role_id is not None:
        normalized_roles = await _validate_privileged_role_updates(
            request,
            guild_id,
            {"staff_role_id": staff_role_id},
            bot,
            user,
        )
        staff_role_id = normalized_roles["staff_role_id"]

    db.add_ticket_category(
        guild_id,
        nombre,
        emoji,
        json.dumps(preguntas),
        json.dumps(
            body.get(
                "close_reasons", ["Solucionado", "Cierre Administrativo", "Inactividad"]
            )
        ),
        welcome_data,
        description=body.get("description"),
        welcome_embed_template_key=body.get("welcome_embed_template_key"),
        staff_role_id=staff_role_id,
    )
    return {"status": "ok"}


@router.delete("/{guild_id}/tickets/categories/{cat_id}")
async def delete_ticket_category(
    guild_id: int,
    cat_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina una categoría únicamente dentro del guild de la ruta."""
    if hasattr(db, "delete_ticket_category"):
        db.delete_ticket_category(cat_id, guild_id)
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/radio
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/radio")
async def get_radio_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    cfg = db.get_lofi_config(guild_id)
    return stringify_fields(cfg or {}, ("guild_id", "channel_id"))


@router.patch("/{guild_id}/radio")
async def patch_radio_config(
    guild_id: int,
    body: RadioConfigUpdate,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    result = await apply_radio_config(guild_id, body, request, db, bot, _user)
    cfg = db.get_lofi_config(guild_id)
    return {**result, "config": stringify_fields(cfg or {}, ("guild_id", "channel_id"))}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/music
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/music")
async def get_guild_music(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    radio_cfg = stringify_fields(db.get_lofi_config(guild_id), ("guild_id", "channel_id"))
    return {"nowPlaying": None, "recentTracks": [], "radioConfig": radio_cfg}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _icon_url(guild_id: str, icon: str | None) -> str | None:
    return (
        f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png?size=256"
        if icon
        else None
    )


def _format_guild(g: dict) -> dict:
    return {
        "id": g.get("id"),
        "name": g.get("name"),
        "icon": _icon_url(g.get("id", ""), g.get("icon")),
        "has_bot": True,
    }


def _format_user(user: dict) -> dict:
    return {
        "id": str(user.get("user_id", "")),
        "username": user.get("username", ""),
        "avatar": user.get("avatar", ""),
    }


def _ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Router legacy
# ─────────────────────────────────────────────────────────────────────────────


@router_legacy.get("/config")
async def get_guild_config_legacy(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    return {
        "guild_id": guild_id,
        "guild_config": db.get_config(guild_id),
        "server_config": db.get_server_config(guild_id),
        "ai_config": db.get_ai_config(guild_id),
        "welcome_config": db.get_welcome_config(guild_id),
        "boost_config": db.get_boost_config(guild_id),
        "suggestions_config": db.get_suggestions_config(guild_id),
    }


@router_legacy.put("/config")
async def update_guild_config_legacy(
    guild_id: int,
    body: dict,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    prepared = []
    for section, method, getter in [
        ("guild_config", "set_config", "get_config"),
        ("server_config", "set_server_config", "get_server_config"),
        ("ai_config", "set_ai_config", "get_ai_config"),
        ("welcome_config", "set_welcome_config", "get_welcome_config"),
        ("boost_config", "set_boost_config", "get_boost_config"),
        ("suggestions_config", "set_suggestions_config", "get_suggestions_config"),
    ]:
        if section in body and hasattr(db, method):
            payload = body[section]
            if not isinstance(payload, dict):
                raise HTTPException(400, f"{section} must be an object")
            payload = dict(payload)
            if "guild_id" in payload:
                raise HTTPException(400, "guild_id is not editable")
            has_delegated_role = any(
                key in payload
                for key in (
                    "mod_role_id",
                    "staff_role_id",
                    "users_role_id",
                    "channels_role_id",
                    "embed_role_id",
                    "ai_role_id",
                )
            )
            current_values = (
                getattr(db, getter)(guild_id) or {}
                if has_delegated_role
                else None
            )
            payload.update(
                await _validate_privileged_role_updates(
                    request,
                    guild_id,
                    payload,
                    bot,
                    user,
                    current_values,
                )
            )
            prepared.append((section, method, payload))

    updated = []
    for section, method, payload in prepared:
        try:
            getattr(db, method)(guild_id, **payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        updated.append(section)
    return {"status": "ok", "updated": updated}


@router_legacy.get("/stats")
async def get_guild_stats_legacy(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    return {
        "guild_id": guild_id,
        "bot_stats": db.get_bot_stats(),
        "open_tickets_guild": db.count_open_tickets_by_guild(guild_id),
    }


# ── Server Logging ────────────────────────────────────────────────────────────

@router.get("/{guild_id}/logging")
async def get_logging_config(
    guild_id: int,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    """Configuración de server event logging."""
    cfg = db.get_server_config(guild_id)
    return {
        "serverlog_channel": _serialize_snowflake(cfg.get("serverlog_channel")),
        "serverlog_enabled": cfg.get("serverlog_enabled", 1),
        "log_events": cfg.get("log_events"),
    }


@router.patch("/{guild_id}/logging")
async def patch_logging_config(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Actualizar configuración de server event logging."""
    body = await request.json()
    allowed = {"serverlog_channel", "serverlog_enabled", "log_events"}
    filtered = {k: v for k, v in body.items() if k in allowed}
    if not filtered:
        return {"status": "noop", "detail": "Sin campos válidos"}
    if "serverlog_channel" in filtered:
        channel_id = _coerce_optional_snowflake(filtered.get("serverlog_channel"), "serverlog_channel")
        filtered["serverlog_channel"] = _repair_rounded_log_channel_id(bot, guild_id, channel_id)
    db.set_server_config(guild_id, **filtered)
    saved = db.get_server_config(guild_id)
    return {
        "status": "ok",
        "updated": list(filtered.keys()),
        "config": {
            "serverlog_channel": _serialize_snowflake(saved.get("serverlog_channel")),
            "serverlog_enabled": saved.get("serverlog_enabled", 1),
            "log_events": saved.get("log_events"),
        },
    }


# ── Utilities (anti-raid, anti-alt, starboard) ────────────────────────────────

@router.get("/{guild_id}/utilities")
async def get_utilities_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Configuración de utilidades: anti-raid, anti-alt y starboard."""
    cfg = db.get_server_config(guild_id)
    return {
        "anti_raid_enabled": cfg.get("anti_raid_enabled", 0),
        "anti_raid_threshold": cfg.get("anti_raid_threshold", 10),
        "anti_raid_window": cfg.get("anti_raid_window", 30),
        "anti_raid_lockdown_duration": cfg.get("anti_raid_lockdown_duration", 300),
        "anti_alt_min_age": cfg.get("anti_alt_min_age", 7),
        "anti_alt_action": cfg.get("anti_alt_action", "log"),
        "anti_alt_role_id": _serialize_snowflake(cfg.get("anti_alt_role_id")),
        "starboard_channel_id": _serialize_snowflake(cfg.get("starboard_channel_id")),
        "starboard_threshold": cfg.get("starboard_threshold", 3),
    }


@router.patch("/{guild_id}/utilities")
async def patch_utilities_config(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualizar configuración de utilidades."""
    body = await request.json()
    allowed = {
        "anti_raid_enabled", "anti_raid_threshold", "anti_raid_window",
        "anti_raid_lockdown_duration", "anti_alt_min_age", "anti_alt_action",
        "anti_alt_role_id", "starboard_channel_id", "starboard_threshold",
    }
    filtered = {k: v for k, v in body.items() if k in allowed}
    for field in ("anti_alt_role_id", "starboard_channel_id"):
        if field in filtered:
            filtered[field] = _coerce_optional_snowflake(filtered[field], field)
    if not filtered:
        return {"status": "noop", "detail": "Sin campos válidos"}
    db.set_server_config(guild_id, **filtered)
    saved = db.get_server_config(guild_id)
    return {
        "status": "ok",
        "updated": list(filtered.keys()),
        "config": {
            "anti_alt_role_id": _serialize_snowflake(saved.get("anti_alt_role_id")),
            "starboard_channel_id": _serialize_snowflake(saved.get("starboard_channel_id")),
        },
    }

