"""
api/routes/embeds.py
────────────────────
Endpoints para configuración y gestión de Embeds Personalizados guardados.

GET    /api/guild/{guild_id}/embeds          → Lista embeds
GET    /api/guild/{guild_id}/embeds/{name}   → Detalle de embed
POST   /api/guild/{guild_id}/embeds          → Guarda embed
DELETE /api/guild/{guild_id}/embeds/{id}     → Elimina embed
"""

from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db, require_guild_admin
from pydantic import BaseModel
import json

router = APIRouter(prefix="/api/guild/{guild_id}/embeds", tags=["embeds"])

class EmbedCreate(BaseModel):
    name: str
    embed_data: str

@router.get("")
async def list_embeds(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Obtiene la lista de plantillas de embeds guardadas en el servidor."""
    embeds = db.get_saved_embeds(guild_id)
    return {
        "guild_id": guild_id,
        "embeds": embeds
    }

@router.get("/{name}")
async def get_embed(
    guild_id: int,
    name: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Obtiene el JSON completo de un embed por su nombre."""
    embed = db.get_saved_embed_by_name(guild_id, name)
    if not embed:
        raise HTTPException(status_code=404, detail="Embed no encontrado.")
        
    return embed

@router.post("")
async def create_embed(
    guild_id: int,
    body: EmbedCreate,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    """Guarda una nueva plantilla de embed personalizado."""
    # Validar que sea un JSON string correcto
    try:
        json.loads(body.embed_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="El campo embed_data debe ser un JSON válido.")

    try:
        creator_id = int(user.get("user_id", 0))

        # Si ya existe uno con ese nombre, eliminarlo primero (upsert)
        existing = db.get_saved_embed_by_name(guild_id, body.name)
        if existing:
            db.delete_saved_embed(existing["id"])

        db.save_embed(guild_id, creator_id, body.name, body.embed_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar: {str(e)}")

    return {"status": "ok", "message": f"Embed '{body.name}' guardado correctamente."}

@router.delete("/{embed_id}")
async def delete_embed(
    guild_id: int,
    embed_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina una plantilla de embed por su ID."""
    db.delete_saved_embed(embed_id)
    return {"status": "ok", "message": "Embed eliminado."}


# ── Endpoint del nuevo dashboard: enviar embed directamente ───────────────────

from pydantic import BaseModel as _BM
from typing import Optional as _Opt
import httpx as _httpx
import os as _os

class SendEmbedBody(_BM):
    channel_id: str
    embed: dict
    webhook_name: _Opt[str] = None
    webhook_avatar: _Opt[str] = None

_send_router = APIRouter(prefix="/api/guilds/{guild_id}/embeds", tags=["embeds"])

@_send_router.post("/send")
async def send_embed_to_channel(
    guild_id: int,
    body: SendEmbedBody,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Envía un embed directamente a un canal de Discord usando el bot token.
    Si se proporciona webhook_name o webhook_avatar, usa un webhook temporal.
    """
    bot_token = _os.getenv("TOKEN", "")
    if not bot_token:
        raise HTTPException(503, "Bot TOKEN no configurado")

    color_str = body.embed.get("color", "#6366f1").lstrip("#")
    try:
        color_int = int(color_str, 16)
    except ValueError:
        color_int = 0x6366F1

    # Construir el objeto embed de Discord
    discord_embed = {"color": color_int}
    if body.embed.get("title"):       discord_embed["title"]       = body.embed["title"]
    if body.embed.get("description"): discord_embed["description"] = body.embed["description"]
    if body.embed.get("image"):       discord_embed["image"]       = {"url": body.embed["image"]}
    if body.embed.get("thumbnail"):   discord_embed["thumbnail"]   = {"url": body.embed["thumbnail"]}

    # Author con icon y url
    author_data = {}
    if body.embed.get("author"):      author_data["name"] = body.embed["author"]
    if body.embed.get("author_icon"): author_data["icon_url"] = body.embed["author_icon"]
    if body.embed.get("author_url"):  author_data["url"] = body.embed["author_url"]
    if author_data: discord_embed["author"] = author_data

    # Footer con icon
    footer_data = {}
    if body.embed.get("footer"):      footer_data["text"] = body.embed["footer"]
    if body.embed.get("footer_icon"): footer_data["icon_url"] = body.embed["footer_icon"]
    if footer_data: discord_embed["footer"] = footer_data

    async with _httpx.AsyncClient(timeout=10) as client:
        if body.webhook_name or body.webhook_avatar:
            # Crear webhook temporal y enviar
            wh_r = await client.post(
                f"https://discord.com/api/v10/channels/{body.channel_id}/webhooks",
                headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                json={"name": body.webhook_name or "Bot ES"},
            )
            if wh_r.status_code not in (200, 201):
                raise HTTPException(wh_r.status_code, f"No se pudo crear el webhook: {wh_r.text}")
            wh = wh_r.json()
            msg_r = await client.post(
                f"https://discord.com/api/v10/webhooks/{wh['id']}/{wh['token']}",
                json={
                    "username":   body.webhook_name or "Bot ES",
                    "avatar_url": body.webhook_avatar,
                    "embeds":     [discord_embed],
                },
            )
            # Eliminar el webhook temporal
            await client.delete(
                f"https://discord.com/api/v10/webhooks/{wh['id']}/{wh['token']}",
            )
            if msg_r.status_code not in (200, 201, 204):
                raise HTTPException(msg_r.status_code, f"Discord rechazó el mensaje: {msg_r.text}")
            return {"status": "ok", "message_id": msg_r.json().get("id") if msg_r.content else None}
        else:
            r = await client.post(
                f"https://discord.com/api/v10/channels/{body.channel_id}/messages",
                headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                json={"embeds": [discord_embed]},
            )
            if r.status_code not in (200, 201):
                raise HTTPException(r.status_code, f"Discord rechazó el embed: {r.text}")
            return {"status": "ok", "message_id": r.json().get("id")}
