"""
api/routes/schedules.py
───────────────────────
Endpoints de mensajes programados (cron).

GET    /api/guilds/{g}/schedules                       → listar
POST   /api/guilds/{g}/schedules                       → crear
PATCH  /api/guilds/{g}/schedules/{schedule_id}         → editar (channel/content/interval/enabled)
POST   /api/guilds/{g}/schedules/{schedule_id}/toggle  → activar/desactivar
POST   /api/guilds/{g}/schedules/{schedule_id}/test    → enviar mensaje ahora (sin actualizar last_sent)
DELETE /api/guilds/{g}/schedules/{schedule_id}         → eliminar (también acepta nombre)
"""

from typing import Optional

import discord
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/schedules", tags=["schedules"])

MAX_SCHEDULES = 10
MIN_INTERVAL = 600
MAX_INTERVAL = 2_592_000


# ── Schemas ──────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name:             str
    channel_id:       int
    content:          str
    interval_seconds: int = Field(..., ge=MIN_INTERVAL, le=MAX_INTERVAL)


class SchedulePatch(BaseModel):
    channel_id:       Optional[int] = None
    content:          Optional[str] = None
    interval_seconds: Optional[int] = Field(None, ge=MIN_INTERVAL, le=MAX_INTERVAL)
    enabled:          Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_schedule(db, guild_id: int, ident) -> Optional[dict]:
    """Resuelve schedule por id numérico o por nombre. Filtra por guild."""
    schedules = db.get_schedules(guild_id)
    try:
        sid = int(ident)
        return next((s for s in schedules if int(s["id"]) == sid), None)
    except (ValueError, TypeError):
        return next((s for s in schedules if s["name"] == str(ident)), None)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_schedules(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    schedules = db.get_schedules(guild_id)
    return {
        "guild_id": guild_id,
        "schedules": schedules,
        "count": len(schedules),
        "limits": {
            "max_schedules": MAX_SCHEDULES,
            "min_interval": MIN_INTERVAL,
            "max_interval": MAX_INTERVAL,
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    guild_id: int,
    body: ScheduleCreate,
    db=Depends(get_db),
    user=Depends(require_guild_admin),
):
    name = body.name.strip()
    content = body.content.strip()
    if not name or not content:
        raise HTTPException(400, "name y content no pueden estar vacíos")

    existing = db.get_schedules(guild_id)
    if len(existing) >= MAX_SCHEDULES:
        raise HTTPException(400, f"Máximo de {MAX_SCHEDULES} schedules alcanzado")
    if any(s["name"] == name for s in existing):
        raise HTTPException(409, f"Ya existe un schedule llamado '{name}'")

    creator_id = int(user.get("user_id", 0)) if isinstance(user, dict) else 0
    db.create_schedule(
        guild_id, name, int(body.channel_id), content,
        int(body.interval_seconds), creator_id,
    )
    return {"status": "created", "name": name}


@router.patch("/{ident}")
async def patch_schedule(
    guild_id: int,
    ident: str,
    body: SchedulePatch,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Edita un schedule por id o nombre."""
    sched = _find_schedule(db, guild_id, ident)
    if not sched:
        raise HTTPException(404, f"Schedule '{ident}' no encontrado en este servidor")

    update = body.model_dump(exclude_none=True)
    if "enabled" in update:
        update["enabled"] = 1 if int(update["enabled"]) else 0
    if not update:
        raise HTTPException(400, "Sin campos para actualizar")

    db.update_schedule(int(sched["id"]), **update)
    return {"status": "ok", "schedule_id": int(sched["id"]), "updated": update}


@router.post("/{ident}/toggle")
async def toggle_schedule(
    guild_id: int,
    ident: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    sched = _find_schedule(db, guild_id, ident)
    if not sched:
        raise HTTPException(404, f"Schedule '{ident}' no encontrado")
    new_state = 0 if int(sched.get("enabled") or 0) else 1
    db.update_schedule(int(sched["id"]), enabled=new_state)
    return {"status": "ok", "schedule_id": int(sched["id"]), "enabled": new_state}


@router.post("/{ident}/test")
async def test_schedule(
    guild_id: int,
    ident: str,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Envía el mensaje del schedule una vez ahora, sin tocar last_sent."""
    sched = _find_schedule(db, guild_id, ident)
    if not sched:
        raise HTTPException(404, f"Schedule '{ident}' no encontrado")

    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(503, "Bot no disponible")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(404, "Servidor no encontrado")
    channel = guild.get_channel(int(sched["channel_id"]))
    if not channel or not isinstance(channel, discord.TextChannel):
        raise HTTPException(404, "Canal de texto no encontrado")
    try:
        await channel.send(sched["content"])
    except discord.Forbidden:
        raise HTTPException(403, "Sin permisos para enviar en ese canal")
    except discord.HTTPException as e:
        raise HTTPException(500, f"Error enviando mensaje: {e}")
    return {"status": "ok", "schedule_id": int(sched["id"])}


@router.delete("/{ident}")
async def delete_schedule(
    guild_id: int,
    ident: str,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    sched = _find_schedule(db, guild_id, ident)
    if not sched:
        raise HTTPException(404, f"Schedule '{ident}' no encontrado")
    db.delete_schedule(guild_id, sched["name"])
    return {"status": "deleted", "name": sched["name"]}
