import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPatch, apiPost, apiDelete } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";

export default function Levels({ selectedGuild: guildId }) {
  const [tab, setTab] = useState("config");
  const [cfg, setCfg] = useState(null);
  const [rewards, setRewards] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [newReward, setNewReward] = useState({ level: "", role_id: "" });
  const [addingReward, setAddingReward] = useState(false);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const lvData = await apiGet(`/api/guilds/${guildId}/levels`);
      setCfg(lvData.config || {});
      setRewards(lvData.rewards || []);
    } catch {
      showToast("Error cargando niveles", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => {
    load();
  }, [load]);

  const set = (k, v) => {
    setCfg((p) => ({ ...p, [k]: v }));
    setDirty(true);
  };
  const setId = (k) => (v) => set(k, v ? parseInt(v, 10) : null);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        enabled: cfg.enabled ? 1 : 0,
        xp_min: cfg.xp_min ?? 15,
        xp_max: cfg.xp_max ?? 25,
        cooldown_seconds: cfg.cooldown_seconds ?? 60,
        announcement_channel_id: cfg.announcement_channel_id ?? null,
        announcement_message: cfg.announcement_message ?? null,
        stack_rewards: cfg.stack_rewards ? 1 : 0,
        levelup_persist: cfg.levelup_persist ? 1 : 0,
        levelup_autodelete: cfg.levelup_autodelete ? 1 : 0,
        levelup_delete_after_seconds: cfg.levelup_delete_after_seconds ?? 30,
        levelup_embed_config: cfg.levelup_embed_config ?? null,
      };
      await apiPatch(`/api/guilds/${guildId}/levels`, payload);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const addReward = async () => {
    if (!newReward.level || !newReward.role_id)
      return showToast("Nivel y rol son requeridos", "error");
    setAddingReward(true);
    try {
      await apiPost(`/api/guilds/${guildId}/levels/rewards`, {
        level: parseInt(newReward.level),
        role_id: parseInt(newReward.role_id),
      });
      setNewReward({ level: "", role_id: "" });
      const data = await apiGet(`/api/guilds/${guildId}/levels`, {
        cache: false,
      });
      setRewards(data.rewards || []);
      showToast("Recompensa añadida");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setAddingReward(false);
    }
  };

  const deleteReward = async (level) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/levels/rewards/${level}`);
      setRewards((r) => r.filter((x) => x.level !== level));
      showToast("Recompensa eliminada");
    } catch (e) {
      showToast(e.message, "error");
    }
  };

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando niveles…</p>
      </div>
    );

  const renderChannel = (opt) => (
    <>
      <Icon name="channel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
    </>
  );
  const renderRole = (opt) => (
    <>
      {opt.color ? (
        <span className="ss-swatch" style={{ background: opt.color }} aria-hidden="true" />
      ) : (
        <Icon name="role" />
      )}
      <span className="ss-option-label">{opt.name}</span>
    </>
  );

  // Texto para describir el comportamiento del mensaje según las flags.
  const persist = !!cfg?.levelup_persist;
  const autodel = !!cfg?.levelup_autodelete;
  const ttl = cfg?.levelup_delete_after_seconds ?? 30;
  const willDelete = !persist || autodel;

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
          Niveles
        </h2>
      </div>

      <div className="tabs-container">
        {[
          ["config", "Configuración"],
          ["rewards", `Recompensas (${rewards.length})`],
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

      {tab === "config" && cfg && (
        <>
          <div
            className="glass-panel mod-section"
            style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div className="config-item inline-check" style={{ marginBottom: 0 }}>
              <div>
                <div style={{ fontWeight: 800 }}>Sistema de XP activo</div>
                <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                  Los usuarios ganan XP al enviar mensajes.
                </div>
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
                gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
                gap: 14,
              }}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>XP mínimo / mensaje</label>
                <input
                  type="number"
                  min="1"
                  max="1000"
                  value={cfg.xp_min ?? 15}
                  onChange={(e) => set("xp_min", parseInt(e.target.value))}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>XP máximo / mensaje</label>
                <input
                  type="number"
                  min="1"
                  max="1000"
                  value={cfg.xp_max ?? 25}
                  onChange={(e) => set("xp_max", parseInt(e.target.value))}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Cooldown (segundos)</label>
                <input
                  type="number"
                  min="0"
                  max="3600"
                  value={cfg.cooldown_seconds ?? 60}
                  onChange={(e) => set("cooldown_seconds", parseInt(e.target.value))}
                />
              </div>
            </div>
          </div>

          <div
            className="glass-panel mod-section"
            style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Anuncio de subida de nivel</h3>
            </div>

            <div className="config-item">
              <label>Canal de anuncios</label>
              <SearchableSelect
                value={cfg.announcement_channel_id || ""}
                onChange={setId("announcement_channel_id")}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="Mismo canal del mensaje (default)…"
                renderOption={renderChannel}
                renderSelected={(opt) => (
                  <><Icon name="channel" /> {opt.name}</>
                )}
              />
            </div>

            <div className="config-item">
              <label>Mensaje de subida (texto plano)</label>
              <input
                type="text"
                value={cfg.announcement_message || ""}
                placeholder="¡{user} ha subido al nivel {level}!"
                onChange={(e) => set("announcement_message", e.target.value)}
              />
              <span style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
                Variables: <code>{"{user}"}</code> <code>{"{level}"}</code>{" "}
                <code>{"{username}"}</code>
              </span>
            </div>

            <div className="config-item inline-check" style={{ marginBottom: 0 }}>
              <div>
                <div style={{ fontWeight: 700 }}>Persistir mensaje</div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  Si está activo, el mensaje queda en el canal. Si lo desactivas
                  el bot lo borra automáticamente al cabo de {ttl}s.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!cfg.levelup_persist}
                  onChange={(e) =>
                    set("levelup_persist", e.target.checked ? 1 : 0)
                  }
                />
                <span className="slider" />
              </label>
            </div>

            <div className="config-item inline-check" style={{ marginBottom: 0 }}>
              <div>
                <div style={{ fontWeight: 700 }}>Autoeliminar siempre</div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  Aplica delete_after incluso si "Persistir" está activo. Útil
                  si quieres mensajes efímeros incondicionales.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!cfg.levelup_autodelete}
                  onChange={(e) =>
                    set("levelup_autodelete", e.target.checked ? 1 : 0)
                  }
                />
                <span className="slider" />
              </label>
            </div>

            <div className="config-item" style={{ marginBottom: 0, maxWidth: 220 }}>
              <label>Borrar después de (seg)</label>
              <input
                type="number"
                min="3"
                max="3600"
                value={cfg.levelup_delete_after_seconds ?? 30}
                onChange={(e) =>
                  set("levelup_delete_after_seconds", parseInt(e.target.value))
                }
                disabled={!willDelete}
                style={{ opacity: willDelete ? 1 : 0.4 }}
              />
            </div>

            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Embed personalizado (JSON, opcional)</label>
              <textarea
                rows={6}
                value={cfg.levelup_embed_config || ""}
                placeholder='{"title":"Subiste de nivel","description":"{user} ahora es nivel {level}","color":3447003}'
                onChange={(e) =>
                  set("levelup_embed_config", e.target.value || null)
                }
                spellCheck={false}
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  background: "var(--panel)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--text)",
                  fontFamily: "ui-monospace, Menlo, Consolas, monospace",
                  fontSize: "0.82rem",
                  resize: "vertical",
                }}
              />
              <span style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
                Si está vacío, se usa el mensaje de texto. Variables disponibles
                en <code>title</code> y <code>description</code>.
              </span>
            </div>

            <div className="config-item inline-check" style={{ marginBottom: 0 }}>
              <div>
                <div style={{ fontWeight: 700 }}>Apilar roles de recompensa</div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  Si está activo, el usuario conserva los roles previos al subir.
                  Si lo apagas, se sustituye por el último.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!cfg.stack_rewards}
                  onChange={(e) =>
                    set("stack_rewards", e.target.checked ? 1 : 0)
                  }
                />
                <span className="slider" />
              </label>
            </div>
          </div>


        </>
      )}

      {tab === "rewards" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div
            className="glass-panel mod-section"
            style={{ padding: 20, borderRadius: 22 }}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Añadir recompensa</h3>
            </div>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                alignItems: "flex-end",
              }}
            >
              <div className="config-item" style={{ marginBottom: 0, flex: "0 0 120px" }}>
                <label>Nivel</label>
                <input
                  type="number"
                  min="1"
                  max="500"
                  placeholder="5"
                  value={newReward.level}
                  onChange={(e) =>
                    setNewReward((p) => ({ ...p, level: e.target.value }))
                  }
                />
              </div>
              <div
                className="config-item"
                style={{ marginBottom: 0, flex: 1, minWidth: 220 }}
              >
                <label>Rol a otorgar</label>
                <SearchableSelect
                  value={newReward.role_id}
                  onChange={(v) =>
                    setNewReward((p) => ({ ...p, role_id: v || "" }))
                  }
                  endpoint={`/api/guilds/${guildId}/roles`}
                  itemsKey="roles"
                  placeholder="Selecciona un rol…"
                  renderOption={renderRole}
                  renderSelected={(opt) => (
                    <>
                      {opt.color ? (
                        <span
                          className="ss-swatch"
                          style={{ background: opt.color }}
                          aria-hidden="true"
                        />
                      ) : (
                        <Icon name="role" />
                      )}{" "}
                      {opt.name}
                    </>
                  )}
                />
              </div>
              <button
                className="btn-primary"
                onClick={addReward}
                disabled={addingReward}
                style={{ height: 42, padding: "0 20px", borderRadius: 12, flexShrink: 0 }}
              >
                <Icon name="add" /> {addingReward ? "Añadiendo…" : "Añadir"}
              </button>
            </div>
          </div>

          <div
            className="glass-panel mod-section"
            style={{ padding: 20, borderRadius: 22 }}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Recompensas configuradas ({rewards.length})</h3>
            </div>
            {rewards.length === 0 && (
              <div className="no-results">
                <p>No hay recompensas. Añade una arriba.</p>
              </div>
            )}
            <div style={{ display: "grid", gap: 10 }}>
              {[...rewards]
                .sort((a, b) => a.level - b.level)
                .map((r) => (
                  <div
                    key={r.level}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: "12px 16px",
                      borderRadius: 14,
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 12,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                        background:
                          "linear-gradient(135deg,rgba(99,102,241,0.25),rgba(139,92,246,0.15))",
                        fontWeight: 900,
                        fontSize: "0.95rem",
                        color: "#c4b5fd",
                      }}
                    >
                      Lv.{r.level}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700 }}>Nivel {r.level}</div>
                      <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
                        Rol id <code>{r.role_id}</code>
                      </div>
                    </div>
                    <button
                      onClick={() => deleteReward(r.level)}
                      aria-label="Eliminar recompensa"
                      style={{
                        background: "rgba(244,63,94,0.12)",
                        border: "1px solid rgba(244,63,94,0.25)",
                        borderRadius: 8,
                        padding: "6px 12px",
                        color: "#f43f5e",
                        cursor: "pointer",
                        fontSize: "0.82rem",
                        fontWeight: 700,
                      }}
                    >
                      <Icon name="close" />
                    </button>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
