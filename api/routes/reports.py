"""
api/routes/reports.py
─────────────────────
Endpoints del sistema de reportes y moderación histórica.

GET   /api/guilds/{guild_id}/reports                  → lista (filtro estado)
GET   /api/guilds/{guild_id}/reports/{id}             → detalle
PATCH /api/guilds/{guild_id}/reports/{id}             → actualizar estado/ticket
DELETE /api/guilds/{guild_id}/reports/{id}            → borrar reporte (admin)

GET   /api/guilds/{guild_id}/reports/mod-actions      → historial de acciones moderativas
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.deps import get_db, require_guild_admin

router = APIRouter(prefix="/api/guilds/{guild_id}/reports", tags=["reports"])


VALID_STATUSES = {"PENDING", "RESOLVED", "DISMISSED"}


class ReportPatch(BaseModel):
    status: Optional[str] = None
    ticket_id: Optional[int] = None


def _enrich(report: dict) -> dict:
    """Normaliza fechas y aliases para el frontend."""
    out = dict(report)
    rid = out.get("reported_user_id")
    if rid is not None:
        out.setdefault("reported_id", rid)
    return out


@router.get("/mod-actions")
async def list_mod_actions(
    guild_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Historial reciente de acciones de moderación (warn/mute/kick/ban/unban)."""
    rows = db.get_mod_actions(guild_id, limit=limit, offset=offset)
    return {"guild_id": guild_id, "actions": rows, "count": len(rows)}


@router.get("")
async def list_reports(
    guild_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Lista reportes del servidor con filtro opcional por estado."""
    if status_filter and status_filter.upper() == "ALL":
        status_filter = None
    if status_filter:
        status_filter = status_filter.upper()
        if status_filter not in VALID_STATUSES:
            raise HTTPException(400, f"status inválido. Permitidos: {sorted(VALID_STATUSES)}")
    rows = db.get_reports(guild_id, status=status_filter)
    return {
        "guild_id": guild_id,
        "reports": [_enrich(r) for r in rows],
        "count": len(rows),
    }


@router.get("/{report_id}")
async def get_report(
    guild_id: int,
    report_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Detalle de un reporte específico."""
    report = db.get_report(report_id)
    if not report or int(report["guild_id"]) != guild_id:
        raise HTTPException(404, f"Reporte #{report_id} no encontrado en este servidor")
    return {"guild_id": guild_id, "report": _enrich(report)}


@router.patch("/{report_id}")
async def patch_report(
    guild_id: int,
    report_id: int,
    body: ReportPatch,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Actualiza el estado de un reporte y/o asocia ticket."""
    report = db.get_report(report_id)
    if not report or int(report["guild_id"]) != guild_id:
        raise HTTPException(404, f"Reporte #{report_id} no encontrado en este servidor")

    update = {}
    if body.status is not None:
        st = body.status.upper()
        if st not in VALID_STATUSES:
            raise HTTPException(400, f"status inválido. Permitidos: {sorted(VALID_STATUSES)}")
        update["status"] = st
    if body.ticket_id is not None:
        update["ticket_id"] = body.ticket_id

    if not update:
        raise HTTPException(400, "Sin campos para actualizar")

    db.update_report(report_id, **update)
    return {"status": "ok", "report_id": report_id, "updated": update}


@router.delete("/{report_id}", status_code=status.HTTP_200_OK)
async def delete_report(
    guild_id: int,
    report_id: int,
    db=Depends(get_db),
    _user=Depends(require_guild_admin),
):
    """Elimina un reporte (irreversible)."""
    report = db.get_report(report_id)
    if not report or int(report["guild_id"]) != guild_id:
        raise HTTPException(404, f"Reporte #{report_id} no encontrado")
    db._execute("DELETE FROM reports WHERE id = ?", (report_id,))
    return {"status": "ok", "report_id": report_id}
