import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";

const RULE_META = {
  spam: {
    label: "Anti-Spam",
    desc: "Detecta mensajes repetidos o envíos masivos",
    icon: "fa-ban",
    color: "#ef4444",
  },
  mentions: {
    label: "Menciones masivas",
    desc: "Limita la cantidad de menciones por mensaje",
    icon: "fa-at",
    color: "#f97316",
  },
  caps: {
    label: "Mayúsculas",
    desc: "Limita el % de mayúsculas en un mensaje",
    icon: "fa-font",
    color: "#eab308",
  },
  links: {
    label: "Anti-Links",
    desc: "Bloquea enlaces no autorizados",
    icon: "fa-link",
    color: "#3b82f6",
  },
  words: {
    label: "Palabras prohibidas",
    desc: "Filtra mensajes con palabras de la lista negra",
    icon: "fa-comment-slash",
    color: "#8b5cf6",
  },
  invites: {
    label: "Anti-Invites",
    desc: "Bloquea enlaces de invitación de Discord",
    icon: "fa-paper-plane",
    color: "#ec4899",
  },
};

export default function AutoMod({ selectedGuild: guildId }) {
  const [cfg, setCfg] = useState(null);
  const [logs, setLogs] = useState([]);
  const [tab, setTab] = useState("rules");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/automod`);
      setCfg(data || { enabled: 1, rules: {} });
    } catch {
      showToast("Error cargando automod", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  const loadLogs = useCallback(async () => {
    if (!guildId) return;
    try {
      const data = await apiGet(`/api/guilds/${guildId}/automod/log?limit=50`, {
        cache: false,
      });
      setLogs(Array.isArray(data) ? data : data.logs || []);
    } catch {
      setLogs([]);
    }
  }, [guildId]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (tab === "log") loadLogs();
  }, [tab, loadLogs]);

  const set = (k, v) => {
    setCfg((p) => ({ ...p, [k]: v }));
    setDirty(true);
  };

  const setRule = (ruleName, field, value) => {
    setCfg((prev) => {
      const rules =
        typeof prev.rules === "string"
          ? JSON.parse(prev.rules || "{}")
          : prev.rules || {};
      const rule = rules[ruleName] || { enabled: false };
      rules[ruleName] = { ...rule, [field]: value };
      return { ...prev, rules };
    });
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...cfg,
        rules:
          typeof cfg.rules === "object"
            ? JSON.stringify(cfg.rules)
            : cfg.rules,
      };
      await apiPatch(`/api/guilds/${guildId}/automod`, payload);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando…</p>
      </div>
    );

  const rules =
    typeof cfg?.rules === "string"
      ? JSON.parse(cfg.rules || "{}")
      : cfg?.rules || {};

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <h2
          style={{
            background: "linear-gradient(90deg,#c4b5fd,#818cf8)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          Automoderación
        </h2>
        <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: "4px 0 0" }}>
          Protección automática contra spam, links y contenido no deseado
        </p>
      </div>

      <div className="tabs-container">
        {[
          ["rules", "Reglas"],
          ["log", "Registro"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={`tab-btn ${tab === id ? "active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "rules" && cfg && (
        <>
          <div
            className="glass-panel"
            style={{
              padding: 24,
              borderRadius: 22,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <div>
              <h3 style={{ margin: 0 }}>Sistema de Automoderación</h3>
              <p
                style={{
                  color: "var(--muted)",
                  margin: "4px 0 0",
                  fontSize: "0.84rem",
                }}
              >
                {cfg.enabled ? "Activo — monitoreando mensajes" : "Desactivado"}
              </p>
            </div>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!cfg.enabled}
                onChange={(e) => set("enabled", e.target.checked ? 1 : 0)}
              />
              <span className="slider" />
            </label>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))",
              gap: 16,
            }}
          >
            {Object.entries(RULE_META).map(([key, meta]) => {
              const rule = rules[key] || {};
              const isOn = !!rule.enabled;
              return (
                <div
                  key={key}
                  className="glass-panel"
                  style={{
                    padding: 20,
                    borderRadius: 18,
                    border: `1px solid ${isOn ? meta.color + "40" : "rgba(255,255,255,0.06)"}`,
                    background: isOn
                      ? meta.color + "08"
                      : "rgba(255,255,255,0.02)",
                    transition: "all 0.2s",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: 10,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <i
                        className={`fa-solid ${meta.icon}`}
                        style={{ color: meta.color, fontSize: "1.1rem" }}
                      />
                      <div>
                        <div style={{ fontWeight: 800 }}>{meta.label}</div>
                        <div
                          style={{
                            fontSize: "0.78rem",
                            color: "var(--muted)",
                          }}
                        >
                          {meta.desc}
                        </div>
                      </div>
                    </div>
                    <label className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={isOn}
                        onChange={(e) =>
                          setRule(key, "enabled", e.target.checked)
                        }
                      />
                      <span className="slider" />
                    </label>
                  </div>

                  {key === "mentions" && isOn && (
                    <div className="config-item" style={{ marginBottom: 0 }}>
                      <label>Máx. menciones por mensaje</label>
                      <input
                        type="number"
                        min="1"
                        max="50"
                        value={rule.max_mentions ?? 5}
                        onChange={(e) =>
                          setRule(key, "max_mentions", parseInt(e.target.value))
                        }
                      />
                    </div>
                  )}
                  {key === "caps" && isOn && (
                    <div className="config-item" style={{ marginBottom: 0 }}>
                      <label>% máximo de mayúsculas</label>
                      <input
                        type="number"
                        min="30"
                        max="100"
                        value={rule.max_caps_percent ?? 70}
                        onChange={(e) =>
                          setRule(
                            key,
                            "max_caps_percent",
                            parseInt(e.target.value)
                          )
                        }
                      />
                    </div>
                  )}
                  {key === "words" && isOn && (
                    <div className="config-item" style={{ marginBottom: 0 }}>
                      <label>Palabras prohibidas (separar con coma)</label>
                      <textarea
                        rows={3}
                        value={(rule.words || []).join(", ")}
                        onChange={(e) =>
                          setRule(
                            key,
                            "words",
                            e.target.value
                              .split(",")
                              .map((w) => w.trim())
                              .filter(Boolean)
                          )
                        }
                        style={{
                          width: "100%",
                          background: "rgba(0,0,0,0.2)",
                          border: "1px solid rgba(139,92,246,0.15)",
                          borderRadius: 10,
                          padding: "8px 12px",
                          color: "var(--text)",
                          fontFamily: "var(--font-main)",
                          fontSize: "0.84rem",
                          resize: "vertical",
                        }}
                      />
                    </div>
                  )}
                  {key === "spam" && isOn && (
                    <div className="config-item" style={{ marginBottom: 0 }}>
                      <label>Mensajes duplicados antes de actuar</label>
                      <input
                        type="number"
                        min="2"
                        max="20"
                        value={rule.duplicate_threshold ?? 4}
                        onChange={(e) =>
                          setRule(
                            key,
                            "duplicate_threshold",
                            parseInt(e.target.value)
                          )
                        }
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {tab === "log" && (
        <div className="glass-panel" style={{ overflow: "hidden" }}>
          {logs.length === 0 ? (
            <div
              style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}
            >
              <i
                className="fa-solid fa-shield-halved"
                style={{ fontSize: "2.5rem", marginBottom: 12, display: "block" }}
              />
              <p>No hay acciones de automoderación registradas.</p>
            </div>
          ) : (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "0.84rem",
              }}
            >
              <thead>
                <tr
                  style={{
                    borderBottom: "1px solid rgba(255,255,255,0.07)",
                  }}
                >
                  {["Regla", "Usuario", "Acción", "Fecha"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "12px 16px",
                        textAlign: "left",
                        fontWeight: 700,
                        color: "var(--muted)",
                        fontSize: "0.75rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.map((l, i) => {
                  const meta = RULE_META[l.rule] || {
                    label: l.rule,
                    color: "#7a9bb5",
                  };
                  return (
                    <tr
                      key={l.id || i}
                      style={{
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <td style={{ padding: "10px 16px" }}>
                        <span
                          style={{
                            padding: "3px 10px",
                            borderRadius: 99,
                            fontSize: "0.74rem",
                            fontWeight: 700,
                            background: meta.color + "18",
                            color: meta.color,
                            border: `1px solid ${meta.color}30`,
                          }}
                        >
                          {meta.label}
                        </span>
                      </td>
                      <td
                        style={{
                          padding: "10px 16px",
                          fontFamily: "monospace",
                          fontSize: "0.78rem",
                        }}
                      >
                        {l.user_id}
                      </td>
                      <td style={{ padding: "10px 16px", color: "var(--muted)" }}>
                        {l.action_taken}
                      </td>
                      <td
                        style={{
                          padding: "10px 16px",
                          color: "var(--muted)",
                          fontSize: "0.76rem",
                        }}
                      >
                        {l.created_at
                          ? new Date(l.created_at).toLocaleDateString("es")
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
