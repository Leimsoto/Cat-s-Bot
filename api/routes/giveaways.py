"""
api/routes/giveaways.py
───────────────────────
Endpoints de sorteos.

GET    /api/guilds/{id}/giveaways            → listar sorteos
POST   /api/guilds/{id}/giveaways            → crear y publicar sorteo en Discord
GET    /api/guilds/{id}/giveaways/{msg_id}   → detalle de sorteo
DELETE /api/guilds/{id}/giveaways/{msg_id}   → cancelar sorteo
"""

import asyncio
import time
from datetime import datetime, timezone

import discord
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from typing import Optional

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/giveaways", tags=["giveaways"])


class GiveawayCreate(BaseModel):
    channel_id:    int
    prize:         str
    duration_hours: float = 1.0
    winners_count: int    = 1
    req_roles:     str    = "[]"
    deny_roles:    str    = "[]"


@router.get("")
async def list_giveaways(
    guild_id: int,
    active_only: bool = Query(True),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista sorteos del servidor."""
    giveaways = db.get_guild_giveaways(guild_id, active_only=active_only)
    return {"guild_id": guild_id, "giveaways": giveaways, "count": len(giveaways)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_giveaway(
    guild_id: int,
    body: GiveawayCreate,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crea y publica un nuevo sorteo en el canal indicado de Discord."""
    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(503, "Bot no disponible")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(404, "Servidor no encontrado")

    channel = guild.get_channel(body.channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        raise HTTPException(404, "Canal de texto no encontrado")

    end_ts = int(time.time() + body.duration_hours * 3600)
    end_dt  = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    # Construir embed del sorteo
    embed = discord.Embed(
        title=f"🎉 {body.prize}",
        description=(
            f"Reacciona con 🎉 para participar.\n\n"
            f"**Ganadores:** {body.winners_count}\n"
            f"**Termina:** <t:{end_ts}:R> (<t:{end_ts}:f>)"
        ),
        color=0x7c3aed,
        timestamp=end_dt,
    )
    embed.set_footer(text=f"Termina • {body.winners_count} ganador(es)")

    try:
        msg = await channel.send(embed=embed)
        await msg.add_reaction("🎉")
    except discord.Forbidden:
        raise HTTPException(403, "El bot no tiene permisos en ese canal")
    except discord.HTTPException as e:
        raise HTTPException(500, f"Error publicando sorteo: {e}")

    # Guardar en BD
    db.create_giveaway(
        guild_id=guild_id,
        channel_id=body.channel_id,
        message_id=msg.id,
        prize=body.prize,
        end_time=end_ts,
        winners_count=body.winners_count,
        req_roles=body.req_roles,
        deny_roles=body.deny_roles,
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
    return {"guild_id": guild_id, "giveaway": gw}


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

    if gw.get("ended"):
        raise HTTPException(400, "El sorteo ya ha terminado")

    # Marcar como terminado en BD
    db.update_giveaway(message_id, ended=1)

    # Editar el mensaje en Discord si el bot está disponible
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
                    await msg.edit(embed=embed)
                except Exception:
                    pass

    return {"status": "cancelled", "message_id": message_id}
