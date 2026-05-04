"""
api/deps.py
───────────
Dependencias compartidas:
  • get_db()                     — Inyecta DatabaseManager
  • get_current_user()           — JWT desde Bearer header o cookie
  • get_current_user_from_request() — Para uso directo con Request
  • require_guild_admin()        — Verifica admin/owner del guild
"""

import os
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("API.deps")
_bearer_scheme = HTTPBearer(auto_error=False)


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
            "user_id":  int(payload["sub"]),
            "username": payload.get("username", ""),
            "avatar":   payload.get("avatar", ""),
            "guilds":   payload.get("guilds", []),
            "is_dev_mode": False,
        }
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expirado", headers={"WWW-Authenticate": "Bearer"})
    except Exception as e:
        logger.warning(f"Token inválido: {e}")
        raise HTTPException(401, "Token inválido", headers={"WWW-Authenticate": "Bearer"})


async def get_current_user_from_request(request: Request) -> dict:
    """Extrae y valida el usuario desde Authorization header o cookie."""
    jwt_secret  = os.getenv("JWT_SECRET", "")
    master_key  = os.getenv("MASTER_ADMIN_KEY", "")

    # Sin seguridad configurada → modo dev
    if not jwt_secret and not master_key:
        logger.debug("Sin JWT_SECRET — modo desarrollo")
        return {"user_id": 0, "username": "dev", "is_dev_mode": True, "guilds": []}

    # Buscar token: 1) Authorization: Bearer, 2) Cookie botES_token
    token: Optional[str] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif "botES_token" in request.cookies:
        token = request.cookies["botES_token"]

    if not token:
        raise HTTPException(401, "Token de autenticación requerido",
                            headers={"WWW-Authenticate": "Bearer"})

    # Master Key bypass
    if master_key and token == master_key:
        return {"user_id": 0, "username": "MasterAdmin", "guilds": [],
                "is_dev_mode": False, "is_master_admin": True}

    return _decode_jwt(token)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    return await get_current_user_from_request(request)


async def require_guild_admin(
    guild_id: int,
    user: dict = Depends(get_current_user),
) -> dict:
    if user.get("is_dev_mode") or user.get("is_master_admin"):
        return user

    user_guilds = user.get("guilds", [])
    match = next((g for g in user_guilds if int(g.get("id", 0)) == guild_id), None)
    if not match:
        raise HTTPException(403, "No tienes acceso a este servidor")

    perms = int(match.get("permissions", 0))
    if not (bool(perms & 0x8) or bool(perms & 0x20) or match.get("owner")):
        raise HTTPException(403, "Necesitas ser administrador o dueño del servidor")

    return user
