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

import json
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.snowflakes import coerce_snowflake, stringify_rows
from cogs._message_payload import render_message_payload

router = APIRouter(prefix="/api/guilds/{guild_id}/schedules", tags=["schedules"])

MAX_SCHEDULES = 10
MIN_INTERVAL = 600
MAX_INTERVAL = 2_592_000


# ── Schemas ──────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name:             str = Field(min_length=1, max_length=50)
    channel_id:       int | str
    content:          str = Field("", max_length=2000)
    interval_seconds: int = Field(MIN_INTERVAL, ge=0, le=MAX_INTERVAL)
    schedule_mode:    Optional[str] = None  # "interval" | "cron"
    cron_hour:        Optional[int] = Field(None, ge=0, le=23)
    cron_minute:      Optional[int] = Field(None, ge=0, le=59)
    # JSON list serializada (e.g. "[0,1,2,3,4]"). 0=lunes…6=domingo.
    cron_weekdays:    Optional[str] = None
    timezone:         Optional[str] = None
    # JSON serializado MessageEditor (override de content cuando está presente).
    message_data:     Optional[str] = None


class SchedulePatch(BaseModel):
    channel_id:       Optional[int | str] = None
    content:          Optional[str] = Field(None, max_length=2000)
    interval_seconds: Optional[int] = Field(None, ge=0, le=MAX_INTERVAL)
    enabled:          Optional[int] = None
    schedule_mode:    Optional[str] = None
    cron_hour:        Optional[int] = Field(None, ge=0, le=23)
    cron_minute:      Optional[int] = Field(None, ge=0, le=59)
    cron_weekdays:    Optional[str] = None
    timezone:         Optional[str] = None
    message_data:     Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_schedule(db, guild_id: int, ident) -> Optional[dict]:
    """Resuelve schedule por id numérico o por nombre. Filtra por guild."""
    schedules = db.get_schedules(guild_id)
    try:
        sid = int(ident)
        match = next((s for s in schedules if int(s["id"]) == sid), None)
        if match is not None:
            return match
    except (ValueError, TypeError):
        pass
    return next((s for s in schedules if s["name"] == str(ident)), None)


def _validate_schedule(settings: dict) -> None:
    mode = settings.get("schedule_mode") or "interval"
    if mode not in {"interval", "cron"}:
        raise HTTPException(400, "schedule_mode debe ser 'interval' o 'cron'")
    if mode == "interval" and not MIN_INTERVAL <= int(settings.get("interval_seconds") or 0) <= MAX_INTERVAL:
        raise HTTPException(400, "El intervalo debe estar entre 10 minutos y 30 días")
    if mode == "cron":
        hour, minute = settings.get("cron_hour"), settings.get("cron_minute")
        if hour is None or minute is None or not 0 <= int(hour) <= 23 or not 0 <= int(minute) <= 59:
            raise HTTPException(400, "Indica una hora y un minuto válidos para el modo cron")
        try:
            ZoneInfo(settings.get("timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise HTTPException(400, "Zona horaria inválida")
        try:
            weekdays = json.loads(settings.get("cron_weekdays") or "[]")
        except (ValueError, TypeError):
            raise HTTPException(400, "cron_weekdays debe ser una lista de días entre 0 y 6")
        if not isinstance(weekdays, list) or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays):
            raise HTTPException(400, "cron_weekdays debe ser una lista de días entre 0 y 6")
    if settings.get("message_data"):
        try:
            payload = render_message_payload(settings["message_data"])
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "El formato del mensaje programado es inválido")
        if not payload["content"] and payload["embed"] is None:
            raise HTTPException(400, "El mensaje programado no puede estar vacío")
    elif not (settings.get("content") or "").strip():
        raise HTTPException(400, "El mensaje programado no puede estar vacío")


def _schedule_payload(row: dict) -> dict:
    return stringify_rows([row], ("guild_id", "channel_id", "created_by"))[0]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_schedules(
    guild_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    schedules = db.get_schedules(guild_id)
    return {
        "guild_id": str(guild_id),
        "schedules": [_schedule_payload(row) for row in schedules],
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
    content = (body.content or "").strip()
    if not name:
        raise HTTPException(400, "name es requerido")
    if not content and not body.message_data:
        raise HTTPException(400, "Debes proporcionar content o message_data")

    mode = (body.schedule_mode or "interval").lower()
    if mode not in ("interval", "cron"):
        raise HTTPException(400, "schedule_mode debe ser 'interval' o 'cron'")
    if mode == "interval" and (body.interval_seconds or 0) < MIN_INTERVAL:
        raise HTTPException(400, f"Intervalo mínimo {MIN_INTERVAL}s")
    if mode == "cron" and (body.cron_hour is None or body.cron_minute is None):
        raise HTTPException(400, "cron_hour y cron_minute son requeridos en modo cron")
    _validate_schedule({**body.model_dump(), "schedule_mode": mode})

    existing = db.get_schedules(guild_id)
    if len(existing) >= MAX_SCHEDULES:
        raise HTTPException(400, f"Máximo de {MAX_SCHEDULES} schedules alcanzado")
    if any(s["name"] == name for s in existing):
        raise HTTPException(409, f"Ya existe un schedule llamado '{name}'")

    creator_id = int(user.get("user_id", 0)) if isinstance(user, dict) else 0
    channel_id = coerce_snowflake(body.channel_id, "channel_id")
    db.create_schedule(
        guild_id, name, channel_id, content,
        int(body.interval_seconds or 0), creator_id,
        schedule_mode=mode,
        cron_hour=body.cron_hour,
        cron_minute=body.cron_minute,
        cron_weekdays=body.cron_weekdays,
        timezone_name=body.timezone,
        message_data=body.message_data,
    )
    return {"status": "created", "name": name, "channel_id": str(channel_id)}


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
    if "channel_id" in update:
        update["channel_id"] = coerce_snowflake(update["channel_id"], "channel_id")
    if "enabled" in update:
        update["enabled"] = 1 if int(update["enabled"]) else 0
    if not update:
        raise HTTPException(400, "Sin campos para actualizar")
    if "schedule_mode" in update:
        update["schedule_mode"] = update["schedule_mode"].strip().lower()
    _validate_schedule({**sched, **update})

    db.update_schedule(int(sched["id"]), **update)
    updated = dict(update)
    if "channel_id" in updated:
        updated["channel_id"] = str(updated["channel_id"])
    return {"status": "ok", "schedule_id": int(sched["id"]), "updated": updated}


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
    channel = guild.get_channel(coerce_snowflake(sched["channel_id"], "channel_id"))
    if not channel or not isinstance(channel, discord.TextChannel):
        raise HTTPException(404, "Canal de texto no encontrado")

    cog = bot.get_cog("Scheduler")
    async def send_now() -> None:
        if cog and hasattr(cog, "_send_scheduled_message"):
            await cog._send_scheduled_message(channel, sched, guild)
        else:
            await channel.send(sched.get("content") or "(vacío)")

    try:
        await run_on_bot_loop(bot, send_now, timeout=30)
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    except discord.Forbidden:
        raise HTTPException(403, "Sin permisos para enviar en ese canal")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
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
