"""
api/deps.py
───────────
Dependencias compartidas:
  • get_db()                     — Inyecta DatabaseManager
  • get_current_user()           — JWT desde Bearer header o cookie
  • get_current_user_from_request() — Para uso directo con Request
  • require_guild_admin()        — Verifica admin/owner del guild
"""

import asyncio
import logging
import os
import secrets
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop

logger = logging.getLogger("API.deps")
_bearer_scheme = HTTPBearer(auto_error=False)
_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}


def _normalized_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _require_trusted_cookie_origin(request: Request) -> None:
    """Bloquea CSRF para mutaciones autenticadas mediante cookie HttpOnly."""
    if request.method.upper() in _SAFE_HTTP_METHODS:
        return
    allowed = {
        _normalized_origin(os.getenv("DASHBOARD_URL", "http://localhost:8080")),
        _normalized_origin(os.getenv("API_BASE_URL", "http://localhost:8080")),
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    }
    allowed.discard("")

    supplied = _normalized_origin(request.headers.get("Origin", ""))
    if not supplied:
        supplied = _normalized_origin(request.headers.get("Referer", ""))
    if not supplied or supplied not in allowed:
        raise HTTPException(403, "Origen no permitido para una sesión web")


def _forbidden_detail(
    *,
    message: str,
    guild_id: int,
    live_status: dict,
    jwt_has_guild: bool,
) -> dict:
    return {
        "message": message,
        "guild_id": str(guild_id),
        "reason": live_status.get("reason"),
        "jwt_has_guild": jwt_has_guild,
        "bot_available": live_status.get("bot_available"),
        "guild_available": live_status.get("guild_available"),
        "member_available": live_status.get("member_available"),
        "is_owner": live_status.get("is_owner"),
        "administrator": live_status.get("administrator"),
        "manage_guild": live_status.get("manage_guild"),
    }


def _log_forbidden(request: Request, user: dict, detail: dict) -> None:
    path = getattr(getattr(request, "url", None), "path", "<unknown>")
    logger.warning(
        "403 dashboard permission path=%s user=%s guild=%s reason=%s jwt_has_guild=%s "
        "bot=%s guild_available=%s member=%s owner=%s admin=%s manage_guild=%s",
        path,
        user.get("user_id"),
        detail.get("guild_id"),
        detail.get("reason"),
        detail.get("jwt_has_guild"),
        detail.get("bot_available"),
        detail.get("guild_available"),
        detail.get("member_available"),
        detail.get("is_owner"),
        detail.get("administrator"),
        detail.get("manage_guild"),
    )


def get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, "Base de datos no disponible")
    return db


def get_bot(request: Request):
    """Inyecta la instancia del bot de Discord (puede ser None en tests)."""
    return getattr(request.app.state, "bot", None)


def _decode_jwt(token: str) -> dict:
    """Decodifica un JWT y devuelve el payload."""
    import jwt as pyjwt

    jwt_secret = os.getenv("JWT_SECRET", "")
    if not jwt_secret:
        raise HTTPException(503, "JWT_SECRET no configurado")
    try:
        payload = pyjwt.decode(token, jwt_secret, algorithms=["HS256"])
        return {
            "user_id": int(payload["sub"]),
            "username": payload.get("username", ""),
            "avatar": payload.get("avatar", ""),
            "guilds": payload.get("guilds", []),
            "is_dev_mode": False,
        }
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            401, "Token expirado", headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        logger.warning(f"Token inválido: {e}")
        raise HTTPException(
            401, "Token inválido", headers={"WWW-Authenticate": "Bearer"}
        )


