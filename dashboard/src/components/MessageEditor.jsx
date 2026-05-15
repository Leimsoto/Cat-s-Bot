/**
 * MessageEditor.jsx
 * ─────────────────
 * Editor de mensajes reutilizable con vista previa estilo Discord.
 *
 * Cubre tanto:
 *   • Mensaje plano: solo `content` (texto).
 *   • Embed: title, description, color, autor, footer, imágenes.
 *
 * El estado lo gestiona el padre (controlled component) para que sea trivial
 * persistir en backend. El valor es siempre la forma:
 *
 *   {
 *     content: string,
 *     embed: { title, description, color, footer, footer_icon,
 *              image, thumbnail, author, author_icon, author_url },
 *     enabled: boolean   // ¿usar embed o solo content?
 *   }
 *
 * Props:
 *   value               objeto con la forma anterior (o null/undefined).
 *   onChange(next)      callback que recibe el nuevo objeto.
 *   placeholders        objeto opcional con texto guía para tabs (ej. variables
 *                       disponibles).
 *   mode                "embed" (por defecto) | "plain" | "both".
 *   compact             si true, reduce paddings (para modales y panels chicos).
 *   showJson            si true, muestra el bloque JSON colapsable.
 */

import { useMemo } from "react";

export const EMPTY_MESSAGE = {
  content: "",
  enabled: true,
  embed: {
    title: "",
    description: "",
    color: "#6366f1",
    footer: "",
    footer_icon: "",
    image: "",
    thumbnail: "",
    author: "",
    author_icon: "",
    author_url: "",
  },
};

export function normalizeMessage(raw) {
  const base = { ...EMPTY_MESSAGE };
  if (!raw || typeof raw !== "object") return base;
  return {
    content: raw.content ?? "",
    enabled: raw.enabled !== false,
    embed: { ...EMPTY_MESSAGE.embed, ...(raw.embed || {}) },
  };
}

const SWATCHES = [
  "#ef4444", "#f472b6", "#f97316", "#facc15", "#84cc16",
  "#10b981", "#0ea5e9", "#6366f1", "#8b5cf6", "#a78bfa",
];

