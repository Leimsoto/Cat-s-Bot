/**
 * components/CustomCommands.jsx
 * ─────────────────────────────
 * CRUD de comandos custom con respuesta tipo embed, permisos por rol y
 * auto-borrar la invocación. El prefijo está fijo a "!".
 */

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import Toast from "./Toast";
import MessageEditor, { EMPTY_MESSAGE, normalizeMessage } from "./MessageEditor";

const PREFIX = "!";

const EMPTY_FORM = {
  name: "",
  enabled: true,
  delete_invocation: false,
  permission_everyone: true,
  permission_role_ids: [],
  message: normalizeMessage(EMPTY_MESSAGE),
};

function parseMessage(cmd) {
  if (cmd?.response_data) {
    try {
      return normalizeMessage(
        typeof cmd.response_data === "string" ? JSON.parse(cmd.response_data) : cmd.response_data
      );
    } catch {/* fallthrough */}
  }
  // Legacy: actions[0].content.
  try {
    const actions = typeof cmd?.actions === "string" ? JSON.parse(cmd.actions || "[]") : (cmd?.actions || []);
    const first = actions.find((a) => a?.content) || actions[0];
    if (first?.content) {
      return normalizeMessage({ content: first.content, enabled: false, embed: EMPTY_MESSAGE.embed });
    }
  } catch {/* */}
  return normalizeMessage(EMPTY_MESSAGE);
}

function parsePermission(cmd) {
  if (!cmd?.permission_data) return { everyone: true, role_ids: [] };
  try {
    const pd = typeof cmd.permission_data === "string" ? JSON.parse(cmd.permission_data) : cmd.permission_data;
    return {
      everyone: pd.everyone !== false,
      role_ids: pd.role_ids || [],
    };
  } catch {
    return { everyone: true, role_ids: [] };
  }
}

