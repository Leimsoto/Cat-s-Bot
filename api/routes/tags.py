"""
api/routes/tags.py
──────────────────
Endpoints de tags personalizados.

GET    /api/guild/{guild_id}/tags           → todos los tags
POST   /api/guild/{guild_id}/tags           → crear tag
PUT    /api/guild/{guild_id}/tags/{name}    → editar tag
DELETE /api/guild/{guild_id}/tags/{name}    → eliminar tag
"""

from fastapi import APIRouter, Depends, HTTPException, status
from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/tags", tags=["tags"])


@router.get("")
async def list_tags(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista todos los tags del servidor."""
    tags = db.get_all_tags(guild_id)
    return {"guild_id": guild_id, "tags": tags, "count": len(tags)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tag(
    guild_id: int,
    body: dict,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    """Crea un nuevo tag."""
    name = body.get("name", "").strip().lower()
    content = body.get("content", "").strip()

    if not name or not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requieren 'name' y 'content'",
        )

    if db.get_tag(guild_id, name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un tag con el nombre '{name}'",
        )

    existing = db.get_all_tags(guild_id)
    if len(existing) >= 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Límite de 50 tags alcanzado",
        )

    creator_id = user.get("user_id", 0)
    db.create_tag(guild_id, name, content, creator_id)
    return {"status": "created", "name": name}


@router.put("/{name}")
async def update_tag(
    guild_id: int,
    name: str,
    body: dict,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Edita el contenido de un tag existente."""
    tag = db.get_tag(guild_id, name.lower())
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag '{name}' no encontrado",
        )

    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere 'content'",
        )

    db.update_tag(guild_id, name.lower(), content)
    return {"status": "updated", "name": name.lower()}


@router.delete("/{name}")
async def delete_tag(
    guild_id: int,
    name: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina un tag."""
    tag = db.get_tag(guild_id, name.lower())
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag '{name}' no encontrado",
        )

    db.delete_tag(guild_id, name.lower())
    return {"status": "deleted", "name": name.lower()}
