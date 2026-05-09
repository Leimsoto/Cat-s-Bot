"""
api/routes/giveaways.py
───────────────────────
Endpoints de sorteos.

GET    /api/guilds/{id}/giveaways                    → listar sorteos
POST   /api/guilds/{id}/giveaways                    → crear y publicar sorteo
GET    /api/guilds/{id}/giveaways/{msg_id}           → detalle
DELETE /api/guilds/{id}/giveaways/{msg_id}           → cancelar
POST   /api/guilds/{id}/giveaways/{msg_id}/reroll    → reroll ganadores
"""

import json
import time
from datetime import datetime, timezone
from typing import List, Optional

import discord
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/giveaways", tags=["giveaways"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class GiveawayCreate(BaseModel):
    channel_id:     int
    prize:          str
    duration_hours: float = 1.0
    winners_count:  int   = Field(1, ge=1, le=50)
    req_roles:      List[int] = Field(default_factory=list)
    deny_roles:     List[int] = Field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _enrich(gw: dict) -> dict:
    """Calcula campos derivados (status, entries) y normaliza JSON cols."""
    out = dict(gw)
    try:
        parts = json.loads(out.get("participants") or "[]")
    except Exception:
        parts = []
    out["entries"] = len(parts)

    try:
        out["req_roles"] = json.loads(out.get("req_roles") or "[]")
    except Exception:
        out["req_roles"] = []
    try:
        out["deny_roles"] = json.loads(out.get("deny_roles") or "[]")
    except Exception:
        out["deny_roles"] = []
    try:
        out["winners"] = json.loads(out.get("winners") or "[]")
    except Exception:
        out["winners"] = []

    if int(out.get("cancelled") or 0):
        out["status"] = "cancelled"
    elif int(out.get("ended") or 0):
        out["status"] = "ended"
    else:
        out["status"] = "active"
    return out


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_giveaways(
    guild_id: int,
    active_only: bool = Query(False),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista sorteos del servidor con campos derivados (status, entries)."""
    rows = db.get_guild_giveaways(guild_id, active_only=active_only)
    enriched = [_enrich(r) for r in rows]
    return {"guild_id": guild_id, "giveaways": enriched, "count": len(enriched)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_giveaway(
    guild_id: int,
    body: GiveawayCreate,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crea y publica un nuevo sorteo en el canal indicado."""
    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(503, "Bot no disponible")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(404, "Servidor no encontrado")

    channel = guild.get_channel(body.channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        raise HTTPException(404, "Canal de texto no encontrado")

    if body.duration_hours <= 0:
        raise HTTPException(400, "duration_hours debe ser mayor que 0")

    end_ts = int(time.time() + body.duration_hours * 3600)
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    desc_lines = [
        "¡Pulsa el botón 🎉 para participar!",
        f"Ganadores: **{body.winners_count}**",
        f"Finaliza: <t:{end_ts}:R> (<t:{end_ts}:f>)",
    ]
    if body.req_roles:
        mentions = " · ".join(f"<@&{r}>" for r in body.req_roles)
        desc_lines.append(f"Requeridos: {mentions}")
    if body.deny_roles:
        mentions = " · ".join(f"<@&{r}>" for r in body.deny_roles)
        desc_lines.append(f"Denegados: {mentions}")

    embed = discord.Embed(
        title=f"🎁 Sorteo: {body.prize}",
        description="\n".join(desc_lines),
        color=0x7c3aed,
        timestamp=end_dt,
    )
    embed.set_footer(text=f"Termina · {body.winners_count} ganador(es)")

    try:
        from cogs.giveaways import GiveawayJoinView
        cog = bot.get_cog("Giveaways")
        view = GiveawayJoinView(cog) if cog else None
        msg = await channel.send(embed=embed, view=view)
    except discord.Forbidden:
        raise HTTPException(403, "El bot no tiene permisos en ese canal")
    except discord.HTTPException as e:
        raise HTTPException(500, f"Error publicando sorteo: {e}")

    db.create_giveaway(
        guild_id=guild_id,
        channel_id=body.channel_id,
        message_id=msg.id,
        prize=body.prize,
        end_time=end_ts,
        winners_count=body.winners_count,
        req_roles=json.dumps(body.req_roles),
        deny_roles=json.dumps(body.deny_roles),
    )

    return {
        "status": "created",
        "message_id": msg.id,
        "channel_id": body.channel_id,
        "ends_at": end_ts,
        "prize": body.prize,
    }


@router.get("/{message_id}")
async def get_giveaway(
    guild_id: int,
    message_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Detalle de un sorteo por message_id."""
    gw = db.get_giveaway(message_id)
    if not gw or int(gw.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, "Sorteo no encontrado en este servidor")
    return {"guild_id": guild_id, "giveaway": _enrich(gw)}


@router.delete("/{message_id}", status_code=status.HTTP_200_OK)
async def cancel_giveaway(
    guild_id: int,
    message_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Cancela un sorteo activo y edita el mensaje en Discord."""
    gw = db.get_giveaway(message_id)
    if not gw or int(gw.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, "Sorteo no encontrado")

    if gw.get("ended") or gw.get("cancelled"):
        raise HTTPException(400, "El sorteo ya ha terminado")

    db.update_giveaway(message_id, ended=1, cancelled=1)

    bot = getattr(request.app.state, "bot", None)
    if bot:
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(int(gw.get("channel_id", 0)))
            if channel:
                try:
                    msg = await channel.fetch_message(message_id)
                    embed = msg.embeds[0] if msg.embeds else discord.Embed()
                    embed.title = f"❌ {gw.get('prize', 'Sorteo')} (Cancelado)"
                    embed.color = 0x6b7280
                    if embed.description:
                        embed.description += "\n\n🚫 **Cancelado por un administrador.**"
                    else:
                        embed.description = "🚫 **Cancelado por un administrador.**"
                    from cogs.giveaways import GiveawayJoinView
                    cog = bot.get_cog("Giveaways")
                    view = GiveawayJoinView(cog) if cog else None
                    if view:
                        view.children[0].disabled = True
                    await msg.edit(embed=embed, view=view)
                except Exception:
                    pass

    return {"status": "cancelled", "message_id": message_id}


@router.post("/{message_id}/reroll", status_code=status.HTTP_200_OK)
async def reroll_giveaway(
    guild_id: int,
    message_id: int,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Re-elige ganadores de un sorteo ya finalizado."""
    gw = db.get_giveaway(message_id)
    if not gw or int(gw.get("guild_id", 0)) != guild_id:
        raise HTTPException(404, "Sorteo no encontrado")
    if not gw.get("ended"):
        raise HTTPException(400, "El sorteo aún está activo")
    if gw.get("cancelled"):
        raise HTTPException(400, "El sorteo fue cancelado")

    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(503, "Bot no disponible")
    cog = bot.get_cog("Giveaways")
    if not cog:
        raise HTTPException(503, "Cog Giveaways no cargado")

    winners_ids = await cog.reroll_giveaway(gw)
    if not winners_ids:
        raise HTTPException(400, "No hubo participantes para reroll")

    return {"status": "ok", "message_id": message_id, "winners": winners_ids}
