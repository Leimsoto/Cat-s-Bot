"""
api/routes/tickets.py
─────────────────────
Endpoints del sistema de tickets (CRUD plantillas + categorías editables).

Listas:
  GET   /api/guilds/{guild_id}/tickets/list                  → tickets paginado
  GET   /api/guilds/{guild_id}/tickets/list/{ticket_id}      → detalle ticket
  GET   /api/guilds/{guild_id}/tickets/templates             → lista plantillas
  PUT   /api/guilds/{guild_id}/tickets/templates/{key}       → upsert plantilla
  DELETE/api/guilds/{guild_id}/tickets/templates/{key}       → borra plantilla
  PATCH /api/guilds/{guild_id}/tickets/categories/{cat_id}   → edita categoría

La config principal y el panel de tickets siguen en api/routes/guild.py para
no fragmentar las URLs que el frontend ya usa.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/tickets", tags=["tickets"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class TicketTemplateUpsert(BaseModel):
    embed_data: dict | str = Field(..., description="JSON del embed (objeto o string).")
    name: Optional[str] = Field(default=None, max_length=150)


class TicketCategoryPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    emoji: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    questions: Optional[list[str]] = None
    close_reasons: Optional[list[str]] = None
    welcome_embed_data: Optional[dict | str] = None
    welcome_embed_template_key: Optional[str] = Field(default=None, max_length=100)
    staff_role_id: Optional[int] = None


# ── Tickets list (legacy plural) ─────────────────────────────────────────────


@router.get("/list")
async def list_tickets(
    guild_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    tickets = db.get_all_tickets(
        guild_id, status=status_filter, limit=limit, offset=offset
    )
    total_open = db.count_open_tickets_by_guild(guild_id)
    return {
        "guild_id": guild_id,
        "tickets": tickets,
        "open_count": total_open,
        "limit": limit,
        "offset": offset,
    }


@router.get("/list/{ticket_id}")
async def get_ticket_detail(
    guild_id: int,
    ticket_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    ticket = db.get_ticket(ticket_id)
    if not ticket or int(ticket.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, f"Ticket #{ticket_id} no encontrado en este servidor")
    return {"guild_id": guild_id, "ticket": ticket}


# ── Plantillas de embed reutilizables ────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista las plantillas del guild. embed_data viene como string JSON."""
    items = db.list_ticket_templates(guild_id)
    # Parseamos embed_data para devolverlo como objeto navegable.
    out = []
    for t in items:
        raw = t.get("embed_data") or "{}"
        try:
            embed = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            embed = {}
        out.append({**t, "embed_data": embed})
    return {"templates": out}


@router.put("/templates/{template_key}")
async def upsert_template(
    guild_id: int,
    template_key: str,
    body: TicketTemplateUpsert,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """
    Crea o actualiza la plantilla identificada por (guild_id, template_key).

    Las claves canónicas son:
      • panel_select   → selector inicial del panel
      • panel_inside   → embed dentro del ticket recién abierto
      • msg_open       → mensaje automático al abrir
      • msg_close      → mensaje automático al cerrar
      • custom_<algo>  → plantillas libres (referenciables por categorías)
    """
    if not template_key or len(template_key) > 100:
        raise HTTPException(400, "template_key inválido")
    embed_str = (
        body.embed_data
        if isinstance(body.embed_data, str)
        else json.dumps(body.embed_data, ensure_ascii=False)
    )
    db.upsert_ticket_template(guild_id, template_key, embed_str, body.name)
    return {"status": "ok", "template_key": template_key}


@router.delete("/templates/{template_key}")
async def delete_template(
    guild_id: int,
    template_key: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    db.delete_ticket_template(guild_id, template_key)
    return {"status": "ok"}


# ── Categorías (PATCH para edición) ──────────────────────────────────────────


@router.patch("/categories/{cat_id}")
async def patch_category(
    guild_id: int,
    cat_id: int,
    body: TicketCategoryPatch,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """
    Edita una categoría existente. Acepta solo los campos enviados.
    `questions`/`close_reasons` se serializan a JSON antes de guardar.
    `welcome_embed_data` igual si llega como dict.
    """
    payload: dict = {}
    if body.name is not None:
        payload["name"] = body.name
    if body.emoji is not None:
        payload["emoji"] = body.emoji
    if body.description is not None:
        payload["description"] = body.description
    if body.questions is not None:
        payload["questions"] = json.dumps(body.questions, ensure_ascii=False)
    if body.close_reasons is not None:
        payload["close_reasons"] = json.dumps(body.close_reasons, ensure_ascii=False)
    if body.welcome_embed_data is not None:
        payload["welcome_embed_data"] = (
            body.welcome_embed_data
            if isinstance(body.welcome_embed_data, str)
            else json.dumps(body.welcome_embed_data, ensure_ascii=False)
        )
    if body.welcome_embed_template_key is not None:
        payload["welcome_embed_template_key"] = body.welcome_embed_template_key
    if body.staff_role_id is not None:
        payload["staff_role_id"] = body.staff_role_id

    if not payload:
        return {"status": "ok", "updated": []}

    try:
        db.update_ticket_category(cat_id, **payload)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"status": "ok", "updated": list(payload.keys())}
