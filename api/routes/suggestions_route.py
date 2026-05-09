"""
api/routes/suggestions_route.py
────────────────────────────────
Endpoints del sistema de sugerencias.

GET    /api/guilds/{g}/suggestions               → config + estadísticas
PATCH  /api/guilds/{g}/suggestions               → actualizar config
GET    /api/guilds/{g}/suggestions/list          → lista paginada (filtro estado, enrich)
PATCH  /api/guilds/{g}/suggestions/list/{id}     → cambiar estado / razón denegación
DELETE /api/guilds/{g}/suggestions/list/{id}     → eliminar
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_bot, get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds", tags=["suggestions"])


VALID_STATUSES = {"PENDING", "ACCEPTED", "DENIED"}


class SuggestionsConfigPatch(BaseModel):
    submit_channel_id: Optional[int] = None
    review_channel_id: Optional[int] = None
    public_channel_id: Optional[int] = None
    enabled:           Optional[int] = None
    auto_publish:      Optional[int] = None
    min_length:        Optional[int] = Field(None, ge=1, le=4000)
    max_length:        Optional[int] = Field(None, ge=10, le=4000)
    cooldown_seconds:  Optional[int] = Field(None, ge=0, le=86400)


class SuggestionPatch(BaseModel):
    status:        Optional[str] = None
    denial_reason: Optional[str] = None


@router.get("/{guild_id}/suggestions")
async def get_suggestions_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Configuración + estadísticas."""
    cfg = db.get_suggestions_config(guild_id) or {}
    all_s = db.get_all_suggestions(guild_id) if hasattr(db, "get_all_suggestions") else []
    pending  = sum(1 for s in all_s if s.get("status") == "PENDING")
    accepted = sum(1 for s in all_s if s.get("status") == "ACCEPTED")
    denied   = sum(1 for s in all_s if s.get("status") == "DENIED")
    return {
        "config": cfg,
        "stats": {
            "total": len(all_s),
            "pending": pending,
            "accepted": accepted,
            "denied": denied,
        },
    }


@router.patch("/{guild_id}/suggestions")
async def patch_suggestions(
    guild_id: int,
    body: SuggestionsConfigPatch,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la config (canales, flags, límites, cooldown)."""
    update = body.model_dump(exclude_none=True)
    if "enabled" in update:
        update["enabled"] = 1 if int(update["enabled"]) else 0
    if "auto_publish" in update:
        update["auto_publish"] = 1 if int(update["auto_publish"]) else 0
    if "min_length" in update and "max_length" in update:
        if int(update["min_length"]) > int(update["max_length"]):
            raise HTTPException(400, "min_length no puede ser mayor que max_length")
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_suggestions_config(guild_id, **update)
    return {"status": "ok", "updated": list(update.keys())}


@router.get("/{guild_id}/suggestions/list")
async def list_suggestions(
    guild_id: int,
    status: Optional[str] = Query(None, description="PENDING/ACCEPTED/DENIED"),
    db=Depends(get_db),
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    """Lista enriquecida con username/avatar."""
    if status:
        status = status.upper()
        if status == "ALL":
            status = None
        elif status not in VALID_STATUSES:
            raise HTTPException(400, f"status inválido. Permitidos: {sorted(VALID_STATUSES)}")
    rows = db.get_all_suggestions(guild_id, status) if hasattr(db, "get_all_suggestions") else []

    discord_guild = bot.get_guild(guild_id) if bot else None
    enriched = []
    for s in rows:
        out = dict(s)
        if discord_guild:
            member = discord_guild.get_member(int(out.get("user_id", 0)))
            if member:
                out["username"] = member.display_name
                out["avatar"] = str(member.display_avatar.url)
        enriched.append(out)
    return {"suggestions": enriched, "count": len(enriched)}


@router.patch("/{guild_id}/suggestions/list/{suggestion_id}")
async def patch_suggestion(
    guild_id: int,
    suggestion_id: int,
    body: SuggestionPatch,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Cambia status o denial_reason de una sugerencia."""
    s = db.get_suggestion(suggestion_id)
    if not s or int(s.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, "Sugerencia no encontrada")

    update = {}
    if body.status is not None:
        st = body.status.upper()
        if st not in VALID_STATUSES:
            raise HTTPException(400, f"status inválido. Permitidos: {sorted(VALID_STATUSES)}")
        update["status"] = st
    if body.denial_reason is not None:
        update["denial_reason"] = body.denial_reason

    if not update:
        raise HTTPException(400, "Sin campos para actualizar")
    db.update_suggestion(suggestion_id, **update)
    return {"status": "ok", "suggestion_id": suggestion_id, "updated": update}


@router.delete("/{guild_id}/suggestions/list/{suggestion_id}")
async def delete_suggestion(
    guild_id: int,
    suggestion_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina una sugerencia (irreversible)."""
    s = db.get_suggestion(suggestion_id)
    if not s or int(s.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, "Sugerencia no encontrada")
    db._execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
    db._execute("DELETE FROM suggestion_votes WHERE suggestion_id = ?", (suggestion_id,))
    return {"status": "ok", "suggestion_id": suggestion_id}
