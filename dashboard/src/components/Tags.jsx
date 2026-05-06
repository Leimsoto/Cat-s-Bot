import { useEffect, useState, useCallback } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import Toast from "./Toast";

const EMPTY_FORM = { name: "", content: "" };

export default function Tags({ selectedGuild }) {
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(() => {
    if (!selectedGuild) return;
    setLoading(true);
    apiGet(`/api/guilds/${selectedGuild}/tags`)
      .then((d) => setTags(d?.tags || []))
      .catch(() => setTags([]))
      .finally(() => setLoading(false));
  }, [selectedGuild]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = tags.filter(
    (t) =>
      t.name?.toLowerCase().includes(search.toLowerCase()) ||
      t.content?.toLowerCase().includes(search.toLowerCase()),
  );

  const createTag = async () => {
    if (!form.name.trim()) return showToast("El nombre es requerido", "error");
    if (!form.content.trim())
      return showToast("El contenido es requerido", "error");
    setCreating(true);
    try {
      await apiPost(`/api/guilds/${selectedGuild}/tags`, {
        name: form.name.trim().toLowerCase().replace(/\s+/g, "-"),
        content: form.content.trim(),
      });
      showToast("✅ Tag creado");
      setForm(EMPTY_FORM);
      setShowCreate(false);
      load();
    } catch (e) {
      showToast(e.message || "Error al crear tag", "error");
    } finally {
      setCreating(false);
    }
  };

  const deleteTag = async (name) => {
    try {
      await apiDelete(`/api/guilds/${selectedGuild}/tags/${name}`);
      showToast("Tag eliminado");
      setTags((t) => t.filter((x) => x.name !== name));
    } catch (e) {
      showToast(e.message || "Error al eliminar", "error");
    }
  };

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando tags…</p>
      </div>
    );

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      {/* Header */}
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div>
            <h2
              style={{
                background: "linear-gradient(90deg,#c4b5fd,#818cf8)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                margin: 0,
              }}
            >
              Tags / Comandos Personalizados
            </h2>
            <p
              style={{
                color: "var(--muted)",
                margin: "4px 0 0",
                fontSize: "0.88rem",
              }}
            >
              {tags.length} tag(s) configurado(s)
            </p>
          </div>
          <button
            onClick={() => setShowCreate((s) => !s)}
            className="btn-primary"
            style={{
              padding: "10px 20px",
              borderRadius: 12,
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: "0.9rem",
            }}
          >
            <span style={{ fontSize: "1.1rem" }}>{showCreate ? "✕" : "+"}</span>
            {showCreate ? "Cancelar" : "Crear tag"}
          </button>
        </div>
      </div>

      {/* Formulario de creación */}
      {showCreate && (
        <div
          className="glass-panel animate-fade-in"
          style={{ padding: 24, marginBottom: 24 }}
        >
          <div
            style={{
              fontWeight: 800,
              fontSize: "1rem",
              borderBottom: "1px solid rgba(139,92,246,0.15)",
              paddingBottom: 12,
              marginBottom: 20,
            }}
          >
            Nuevo Tag
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Nombre del comando</label>
              <input
                type="text"
                placeholder="info, reglas, ayuda…"
                value={form.name}
                onChange={(e) =>
                  setForm((p) => ({ ...p, name: e.target.value }))
                }
              />
              <span style={{ fontSize: "0.73rem", color: "var(--muted)" }}>
                Se convertirá a minúsculas con guiones
              </span>
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Contenido (respuesta del tag)</label>
              <div className="lg-input-wrap">
                <div className="lg-input-inner">
                  <textarea
                    rows={4}
                    placeholder="El contenido que enviará el bot cuando alguien use /tag nombre…"
                    value={form.content}
                    onChange={(e) =>
                      setForm((p) => ({ ...p, content: e.target.value }))
                    }
                  />
                  <div className="lg-input-actions">
                    <span
                      style={{
                        fontSize: "0.72rem",
                        color: "rgba(200,200,220,0.4)",
                      }}
                    >
                      {form.content.length}/1900 chars
                    </span>
                    <button
                      className="lg-submit-btn"
                      onClick={createTag}
                      disabled={creating}
                      title="Crear tag"
                    >
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <line x1="22" y1="2" x2="11" y2="13" />
                        <polygon points="22 2 15 22 11 13 2 9 22 2" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div
              style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}
            >
              <button
                className="btn-secondary"
                onClick={() => {
                  setShowCreate(false);
                  setForm(EMPTY_FORM);
                }}
              >
                Cancelar
              </button>
              <button
                className="btn-primary btn-save"
                onClick={createTag}
                disabled={creating}
                style={{ padding: "10px 24px", borderRadius: 12 }}
              >
                {creating ? "Creando…" : "✅ Crear tag"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Búsqueda */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 20,
          background: "rgba(0,0,0,0.25)",
          border: "1px solid rgba(139,92,246,0.2)",
          borderRadius: 14,
          padding: "11px 16px",
        }}
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#a78bfa"
          strokeWidth="2.5"
          strokeLinecap="round"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          placeholder="Buscar por nombre o contenido…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: "var(--text)",
            fontSize: "0.88rem",
            fontFamily: "var(--font-main)",
          }}
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--muted)",
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Lista */}
      {filtered.length === 0 ? (
        <div
          className="glass-panel"
          style={{ padding: "48px", textAlign: "center" }}
        >
          <div style={{ fontSize: "2.5rem", marginBottom: 12 }}>🏷️</div>
          <h3 style={{ margin: "0 0 8px" }}>
            {search ? "Sin resultados" : "Sin tags configurados"}
          </h3>
          <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.85rem" }}>
            {search
              ? "Prueba con otro término."
              : "Crea tu primer tag con el botón de arriba."}
          </p>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))",
            gap: 14,
          }}
        >
          {filtered.map((tag) => (
            <div
              key={tag.name}
              className="glass-panel"
              style={{ padding: 18, position: "relative" }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginBottom: 10,
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 10,
                    flexShrink: 0,
                    background: "rgba(56,189,248,0.12)",
                    color: "#38bdf8",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "1rem",
                  }}
                >
                  🏷️
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong
                    style={{
                      fontSize: "0.95rem",
                      display: "block",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    /{tag.name}
                  </strong>
                  {tag.uses !== undefined && (
                    <span
                      style={{ fontSize: "0.72rem", color: "var(--muted)" }}
                    >
                      {tag.uses} uso{tag.uses !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => deleteTag(tag.name)}
                  style={{
                    background: "rgba(244,63,94,0.1)",
                    border: "1px solid rgba(244,63,94,0.2)",
                    borderRadius: 8,
                    padding: "5px 10px",
                    color: "#f43f5e",
                    cursor: "pointer",
                    fontSize: "0.76rem",
                    fontWeight: 700,
                    flexShrink: 0,
                  }}
                >
                  ✕
                </button>
              </div>
              <p
                style={{
                  margin: 0,
                  color: "var(--muted)",
                  fontSize: "0.82rem",
                  lineHeight: 1.5,
                  display: "-webkit-box",
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                }}
              >
                {tag.content || "Sin contenido"}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
