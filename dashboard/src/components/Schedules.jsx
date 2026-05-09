/**
 * components/Schedules.jsx
 * ────────────────────────
 * Mensajes programados (cron). Crear, listar, editar, toggle, test, eliminar.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/schedules
 *   POST   /api/guilds/{g}/schedules
 *   PATCH  /api/guilds/{g}/schedules/{id|name}
 *   POST   /api/guilds/{g}/schedules/{id|name}/toggle
 *   POST   /api/guilds/{g}/schedules/{id|name}/test
 *   DELETE /api/guilds/{g}/schedules/{id|name}
 */

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";

const INTERVAL_PRESETS = [
  { label: "1 hora",   seconds: 3600 },
  { label: "2 horas",  seconds: 7200 },
  { label: "6 horas",  seconds: 21600 },
  { label: "12 horas", seconds: 43200 },
  { label: "24 horas", seconds: 86400 },
  { label: "1 semana", seconds: 604800 },
];

function fmtInterval(seconds) {
  const s = Number(seconds || 0);
  if (!s) return "—";
  if (s >= 604800) return `${Math.floor(s / 604800)} sem`;
  if (s >= 86400)  return `${Math.floor(s / 86400)}d`;
  if (s >= 3600)   return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 60)}min`;
}

function fmtDate(iso) {
  if (!iso) return "Nunca";
  try {
    return new Date(iso).toLocaleString("es");
  } catch {
    return String(iso);
  }
}

const EMPTY_FORM = {
  name: "",
  channel_id: null,
  content: "",
  interval_seconds: 3600,
  custom_interval_min: "",
};

export default function Schedules({ selectedGuild, onToast }) {
  const guildId = selectedGuild;
  const [schedules, setSchedules] = useState([]);
  const [limits, setLimits] = useState({ max_schedules: 10, min_interval: 600, max_interval: 2592000 });
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/schedules`, { cache: false });
      setSchedules(data?.schedules || []);
      if (data?.limits) setLimits(data.limits);
    } catch (e) {
      toast("error", e?.message || "Error cargando horarios");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const setF = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const computedInterval = () => {
    if (form.custom_interval_min) {
      const m = parseInt(form.custom_interval_min, 10);
      if (Number.isFinite(m) && m > 0) return m * 60;
    }
    return Number(form.interval_seconds);
  };

  const create = async () => {
    if (!form.name.trim()) return toast("error", "Nombre requerido");
    if (!form.channel_id) return toast("error", "Selecciona un canal");
    if (!form.content.trim()) return toast("error", "Contenido requerido");
    const interval = computedInterval();
    if (interval < limits.min_interval) return toast("error", `Intervalo mínimo: ${limits.min_interval / 60} min`);
    if (interval > limits.max_interval) return toast("error", "Intervalo máximo: 30 días");

    setCreating(true);
    try {
      await apiPost(`/api/guilds/${guildId}/schedules`, {
        name: form.name.trim(),
        channel_id: Number(form.channel_id),
        content: form.content.trim(),
        interval_seconds: interval,
      });
      toast("success", "Horario creado");
      setForm(EMPTY_FORM);
      setShowCreate(false);
      await load();
    } catch (e) {
      toast("error", e?.message || "Error creando horario");
    } finally {
      setCreating(false);
    }
  };

  const toggleEnabled = async (s) => {
    setBusyId(s.id);
    try {
      await apiPost(`/api/guilds/${guildId}/schedules/${s.id}/toggle`, {});
      await load();
    } catch (e) {
      toast("error", e?.message || "Error al cambiar estado");
    } finally {
      setBusyId(null);
    }
  };

  const testSchedule = async (s) => {
    setBusyId(s.id);
    try {
      await apiPost(`/api/guilds/${guildId}/schedules/${s.id}/test`, {});
      toast("success", `Mensaje de prueba enviado: ${s.name}`);
    } catch (e) {
      toast("error", e?.message || "Error en envío de prueba");
    } finally {
      setBusyId(null);
    }
  };

  const deleteSchedule = async (s) => {
    if (!confirm(`¿Eliminar el horario "${s.name}"? Irreversible.`)) return;
    setBusyId(s.id);
    try {
      await apiDelete(`/api/guilds/${guildId}/schedules/${s.id}`);
      toast("success", `Horario ${s.name} eliminado`);
      await load();
    } catch (e) {
      toast("error", e?.message || "Error eliminando");
    } finally {
      setBusyId(null);
    }
  };

  const editSchedule = async (s) => {
    const newContent = prompt(`Editar contenido de "${s.name}":`, s.content);
    if (newContent == null || newContent.trim() === s.content) return;
    setBusyId(s.id);
    try {
      await apiPatch(`/api/guilds/${guildId}/schedules/${s.id}`, { content: newContent.trim() });
      toast("success", "Contenido actualizado");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error editando");
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="loader">Cargando horarios…</div>;

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 className="glow-text" style={{ margin: 0 }}>Mensajes programados</h2>
            <p className="subtitle" style={{ margin: "4px 0 0" }}>
              Mensajes automáticos por intervalo. Las horas se muestran en tu zona horaria local: <code>{tz}</code>.
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span
              style={{
                padding: "6px 14px", borderRadius: 999, fontSize: "0.8rem", fontWeight: 700,
                background: "rgba(99,102,241,0.15)",
                border: "1px solid rgba(139,92,246,0.3)",
                color: "var(--accent)",
              }}
            >
              {schedules.filter((s) => s.enabled).length} activos · {schedules.length} / {limits.max_schedules}
            </span>
            <button
              className="btn-primary"
              onClick={() => setShowCreate((v) => !v)}
              disabled={schedules.length >= limits.max_schedules && !showCreate}
            >
              <Icon name={showCreate ? "close" : "add"} /> {showCreate ? "Cancelar" : "Nuevo horario"}
            </button>
          </div>
        </div>
      </div>

      {showCreate && (
        <div className="glass-panel mod-section animate-fade-in" style={{ padding: 22, marginBottom: 24 }}>
          <div className="section-title">
            <Icon name="add" /> <h3>Crear horario</h3>
          </div>
          <div className="form-grid">
            <div className="form-field">
              <label>Nombre único</label>
              <input
                type="text"
                placeholder="recordatorio-diario"
                value={form.name}
                onChange={(e) => setF("name", e.target.value)}
              />
            </div>
            <div className="form-field">
              <label>Canal destino</label>
              <SearchableSelect
                value={form.channel_id}
                onChange={(v) => setF("channel_id", v ? Number(v) : null)}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="Seleccionar canal…"
                renderOption={(o) => <span>#{o.name}</span>}
                renderSelected={(o) => <span>#{o.name}</span>}
              />
            </div>
            <div className="form-field full-width">
              <label>Contenido del mensaje</label>
              <textarea
                rows={4}
                placeholder="¡Buenos días! Recuerda revisar las reglas del servidor…"
                value={form.content}
                onChange={(e) => setF("content", e.target.value)}
                style={{ width: "100%", resize: "vertical" }}
              />
              <span className="hint">Markdown soportado. Mentions @everyone/@role requieren permisos en el canal.</span>
            </div>
            <div className="form-field full-width">
              <label>Intervalo</label>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {INTERVAL_PRESETS.map((p) => {
                  const active = form.interval_seconds === p.seconds && !form.custom_interval_min;
                  return (
                    <button
                      key={p.seconds}
                      onClick={() => { setF("interval_seconds", p.seconds); setF("custom_interval_min", ""); }}
                      className={`tab-btn ${active ? "active" : ""}`}
                      type="button"
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
                <input
                  type="number"
                  min="10"
                  placeholder="Personalizado"
                  value={form.custom_interval_min}
                  onChange={(e) => setF("custom_interval_min", e.target.value)}
                  style={{ width: 220 }}
                />
                <span className="hint">minutos (mín {limits.min_interval / 60})</span>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 16 }}>
            <button className="btn-secondary" onClick={() => { setShowCreate(false); setForm(EMPTY_FORM); }}>
              Cancelar
            </button>
            <button className="btn-primary btn-save" onClick={create} disabled={creating}>
              {creating ? "Creando…" : <><Icon name="save" /> Crear horario</>}
            </button>
          </div>
        </div>
      )}

      {schedules.length === 0 && !showCreate && (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <Icon name="schedules" />
          <h3 style={{ margin: "12px 0 8px" }}>Sin horarios configurados</h3>
          <p className="subtitle" style={{ margin: 0 }}>
            Crea tu primer mensaje automático con el botón de arriba.
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {schedules.map((s) => {
          const enabled = !!Number(s.enabled);
          return (
            <div
              key={s.id}
              className="glass-panel mod-section"
              style={{
                padding: "16px 20px",
                display: "flex",
                alignItems: "center",
                gap: 16,
                flexWrap: "wrap",
                borderLeft: `3px solid ${enabled ? "var(--accent)" : "rgba(139,92,246,0.2)"}`,
              }}
            >
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <span style={{ fontWeight: 900, fontSize: "1rem" }}>{s.name}</span>
                  <span
                    style={{
                      padding: "2px 10px",
                      borderRadius: 999,
                      fontSize: "0.72rem",
                      fontWeight: 800,
                      background: enabled ? "rgba(16,185,129,0.15)" : "rgba(255,255,255,0.05)",
                      border: `1px solid ${enabled ? "rgba(16,185,129,0.4)" : "rgba(255,255,255,0.1)"}`,
                      color: enabled ? "#34d399" : "var(--muted)",
                    }}
                  >
                    {enabled ? "Activo" : "Pausado"}
                  </span>
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--muted)", display: "flex", gap: 14, flexWrap: "wrap" }}>
                  <span><Icon name="channel" /> Canal {s.channel_id}</span>
                  <span><Icon name="settings" /> cada {fmtInterval(s.interval_seconds)}</span>
                  <span><Icon name="loading" /> último: {fmtDate(s.last_sent)}</span>
                </div>
                <div
                  style={{
                    marginTop: 8,
                    fontSize: "0.85rem",
                    color: "var(--text)",
                    opacity: 0.8,
                    maxWidth: 600,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={s.content}
                >
                  {s.content}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexShrink: 0, alignItems: "center" }}>
                <label className="toggle-switch" title={enabled ? "Pausar" : "Activar"}>
                  <input
                    type="checkbox"
                    checked={enabled}
                    disabled={busyId === s.id}
                    onChange={() => toggleEnabled(s)}
                  />
                  <span className="slider" />
                </label>
                <button
                  className="btn-icon"
                  title="Enviar prueba"
                  disabled={busyId === s.id}
                  onClick={() => testSchedule(s)}
                  style={{ color: "var(--accent)" }}
                >
                  <Icon name="send" />
                </button>
                <button
                  className="btn-icon"
                  title="Editar contenido"
                  disabled={busyId === s.id}
                  onClick={() => editSchedule(s)}
                >
                  <Icon name="edit" />
                </button>
                <button
                  className="btn-icon"
                  title="Eliminar"
                  disabled={busyId === s.id}
                  onClick={() => deleteSchedule(s)}
                  style={{ color: "#f43f5e" }}
                >
                  <Icon name="delete" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
