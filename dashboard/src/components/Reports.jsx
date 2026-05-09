/**
 * components/Reports.jsx
 * ──────────────────────
 * Cola de moderación: reportes de usuarios + historial de mod_actions.
 *
 * Tabs:
 *   • Reportes — pendientes/resueltos/desestimados/todos. Resolver/desestimar/borrar inline.
 *   • Acciones — historial de warns/mutes/kicks/bans desde mod_actions.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/reports?status=PENDING|RESOLVED|DISMISSED
 *   PATCH  /api/guilds/{g}/reports/{id}    {status?, ticket_id?}
 *   DELETE /api/guilds/{g}/reports/{id}
 *   GET    /api/guilds/{g}/reports/mod-actions?limit=&offset=
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPatch, apiDelete } from "../lib/api";
import { Icon } from "../lib/icons";

const STATUS_META = {
  PENDING:   { label: "Pendiente",   color: "#f59e0b", icon: "loading" },
  RESOLVED:  { label: "Resuelto",    color: "#34d399", icon: "success" },
  DISMISSED: { label: "Desestimado", color: "#9ca3af", icon: "close" },
};

const FILTERS = [
  { id: "PENDING",   label: "Pendientes" },
  { id: "RESOLVED",  label: "Resueltos" },
  { id: "DISMISSED", label: "Desestimados" },
  { id: "ALL",       label: "Todos" },
];

const ACTION_COLOR = {
  warn:   "#f59e0b",
  mute:   "#a78bfa",
  unmute: "#9ca3af",
  kick:   "#fb923c",
  ban:    "#ef4444",
  unban:  "#34d399",
};

export default function Reports({ selectedGuild, onToast }) {
  const guildId = selectedGuild;
  const [tab, setTab] = useState("reports");
  const [reports, setReports] = useState([]);
  const [actions, setActions] = useState([]);
  const [filter, setFilter] = useState("PENDING");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const loadReports = useCallback(async () => {
    if (!guildId) return;
    const qs = filter === "ALL" ? "" : `?status=${filter}`;
    const data = await apiGet(`/api/guilds/${guildId}/reports${qs}`, { cache: false }).catch(() => ({ reports: [] }));
    setReports(data?.reports || []);
  }, [guildId, filter]);

  const loadActions = useCallback(async () => {
    if (!guildId) return;
    const data = await apiGet(`/api/guilds/${guildId}/reports/mod-actions?limit=100`, { cache: false }).catch(() => ({ actions: [] }));
    setActions(data?.actions || []);
  }, [guildId]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([loadReports(), loadActions()]);
    } finally {
      setLoading(false);
    }
  }, [loadReports, loadActions]);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { if (!loading) loadReports(); /* eslint-disable-next-line */ }, [filter]);

  const counts = useMemo(() => {
    const c = { PENDING: 0, RESOLVED: 0, DISMISSED: 0, ALL: reports.length };
    for (const r of reports) {
      const s = String(r.status || "").toUpperCase();
      if (c[s] != null) c[s] += 1;
    }
    return c;
  }, [reports]);

  const updateStatus = async (id, status) => {
    setBusyId(id);
    try {
      await apiPatch(`/api/guilds/${guildId}/reports/${id}`, { status });
      toast("success", `Reporte #${id} → ${STATUS_META[status]?.label || status}`);
      await loadReports();
    } catch (e) {
      toast("error", e?.message || "Error actualizando reporte");
    } finally {
      setBusyId(null);
    }
  };

  const deleteReport = async (id) => {
    if (!confirm(`¿Eliminar reporte #${id}? Esto es irreversible.`)) return;
    setBusyId(id);
    try {
      await apiDelete(`/api/guilds/${guildId}/reports/${id}`);
      toast("success", `Reporte #${id} eliminado`);
      await loadReports();
    } catch (e) {
      toast("error", e?.message || "Error eliminando");
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="loader">Cargando reportes…</div>;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header">
        <h2 className="glow-text" style={{ margin: 0 }}>Cola de Moderación</h2>
        <p className="subtitle" style={{ margin: "4px 0 0" }}>
          Reportes de usuarios e historial de acciones de moderación.
        </p>
      </div>

      <div className="tab-bar">
        <button
          className={`tab-btn ${tab === "reports" ? "active" : ""}`}
          onClick={() => setTab("reports")}
        >
          <Icon name="reports" /> Reportes
        </button>
        <button
          className={`tab-btn ${tab === "actions" ? "active" : ""}`}
          onClick={() => setTab("actions")}
        >
          <Icon name="moderation" /> Acciones moderativas
        </button>
      </div>

      {tab === "reports" && (
        <>
          <div className="tab-bar" style={{ marginBottom: 16 }}>
            {FILTERS.map((f) => (
              <button
                key={f.id}
                className={`tab-btn ${filter === f.id ? "active" : ""}`}
                onClick={() => setFilter(f.id)}
              >
                {f.label}
                <span style={{ marginLeft: 6, opacity: 0.7, fontSize: "0.78rem" }}>
                  ({counts[f.id] || 0})
                </span>
              </button>
            ))}
          </div>

          {reports.length === 0 ? (
            <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
              <Icon name="reports" />
              <h3 style={{ margin: "12px 0 8px" }}>Sin reportes</h3>
              <p className="subtitle" style={{ margin: 0 }}>
                No hay reportes con el filtro seleccionado.
              </p>
            </div>
          ) : (
            <div className="glass-panel" style={{ overflow: "hidden" }}>
              <div className="ops-table">
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      {["ID", "Reportado", "Reportador", "Razón", "Estado", "Fecha", "Acciones"].map((h) => (
                        <th key={h} style={{ padding: "14px 18px", textAlign: "left", color: "var(--muted)", fontWeight: 600, fontSize: "0.82rem" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map((r) => {
                      const statusUpper = String(r.status || "").toUpperCase();
                      const meta = STATUS_META[statusUpper] || { label: r.status, color: "#9ca3af" };
                      const isPending = statusUpper === "PENDING";
                      return (
                        <tr key={r.id} className="ops-list-row">
                          <td style={{ padding: "12px 18px", color: "var(--accent)", fontWeight: 700 }}>#{r.id}</td>
                          <td style={{ padding: "12px 18px", fontFamily: "monospace", fontSize: "0.82rem" }}>
                            {r.reported_user_id || r.reported_id}
                          </td>
                          <td style={{ padding: "12px 18px", color: "var(--muted)", fontSize: "0.82rem" }}>
                            {r.reporter_id}
                          </td>
                          <td style={{ padding: "12px 18px", color: "var(--muted)", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                              title={r.reason}>
                            {r.reason || "—"}
                          </td>
                          <td style={{ padding: "12px 18px" }}>
                            <span
                              style={{
                                background: `${meta.color}22`,
                                color: meta.color,
                                padding: "3px 10px",
                                borderRadius: 999,
                                fontSize: "0.72rem",
                                fontWeight: 700,
                              }}
                            >
                              {meta.label}
                            </span>
                          </td>
                          <td style={{ padding: "12px 18px", color: "var(--dim)", fontSize: "0.78rem" }}>
                            {r.created_at ? new Date(r.created_at).toLocaleString("es") : "—"}
                          </td>
                          <td style={{ padding: "12px 18px" }}>
                            <div style={{ display: "flex", gap: 6 }}>
                              {isPending && (
                                <>
                                  <button
                                    className="btn-icon"
                                    title="Resolver"
                                    disabled={busyId === r.id}
                                    onClick={() => updateStatus(r.id, "RESOLVED")}
                                    style={{ color: "#34d399" }}
                                  >
                                    <Icon name="success" />
                                  </button>
                                  <button
                                    className="btn-icon"
                                    title="Desestimar"
                                    disabled={busyId === r.id}
                                    onClick={() => updateStatus(r.id, "DISMISSED")}
                                    style={{ color: "#9ca3af" }}
                                  >
                                    <Icon name="close" />
                                  </button>
                                </>
                              )}
                              <button
                                className="btn-icon"
                                title="Eliminar"
                                disabled={busyId === r.id}
                                onClick={() => deleteReport(r.id)}
                                style={{ color: "#ef4444" }}
                              >
                                <Icon name="delete" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {tab === "actions" && (
        <div className="glass-panel" style={{ overflow: "hidden" }}>
          <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "1rem" }}>
              <Icon name="moderation" /> Historial de moderación ({actions.length})
            </h3>
            <button className="btn-icon" onClick={loadActions} title="Recargar">
              <Icon name="refresh" />
            </button>
          </div>
          {actions.length === 0 ? (
            <div className="no-results"><p>Sin acciones de moderación registradas.</p></div>
          ) : (
            <div className="ops-table">
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    {["Tipo", "Objetivo", "Moderador", "Razón", "Fecha"].map((h) => (
                      <th key={h} style={{ padding: "14px 18px", textAlign: "left", color: "var(--muted)", fontWeight: 600, fontSize: "0.82rem" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {actions.map((a) => {
                    const t = String(a.action_type || "").toLowerCase();
                    const color = ACTION_COLOR[t] || "#a78bfa";
                    return (
                      <tr key={a.id} className="ops-list-row">
                        <td style={{ padding: "12px 18px" }}>
                          <span
                            style={{
                              background: `${color}22`,
                              color: color,
                              padding: "3px 10px",
                              borderRadius: 999,
                              fontSize: "0.72rem",
                              fontWeight: 700,
                              textTransform: "uppercase",
                            }}
                          >
                            {a.action_type}
                          </span>
                        </td>
                        <td style={{ padding: "12px 18px", fontFamily: "monospace", fontSize: "0.82rem" }}>{a.target_id}</td>
                        <td style={{ padding: "12px 18px", fontFamily: "monospace", fontSize: "0.82rem", color: "var(--muted)" }}>{a.moderator_id}</td>
                        <td style={{ padding: "12px 18px", color: "var(--muted)", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={a.reason}>
                          {a.reason || "—"}
                        </td>
                        <td style={{ padding: "12px 18px", color: "var(--dim)", fontSize: "0.78rem" }}>
                          {a.created_at ? new Date(a.created_at).toLocaleString("es") : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