async def get_current_user_from_request(request: Request) -> dict:
    """Extrae y valida el usuario desde Authorization header o cookie."""
    jwt_secret = os.getenv("JWT_SECRET", "")
    master_key = os.getenv("MASTER_ADMIN_KEY", "")

    if not jwt_secret and not master_key:
        logger.error("API without JWT_SECRET or MASTER_ADMIN_KEY")
        raise HTTPException(503, "API authentication is not configured")

    # Buscar token: 1) Authorization: Bearer, 2) Cookie botES_token
    token: Optional[str] = None
    token_from_header = False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_from_header = True
    elif "botES_token" in request.cookies:
        token = request.cookies["botES_token"]
        _require_trusted_cookie_origin(request)

    if not token:
        raise HTTPException(
            401,
            "Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Master Key bypass
    if master_key and token_from_header and secrets.compare_digest(token, master_key):
        return {
            "user_id": 0,
            "username": "MasterAdmin",
            "guilds": [],
            "is_dev_mode": False,
            "is_master_admin": True,
        }

    return _decode_jwt(token)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    return await get_current_user_from_request(request)


async def require_guild_admin(
    guild_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    if user.get("is_master_admin"):
        return user

    user_guilds = user.get("guilds", [])
    match = next((g for g in user_guilds if int(g.get("id", 0)) == guild_id), None)

    live_status = await get_guild_admin_status(request, guild_id, user)
    if live_status.get("allowed"):
        # El JWT puede estar viejo después de cambiar dominio/callback o roles.
        # Si el bot conectado confirma permisos reales, permitir la operación.
        user["is_live_guild_admin"] = True
        user["_live_guild_admin_status"] = live_status
        return user

    if not match:
        detail = _forbidden_detail(
            message="No tienes acceso a este servidor",
            guild_id=guild_id,
            live_status=live_status,
            jwt_has_guild=False,
        )
        _log_forbidden(request, user, detail)
        raise HTTPException(403, detail)

    detail = _forbidden_detail(
        message="Necesitas ser administrador o dueño del servidor",
        guild_id=guild_id,
        live_status=live_status,
        jwt_has_guild=True,
    )
    _log_forbidden(request, user, detail)
    raise HTTPException(403, detail)


async def _has_live_guild_admin(request: Request, guild_id: int, user: dict) -> bool:
    status = await get_guild_admin_status(request, guild_id, user)
    return bool(status.get("allowed"))


async def get_live_guild_member(request: Request, guild_id: int, user: dict) -> dict:
    """Resuelve guild y miembro actuales para autorización y filtros de canal.

    Los objetos ``guild`` y ``member`` son solo para consumo interno; los campos
    de estado permiten fallar de forma cerrada sin repetir lógica de diagnóstico.
    """
    result = {
        "bot": None,
        "guild": None,
        "member": None,
        "bot_available": False,
        "guild_available": False,
        "member_available": False,
        "reason": None,
    }
    bot = getattr(request.app.state, "bot", None)
    user_id = user.get("user_id")
    if bot is None or not user_id:
        result["reason"] = "bot_or_user_unavailable"
        return result
    result["bot"] = bot
    result["bot_available"] = True

    try:
        user_id_int = int(user_id)
        guild = bot.get_guild(int(guild_id))
    except Exception:
        result["reason"] = "invalid_user_or_guild_id"
        return result

    if guild is None:
        result["reason"] = "guild_not_found_in_bot"
        return result
    result["guild"] = guild
    result["guild_available"] = True

    try:
        member = await run_on_bot_loop(
            bot,
            lambda: guild.fetch_member(user_id_int),
            timeout=10,
        )
    except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
        logger.debug(
            "No se pudo consultar miembro live para user=%s guild=%s: %s",
            user_id_int,
            guild_id,
            exc,
        )
        result["reason"] = "bot_loop_unavailable_or_timeout"
        return result
    except Exception as exc:
        logger.debug(
            "No se pudo resolver miembro live para user=%s guild=%s: %s",
            user_id_int,
            guild_id,
            exc,
        )
        result["reason"] = "member_not_found_or_fetch_failed"
        return result

    member_guild = getattr(member, "guild", None)
    if (
        getattr(member, "id", None) != user_id_int
        or getattr(member_guild, "id", None) != int(guild_id)
    ):
        result["reason"] = "member_identity_mismatch"
        return result

    result["member"] = member
    result["member_available"] = True
    return result


async def get_guild_admin_status(request: Request, guild_id: int, user: dict) -> dict:
    """Describe permisos reales en el guild usando el bot conectado.

    El OAuth/JWT guarda un snapshot de permisos. En producción ese snapshot puede
    quedar desactualizado tras cambiar dominio, callback, roles o volver a invitar
    el bot. Las rutas protegidas usan la autoridad observada por Discord en vivo:
    owner, Administrator o Manage Guild.
    """
    base = {
        "allowed": False,
        "source": "live_bot",
        "bot_available": False,
        "guild_available": False,
        "member_available": False,
        "is_owner": False,
        "administrator": False,
        "manage_guild": False,
        "manage_roles": False,
        "reason": None,
    }
    resolved = await get_live_guild_member(request, guild_id, user)
    for key in ("bot_available", "guild_available", "member_available", "reason"):
        base[key] = resolved.get(key)
    guild = resolved.get("guild")
    if guild is None:
        return base

    try:
        user_id_int = int(user.get("user_id"))
    except (TypeError, ValueError):
        base["reason"] = "invalid_user_or_guild_id"
        return base
    member = resolved.get("member")
    if member is None:
        return base

    # ``fetch_member`` actualiza la pertenencia a roles, pero
    # ``member.guild_permissions`` puede seguir usando objetos Role cacheados.
    # Recuperar también las definiciones actuales evita autorizar durante la
    # ventana posterior a retirar Administrator o Manage Guild de un rol.
    bot = resolved.get("bot")

    async def fetch_current_authority():
        return await asyncio.gather(
            guild.fetch_roles(),
            bot.fetch_guild(int(guild_id)),
        )

    try:
        fresh_roles, live_guild = await run_on_bot_loop(
            bot,
            fetch_current_authority,
            timeout=10,
        )
    except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
        logger.debug(
            "No se pudieron consultar roles live para user=%s guild=%s: %s",
            user_id_int,
            guild_id,
            exc,
        )
        base["reason"] = "role_state_unavailable_or_timeout"
        return base
    except Exception as exc:
        logger.debug(
            "No se pudo resolver roles live para user=%s guild=%s: %s",
            user_id_int,
            guild_id,
            exc,
        )
        base["reason"] = "role_state_fetch_failed"
        return base

    if getattr(live_guild, "id", None) != int(guild_id):
        base["reason"] = "guild_identity_mismatch"
        return base
    if user_id_int == int(live_guild.owner_id):
        base.update({"allowed": True, "is_owner": True})
        return base

    roles_by_id = {int(role.id): role for role in fresh_roles}
    member_role_ids = {int(guild_id)}
    raw_role_ids = getattr(member, "_roles", None)
    if raw_role_ids is not None:
        member_role_ids.update(int(role_id) for role_id in raw_role_ids)
    else:
        member_role_ids.update(
            int(role.id) for role in getattr(member, "roles", ())
        )
    if any(role_id not in roles_by_id for role_id in member_role_ids):
        base["reason"] = "member_role_state_incomplete"
        return base

    permissions_value = 0
    for role_id in member_role_ids:
        permissions_value |= int(roles_by_id[role_id].permissions.value)
    base["administrator"] = bool(permissions_value & 0x8)
    base["manage_guild"] = bool(permissions_value & 0x20)
    base["manage_roles"] = bool(permissions_value & (1 << 28))
    base["allowed"] = bool(base["administrator"] or base["manage_guild"])
    if not base["allowed"]:
        base["reason"] = "member_lacks_admin_or_manage_guild"
    return base


async def require_master_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    Restringe a operaciones globales del bot (gestión del pool de API keys, etc).
    Solo permite el token configurado en MASTER_ADMIN_KEY.
    """
    if user.get("is_master_admin"):
        return user
    raise HTTPException(403, "Operación restringida al administrador del bot")
