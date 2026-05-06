"""
api/routes/suggestions_route.py
────────────────────────────────
GET   /api/guilds/{id}/suggestions       → config + estadísticas de sugerencias
PATCH /api/guilds/{id}/suggestions       → actualizar config de sugerencias
GET   /api/guilds/{id}/suggestions/list  → lista paginada de sugerencias
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds", tags=["suggestions"])


@router.get("/{guild_id}/suggestions")
async def get_suggestions_config(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Devuelve la configuración y estadísticas del sistema de sugerencias."""
    cfg = db.get_suggestions_config(guild_id)

    # Obtener conteos por estado si el método está disponible
    all_s = (
        db.get_all_suggestions(guild_id) if hasattr(db, "get_all_suggestions") else []
    )
    pending = sum(1 for s in all_s if s.get("status") == "PENDING")
    accepted = sum(1 for s in all_s if s.get("status") == "ACCEPTED")
    denied = sum(1 for s in all_s if s.get("status") == "DENIED")

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
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza la configuración del sistema de sugerencias."""
    allowed = {"submit_channel_id", "review_channel_id", "public_channel_id"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Sin campos válidos")
    db.set_suggestions_config(guild_id, **update)
    return {"status": "ok"}


@router.get("/{guild_id}/suggestions/list")
async def list_suggestions(
    guild_id: int,
    status: str = Query(
        None, description="Filtrar por estado: PENDING, ACCEPTED, DENIED"
    ),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Devuelve la lista de sugerencias, opcionalmente filtrada por estado."""
    suggestions = (
        db.get_all_suggestions(guild_id, status)
        if hasattr(db, "get_all_suggestions")
        else []
    )
    return {"suggestions": [dict(s) for s in suggestions]}
