"""
api/auth.py
───────────
Autenticación Discord OAuth2 con CSRF state y JWT.

Flujo:
  1. /api/auth/login  → genera state + redirige a Discord
  2. Discord           → /api/auth/callback?code=&state=
  3. Intercambia code por access_token
  4. Obtiene usuario + guilds
  5. Genera JWT y redirige al panel con ?token=<jwt>

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
import time
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger("API.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api/v10"
_oauth_states: dict[str, float] = {}   # state → expiry timestamp


def _cfg() -> dict:
    api_base = os.getenv("API_BASE_URL", "http://localhost:8080")
    return {
        "client_id":     os.getenv("DISCORD_CLIENT_ID", ""),
        "client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
        "jwt_secret":    os.getenv("JWT_SECRET", ""),
        "dashboard_url": os.getenv("DASHBOARD_URL", "http://localhost:8080"),
        "redirect_uri":  api_base.rstrip("/") + "/api/auth/callback",
    }


def _avatar_url(user_id: str, avatar: str | None) -> str:
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=256"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _has_manage_guild(permissions: int | str) -> bool:
    try:
        p = int(permissions)
        return bool(p & 0x8) or bool(p & 0x20)   # ADMINISTRATOR | MANAGE_GUILD
    except Exception:
        return False


@router.get("/login")
async def login():
    """Genera un state anti-CSRF y redirige a Discord OAuth2."""
    cfg = _cfg()
    if not cfg["client_id"]:
        raise HTTPException(503, "DISCORD_CLIENT_ID no configurado")

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time() + 300   # válido 5 minutos

    from urllib.parse import urlencode
    params = urlencode({
        "client_id":     cfg["client_id"],
        "redirect_uri":  cfg["redirect_uri"],
        "response_type": "code",
        "scope":         "identify guilds",
        "state":         state,
    })
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{params}")


@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Callback OAuth2 de Discord — intercambia code → JWT."""
    dashboard = _cfg()["dashboard_url"].rstrip("/")

    # Error desde Discord (usuario rechazó)
    if error or not code:
        return RedirectResponse(f"{dashboard}/panel/login?error=access_denied")

    # Verificar state CSRF
    expiry = _oauth_states.pop(state or "", None)
    if expiry is None or time.time() > expiry:
        logger.warning("OAuth2 callback con state inválido o expirado")
        return RedirectResponse(f"{dashboard}/panel/login?error=invalid_state")

    cfg = _cfg()
    if not cfg["client_id"] or not cfg["client_secret"] or not cfg["jwt_secret"]:
        raise HTTPException(503, "OAuth2 incompleto — revisa .env")

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Intercambiar code por token
        token_r = await client.post(f"{DISCORD_API}/oauth2/token", data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  cfg["redirect_uri"],
            "client_id":     cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})

        if token_r.status_code != 200:
            logger.warning(f"Token exchange falló: {token_r.text}")
            return RedirectResponse(f"{dashboard}/panel/login?error=token_failed")

        access_token = token_r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Obtener usuario y guilds
        user_r   = await client.get(f"{DISCORD_API}/users/@me", headers=headers)
        guilds_r = await client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)

    if user_r.status_code != 200:
        return RedirectResponse(f"{dashboard}/panel/login?error=user_failed")

    user_data  = user_r.json()
    guilds_raw = guilds_r.json() if guilds_r.status_code == 200 else []

    admin_guilds = [
        {
            "id":          g["id"],
            "name":        g["name"],
            "icon":        g.get("icon"),
            "permissions": g.get("permissions", 0),
            "owner":       g.get("owner", False),
        }
        for g in guilds_raw
        if g.get("owner") or _has_manage_guild(g.get("permissions", 0))
    ]

    import jwt as pyjwt
    payload = {
        "sub":      str(user_data["id"]),
        "username": user_data.get("username", ""),
        "avatar":   _avatar_url(str(user_data["id"]), user_data.get("avatar")),
        "guilds":   admin_guilds,
        "iat":      datetime.now(timezone.utc),
        "exp":      datetime.now(timezone.utc) + timedelta(hours=24),
    }
    token = pyjwt.encode(payload, cfg["jwt_secret"], algorithm="HS256")

    # Redirigir al panel con el token
    return RedirectResponse(f"{dashboard}/panel/auth/callback?token={token}")


@router.get("/me")
async def get_me(request: Request):
    """Devuelve los datos del usuario autenticado (desde JWT)."""
    from api.deps import get_current_user_from_request
    user = await get_current_user_from_request(request)
    return {
        "user_id":    user["user_id"],
        "username":   user.get("username", ""),
        "avatar":     user.get("avatar", ""),
        "guilds":     user.get("guilds", []),
        "is_master":  user.get("is_master_admin", False),
    }


@router.post("/logout")
async def logout():
    """Cierra sesión (el token JWT se invalida en el cliente)."""
    return {"message": "Sesión cerrada. Elimina el token del cliente."}
