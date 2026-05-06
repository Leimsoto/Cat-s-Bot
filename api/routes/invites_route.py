"""
api/routes/invites_route.py
────────────────────────────
GET   /api/guilds/{id}/invites  → leaderboard enriquecido + config de invitaciones
PATCH /api/guilds/{id}/invites  → actualizar config de invitaciones
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_bot, get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds", tags=["invites"])


@router.get("/{guild_id}/invites")
async def get_invites(
    guild_id: int,
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Devuelve el leaderboard de invitaciones y la configuración del módulo."""
    cfg = db.get_invite_config(guild_id)
    leaderboard_raw = (
        db.get_invite_leaderboard(guild_id, limit=20)
        if hasattr(db, "get_invite_leaderboard")
        else []
    )

    # Enriquecer con datos de miembro desde el caché del bot
    enriched = []
    discord_guild = bot.get_guild(guild_id) if bot else None
    for row in leaderboard_raw:
        inviter_id = row["inviter_id"]
        member = discord_guild.get_member(inviter_id) if discord_guild else None
        enriched.append(
            {
                "user_id": str(inviter_id),
                "username": member.display_name if member else f"Usuario {inviter_id}",
                "avatar": str(member.display_avatar.url) if member else None,
                "total": row["total"],
            }
        )

    return {"config": cfg, "leaderboard": enriched}


@router.patch("/{guild_id}/invites")
async def patch_invites(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del módulo de invitaciones."""
    allowed = {"channel_id", "enabled"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_invite_config(guild_id, **update)
    return {"status": "ok"}
