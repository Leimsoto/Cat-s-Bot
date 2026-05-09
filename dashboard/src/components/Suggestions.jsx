/**
 * components/Suggestions.jsx
 * ──────────────────────────
 * Sistema de sugerencias con review opcional + límites + cooldown.
 *
 * Tabs:
 *   • Configuración — canales, toggles, límites
 *   • Sugerencias   — lista filtrable con acciones inline
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/suggestions
 *   PATCH  /api/guilds/{g}/suggestions
 *   GET    /api/guilds/{g}/suggestions/list?status=
 *   PATCH  /api/guilds/{g}/suggestions/list/{id}
 *   DELETE /api/guilds/{g}/suggestions/list/{id}
 */

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiDelete } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";

const STATUS_LABEL = { PENDING: "Pendiente", ACCEPTED: "Aprobada", DENIED: "Denegada" };
const STATUS_COLOR = { PENDING: "#f59e0b", ACCEPTED: "#10b981", DENIED: "#f43f5e" };

const STATUS_FILTERS = [
  { id: "all",      label: "Todas" },
  { id: "PENDING",  label: "Pendientes" },
  { id: "ACCEPTED", label: "Aprobadas" },
  { id: "DENIED",   label: "Denegadas" },
];

export default function Suggestions({ selectedGuild: guildId, onToast }) {
  const [tab, setTab] = useState("config");
  const [cfg, setCfg] = useState(null);
  const [stats, setStats] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingSugg, setLoadingSugg] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState("PENDING");
  const [busyId, setBusyId] = useState(null);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/suggestions`);
      setCfg(data?.config || {});
      setStats(data?.stats || {});
    } catch (e) {
      toast("error", e?.message || "Error cargando sugerencias");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line
  }, [guildId]);

  const loadSuggestions = useCallback(async (status) => {
    if (!guildId) return;
    setLoadingSugg(true);
    try {
      const url = status && status !== "all"
        ? `/api/guilds/${guildId}/suggestions/list?status=${status}`
        : `/api/guilds/${guildId}/suggestions/list`;
      const data = await apiGet(url, { cache: false });
      setSuggestions(data?.suggestions || []);
    } catch {
      setSuggestions([]);
    } finally {
      setLoadingSugg(false);
    }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === "list") loadSuggestions(statusFilter); }, [tab, statusFilter, loadSuggestions]);

  const set = (k, v) => {
    setCfg((p) => ({ ...p, [k]: v }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        submit_channel_id: cfg.submit_channel_id ? Number(cfg.submit_channel_id) : null,
        review_channel_id: cfg.review_channel_id ? Number(cfg.review_channel_id) : null,
        public_channel_id: cfg.public_channel_id ? Number(cfg.public_channel_id) : null,
        enabled: Number(cfg.enabled || 0),
        auto_publish: Number(cfg.auto_publish || 0),
        min_length: Number(cfg.min_length || 10),
        max_length: Number(cfg.max_length || 2000),
        cooldown_seconds: Number(cfg.cooldown_seconds || 0),
      };
      // remover null para no sobreescribir con NULL involuntariamente
      Object.keys(payload).forEach((k) => payload[k] == null && delete payload[k]);
      await apiPatch(`/api/guilds/${guildId}/suggestions`, payload);
      setDirty(false);
      toast("success", "Configuración guardada");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error guardando");
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (id, status) => {
    setBusyId(id);
    try {
      await apiPatch(`/api/guilds/${guildId}/suggestions/list/${id}`, { status });
      toast("success", `#${id} → ${STATUS_LABEL[status] || status}`);
      await Promise.all([loadSuggestions(statusFilter), load()]);
    } catch (e) {
      toast("error", e?.message || "Error actualizando");
    } finally {
      setBusyId(null);
    }
  };

  const denyWithReason = async (id) => {
    const reason = prompt("Razón de denegación (opcional):", "");
    if (reason == null) return;
    setBusyId(id);
    try {
      await apiPatch(`/api/guilds/${guildId}/suggestions/list/${id}`, {
        status: "DENIED",
        denial_reason: reason.trim() || null,
      });
      toast("success", `#${id} → Denegada`);
      await Promise.all([loadSuggestions(statusFilter), load()]);
    } catch (e) {
      toast("error", e?.message || "Error denegando");
    } finally {
      setBusyId(null);
    }
  };

  const deleteSugg = async (id) => {
    if (!confirm(`¿Eliminar sugerencia #${id}? Irreversible.`)) return;
    setBusyId(id);
    try {
      await apiDelete(`/api/guilds/${guildId}/suggestions/list/${id}`);
      toast("success", `#${id} eliminada`);
      await Promise.all([loadSuggestions(statusFilter), load()]);
    } catch (e) {
      toast("error", e?.message || "Error eliminando");
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="loader">Cargando sugerencias…</div>;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 className="glow-text" style={{ margin: 0 }}>Sistema de Sugerencias</h2>
            <p className="subtitle" style={{ margin: "4px 0 0" }}>
              {stats?.total || 0} totales · {stats?.pending || 0} pendientes
            </p>
          </div>
          {stats && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {["PENDING", "ACCEPTED", "DENIED"].map((s) => {
                const color = STATUS_COLOR[s];
                return (
                  <span
                    key={s}
                    style={{
                      padding: "5px 12px", borderRadius: 999,
                      fontSize: "0.75rem", fontWeight: 700,
                      background: `${color}18`, color, border: `1px solid ${color}33`,
                    }}
                  >
                    {stats[s.toLowerCase()] || 0} {STATUS_LABEL[s]}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="tab-bar">
        <button
          className={`tab-btn ${tab === "config" ? "active" : ""}`}
          onClick={() => setTab("config")}
        >
          <Icon name="settings" /> Configuración
        </button>
        <button
          className={`tab-btn ${tab === "list" ? "active" : ""}`}
          onClick={() => setTab("list")}
        >
          <Icon name="suggestions" /> Sugerencias
        </button>
      </div>

      {tab === "config" && cfg && (
        <>
          <div className="glass-panel mod-section" style={{ padding: 24, marginBottom: 16 }}>
            <div className="config-item inline-check">
              <div>
                <div style={{ fontWeight: 800 }}>Sistema de sugerencias</div>
                <div className="hint">Activa o desactiva todo el módulo</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!Number(cfg.enabled)}
                  onChange={(e) => set("enabled", e.target.checked ? 1 : 0)}
                />
                <span className="slider" />
              </label>
            </div>

            <div className="config-item inline-check" style={{ marginTop: 16 }}>
              <div>
                <div style={{ fontWeight: 800 }}>Auto-publicar</div>
                <div className="hint">
                  Si está activo, las sugerencias se publican directamente en el canal público
                  saltando la revisión del staff.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!Number(cfg.auto_publish)}
                  onChange={(e) => set("auto_publish", e.target.checked ? 1 : 0)}
                />
                <span className="slider" />
              </label>
            </div>
          </div>

          <div className="glass-panel mod-section" style={{ padding: 24, marginBottom: 16 }}>
            <div className="section-title">
              <Icon name="channel" /> <h3>Canales</h3>
            </div>
            <div className="form-grid">
              {[
                ["submit_channel_id", "Canal de envío", "Donde los usuarios escriben sus sugerencias"],
                ["review_channel_id", "Canal de revisión", "Staff aprueba/deniega aquí (ignorado si auto-publicar está activo)"],
                ["public_channel_id", "Canal público", "Donde se muestran las sugerencias aprobadas con votos"],
              ].map(([key, label, desc]) => (
                <div key={key} className="form-field">
                  <label>{label}</label>
                  <SearchableSelect
                    value={cfg[key] || null}
                    onChange={(v) => set(key, v ? Number(v) : null)}
                    endpoint={`/api/guilds/${guildId}/channels?type=text`}
                    itemsKey="channels"
                    placeholder="Seleccionar canal…"
                    renderOption={(o) => <span>#{o.name}</span>}
                    renderSelected={(o) => <span>#{o.name}</span>}
                  />
                  <span className="hint">{desc}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-panel mod-section" style={{ padding: 24, marginBottom: 16 }}>
            <div className="section-title">
              <Icon name="filter" /> <h3>Límites y cooldown</h3>
            </div>
            <div className="form-grid">
              <div className="form-field">
                <label>Longitud mínima</label>
                <input
                  type="number" min="1" max="4000"
                  value={cfg.min_length ?? 10}
                  onChange={(e) => set("min_length", Number(e.target.value))}
                />
                <span className="hint">Caracteres mínimos por sugerencia</span>
              </div>
              <div className="form-field">
                <label>Longitud máxima</label>
                <input
                  type="number" min="10" max="4000"
                  value={cfg.max_length ?? 2000}
                  onChange={(e) => set("max_length", Number(e.target.value))}
                />
                <span className="hint">Caracteres máximos por sugerencia</span>
              </div>
              <div className="form-field">
                <label>Cooldown (segundos)</label>
                <input
                  type="number" min="0" max="86400"
                  value={cfg.cooldown_seconds ?? 300}
                  onChange={(e) => set("cooldown_seconds", Number(e.target.value))}
                />
                <span className="hint">Tiempo mínimo entre sugerencias del mismo usuario (0 = sin cooldown)</span>
              </div>
            </div>
          </div>

          <div className={`save-bar-container ${dirty ? "visible" : ""}`}>
            <div className="save-bar">
              <span style={{ color: "var(--muted)", fontSize: "0.88rem" }}>Cambios sin guardar</span>
              <div className="save-bar-actions">
                <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
                <button className="btn-primary btn-save" onClick={save} disabled={saving}>
                  {saving ? "Guardando…" : <><Icon name="save" /> Guardar</>}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {tab === "list" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="tab-bar">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.id}
                className={`tab-btn ${statusFilter === f.id ? "active" : ""}`}
                onClick={() => setStatusFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {loadingSugg ? (
            <div className="loader">Cargando…</div>
          ) : suggestions.length === 0 ? (
            <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
              <Icon name="suggestions" />
              <h3 style={{ margin: "12px 0 8px" }}>Sin sugerencias</h3>
              <p className="subtitle" style={{ margin: 0 }}>No hay sugerencias con este filtro.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {suggestions.map((s) => {
                const stColor = STATUS_COLOR[s.status] || "#6366f1";
                const isPending = s.status === "PENDING";
                return (
                  <div key={s.id} className="glass-panel" style={{ padding: "16px 20px", display: "flex", gap: 14, alignItems: "flex-start" }}>
                    {s.avatar ? (
                      <img src={s.avatar} alt="" style={{ width: 36, height: 36, borderRadius: "50%", flexShrink: 0 }} />
                    ) : (
                      <div
                        style={{
                          width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
                          background: "var(--accent-light)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "var(--accent)", fontWeight: 700,
                        }}
                      >
                        {(s.username || "?")[0].toUpperCase()}
                      </div>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
                        <span
                          style={{
                            padding: "3px 10px", borderRadius: 999,
                            fontSize: "0.72rem", fontWeight: 700,
                            background: `${stColor}18`, color: stColor,
                            border: `1px solid ${stColor}33`,
                          }}
                        >
                          {STATUS_LABEL[s.status] || s.status}
                        </span>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                          #{s.id} · {s.username || `Usuario ${s.user_id}`}
                        </span>
                        <span style={{ fontSize: "0.72rem", color: "var(--dim)", marginLeft: "auto" }}>
                          {s.created_at ? new Date(s.created_at).toLocaleString("es") : "—"}
                        </span>
                      </div>
                      <p style={{ margin: 0, fontSize: "0.9rem", lineHeight: 1.5 }}>{s.content}</p>
                      {(s.upvotes > 0 || s.downvotes > 0) && (
                        <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: "0.78rem" }}>
                          <span style={{ color: "#10b981" }}>+{s.upvotes || 0}</span>
                          <span style={{ color: "#f43f5e" }}>−{s.downvotes || 0}</span>
                        </div>
                      )}
                      {s.denial_reason && (
                        <div style={{ marginTop: 8, fontSize: "0.78rem", color: "#f43f5e" }}>
                          <strong>Razón de denegación:</strong> {s.denial_reason}
                        </div>
                      )}
                    </div>
                    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                      {isPending && (
                        <>
                          <button
                            className="btn-icon"
                            title="Aprobar"
                            disabled={busyId === s.id}
                            onClick={() => updateStatus(s.id, "ACCEPTED")}
                            style={{ color: "#10b981" }}
                          >
                            <Icon name="success" />
                          </button>
                          <button
                            className="btn-icon"
                            title="Denegar"
                            disabled={busyId === s.id}
                            onClick={() => denyWithReason(s.id)}
                            style={{ color: "#f43f5e" }}
                          >
                            <Icon name="close" />
                          </button>
                        </>
                      )}
                      <button
                        className="btn-icon"
                        title="Eliminar"
                        disabled={busyId === s.id}
                        onClick={() => deleteSugg(s.id)}
                        style={{ color: "#9ca3af" }}
                      >
                        <Icon name="delete" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
