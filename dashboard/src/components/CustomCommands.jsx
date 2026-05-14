import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import Toast from "./Toast";

export default function CustomCommands({ selectedGuild: guildId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", trigger_type: "prefix", trigger_value: "", actions: [{ type: "reply", content: "" }] });
  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/custom-commands`, { cache: false });
      setItems(data.commands || []);
    } catch { showToast("Error cargando comandos", "error"); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.name.trim() || !form.trigger_value.trim()) return showToast("Nombre y trigger requeridos", "error");
    try {
      await apiPost(`/api/guilds/${guildId}/custom-commands`, form);
      showToast("Comando creado"); setForm({ name: "", trigger_type: "prefix", trigger_value: "", actions: [{ type: "reply", content: "" }] }); setShowForm(false); load();
    } catch (e) { showToast(e.message, "error"); }
  };

  const handleToggle = async (cmd) => {
    try {
      await apiPut(`/api/guilds/${guildId}/custom-commands/${cmd.name}`, { enabled: cmd.enabled ? 0 : 1 });
      showToast(cmd.enabled ? "Desactivado" : "Activado"); load();
    } catch (e) { showToast(e.message, "error"); }
  };

  const handleDelete = async (name) => {
    try { await apiDelete(`/api/guilds/${guildId}/custom-commands/${name}`); showToast("Eliminado"); load(); }
    catch (e) { showToast(e.message, "error"); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner"/><p>Cargando…</p></div>;

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0 }}>Comandos Personalizados</h2>
            <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: "0.85rem" }}>{items.length} comando(s)</p>
          </div>
          <button onClick={() => setShowForm(!showForm)} style={{ padding: "10px 20px", borderRadius: 12, color: "#fff", border: "none", cursor: "pointer", fontWeight: 700, fontSize: "0.85rem", display: "flex", alignItems: "center", gap: 8 }}>
            <i className="fa-solid fa-plus" /> Nuevo comando
          </button>
        </div>
      </div>

      {showForm && (
        <div className="glass-panel" style={{ padding: 24, borderRadius: 22, marginBottom: 20 }}>
          <h3 style={{ margin: "0 0 16px" }}>Crear comando</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Nombre</label>
              <input type="text" placeholder="saludo" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Tipo de trigger</label>
              <select value={form.trigger_type} onChange={e => setForm(f => ({ ...f, trigger_type: e.target.value }))} style={{ width: "100%", padding: "8px 12px", borderRadius: 10, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(139,92,246,0.15)", color: "var(--text)" }}>
                <option value="prefix">Prefijo (!)</option>
                <option value="exact">Exacto</option>
                <option value="contains">Contiene</option>
              </select>
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Trigger</label>
              <input type="text" placeholder="!saludo" value={form.trigger_value} onChange={e => setForm(f => ({ ...f, trigger_value: e.target.value }))} />
            </div>
          </div>
          <div className="config-item" style={{ marginTop: 12, marginBottom: 0 }}>
            <label>Respuesta</label>
            <textarea rows={3} value={form.actions[0]?.content || ""} onChange={e => setForm(f => ({ ...f, actions: [{ type: "reply", content: e.target.value }] }))} placeholder="¡Hola {user}! Bienvenido a {server}" style={{ width: "100%", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(139,92,246,0.15)", borderRadius: 10, padding: "8px 12px", color: "var(--text)", fontFamily: "var(--font-main)", fontSize: "0.84rem", resize: "vertical" }} />
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
            <button onClick={() => setShowForm(false)} style={{ padding: "8px 18px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.05)", color: "var(--text)", cursor: "pointer" }}>Cancelar</button>
            <button onClick={handleAdd} style={{ padding: "8px 18px", borderRadius: 10, color: "#fff", border: "none", cursor: "pointer", fontWeight: 700 }}><i className="fa-solid fa-plus" style={{ marginRight: 6 }} />Crear</button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <i className="fa-solid fa-terminal" style={{ fontSize: "2.5rem", marginBottom: 12, display: "block", color: "var(--muted)" }} />
          <h3 style={{ margin: "0 0 8px" }}>Sin comandos personalizados</h3>
          <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.85rem" }}>Crea tu primer comando.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map(cmd => {
            const actions = typeof cmd.actions === "string" ? JSON.parse(cmd.actions || "[]") : (cmd.actions || []);
            return (
              <div key={cmd.id || cmd.name} className="glass-panel" style={{ padding: "16px 20px", borderRadius: 16, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, opacity: cmd.enabled ? 1 : 0.5 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <span style={{ fontWeight: 800, fontSize: "0.92rem" }}>{cmd.name}</span>
                    <span style={{ padding: "2px 8px", borderRadius: 99, fontSize: "0.7rem", fontWeight: 700, background: "rgba(99,102,241,0.15)", color: "#818cf8", border: "1px solid rgba(99,102,241,0.25)" }}>{cmd.trigger_type}</span>
                    <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "var(--muted)" }}>{cmd.trigger_value}</span>
                  </div>
                  <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
                    {actions[0]?.content ? actions[0].content.substring(0, 80) + (actions[0].content.length > 80 ? "…" : "") : "Sin respuesta"}
                    {cmd.uses > 0 && <span style={{ marginLeft: 12, opacity: 0.7 }}>· {cmd.uses} usos</span>}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <label className="toggle-switch" style={{ transform: "scale(0.85)" }}>
                    <input type="checkbox" checked={!!cmd.enabled} onChange={() => handleToggle(cmd)} />
                    <span className="slider" />
                  </label>
                  <button onClick={() => handleDelete(cmd.name)} title="Eliminar" style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", color: "#ef4444", borderRadius: 10, padding: "8px 12px", cursor: "pointer" }}>
                    <i className="fa-solid fa-trash" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
