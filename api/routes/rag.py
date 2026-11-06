"""Endpoints del módulo RAG/Scraper pasivo."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import (
    get_bot,
    get_current_user,
    get_guild_admin_status,
    require_guild_admin,
)
from api.discord_bridge import DiscordBridgeTimeout, DiscordBridgeUnavailable, run_on_bot_loop
from rag import DEFAULT_RAG_CONFIG, RAGWorkspaceManager
from rag.workspace import (
    MAX_ARCHIVED_THREADS_PER_CHANNEL,
    MAX_BACKFILL_INTERVAL_SECONDS,
    MAX_EXCLUDED_CHANNELS,
    MAX_EXPORT_ROWS,
    MAX_HISTORY_BATCH_SIZE,
    MAX_SOURCES_PER_CYCLE,
    MIN_BACKFILL_INTERVAL_SECONDS,
)

router = APIRouter(prefix="/api/guilds/{guild_id}/rag", tags=["rag"])


class RAGConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    backfill_enabled: Optional[bool] = None
    capture_live_messages: Optional[bool] = None
    capture_threads: Optional[bool] = None
    capture_forums: Optional[bool] = None
    capture_archived_threads: Optional[bool] = None
    include_bots: Optional[bool] = None
    history_batch_size: Optional[int] = Field(default=None, ge=1, le=MAX_HISTORY_BATCH_SIZE)
    max_sources_per_cycle: Optional[int] = Field(default=None, ge=1, le=MAX_SOURCES_PER_CYCLE)
    archived_threads_limit_per_channel: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_ARCHIVED_THREADS_PER_CHANNEL,
    )
    backfill_interval_seconds: Optional[int] = Field(
        default=None,
        ge=MIN_BACKFILL_INTERVAL_SECONDS,
        le=MAX_BACKFILL_INTERVAL_SECONDS,
    )
    excluded_channel_ids: Optional[list[str | int]] = Field(
        default=None,
        max_length=MAX_EXCLUDED_CHANNELS,
    )


class RAGBackfillRequest(BaseModel):
    max_sources: Optional[int] = Field(default=None, ge=1, le=MAX_SOURCES_PER_CYCLE)


class RAGExportRequest(BaseModel):
    format: str = "markdown"
    channel_id: Optional[str | int] = None
    include_deleted: bool = False
    limit: Optional[int] = Field(default=None, ge=1, le=MAX_EXPORT_ROWS)
    export_all: bool = False


def _manager(request: Request, bot=None) -> RAGWorkspaceManager:
    if bot is not None and hasattr(bot, "rag_workspace"):
        return bot.rag_workspace
    mgr = getattr(request.app.state, "rag_workspace", None)
    if mgr is None:
        mgr = RAGWorkspaceManager()
        request.app.state.rag_workspace = mgr
    return mgr


def _public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    data = {k: cfg.get(k, v) for k, v in DEFAULT_RAG_CONFIG.items()}
    data["excluded_channel_ids"] = [str(x) for x in data.get("excluded_channel_ids") or []]
    return data


def _canonical_channel_id(value: str | int | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdecimal() or int(text) <= 0 or str(int(text)) != text:
        raise HTTPException(400, "channel_id debe ser un ID numérico positivo de Discord.")
    return text


async def require_rag_corpus_admin(
    guild_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """El corpus histórico solo puede salir por owner/Administrator en vivo."""
    status = await get_guild_admin_status(request, guild_id, user)
    if status.get("is_owner") or status.get("administrator"):
        return user
    raise HTTPException(
        403,
        {
            "message": "El backfill y los exports RAG requieren dueño o Administrador en vivo.",
            "guild_id": str(guild_id),
            "reason": status.get("reason") or "rag_corpus_requires_live_administrator",
        },
    )


@router.get("/status")
async def get_rag_status(
    guild_id: int,
    request: Request,
    bot=Depends(get_bot),
    _user=Depends(require_guild_admin),
):
    mgr = _manager(request, bot)
    mgr.ensure_workspace(guild_id)
    cfg = mgr.load_config(guild_id)
    return {
        "guild_id": str(guild_id),
        "config": _public_config(cfg),
        "stats": mgr.stats(guild_id),
    }


@router.patch("/config")
async def patch_rag_config(
    guild_id: int,
    body: RAGConfigPatch,
    request: Request,
    bot=Depends(get_bot),
    user=Depends(require_guild_admin),
):
    status = await get_guild_admin_status(request, guild_id, user)
    if not (
        status.get("is_owner")
        or status.get("administrator")
        or status.get("manage_guild")
    ):
        raise HTTPException(403, "Tus permisos cambiaron; no se modificó RAG")
    mgr = _manager(request, bot)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "excluded_channel_ids" in updates:
        updates["excluded_channel_ids"] = [str(x) for x in updates["excluded_channel_ids"]]
    cfg = mgr.save_config(guild_id, updates)
    return {
        "status": "ok",
        "guild_id": str(guild_id),
        "config": _public_config(cfg),
        "stats": mgr.stats(guild_id),
    }


@router.post("/backfill")
async def trigger_rag_backfill(
    guild_id: int,
    body: RAGBackfillRequest,
    request: Request,
    bot=Depends(get_bot),
    user=Depends(require_rag_corpus_admin),
):
    if bot is None:
        raise HTTPException(503, "Bot no conectado")
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(404, "Servidor no encontrado en el bot")
    cog = bot.get_cog("RAGScraper") if hasattr(bot, "get_cog") else None
    if cog is None or not hasattr(cog, "run_manual_backfill"):
        raise HTTPException(503, "Cog RAG/Scraper no cargado")
    try:
        actor_id = int(user.get("user_id") or 0)
    except (TypeError, ValueError):
        actor_id = 0
    if not actor_id:
        raise HTTPException(403, "No se pudo verificar la identidad Discord actual")

    try:
        result = await run_on_bot_loop(
            bot,
            lambda: cog.run_manual_backfill(
                guild,
                max_sources=body.max_sources,
                authorize=lambda: cog._authorized_user(
                    guild,
                    actor_id,
                    admin_only=True,
                ),
            ),
            timeout=120,
        )
    except DiscordBridgeUnavailable as exc:
        raise HTTPException(503, str(exc))
    except DiscordBridgeTimeout as exc:
        raise HTTPException(504, str(exc))
    if result.get("skipped") == "unauthorized":
        raise HTTPException(403, "Tus permisos cambiaron; el backfill fue cancelado")
    if result.get("skipped") == "already_running":
        raise HTTPException(409, "Ya hay un backfill manual en curso")
    mgr = _manager(request, bot)
    return {
        "status": "ok",
        "guild_id": str(guild_id),
        "backfill": result,
        "stats": mgr.stats(guild_id),
    }


@router.post("/export")
async def export_rag_messages(
    guild_id: int,
    body: RAGExportRequest,
    request: Request,
    bot=Depends(get_bot),
    user=Depends(require_rag_corpus_admin),
):
    mgr = _manager(request, bot)
    channel_id = _canonical_channel_id(body.channel_id)
    try:
        result = await asyncio.to_thread(
            mgr.export_messages,
            guild_id,
            format=body.format,
            channel_id=channel_id,
            include_deleted=body.include_deleted,
            limit=body.limit,
            export_all=body.export_all,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(429, str(exc))
    status = await get_guild_admin_status(request, guild_id, user)
    if not (status.get("is_owner") or status.get("administrator")):
        raise HTTPException(403, "Tus permisos cambiaron; el export no se entregará")
    return {"status": "ok", "guild_id": str(guild_id), "export": result}