export default function CustomCommands({ selectedGuild: guildId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(false);
  const [editorTab, setEditorTab] = useState("content");
  const [allRoles, setAllRoles] = useState([]);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/custom-commands`, { cache: false });
      setItems(data.commands || []);
      apiGet(`/api/guilds/${guildId}/roles?include_managed=0`)
        .then((r) => setAllRoles(r.roles || []))
        .catch(() => setAllRoles([]));
    } catch {
      showToast("Error cargando comandos", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const startNew = () => { setForm(EMPTY_FORM); setEditing(true); };

  const startEdit = (cmd) => {
    const perm = parsePermission(cmd);
    setForm({
      name: cmd.name,
      enabled: !!cmd.enabled,
      delete_invocation: !!cmd.delete_invocation,
      permission_everyone: perm.everyone,
      permission_role_ids: perm.role_ids,
      message: parseMessage(cmd),
    });
    setEditorTab(parseMessage(cmd).enabled ? "embed-content" : "content");
    setEditing(true);
  };

  const save = async () => {
    const cleanName = form.name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    if (!cleanName) return showToast("Nombre inválido (a-z, 0-9, _, -)", "error");
    const msg = form.message || EMPTY_MESSAGE;
    const hasContent = (msg.content && msg.content.trim()) ||
      (msg.enabled && (msg.embed?.title || msg.embed?.description));
    if (!hasContent) return showToast("La respuesta no puede estar vacía", "error");

    const payload = {
      enabled: form.enabled ? 1 : 0,
      delete_invocation: !!form.delete_invocation,
      response_data: JSON.stringify(msg),
      permission_data: {
        everyone: !!form.permission_everyone,
        role_ids: form.permission_role_ids,
      },
    };

    try {
      const exists = items.some((c) => c.name === cleanName);
      if (exists) {
        await apiPut(`/api/guilds/${guildId}/custom-commands/${cleanName}`, payload);
        showToast("Actualizado");
      } else {
        await apiPost(`/api/guilds/${guildId}/custom-commands`, {
          name: cleanName,
          ...payload,
          actions: [],
        });
        showToast("Creado");
      }
      setEditing(false);
      load();
    } catch (e) {
      showToast(e.message || "Error", "error");
    }
  };

  const toggleEnabled = async (cmd) => {
    try {
      await apiPut(`/api/guilds/${guildId}/custom-commands/${cmd.name}`, {
        enabled: cmd.enabled ? 0 : 1,
      });
      load();
    } catch (e) { showToast(e.message, "error"); }
  };

  const remove = async (name) => {
    if (!window.confirm(`¿Eliminar comando ${PREFIX}${name}?`)) return;
    try {
      await apiDelete(`/api/guilds/${guildId}/custom-commands/${name}`);
      showToast("Eliminado");
      load();
    } catch (e) { showToast(e.message, "error"); }
  };

  const toggleRole = (roleId) => {
    setForm((f) => {
      const set = new Set(f.permission_role_ids);
      if (set.has(roleId)) set.delete(roleId);
      else set.add(roleId);
      return { ...f, permission_role_ids: Array.from(set) };
    });
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
            <h2 style={{ margin: 0 }}>Comandos Personalizados</h2>
            <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: "0.85rem" }}>
              {items.length} comando(s) · prefijo fijo <code>{PREFIX}</code>
            </p>
          </div>
          {!editing && (
            <button onClick={startNew} className="btn-primary" style={{ padding: "10px 20px", borderRadius: 12 }}>
              <i className="fa-solid fa-plus" /> Nuevo comando
            </button>
          )}
        </div>
      </div>

      {editing && (
        <div className="glass-panel" style={{ padding: 24, borderRadius: 22, marginBottom: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          <h3 style={{ margin: 0 }}>{items.some((c) => c.name === form.name) ? `Editar ${PREFIX}${form.name}` : "Crear comando"}</h3>

          <div className="config-item" style={{ marginBottom: 0, maxWidth: 320 }}>
            <label>Nombre del comando (sin prefijo)</label>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontFamily: "monospace", color: "var(--muted)", fontSize: "1rem" }}>{PREFIX}</span>
              <input
                type="text"
                placeholder="saludo"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                style={{ flex: 1 }}
              />
            </div>
            <span style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
              Caracteres permitidos: a-z, 0-9, _ y -
            </span>
          </div>

          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <label className="inline-check" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              <span>Activo</span>
            </label>
            <label className="inline-check" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={form.delete_invocation}
                onChange={(e) => setForm((f) => ({ ...f, delete_invocation: e.target.checked }))}
              />
              <span>Auto-borrar mensaje de invocación</span>
            </label>
          </div>

          <hr style={{ borderColor: "rgba(139,92,246,0.15)" }} />
          <h4 style={{ margin: 0 }}>Permisos: ¿Quién puede usar este comando?</h4>
          <label className="inline-check" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={form.permission_everyone}
              onChange={(e) => setForm((f) => ({ ...f, permission_everyone: e.target.checked }))}
            />
            <span>Cualquiera (@everyone)</span>
          </label>
          {!form.permission_everyone && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 160, overflowY: "auto" }}>
              {allRoles.map((r) => {
                const active = form.permission_role_ids.includes(r.id);
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => toggleRole(r.id)}
                    className={`tab-btn ${active ? "active" : ""}`}
                    style={{ fontSize: "0.74rem", padding: "5px 10px" }}
                  >
                    {r.color && <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: r.color, marginRight: 6 }} />}
                    {r.name}
                  </button>
                );
              })}
              {allRoles.length === 0 && (
                <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Sin roles disponibles.</span>
              )}
            </div>
          )}

          <hr style={{ borderColor: "rgba(139,92,246,0.15)" }} />
          <h4 style={{ margin: 0 }}>Respuesta</h4>

          <MessageEditor
            value={form.message}
            onChange={(next) => setForm((f) => ({ ...f, message: next }))}
            mode="both"
            tab={editorTab}
            setTab={setEditorTab}
            variablesHelp={"Variables: {user}, {username}, {display_name}, {server}, {channel}, {args}, {1}, {2}…"}
            placeholders={{
              content: `¡Hola {user}! Esto es ${PREFIX}${form.name || "comando"}`,
              title: "Título",
              description: "Descripción enriquecida…",
            }}
          />

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button onClick={() => setEditing(false)} className="btn-secondary">Cancelar</button>
            <button onClick={save} className="btn-primary">Guardar</button>
          </div>
        </div>
      )}

      {items.length === 0 && !editing ? (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <i className="fa-solid fa-terminal" style={{ fontSize: "2.5rem", marginBottom: 12, display: "block", color: "var(--muted)" }} />
          <h3 style={{ margin: "0 0 8px" }}>Sin comandos personalizados</h3>
          <p style={{ color: "var(--muted)", margin: 0 }}>Crea tu primer comando.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((cmd) => {
            const msg = parseMessage(cmd);
            const preview = msg.content || msg.embed?.title || msg.embed?.description || "(vacío)";
            return (
              <div
                key={cmd.name}
                className="glass-panel"
                style={{
                  padding: "14px 18px",
                  borderRadius: 16,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  opacity: cmd.enabled ? 1 : 0.5,
                }}
              >
                <span style={{ fontFamily: "monospace", fontWeight: 700, color: "#c4b5fd" }}>
                  {PREFIX}{cmd.name}
                </span>
                {cmd.delete_invocation ? (
                  <span title="Auto-borra invocación" style={{ fontSize: "0.7rem", padding: "2px 8px", borderRadius: 99, background: "rgba(239,68,68,0.12)", color: "#fca5a5", border: "1px solid rgba(239,68,68,0.25)" }}>
                    🗑️ delete
                  </span>
                ) : null}
                <div style={{ flex: 1, minWidth: 0, fontSize: "0.82rem", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  → {String(preview).slice(0, 90)}
                </div>
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{cmd.uses || 0} usos</span>
                <label className="toggle-switch" style={{ transform: "scale(0.85)" }}>
                  <input type="checkbox" checked={!!cmd.enabled} onChange={() => toggleEnabled(cmd)} />
                  <span className="slider" />
                </label>
                <button onClick={() => startEdit(cmd)} className="btn-secondary" style={{ padding: "6px 10px" }} title="Editar">
                  <i className="fa-solid fa-pen" />
                </button>
                <button onClick={() => remove(cmd.name)} title="Eliminar" style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", color: "#ef4444", borderRadius: 10, padding: "6px 10px", cursor: "pointer" }}>
                  <i className="fa-solid fa-trash" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
