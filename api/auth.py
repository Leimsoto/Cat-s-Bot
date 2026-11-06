"""
api/auth.py
───────────
Autenticación Discord OAuth2 con CSRF state y JWT.

Flujo:
  1. /api/auth/login  → genera state + redirige a Discord
  2. Discord           → /api/auth/callback?code=&state=
  3. Intercambia code por access_token
  4. Obtiene usuario + guilds
  5. Genera JWT, lo guarda en cookie HttpOnly y redirige al panel

Variables de entorno (.env):
  DISCORD_CLIENT_ID
  DISCORD_CLIENT_SECRET
  JWT_SECRET
  DASHBOARD_URL       (URL pública del panel, ej: http://localhost:8080)
  API_BASE_URL        (URL pública de la API)
"""

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger("API.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api/v10"
OAUTH_STATE_COOKIE = "botES_oauth_state"
SESSION_COOKIE = "botES_token"
OAUTH_STATE_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 24 * 60 * 60


def _cfg() -> dict:
    api_base = os.getenv("API_BASE_URL", "http://localhost:8080")
    return {
        "client_id": os.getenv("DISCORD_CLIENT_ID", ""),
        "client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
        "jwt_secret": os.getenv("JWT_SECRET", ""),
        "dashboard_url": os.getenv("DASHBOARD_URL", "http://localhost:8080"),
        "redirect_uri": api_base.rstrip("/") + "/api/auth/callback",
    }


def _dashboard_panel_url() -> str:
    dashboard = _cfg()["dashboard_url"].rstrip("/")
    if dashboard.endswith("/panel"):
        return dashboard
    return dashboard + "/panel"


def _secure_cookies() -> bool:
    """Usa cookies Secure en HTTPS sin romper el desarrollo localhost por HTTP."""
    return urlsplit(_cfg()["redirect_uri"]).scheme.lower() == "https"


def _oauth_state_cookie_value(state: str, secret: str) -> str:
    issued_at = int(datetime.now(timezone.utc).timestamp())
    signature = hmac.new(
        secret.encode(),
        f"oauth-state:{state}.{issued_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{issued_at}.{signature}"


def _valid_oauth_state(state: str, cookie_value: str, secret: str) -> bool:
    try:
        issued_at_text, supplied_signature = cookie_value.split(".", 1)
        issued_at = int(issued_at_text)
    except (AttributeError, TypeError, ValueError):
        return False

    age = int(datetime.now(timezone.utc).timestamp()) - issued_at
    if age < 0 or age > OAUTH_STATE_TTL_SECONDS:
        return False
    expected_signature = hmac.new(
        secret.encode(),
        f"oauth-state:{state}.{issued_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return secrets.compare_digest(supplied_signature, expected_signature)


def _set_oauth_state_cookie(
    response: RedirectResponse, state: str, secret: str
) -> None:
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        _oauth_state_cookie_value(state, secret),
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookies(),
        samesite="lax",
        path="/",
    )


def _clear_oauth_state_cookie(response) -> None:
    response.delete_cookie(
        OAUTH_STATE_COOKIE,
        path="/",
        secure=_secure_cookies(),
        httponly=True,
        samesite="lax",
    )


def _set_session_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookies(),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=_secure_cookies(),
        httponly=True,
        samesite="lax",
    )


def _avatar_url(user_id: str, avatar: str | None) -> str:
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=256"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _has_manage_guild(permissions: int | str) -> bool:
    try:
        p = int(permissions)
        return bool(p & 0x8) or bool(p & 0x20)  # ADMINISTRATOR | MANAGE_GUILD
    except Exception:
        return False


@router.get("/login")
async def login():
    """Genera un state anti-CSRF ligado al navegador y redirige a Discord."""
    cfg = _cfg()
    if not cfg["client_id"] or not cfg["client_secret"] or not cfg["jwt_secret"]:
        raise HTTPException(503, "OAuth2 incompleto — revisa .env")

    state = secrets.token_urlsafe(24)

    from urllib.parse import urlencode

    params = urlencode(
        {
            "client_id": cfg["client_id"],
            "redirect_uri": cfg["redirect_uri"],
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        }
    )
    response = RedirectResponse(f"https://discord.com/oauth2/authorize?{params}")
    response.headers["Cache-Control"] = "no-store"
    _set_oauth_state_cookie(response, state, cfg["jwt_secret"])
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None, state: str | None = None, error: str | None = None
):
    """Callback OAuth2 de Discord — intercambia code → JWT."""
    cfg = _cfg()
    dashboard = cfg["dashboard_url"].rstrip("/")
    if not cfg["client_id"] or not cfg["client_secret"] or not cfg["jwt_secret"]:
        raise HTTPException(503, "OAuth2 incompleto — revisa .env")

    # El state vive en una cookie HttpOnly temporal del navegador que inició
    # el flujo. No hay una tabla global que pueda crecer con peticiones anónimas.
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not state or not _valid_oauth_state(state, cookie_state, cfg["jwt_secret"]):
        logger.warning("OAuth2 callback con state inválido o expirado")
        response = RedirectResponse(f"{dashboard}/login?error=invalid_state")
        response.headers["Cache-Control"] = "no-store"
        return response

    # Error desde Discord (usuario rechazó). Consumir la transacción ligada.
    if error or not code:
        response = RedirectResponse(f"{dashboard}/login?error=access_denied")
        response.headers["Cache-Control"] = "no-store"
        _clear_oauth_state_cookie(response)
        return response

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Intercambiar code por token
        token_r = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg["redirect_uri"],
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_r.status_code != 200:
            logger.warning(f"Token exchange falló: {token_r.text}")
            response = RedirectResponse(f"{dashboard}/login?error=token_failed")
            response.headers["Cache-Control"] = "no-store"
            _clear_oauth_state_cookie(response)
            return response

        access_token = token_r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Obtener usuario y guilds
        user_r = await client.get(f"{DISCORD_API}/users/@me", headers=headers)
        guilds_r = await client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)

    if user_r.status_code != 200:
        response = RedirectResponse(f"{dashboard}/login?error=user_failed")
        response.headers["Cache-Control"] = "no-store"
        _clear_oauth_state_cookie(response)
        return response

    user_data = user_r.json()
    guilds_raw = guilds_r.json() if guilds_r.status_code == 200 else []

    admin_guilds = [
        {
            "id": g["id"],
            "name": g["name"],
            "icon": g.get("icon"),
            "permissions": g.get("permissions", 0),
            "owner": g.get("owner", False),
        }
        for g in guilds_raw
        if g.get("owner") or _has_manage_guild(g.get("permissions", 0))
    ]

    import jwt as pyjwt

    payload = {
        "sub": str(user_data["id"]),
        "username": user_data.get("username", ""),
        "avatar": _avatar_url(str(user_data["id"]), user_data.get("avatar")),
        "guilds": admin_guilds,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    token = pyjwt.encode(payload, cfg["jwt_secret"], algorithm="HS256")

    # La credencial nunca viaja en la URL ni queda accesible a JavaScript.
    response = RedirectResponse(f"{dashboard}/auth/callback")
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, token)
    _clear_oauth_state_cookie(response)
    return response


