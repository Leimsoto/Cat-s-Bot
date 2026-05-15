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

import json
import logging
from datetime import datetime, timedelta, timezone

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import get_bot, get_current_user, get_db, require_guild_admin

logger = logging.getLogger("API.guild")

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

    # Usuarios normales: filtrar sus guilds por los que el bot conoce en memoria
    result = []
    for g in user_guilds:
        guild_id = int(g["id"])
        # Si el bot está disponible, chequeamos en memoria (sin API call)
        if bot is not None:
            discord_guild = bot.get_guild(guild_id)
            if discord_guild is not None:
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
        else:
            # Fallback: el bot no está disponible (startup), devolver info del usuario
            result.append(
                {
                    "id": str(guild_id),
                    "name": g["name"],
                    "icon": _icon_url(str(guild_id), g.get("icon")),
                    "has_bot": False,
                }
            )

    return {"guilds": result, "user": _format_user(user)}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/channels  — lista desde bot en memoria
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/channels")
async def get_guild_channels(
    guild_id: int,
    search: str = "",
    type: str = "",
    limit: int = 200,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
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

    limit = max(1, min(int(limit), 500))
    type_filter = {t.strip() for t in type.split(",") if t.strip()} if type else set()
    search_lower = search.strip().lower()

    channels = []
    for ch in sorted(
        guild.channels, key=lambda c: c.position if hasattr(c, "position") else 0
    ):
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
    guild_id: int,
    search: str = "",
    limit: int = 200,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Atajo: lista solo las categorías del servidor (CategoryChannel)."""
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")

    limit = max(1, min(int(limit), 500))
    search_lower = search.strip().lower()

    categories = []
    for cat in sorted(guild.categories, key=lambda c: c.position):
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
        tickets = (
            db.get_tickets_by_guild(guild_id)
            if hasattr(db, "get_tickets_by_guild")
            else []
        )
        open_t = [t for t in tickets if t.get("status") in ("OPEN", "abierto")]
        members = (
            db.get_member_count(guild_id) if hasattr(db, "get_member_count") else 0
        )

        now = datetime.now(timezone.utc)
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
                "openTickets": len(open_t),
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
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    if "guild" in body:
        db.set_config(guild_id, **body["guild"])
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/ia
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/ia")
async def get_ia_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    return db.get_ai_config(guild_id) or {}


@router.patch("/{guild_id}/ia")
async def patch_ia_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    db.set_ai_config(guild_id, **body)
    return db.get_ai_config(guild_id) or body


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
    merged = {**cfg, **srv_cfg}
    return {
        "mute_role_id": merged.get("mute_role_id"),
        "mod_role_id": merged.get("mod_role_id"),
        "staff_role_id": merged.get("staff_role_id"),
        "modlog_channel": merged.get("modlog_channel"),
        "modlog_enabled": merged.get("modlog_enabled", 1),
        "warn_ban_threshold": merged.get("warn_ban_threshold", 7),
        "warn_kick_threshold": merged.get("warn_kick_threshold", 5),
        "warn_mute_threshold": merged.get("warn_mute_threshold", 3),
        "warn_ban_enabled": merged.get("warn_ban_enabled", 0),
        "warn_kick_enabled": merged.get("warn_kick_enabled", 0),
        "warn_mute_enabled": merged.get("warn_mute_enabled", 1),
        "warn_mute_duration": merged.get("warn_mute_duration", 600),
        "warn_embed_config": merged.get("warn_embed_config"),
    }


@router.patch("/{guild_id}/moderation")
async def patch_moderation_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
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
    }
    server_keys = {
        "mod_role_id",
        "modlog_channel",
        "modlog_enabled",
    }

    config_payload = {k: v for k, v in body.items() if k in config_keys}
    server_payload = {k: v for k, v in body.items() if k in server_keys}

    if config_payload:
        db.set_config(guild_id, **config_payload)
    if server_payload and hasattr(db, "set_server_config"):
        db.set_server_config(guild_id, **server_payload)

    updated = list(config_payload.keys()) + list(server_payload.keys())
    return {"status": "ok", "updated_keys": updated}


@router.post("/{guild_id}/moderation/mute-role")
async def create_mute_role(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
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

    role = await cog._ensure_mute_role(guild)
    if role is None:
        raise HTTPException(
            403,
            "No se pudo crear el rol. Verifica que el bot tenga el permiso "
            "`Gestionar roles` y que su rol esté arriba del nuevo rol Muted.",
        )

    return {
        "id": role.id,
        "name": role.name,
        "created": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/automod — config automoderación
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/automod")
async def get_automod_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    """Devuelve la configuración completa de automoderación."""
    return db.get_automod_config(guild_id)


@router.patch("/{guild_id}/automod")
async def patch_automod_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    enabled = body.get("enabled")
    rules = body.get("rules")
    db.set_automod_config(guild_id, enabled=enabled, rules=rules)
    return {"status": "ok"}


@router.get("/{guild_id}/automod/log")
async def get_automod_log(
    guild_id: int,
    limit: int = 50,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    return db.get_automod_log(guild_id, limit=min(limit, 200))


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/levels — config XP/niveles
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/levels")
async def get_levels_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    cfg = db.get_xp_config(guild_id) or {}
    rewards = db.get_level_rewards(guild_id) or []
    return {"config": cfg, "rewards": rewards}


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
    if filtered:
        db.set_xp_config(guild_id, **filtered)
    return {"status": "ok", "updated": list(filtered.keys())}


@router.get("/{guild_id}/levels/rewards")
async def get_level_rewards(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    return {"rewards": db.get_level_rewards(guild_id) or []}


@router.post("/{guild_id}/levels/rewards")
async def add_level_reward(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    nivel = int(body.get("level", 0))
    role_id = int(body.get("role_id", 0))
    if nivel < 1 or role_id < 1:
        raise HTTPException(400, "nivel y role_id son requeridos y deben ser > 0")
    db.set_level_reward(guild_id, nivel, role_id)
    return {"status": "ok", "level": nivel, "role_id": role_id}


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
    return {"config": cfg, "categories": categories}


@router.patch("/{guild_id}/tickets")
async def patch_tickets_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
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
    if filtered:
        db.set_ticket_config(guild_id, **filtered)
    return {"status": "ok", "updated": list(filtered.keys())}


@router.post("/{guild_id}/tickets/send-panel")
async def send_ticket_panel(
    guild_id: int,
    body: dict,
    bot=Depends(get_bot),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Envía el panel de tickets a un canal usando el bot."""
    if bot is None:
        raise HTTPException(503, "Bot no disponible")
    channel_id = int(body.get("channel_id", 0))
    if not channel_id:
        raise HTTPException(400, "channel_id requerido")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado")
    tickets_cog = bot.get_cog("Tickets")
    if tickets_cog is None:
        raise HTTPException(503, "Módulo de tickets no disponible")
    ok, msg = await tickets_cog.send_panel_to_channel(guild, channel_id)
    if not ok:
        raise HTTPException(400, msg)
    return {"status": "ok", "message": msg}


@router.post("/{guild_id}/tickets/categories")
async def add_ticket_category(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    nombre = body.get("name", "").strip()
    emoji = body.get("emoji", "")
    preguntas = body.get("questions", ["¿En qué podemos ayudarte?"])
    if not nombre:
        raise HTTPException(400, "name es requerido")

    welcome_data = body.get("welcome_embed_json") or body.get("welcome_embed_data")
    if isinstance(welcome_data, dict):
        welcome_data = json.dumps(welcome_data, ensure_ascii=False)

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
        staff_role_id=body.get("staff_role_id"),
    )
    return {"status": "ok"}


@router.delete("/{guild_id}/tickets/categories/{cat_id}")
async def delete_ticket_category(
    guild_id: int,
    cat_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """
    Elimina una categoría. Antes se llamaba a `delete_ticket_category` con dos
    argumentos pero la firma del manager solo acepta el id → TypeError.
    """
    if hasattr(db, "delete_ticket_category"):
        db.delete_ticket_category(cat_id)
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/radio
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/radio")
async def get_radio_config(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    cfg = db.get_radio_config(guild_id) if hasattr(db, "get_radio_config") else {}
    return cfg or {}


@router.patch("/{guild_id}/radio")
async def patch_radio_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    if hasattr(db, "set_radio_config"):
        db.set_radio_config(guild_id, **body)
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/music
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/music")
async def get_guild_music(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    radio_cfg = db.get_radio_config(guild_id) if hasattr(db, "get_radio_config") else {}
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
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    updated = []
    for section, method in [
        ("guild_config", "set_config"),
        ("server_config", "set_server_config"),
        ("ai_config", "set_ai_config"),
        ("welcome_config", "set_welcome_config"),
        ("boost_config", "set_boost_config"),
        ("suggestions_config", "set_suggestions_config"),
    ]:
        if section in body and hasattr(db, method):
            getattr(db, method)(guild_id, **body[section])
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


# ─────────────────────────────────────────────────────────────────────────────
# /api/guilds/{id}/schedules  — Mensajes Programados desde dashboard
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{guild_id}/schedules")
async def get_schedules(
    guild_id: int, db=Depends(get_db), _user=Depends(require_guild_admin)
):
    schedules = db.get_schedules(guild_id) if hasattr(db, "get_schedules") else []
    return {"schedules": schedules}


@router.post("/{guild_id}/schedules")
async def create_schedule(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    name = body.get("name", "").strip()
    channel = int(body.get("channel_id", 0))
    content = body.get("content", "").strip()
    interval = int(body.get("interval_seconds", 3600))
    creator = int(user.get("user_id", 0))

    if not name:
        raise HTTPException(400, "name requerido")
    if not channel:
        raise HTTPException(400, "channel_id requerido")
    if not content:
        raise HTTPException(400, "content requerido")
    if interval < 60:
        raise HTTPException(400, "interval_seconds mínimo 60")

    existing = (
        db.get_schedule_by_name(guild_id, name)
        if hasattr(db, "get_schedule_by_name")
        else None
    )
    if existing:
        raise HTTPException(409, f"Ya existe un horario con el nombre '{name}'")

    db.create_schedule(guild_id, name, channel, content, interval, creator)
    return {"status": "ok", "name": name}


@router.patch("/{guild_id}/schedules/{name}")
async def update_schedule(
    guild_id: int,
    name: str,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    sched = (
        db.get_schedule_by_name(guild_id, name)
        if hasattr(db, "get_schedule_by_name")
        else None
    )
    if not sched:
        raise HTTPException(404, "Horario no encontrado")
    allowed = {"enabled", "channel_id", "content", "interval_seconds"}
    filtered = {k: v for k, v in body.items() if k in allowed}
    if filtered:
        db.update_schedule(sched["id"], **filtered)
    return {"status": "ok"}


@router.delete("/{guild_id}/schedules/{name}")
async def delete_schedule(
    guild_id: int,
    name: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    db.delete_schedule(guild_id, name)
    return {"status": "ok"}


# ── Server Logging ────────────────────────────────────────────────────────────

@router.get("/{guild_id}/logging")
async def get_logging_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Configuración de server event logging."""
    cfg = db.get_server_config(guild_id)
    return {
        "serverlog_channel": cfg.get("serverlog_channel"),
        "serverlog_enabled": cfg.get("serverlog_enabled", 1),
        "log_events": cfg.get("log_events"),
    }


@router.patch("/{guild_id}/logging")
async def patch_logging_config(
    guild_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualizar configuración de server event logging."""
    body = await request.json()
    allowed = {"serverlog_channel", "serverlog_enabled", "log_events"}
    filtered = {k: v for k, v in body.items() if k in allowed}
    if not filtered:
        return {"status": "noop", "detail": "Sin campos válidos"}
    db.set_server_config(guild_id, **filtered)
    return {"status": "ok", "updated": list(filtered.keys())}


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
        "anti_alt_role_id": cfg.get("anti_alt_role_id"),
        "starboard_channel_id": cfg.get("starboard_channel_id"),
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
    if not filtered:
        return {"status": "noop", "detail": "Sin campos válidos"}
    db.set_server_config(guild_id, **filtered)
    return {"status": "ok", "updated": list(filtered.keys())}

