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
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from api.snowflakes import coerce_snowflake, serialize_snowflake

router = APIRouter(prefix="/api/guilds/{guild_id}/giveaways", tags=["giveaways"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class GiveawayCreate(BaseModel):
    channel_id:     int | str
    prize:          str = Field(min_length=1, max_length=240)
    duration_hours: float = Field(1.0, ge=0.01, le=8760, allow_inf_nan=False)
    winners_count:  int   = Field(1, ge=1, le=50)
    req_roles:      List[int | str] = Field(default_factory=list)
    deny_roles:     List[int | str] = Field(default_factory=list)


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
        out["req_roles"] = [serialize_snowflake(x) for x in json.loads(out.get("req_roles") or "[]")]
    except Exception:
        out["req_roles"] = []
    try:
        out["deny_roles"] = [serialize_snowflake(x) for x in json.loads(out.get("deny_roles") or "[]")]
    except Exception:
        out["deny_roles"] = []
    try:
        out["winners"] = [serialize_snowflake(x) for x in json.loads(out.get("winners") or "[]")]
    except Exception:
        out["winners"] = []
    for key in ("guild_id", "channel_id", "message_id"):
        if key in out:
            out[key] = serialize_snowflake(out.get(key))

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
    return {"guild_id": serialize_snowflake(guild_id), "giveaways": enriched, "count": len(enriched)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_giveaway(
    guild_id: int,
    body: GiveawayCreate,
    request: Request,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Crea y publica un nuevo sorteo en el canal indicado."""
    body.prize = body.prize.strip()
    if not body.prize:
        raise HTTPException(400, "El premio no puede quedar en blanco")
    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(503, "Bot no disponible")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(404, "Servidor no encontrado")

    channel_id = coerce_snowflake(body.channel_id, "channel_id")
    req_roles = [coerce_snowflake(role_id, "req_roles") for role_id in body.req_roles]
    deny_roles = [coerce_snowflake(role_id, "deny_roles") for role_id in body.deny_roles]
    channel = guild.get_channel(channel_id)
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
    if req_roles:
        mentions = " · ".join(f"<@&{r}>" for r in req_roles)
        desc_lines.append(f"Requeridos: {mentions}")
    if deny_roles:
        mentions = " · ".join(f"<@&{r}>" for r in deny_roles)
        desc_lines.append(f"Denegados: {mentions}")

    embed = discord.Embed(
        title=f"🎁 Sorteo: {body.prize}",
        description="\n".join(desc_lines),
        color=0x7c3aed,
        timestamp=end_dt,
    )
    embed.set_footer(text=f"Termina · {body.winners_count} ganador(es)")

    async def publish_giveaway():
        from cogs.giveaways import GiveawayJoinView
        cog = bot.get_cog("Giveaways")
        view = GiveawayJoinView(cog) if cog else None
        return await channel.send(embed=embed, view=view)

    try:
        msg = await run_on_bot_loop(bot, publish_giveaway, timeout=30)
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    except discord.Forbidden:
        raise HTTPException(403, "El bot no tiene permisos en ese canal")
    except discord.HTTPException as e:
        raise HTTPException(500, f"Error publicando sorteo: {e}")

    db.create_giveaway(
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=msg.id,
        prize=body.prize,
        end_time=end_ts,
        winners_count=body.winners_count,
        req_roles=json.dumps(req_roles),
        deny_roles=json.dumps(deny_roles),
    )

    return {
        "status": "created",
        "message_id": serialize_snowflake(msg.id),
        "channel_id": serialize_snowflake(channel_id),
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
    return {"guild_id": serialize_snowflake(guild_id), "giveaway": _enrich(gw)}


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

    if not db.cancel_active_giveaway(message_id):
        raise HTTPException(409, "El sorteo ya está finalizando, terminado o cancelado")

    bot = getattr(request.app.state, "bot", None)
    if bot:
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(int(gw.get("channel_id", 0)))
            if channel:
                async def update_cancelled_message() -> None:
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

                try:
                    await run_on_bot_loop(bot, update_cancelled_message, timeout=30)
                except (DiscordBridgeUnavailable, DiscordBridgeTimeout) as exc:
                    raise HTTPException(503 if isinstance(exc, DiscordBridgeUnavailable) else 504, str(exc))
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException) as exc:
                    raise HTTPException(502, f"El sorteo se canceló, pero no se pudo actualizar el mensaje: {exc}")

    return {"status": "cancelled", "message_id": serialize_snowflake(message_id)}


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

    try:
        winners_ids = await run_on_bot_loop(
            bot,
            lambda: cog.reroll_giveaway(gw),
            timeout=30,
        )
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except discord.HTTPException as exc:
        raise HTTPException(502, f"No se pudieron anunciar los nuevos ganadores: {exc}")
    if not winners_ids:
        raise HTTPException(400, "No hubo participantes para reroll")

    return {"status": "ok", "message_id": serialize_snowflake(message_id), "winners": [serialize_snowflake(x) for x in winners_ids]}
