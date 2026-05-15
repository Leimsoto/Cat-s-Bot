/**
 * components/Schedules.jsx
 * ────────────────────────
 * Mensajes programados. Soporta dos modos:
 *   • interval — cada cierto tiempo (mín 10 min, máx 30 días).
 *   • cron     — hora exacta en una timezone IANA, opcionalmente filtrada
 *                por días de la semana.
 *
 * El contenido se edita con MessageEditor (content + embed) y se envía con
 * variables {server}, {channel}.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/schedules
 *   POST   /api/guilds/{g}/schedules
 *   PATCH  /api/guilds/{g}/schedules/{id|name}
 *   POST   /api/guilds/{g}/schedules/{id|name}/toggle
 *   POST   /api/guilds/{g}/schedules/{id|name}/test
 *   DELETE /api/guilds/{g}/schedules/{id|name}
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";
import MessageEditor, { EMPTY_MESSAGE, normalizeMessage } from "./MessageEditor";

const INTERVAL_PRESETS = [
  { label: "10 min",  seconds: 600 },
  { label: "30 min",  seconds: 1800 },
  { label: "1 hora",  seconds: 3600 },
  { label: "6 horas", seconds: 21600 },
  { label: "24 horas",seconds: 86400 },
  { label: "1 semana",seconds: 604800 },
];

// Lista corta de zonas más usadas. La detectada del navegador siempre va arriba.
const COMMON_TZ = [
  "UTC",
  "Europe/Madrid", "Europe/London", "Europe/Berlin", "Europe/Paris",
  "America/Mexico_City", "America/Bogota", "America/Lima",
  "America/Buenos_Aires", "America/Santiago", "America/Caracas",
  "America/New_York", "America/Los_Angeles",
  "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
];

const WEEKDAYS = [
  ["L", 0], ["M", 1], ["X", 2], ["J", 3], ["V", 4], ["S", 5], ["D", 6],
];

function fmtInterval(seconds) {
  const s = Number(seconds || 0);
  if (!s) return "—";
  if (s >= 604800) return `${Math.floor(s / 604800)} sem`;
  if (s >= 86400)  return `${Math.floor(s / 86400)} d`;
  if (s >= 3600)   return `${Math.floor(s / 3600)} h`;
  return `${Math.floor(s / 60)} min`;
}

function fmtDate(iso) {
  if (!iso) return "Nunca";
  try { return new Date(iso).toLocaleString("es"); } catch { return String(iso); }
}

function makeForm() {
  return {
    id: null,
    name: "",
    channel_id: null,
    mode: "interval",
    interval_seconds: 3600,
    custom_interval_min: "",
    cron_hour: 9,
    cron_minute: 0,
    cron_weekdays: [0, 1, 2, 3, 4], // L-V por defecto
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    message: normalizeMessage(EMPTY_MESSAGE),
  };
}

export default function Schedules({ selectedGuild, onToast }) {
  const guildId = selectedGuild;
  const [schedules, setSchedules] = useState([]);
  const [limits, setLimits] = useState({ max_schedules: 10, min_interval: 600, max_interval: 2592000 });
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState(makeForm());
  const [editorTab, setEditorTab] = useState("content");

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

  const tzOptions = useMemo(() => {
    const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const set = new Set([local, ...COMMON_TZ]);
    return Array.from(set);
  }, []);

  const startNew = () => { setForm(makeForm()); setEditing(true); };

  const startEdit = (s) => {
    let msg = normalizeMessage(EMPTY_MESSAGE);
    if (s.message_data) {
      try { msg = normalizeMessage(typeof s.message_data === "string" ? JSON.parse(s.message_data) : s.message_data); } catch { /* */ }
    } else if (s.content) {
      msg = normalizeMessage({ content: s.content, enabled: false, embed: EMPTY_MESSAGE.embed });
    }
    let weekdays = [0, 1, 2, 3, 4];
    if (s.cron_weekdays) {
      try {
        const parsed = typeof s.cron_weekdays === "string" ? JSON.parse(s.cron_weekdays) : s.cron_weekdays;
        if (Array.isArray(parsed)) weekdays = parsed.map((x) => Number(x));
      } catch { /* */ }
    }
    setForm({
      id: s.id,
      name: s.name,
      channel_id: s.channel_id ? Number(s.channel_id) : null,
      mode: (s.schedule_mode || "interval").toLowerCase(),
      interval_seconds: Number(s.interval_seconds) || 3600,
      custom_interval_min: "",
      cron_hour: s.cron_hour == null ? 9 : Number(s.cron_hour),
      cron_minute: s.cron_minute == null ? 0 : Number(s.cron_minute),
      cron_weekdays: weekdays,
      timezone: s.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      message: msg,
    });
    setEditorTab(msg.enabled ? "embed-content" : "content");
    setEditing(true);
  };

  const computedInterval = () => {
    if (form.custom_interval_min) {
      const m = parseInt(form.custom_interval_min, 10);
      if (Number.isFinite(m) && m > 0) return m * 60;
    }
    return Number(form.interval_seconds);
  };

  const toggleWeekday = (d) => {
    setForm((p) => {
      const set = new Set(p.cron_weekdays);
      if (set.has(d)) set.delete(d);
      else set.add(d);
      return { ...p, cron_weekdays: Array.from(set).sort((a, b) => a - b) };
    });
  };

  const save = async () => {
    if (!form.name.trim()) return toast("error", "Nombre requerido");
    if (!form.channel_id) return toast("error", "Selecciona un canal");
    const msg = form.message || EMPTY_MESSAGE;
    const hasContent = (msg.content && msg.content.trim()) ||
      (msg.enabled && (msg.embed?.title || msg.embed?.description));
    if (!hasContent) return toast("error", "El mensaje no puede estar vacío");

    const payload = {
      channel_id: Number(form.channel_id),
      schedule_mode: form.mode,
      message_data: JSON.stringify(msg),
      content: msg.content || "",
    };

    if (form.mode === "interval") {
      const interval = computedInterval();
      if (interval < limits.min_interval) return toast("error", `Intervalo mínimo: ${limits.min_interval / 60} min`);
      if (interval > limits.max_interval) return toast("error", "Intervalo máximo: 30 días");
      payload.interval_seconds = interval;
    } else {
      payload.cron_hour = Number(form.cron_hour);
      payload.cron_minute = Number(form.cron_minute);
      payload.cron_weekdays = JSON.stringify(form.cron_weekdays);
      payload.timezone = form.timezone || "UTC";
      // interval_seconds requerido por validador previo; sin uso en modo cron.
      payload.interval_seconds = 0;
    }

    setSaving(true);
    try {
      if (form.id) {
        await apiPatch(`/api/guilds/${guildId}/schedules/${form.id}`, payload);
        toast("success", "Horario actualizado");
      } else {
        await apiPost(`/api/guilds/${guildId}/schedules`, { name: form.name.trim(), ...payload });
        toast("success", "Horario creado");
      }
      setEditing(false);
      load();
    } catch (e) {
      toast("error", e?.message || "Error guardando");
    } finally {
      setSaving(false);
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

  if (loading) return <div className="loader">Cargando horarios…</div>;

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 className="glow-text" style={{ margin: 0 }}>Mensajes programados</h2>
            <p className="subtitle" style={{ margin: "4px 0 0" }}>
              Programa por intervalo o a una hora exacta según zona horaria. Tu hora local: <code>{tz}</code>.
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ padding: "6px 14px", borderRadius: 999, fontSize: "0.8rem", fontWeight: 700, background: "rgba(99,102,241,0.15)", border: "1px solid rgba(139,92,246,0.3)", color: "var(--accent)" }}>
              {schedules.filter((s) => s.enabled).length} activos · {schedules.length}/{limits.max_schedules}
            </span>
            {!editing && (
              <button
                className="btn-primary"
                onClick={startNew}
                disabled={schedules.length >= limits.max_schedules}
              >
                <Icon name="add" /> Nuevo horario
              </button>
            )}
          </div>
        </div>
      </div>

      {editing && (
        <div className="glass-panel mod-section animate-fade-in" style={{ padding: 22, marginBottom: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <h3 style={{ margin: 0 }}>{form.id ? `Editar "${form.name}"` : "Crear horario"}</h3>

          <div className="form-grid">
            <div className="form-field">
              <label>Nombre único</label>
              <input
                type="text"
                placeholder="recordatorio-diario"
                value={form.name}
                onChange={(e) => setF("name", e.target.value)}
                disabled={!!form.id}
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
                renderOption={(o) => <span># {o.name}</span>}
                renderSelected={(o) => <span># {o.name}</span>}
              />
            </div>
          </div>

          <div className="form-field">
            <label>Modo de programación</label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[
                ["interval", "⏱️ Cada cierto tiempo"],
                ["cron", "🕐 Hora exacta por timezone"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`tab-btn ${form.mode === id ? "active" : ""}`}
                  onClick={() => setF("mode", id)}
                  style={{ fontSize: "0.82rem", padding: "8px 14px" }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {form.mode === "interval" && (
            <div className="form-field">
              <label>Intervalo</label>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {INTERVAL_PRESETS.map((p) => {
                  const active = form.interval_seconds === p.seconds && !form.custom_interval_min;
                  return (
                    <button
                      key={p.seconds}
                      onClick={() => { setF("interval_seconds", p.seconds); setF("custom_interval_min", ""); }}
                      className={`tab-btn ${active ? "active" : ""}`}
                      type="button"
                      style={{ fontSize: "0.78rem", padding: "6px 12px" }}
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
          )}

          {form.mode === "cron" && (
            <>
              <div className="form-grid">
                <div className="form-field">
                  <label>Hora (24h)</label>
                  <input
                    type="number"
                    min="0"
                    max="23"
                    value={form.cron_hour}
                    onChange={(e) => setF("cron_hour", Math.max(0, Math.min(23, parseInt(e.target.value, 10) || 0)))}
                  />
                </div>
                <div className="form-field">
                  <label>Minuto</label>
                  <input
                    type="number"
                    min="0"
                    max="59"
                    value={form.cron_minute}
                    onChange={(e) => setF("cron_minute", Math.max(0, Math.min(59, parseInt(e.target.value, 10) || 0)))}
                  />
                </div>
                <div className="form-field">
                  <label>Zona horaria (IANA)</label>
                  <select
                    value={form.timezone}
                    onChange={(e) => setF("timezone", e.target.value)}
                    style={{ width: "100%" }}
                  >
                    {tzOptions.map((tzn) => (
                      <option key={tzn} value={tzn}>{tzn}</option>
                    ))}
                  </select>
                  <span className="hint">Detectada de tu navegador: {tz}</span>
                </div>
              </div>
              <div className="form-field">
                <label>Días de la semana</label>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {WEEKDAYS.map(([lbl, d]) => {
                    const active = form.cron_weekdays.includes(d);
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => toggleWeekday(d)}
                        className={`tab-btn ${active ? "active" : ""}`}
                        style={{ fontSize: "0.78rem", padding: "6px 12px", minWidth: 36 }}
                      >
                        {lbl}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => setF("cron_weekdays", [0, 1, 2, 3, 4, 5, 6])}
                    className="btn-secondary"
                    style={{ fontSize: "0.74rem", padding: "5px 10px" }}
                  >
                    Todos
                  </button>
                </div>
                <span className="hint">L=Lunes · D=Domingo. Si no marcas ninguno, no se enviará.</span>
              </div>
            </>
          )}

          <hr style={{ borderColor: "rgba(139,92,246,0.15)" }} />
          <h4 style={{ margin: 0 }}>Mensaje</h4>

          <MessageEditor
            value={form.message}
            onChange={(next) => setF("message", next)}
            mode="both"
            tab={editorTab}
            setTab={setEditorTab}
            variablesHelp={"Variables: {server}, {channel}."}
            placeholders={{
              content: "@everyone recordatorio…",
              title: "Título del embed",
              description: "Contenido enriquecido…",
            }}
          />

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button className="btn-secondary" onClick={() => setEditing(false)}>Cancelar</button>
            <button className="btn-primary btn-save" onClick={save} disabled={saving}>
              {saving ? "Guardando…" : <><Icon name="save" /> {form.id ? "Guardar" : "Crear"}</>}
            </button>
          </div>
        </div>
      )}

      {schedules.length === 0 && !editing && (
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
          const mode = (s.schedule_mode || "interval").toLowerCase();
          const scheduleLabel = mode === "cron"
            ? `Cron · ${String(s.cron_hour ?? 0).padStart(2, "0")}:${String(s.cron_minute ?? 0).padStart(2, "0")} ${s.timezone || "UTC"}`
            : `Cada ${fmtInterval(s.interval_seconds)}`;
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
                borderLeft: `1px solid ${enabled ? "var(--border-accent)" : "var(--border)"}`,
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
                  <span
                    style={{
                      padding: "2px 10px",
                      borderRadius: 999,
                      fontSize: "0.7rem",
                      fontWeight: 700,
                      background: "rgba(99,102,241,0.12)",
                      border: "1px solid rgba(99,102,241,0.25)",
                      color: "#a5b4fc",
                    }}
                  >
                    {scheduleLabel}
                  </span>
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--muted)", display: "flex", gap: 14, flexWrap: "wrap" }}>
                  <span><Icon name="channel" /> Canal {s.channel_id}</span>
                  <span><Icon name="loading" /> último: {fmtDate(s.last_sent)}</span>
                </div>
                <div style={{ marginTop: 8, fontSize: "0.85rem", color: "var(--text)", opacity: 0.8, maxWidth: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.content}>
                  {s.content || "(embed)"}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexShrink: 0, alignItems: "center" }}>
                <label className="toggle-switch" title={enabled ? "Pausar" : "Activar"}>
                  <input type="checkbox" checked={enabled} disabled={busyId === s.id} onChange={() => toggleEnabled(s)} />
                  <span className="slider" />
                </label>
                <button className="btn-icon" title="Enviar prueba" disabled={busyId === s.id} onClick={() => testSchedule(s)} style={{ color: "var(--accent)" }}>
                  <Icon name="send" />
                </button>
                <button className="btn-icon" title="Editar" disabled={busyId === s.id} onClick={() => startEdit(s)}>
                  <Icon name="edit" />
                </button>
                <button className="btn-icon" title="Eliminar" disabled={busyId === s.id} onClick={() => deleteSchedule(s)} style={{ color: "#f43f5e" }}>
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
