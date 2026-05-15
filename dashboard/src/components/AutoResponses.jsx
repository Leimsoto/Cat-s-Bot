/**
 * components/AutoResponses.jsx
 * ────────────────────────────
 * CRUD de auto-respuestas con matching avanzado y respuestas tipo embed.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/autoresponses
 *   POST   /api/guilds/{g}/autoresponses
 *   PATCH  /api/guilds/{g}/autoresponses/{id}
 *   DELETE /api/guilds/{g}/autoresponses/{id}
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "../lib/api";
import Toast from "./Toast";
import { SearchableSelect } from "./ui";
import MessageEditor, { EMPTY_MESSAGE, normalizeMessage } from "./MessageEditor";

const MATCH_TYPES = [
  ["contains", "Contiene", "Si el mensaje incluye el texto en cualquier lugar."],
  ["word", "Palabra completa", "Coincide con la palabra exacta (\\btrigger\\b)."],
  ["exact", "Exacto", "El mensaje debe ser idéntico al trigger."],
  ["starts_with", "Empieza con", "El mensaje comienza con el trigger."],
  ["regex", "Regex", "Patrón regex (potente; valida tu propio regex)."],
];

const EMPTY_FORM = {
  id: null,
  trigger: "",
  match_type: "contains",
  case_sensitive: false,
  enabled: true,
  channel_id: null,
  message: normalizeMessage(EMPTY_MESSAGE),
};

export default function AutoResponses({ selectedGuild: guildId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(false);
  const [editorTab, setEditorTab] = useState("content");

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/autoresponses`, { cache: false });
      setItems(data.autoresponses || []);
    } catch {
      showToast("Error cargando auto-respuestas", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const matchLabel = (mt) =>
    MATCH_TYPES.find((t) => t[0] === mt)?.[1] || mt;

  const startNew = () => {
    setForm(EMPTY_FORM);
    setEditing(true);
  };

  const startEdit = (ar) => {
    let msg = EMPTY_MESSAGE;
    if (ar.response_data) {
      try { msg = normalizeMessage(typeof ar.response_data === "string" ? JSON.parse(ar.response_data) : ar.response_data); }
      catch { msg = EMPTY_MESSAGE; }
    } else if (ar.response) {
      msg = normalizeMessage({ content: ar.response, enabled: false, embed: EMPTY_MESSAGE.embed });
    }
    setForm({
      id: ar.id,
      trigger: ar.trigger || "",
      match_type: ar.match_type || "contains",
      case_sensitive: !!ar.case_sensitive,
      enabled: ar.enabled !== 0,
      channel_id: ar.channel_id || null,
      message: msg,
    });
    setEditorTab(msg.enabled ? "embed-content" : "content");
    setEditing(true);
  };

  const save = async () => {
    if (!form.trigger.trim()) return showToast("Trigger es requerido", "error");
    const msg = form.message || EMPTY_MESSAGE;
    const hasContent = (msg.content && msg.content.trim()) ||
      (msg.enabled && (msg.embed?.title || msg.embed?.description));
    if (!hasContent) return showToast("La respuesta no puede estar vacía", "error");

    const payload = {
      trigger: form.trigger.trim(),
      match_type: form.match_type,
      case_sensitive: form.case_sensitive,
      enabled: form.enabled,
      channel_id: form.channel_id || null,
      response: msg.content || "",
      response_data: JSON.stringify(msg),
    };

    try {
      if (form.id) {
        await apiPatch(`/api/guilds/${guildId}/autoresponses/${form.id}`, payload);
        showToast("Actualizada");
      } else {
        await apiPost(`/api/guilds/${guildId}/autoresponses`, payload);
        showToast("Creada");
      }
      setEditing(false);
      load();
    } catch (e) {
      showToast(e.message || "Error", "error");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("¿Eliminar auto-respuesta?")) return;
    try {
      await apiDelete(`/api/guilds/${guildId}/autoresponses/${id}`);
      showToast("Eliminada");
      load();
    } catch (e) {
      showToast(e.message || "Error", "error");
    }
  };

  const toggleEnabled = async (ar) => {
    try {
      await apiPatch(`/api/guilds/${guildId}/autoresponses/${ar.id}`, {
        enabled: !ar.enabled,
      });
      load();
    } catch (e) { showToast(e.message || "Error", "error"); }
  };

  if (loading) {
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando…</p>
      </div>
    );
  }

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0 }}>Auto-Respuestas</h2>
            <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: "0.85rem" }}>
              {items.length} configurada{items.length === 1 ? "" : "s"}
            </p>
          </div>
          {!editing && (
            <button
              onClick={startNew}
              className="btn-primary"
              style={{ padding: "10px 20px", borderRadius: 12 }}
            >
              <i className="fa-solid fa-plus" /> Nueva auto-respuesta
            </button>
          )}
        </div>
      </div>

      {editing && (
        <div className="glass-panel" style={{ padding: 24, borderRadius: 22, marginBottom: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          <h3 style={{ margin: 0 }}>{form.id ? `Editar #${form.id}` : "Crear auto-respuesta"}</h3>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Trigger</label>
              <input
                type="text"
                placeholder="hola"
                value={form.trigger}
                onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value }))}
              />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Canal (opcional)</label>
              <SearchableSelect
                value={form.channel_id || ""}
                onChange={(v) => setForm((f) => ({ ...f, channel_id: v ? parseInt(v, 10) : null }))}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="🌐 Todos los canales"
                renderOption={(o) => <span># {o.name}</span>}
                renderSelected={(o) => <span># {o.name}</span>}
              />
            </div>
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Tipo de coincidencia</label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {MATCH_TYPES.map(([id, label, desc]) => (
                <button
                  key={id}
                  type="button"
                  title={desc}
                  className={`tab-btn ${form.match_type === id ? "active" : ""}`}
                  onClick={() => setForm((f) => ({ ...f, match_type: id }))}
                  style={{ fontSize: "0.78rem", padding: "6px 12px" }}
                >
                  {label}
                </button>
              ))}
            </div>
            <span style={{ fontSize: "0.74rem", color: "var(--muted)", marginTop: 4, display: "block" }}>
              {MATCH_TYPES.find((t) => t[0] === form.match_type)?.[2]}
            </span>
          </div>

          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <label className="inline-check" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={form.case_sensitive}
                onChange={(e) => setForm((f) => ({ ...f, case_sensitive: e.target.checked }))}
              />
              <span>Sensible a mayúsculas</span>
            </label>
            <label className="inline-check" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              <span>Activa</span>
            </label>
          </div>

          <hr style={{ borderColor: "rgba(139,92,246,0.15)" }} />
          <h4 style={{ margin: 0 }}>Respuesta</h4>

          <MessageEditor
            value={form.message}
            onChange={(next) => setForm((f) => ({ ...f, message: next }))}
            mode="both"
            tab={editorTab}
            setTab={setEditorTab}
            variablesHelp={"Variables: {user}, {username}, {server}, {channel}."}
            placeholders={{
              content: "¡Hola {user}!",
              title: "Título del embed",
              description: "Descripción enriquecida…",
            }}
          />

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button onClick={() => setEditing(false)} className="btn-secondary">Cancelar</button>
            <button onClick={save} className="btn-primary">{form.id ? "Guardar" : "Crear"}</button>
          </div>
        </div>
      )}

      {items.length === 0 && !editing ? (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <i className="fa-solid fa-comments" style={{ fontSize: "2.5rem", marginBottom: 12, display: "block", color: "var(--muted)" }} />
          <h3 style={{ margin: "0 0 8px" }}>Sin auto-respuestas</h3>
          <p style={{ color: "var(--muted)", margin: 0 }}>Crea tu primera auto-respuesta.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((ar) => (
            <div
              key={ar.id}
              className="glass-panel"
              style={{
                padding: "14px 18px",
                borderRadius: 16,
                display: "flex",
                alignItems: "center",
                gap: 14,
                opacity: ar.enabled ? 1 : 0.55,
              }}
            >
              <span
                style={{
                  padding: "3px 10px",
                  borderRadius: 99,
                  background: "rgba(139,92,246,0.15)",
                  color: "#c4b5fd",
                  fontSize: "0.74rem",
                  fontWeight: 700,
                  border: "1px solid rgba(139,92,246,0.25)",
                }}
              >
                {matchLabel(ar.match_type)}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontFamily: "monospace" }}>
                  #{ar.id} · {ar.trigger}
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  → {ar.response || "(embed)"}
                </div>
              </div>
              <button
                onClick={() => toggleEnabled(ar)}
                title={ar.enabled ? "Desactivar" : "Activar"}
                className="btn-secondary"
                style={{ padding: "6px 10px" }}
              >
                <i className={`fa-solid ${ar.enabled ? "fa-pause" : "fa-play"}`} />
              </button>
              <button
                onClick={() => startEdit(ar)}
                title="Editar"
                className="btn-secondary"
                style={{ padding: "6px 10px" }}
              >
                <i className="fa-solid fa-pen" />
              </button>
              <button
                onClick={() => remove(ar.id)}
                title="Eliminar"
                style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", color: "#ef4444", borderRadius: 10, padding: "6px 10px", cursor: "pointer" }}
              >
                <i className="fa-solid fa-trash" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