export default function MessageEditor({
  value,
  onChange,
  mode = "embed",
  compact = false,
  showJson = false,
  placeholders = {},
  variablesHelp = "",
  tab,
  setTab,
}) {
  const v = useMemo(() => normalizeMessage(value), [value]);

  const showEmbedTabs = mode !== "plain";
  const showPlainTab = mode !== "embed";

  const TABS = useMemo(() => {
    const tabs = [];
    if (showPlainTab) tabs.push(["content", "💬 Mensaje"]);
    if (showEmbedTabs) {
      tabs.push(["embed-content", "✏️ Embed"]);
      tabs.push(["author", "👤 Autor/Footer"]);
      tabs.push(["media", "🖼️ Imágenes"]);
    }
    return tabs;
  }, [showEmbedTabs, showPlainTab]);

  const activeTab = tab || TABS[0]?.[0];
  const handleTab = setTab || (() => {});

  const setEmbed = (k, val) =>
    onChange({ ...v, embed: { ...v.embed, [k]: val } });
  const setContent = (val) => onChange({ ...v, content: val });
  const setEnabled = (val) => onChange({ ...v, enabled: val });

  const padding = compact ? 14 : 22;

  return (
    <div style={{ display: "grid", gridTemplateColumns: compact ? "1fr" : "1fr 380px", gap: 18, alignItems: "start" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {mode === "both" && (
          <label className="inline-check" style={{ gap: 10, alignItems: "center", display: "flex" }}>
            <input
              type="checkbox"
              checked={!!v.enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span style={{ fontWeight: 700 }}>Mostrar como embed</span>
          </label>
        )}

        <div className="tabs-container">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`tab-btn ${activeTab === id ? "active" : ""}`}
              onClick={() => handleTab(id)}
              style={{ fontSize: "0.8rem", padding: "8px 14px" }}
            >
              {label}
            </button>
          ))}
        </div>

        <div
          className="glass-panel"
          style={{ padding, borderRadius: 18, display: "flex", flexDirection: "column", gap: 12 }}
        >
          {variablesHelp && (
            <div
              style={{
                padding: 10,
                borderRadius: 10,
                background: "rgba(99,102,241,0.06)",
                border: "1px solid rgba(139,92,246,0.15)",
                fontSize: "0.78rem",
                color: "var(--muted)",
                whiteSpace: "pre-wrap",
              }}
            >
              {variablesHelp}
            </div>
          )}

          {activeTab === "content" && (
            <div className="config-item">
              <label>Contenido del mensaje (texto plano)</label>
              <textarea
                rows={5}
                value={v.content}
                placeholder={placeholders.content || "Escribe el mensaje…"}
                onChange={(e) => setContent(e.target.value)}
                style={{ width: "100%", resize: "vertical", padding: "10px 12px", fontFamily: "var(--font-main)" }}
              />
            </div>
          )}

          {activeTab === "embed-content" && (
            <>
              <div className="config-item">
                <label>Título</label>
                <input
                  type="text"
                  value={v.embed.title}
                  placeholder={placeholders.title || "Título del embed"}
                  onChange={(e) => setEmbed("title", e.target.value)}
                />
              </div>
              <div className="config-item">
                <label>Descripción</label>
                <textarea
                  rows={5}
                  value={v.embed.description}
                  placeholder={placeholders.description || "Contenido principal del embed…"}
                  onChange={(e) => setEmbed("description", e.target.value)}
                  style={{ width: "100%", resize: "vertical", padding: "10px 12px", fontFamily: "var(--font-main)" }}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Color del borde</label>
                <div className="embed-color-dock" style={{ transform: "perspective(600px)" }}>
                  {SWATCHES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={`ecd-swatch${v.embed.color === c ? " ecd-selected" : ""}`}
                      style={{ "--swatch-color": c }}
                      onClick={() => setEmbed("color", c)}
                      title={c}
                      aria-label={c}
                      data-hex={c}
                    />
                  ))}
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10 }}>
                  <input
                    type="color"
                    value={v.embed.color || "#6366f1"}
                    onChange={(e) => setEmbed("color", e.target.value)}
                    style={{ height: 38, width: 48, cursor: "pointer", borderRadius: 8, border: "1px solid rgba(139,92,246,0.22)", padding: 2, background: "transparent" }}
                  />
                  <input
                    type="text"
                    value={v.embed.color || ""}
                    onChange={(e) => setEmbed("color", e.target.value)}
                    placeholder="#6366f1"
                    style={{ flex: 1, fontFamily: "monospace" }}
                  />
                </div>
              </div>
            </>
          )}

          {activeTab === "author" && (
            <>
              <div className="config-item">
                <label>Nombre del autor</label>
                <input
                  type="text"
                  value={v.embed.author}
                  onChange={(e) => setEmbed("author", e.target.value)}
                />
              </div>
              <div className="config-item">
                <label>Icono del autor (URL)</label>
                <input
                  type="url"
                  value={v.embed.author_icon}
                  onChange={(e) => setEmbed("author_icon", e.target.value)}
                />
              </div>
              <div className="config-item">
                <label>URL del autor (enlace clickeable)</label>
                <input
                  type="url"
                  value={v.embed.author_url}
                  onChange={(e) => setEmbed("author_url", e.target.value)}
                />
              </div>
              <hr style={{ borderColor: "rgba(139,92,246,0.15)" }} />
              <div className="config-item">
                <label>Texto del footer</label>
                <input
                  type="text"
                  value={v.embed.footer}
                  onChange={(e) => setEmbed("footer", e.target.value)}
                />
              </div>
              <div className="config-item">
                <label>Icono del footer (URL)</label>
                <input
                  type="url"
                  value={v.embed.footer_icon}
                  onChange={(e) => setEmbed("footer_icon", e.target.value)}
                />
              </div>
            </>
          )}

          {activeTab === "media" && (
            <>
              <div className="config-item">
                <label>Imagen grande (URL)</label>
                <input
                  type="url"
                  value={v.embed.image}
                  onChange={(e) => setEmbed("image", e.target.value)}
                />
              </div>
              <div className="config-item">
                <label>Miniatura (URL, esquina superior derecha)</label>
                <input
                  type="url"
                  value={v.embed.thumbnail}
                  onChange={(e) => setEmbed("thumbnail", e.target.value)}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {!compact && (
        <div style={{ position: "sticky", top: 80 }}>
          <p className="sidebar-kicker" style={{ marginBottom: 10 }}>VISTA PREVIA</p>
          <MessagePreview value={v} />
          {showJson && (
            <details style={{ marginTop: 14 }}>
              <summary style={{ color: "var(--muted)", fontSize: "0.78rem", cursor: "pointer", fontWeight: 700, padding: "8px 0" }}>
                Ver JSON
              </summary>
              <pre style={{ marginTop: 8, padding: "12px 14px", borderRadius: 12, fontSize: "0.72rem", background: "rgba(0,0,0,0.4)", border: "1px solid rgba(139,92,246,0.2)", color: "#c4b5fd", overflow: "auto", maxHeight: 220, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(v, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export function MessagePreview({ value }) {
  const v = normalizeMessage(value);
  const e = v.embed;
  return (
    <div
      style={{
        background: "#313338",
        borderRadius: 16,
        padding: 16,
        fontFamily: "Whitney,system-ui,sans-serif",
        minHeight: 80,
      }}
    >
      {v.content && (
        <p style={{ color: "#dbdee1", fontSize: "0.9rem", margin: "0 0 10px", whiteSpace: "pre-wrap" }}>
          {v.content}
        </p>
      )}
      {v.enabled && (e.title || e.description || e.image || e.author) && (
        <div
          style={{
            borderLeft: `4px solid ${e.color || "#6366f1"}`,
            background: "#2b2d31",
            borderRadius: "0 6px 6px 0",
            padding: "12px 16px",
            maxWidth: 440,
          }}
        >
          {e.thumbnail && (
            <img
              src={e.thumbnail}
              alt=""
              style={{ float: "right", width: 64, height: 64, borderRadius: 4, objectFit: "cover", marginLeft: 12 }}
              onError={(ev) => (ev.target.style.display = "none")}
            />
          )}
          {(e.author || e.author_icon) && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              {e.author_icon && (
                <img
                  src={e.author_icon}
                  alt=""
                  style={{ width: 20, height: 20, borderRadius: "50%" }}
                  onError={(ev) => (ev.target.style.display = "none")}
                />
              )}
              {e.author && (
                <p style={{ color: "#dbdee1", fontSize: "0.82rem", margin: 0, fontWeight: 700 }}>
                  {e.author}
                </p>
              )}
            </div>
          )}
          {e.title && (
            <p style={{ color: "#fff", fontWeight: 700, margin: "0 0 6px", fontSize: "1rem" }}>
              {e.title}
            </p>
          )}
          {e.description && (
            <p style={{ color: "#dbdee1", fontSize: "0.875rem", margin: "0 0 8px", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
              {e.description}
            </p>
          )}
          {e.image && (
            <img
              src={e.image}
              alt=""
              style={{ width: "100%", borderRadius: 4, marginTop: 8, objectFit: "cover", maxHeight: 200 }}
              onError={(ev) => (ev.target.style.display = "none")}
            />
          )}
          {(e.footer || e.footer_icon) && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10 }}>
              {e.footer_icon && (
                <img
                  src={e.footer_icon}
                  alt=""
                  style={{ width: 16, height: 16, borderRadius: "50%" }}
                  onError={(ev) => (ev.target.style.display = "none")}
                />
              )}
              {e.footer && (
                <p style={{ color: "#80848e", fontSize: "0.72rem", margin: 0 }}>
                  {e.footer}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
