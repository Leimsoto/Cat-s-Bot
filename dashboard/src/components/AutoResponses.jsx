import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import Toast from "./Toast";

export default function AutoResponses({ selectedGuild: guildId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ trigger: "", response: "" });
  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/autoresponses`, { cache: false });
      setItems(data.autoresponses || []);
    } catch { showToast("Error cargando auto-respuestas", "error"); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.trigger.trim() || !form.response.trim()) return showToast("Campos requeridos", "error");
    try {
      await apiPost(`/api/guilds/${guildId}/autoresponses`, form);
      showToast("Creada"); setForm({ trigger: "", response: "" }); setShowForm(false); load();
    } catch (e) { showToast(e.message, "error"); }
  };

  const handleDelete = async (id) => {
    try { await apiDelete(`/api/guilds/${guildId}/autoresponses/${id}`); showToast("Eliminada"); load(); }
    catch (e) { showToast(e.message, "error"); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner"/><p>Cargando…</p></div>;

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0 }}>Auto-Respuestas</h2>
            <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: "0.85rem" }}>{items.length} configuradas</p>
          </div>
          <button onClick={() => setShowForm(!showForm)} style={{ padding: "10px 20px", borderRadius: 12, color: "#fff", border: "none", cursor: "pointer", fontWeight: 700, fontSize: "0.85rem", display: "flex", alignItems: "center", gap: 8 }}>
            <i className="fa-solid fa-plus" /> Nueva
          </button>
        </div>
      </div>

      {showForm && (
        <div className="glass-panel" style={{ padding: 24, borderRadius: 22, marginBottom: 20 }}>
          <h3 style={{ margin: "0 0 16px" }}>Crear auto-respuesta</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Trigger</label>
              <input type="text" placeholder="Ej: hola" value={form.trigger} onChange={e => setForm(f => ({ ...f, trigger: e.target.value }))} />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Respuesta</label>
              <input type="text" placeholder="Ej: ¡Hola!" value={form.response} onChange={e => setForm(f => ({ ...f, response: e.target.value }))} />
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
            <button onClick={() => setShowForm(false)} style={{ padding: "8px 18px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.05)", color: "var(--text)", cursor: "pointer" }}>Cancelar</button>
            <button onClick={handleAdd} style={{ padding: "8px 18px", borderRadius: 10, color: "#fff", border: "none", cursor: "pointer", fontWeight: 700 }}><i className="fa-solid fa-plus" style={{ marginRight: 6 }} />Crear</button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <i className="fa-solid fa-comments" style={{ fontSize: "2.5rem", marginBottom: 12, display: "block", color: "var(--muted)" }} />
          <h3 style={{ margin: "0 0 8px" }}>Sin auto-respuestas</h3>
          <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.85rem" }}>Crea tu primera auto-respuesta.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map(ar => (
            <div key={ar.id} className="glass-panel" style={{ padding: "16px 20px", borderRadius: 16, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <span style={{ padding: "3px 10px", borderRadius: 99, background: "rgba(139,92,246,0.15)", color: "#c4b5fd", fontSize: "0.78rem", fontWeight: 700, border: "1px solid rgba(139,92,246,0.25)" }}>{ar.trigger}</span>
                <div style={{ fontSize: "0.84rem", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 4 }}>→ {ar.response}</div>
              </div>
              <button onClick={() => handleDelete(ar.id)} title="Eliminar" style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", color: "#ef4444", borderRadius: 10, padding: "8px 12px", cursor: "pointer" }}>
                <i className="fa-solid fa-trash" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