@router.get("/me")
async def get_me(request: Request):
    """Devuelve los datos del usuario autenticado (desde JWT)."""
    from api.deps import get_current_user_from_request

    user = await get_current_user_from_request(request)
    return JSONResponse(
        {
            "user_id": user["user_id"],
            "username": user.get("username", ""),
            "avatar": user.get("avatar", ""),
            "guilds": user.get("guilds", []),
            "is_master": user.get("is_master_admin", False),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/permissions/{guild_id}")
async def get_permissions_debug(guild_id: int, request: Request):
    """Diagnóstico seguro de permisos del usuario actual para un servidor.

    Sirve para diferenciar 403 por token/JWT viejo, bot sin acceso al guild,
    miembro no encontrado o falta real de permisos.
    """
    from api.deps import get_current_user_from_request, get_guild_admin_status

    user = await get_current_user_from_request(request)
    jwt_match = next(
        (g for g in user.get("guilds", []) if int(g.get("id", 0)) == guild_id),
        None,
    )
    jwt_permissions = int(jwt_match.get("permissions", 0)) if jwt_match else 0
    jwt_allowed = bool(
        user.get("is_dev_mode")
        or user.get("is_master_admin")
        or (jwt_match and (jwt_match.get("owner") or jwt_permissions & 0x8 or jwt_permissions & 0x20))
    )
    live = await get_guild_admin_status(request, guild_id, user)

    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "user_id": str(user.get("user_id")),
            "allowed": bool(user.get("is_master_admin") or live.get("allowed")),
            "jwt": {
                "has_guild": jwt_match is not None,
                "allowed": jwt_allowed,
                "owner": bool(jwt_match.get("owner")) if jwt_match else False,
                "administrator": bool(jwt_permissions & 0x8),
                "manage_guild": bool(jwt_permissions & 0x20),
            },
            "live": live,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/logout")
async def logout():
    """Cierra la sesión del navegador eliminando la cookie HttpOnly."""
    response = JSONResponse({"message": "Sesión cerrada."})
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response)
    _clear_oauth_state_cookie(response)
    return response
