"""
api/routes/welcome.py
─────────────────────
GET   /api/guilds/{id}/welcome          → config de bienvenidas + boost + invites
PATCH /api/guilds/{id}/welcome          → actualizar config de bienvenidas
PATCH /api/guilds/{id}/welcome/boost    → actualizar config de boosters
PATCH /api/guilds/{id}/welcome/invites  → actualizar config de invitaciones
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds", tags=["welcome"])


@router.get("/{guild_id}/welcome")
async def get_welcome(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Devuelve la configuración completa de bienvenidas, boosters e invitaciones."""
    cfg = db.get_welcome_config(guild_id)
    boost = db.get_boost_config(guild_id)
    invite = db.get_invite_config(guild_id)
    return {
        "welcome": cfg,
        "boost": boost,
        "invites": invite,
    }


@router.patch("/{guild_id}/welcome")
async def patch_welcome(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del sistema de bienvenidas."""
    allowed = {"channel_id", "embed_data", "enabled"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_welcome_config(guild_id, **update)
    return {"status": "ok"}


@router.patch("/{guild_id}/welcome/boost")
async def patch_boost(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del sistema de agradecimiento a boosters."""
    allowed = {"channel_id", "embed_data", "gif_url", "enabled"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_boost_config(guild_id, **update)
    return {"status": "ok"}


@router.patch("/{guild_id}/welcome/invites")
async def patch_invite_config(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del canal de log de invitaciones."""
    allowed = {"channel_id", "enabled"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_invite_config(guild_id, **update)
    return {"status": "ok"}
