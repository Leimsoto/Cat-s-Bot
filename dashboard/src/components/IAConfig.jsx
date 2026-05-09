import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";

// Modelos válidos. Debe mantenerse sincronizado con CHAT_MODELS en cogs/ia.py.
// Si añades/quitas modelos del cog, actualizar también esta lista.
const MODELS = [
  { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", subtitle: "Default" },
  { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash-Lite", subtitle: "Rápido" },
  { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", subtitle: "Calidad" },
  { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash", subtitle: "Estable" },
  { id: "gemma-3-27b-it", name: "Gemma 3 (27B)", subtitle: "Open" },
];

export default function IAConfig({ selectedGuild: guildId }) {
  const [cfg, setCfg] = useState(null);
  const [keyAssignment, setKeyAssignment] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [iaCfg, keyData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/ia`),
        apiGet(`/api/guilds/${guildId}/ia/key`).catch(() => ({
          assigned: null,
        })),
      ]);
      setCfg(iaCfg || {});
      setKeyAssignment(keyData?.assigned || null);
    } catch {
      showToast("Error cargando configuración IA", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => {
    load();
  }, [load]);

  const set = (key, val) => {
    setCfg((prev) => ({ ...prev, [key]: val }));
    setDirty(true);
  };
  const setId = (key) => (v) => set(key, v ? parseInt(v, 10) : null);

  const save = async () => {
    setSaving(true);
    try {
      // Solo enviamos columnas reales de ai_config para evitar el ValueError
      // que producía el viejo formulario al usar nombres como "model_name".
      const payload = {
        ai_channel_id: cfg.ai_channel_id ?? null,
        ai_role_id: cfg.ai_role_id ?? null,
        ai_model: cfg.ai_model || null,
        ai_system_prompt: cfg.ai_system_prompt || null,
        ai_limit_requests: cfg.ai_limit_requests ?? 50,
        ai_limit_hours: cfg.ai_limit_hours ?? 12,
        ai_imagine_enabled: cfg.ai_imagine_enabled ? 1 : 0,
        ai_webhook_name: cfg.ai_webhook_name || null,
        ai_webhook_icon: cfg.ai_webhook_icon || null,
      };
      await apiPatch(`/api/guilds/${guildId}/ia`, payload);
      setDirty(false);
      showToast("Configuración IA guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando módulo IA…</p>
      </div>
    );

  // Renderers para SearchableSelect.
  const renderChannelOption = (opt) => (
    <>
      <Icon name="channel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
    </>
  );
  const renderChannelSelected = (opt) => (
    <>
      <Icon name="channel" /> {opt.name}
    </>
  );
  const renderRoleOption = (opt) => (
    <>
      {opt.color ? (
        <span className="ss-swatch" style={{ background: opt.color }} aria-hidden="true" />
      ) : (
        <Icon name="role" />
      )}
      <span className="ss-option-label">{opt.name}</span>
    </>
  );
  const renderModelOption = (opt) => (
    <>
      <Icon name="ia" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.subtitle ? <span className="ss-option-sub">{opt.subtitle}</span> : null}
    </>
  );

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
          Inteligencia Artificial
        </h2>
        <p className="muted-text">
          Configura el asistente de IA del servidor: canal, modelo, prompt y API key.
        </p>
      </div>

      {/* Sección API Key */}
      <div
        className="glass-panel"
        style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 12 }}
      >
        <div className="section-title">
          <h3 style={{ margin: 0 }}>API Key asignada</h3>
        </div>
        {keyAssignment ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "10px 14px",
              background: "var(--accent-light)",
              border: "1px solid var(--border-accent)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <div>
              <div style={{ fontWeight: 700 }}>
                {keyAssignment.label}
                {!keyAssignment.active ? (
                  <span style={{ marginLeft: 10, color: "var(--warning)", fontSize: "0.8rem" }}>
                    (inactiva)
                  </span>
                ) : null}
              </div>
              <code style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                {keyAssignment.api_key_preview}
              </code>
            </div>
            <Icon name="check" style={{ color: "var(--success)" }} />
          </div>
        ) : (
          <div
            style={{
              padding: "10px 14px",
              background: "var(--warning-light)",
              border: "1px solid rgba(245,158,11,0.3)",
              borderRadius: "var(--radius-md)",
              color: "var(--warning)",
              fontSize: "0.88rem",
            }}
          >
            <Icon name="warning" /> Sin key asignada. La IA usará la key global del bot
            (GEMINI_API_KEY) si está configurada, o no responderá. Contacta con el
            administrador del bot para asignar una key dedicada.
          </div>
        )}
      </div>

      {/* Modelo + canales */}
      <div
        className="glass-panel"
        style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 16 }}
      >
        <div className="section-title">
          <h3 style={{ margin: 0 }}>Modelo y ubicación</h3>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))",
            gap: 16,
          }}
        >
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Modelo</label>
            <SearchableSelect
              value={cfg?.ai_model || ""}
              onChange={(v) => set("ai_model", v || null)}
              options={MODELS}
              placeholder="Selecciona un modelo…"
              renderOption={renderModelOption}
              renderSelected={(opt) => (
                <>
                  <Icon name="ia" /> {opt.name}
                </>
              )}
            />
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Canal de IA</label>
            <SearchableSelect
              value={cfg?.ai_channel_id || ""}
              onChange={setId("ai_channel_id")}
              endpoint={`/api/guilds/${guildId}/channels`}
              itemsKey="channels"
              placeholder="Cualquier canal…"
              renderOption={renderChannelOption}
              renderSelected={renderChannelSelected}
            />
            <span style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
              Si seleccionas un canal, la IA solo responde ahí.
            </span>
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Rol con permiso (opcional)</label>
            <SearchableSelect
              value={cfg?.ai_role_id || ""}
              onChange={setId("ai_role_id")}
              endpoint={`/api/guilds/${guildId}/roles`}
              itemsKey="roles"
              placeholder="Sin restricción de rol…"
              renderOption={renderRoleOption}
              renderSelected={(opt) => (
                <>
                  {opt.color ? (
                    <span className="ss-swatch" style={{ background: opt.color }} aria-hidden="true" />
                  ) : (
                    <Icon name="role" />
                  )}{" "}
                  {opt.name}
                </>
              )}
            />
          </div>
        </div>
      </div>

      {/* Prompt + webhook */}
      <div
        className="glass-panel"
        style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div className="section-title">
          <h3 style={{ margin: 0 }}>Personalidad y webhook</h3>
        </div>

        <div className="config-item">
          <label>Prompt del sistema</label>
          <textarea
            rows={6}
            value={cfg?.ai_system_prompt || ""}
            placeholder="Eres un asistente del servidor…"
            onChange={(e) => set("ai_system_prompt", e.target.value)}
            style={{
              width: "100%",
              resize: "vertical",
              padding: "10px 12px",
              background: "var(--panel)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
              color: "var(--text)",
              fontFamily: "var(--font-main)",
              fontSize: "0.9rem",
            }}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Nombre del webhook</label>
            <input
              type="text"
              value={cfg?.ai_webhook_name || ""}
              placeholder="Bot ES IA"
              onChange={(e) => set("ai_webhook_name", e.target.value)}
            />
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Avatar del webhook (URL)</label>
            <input
              type="url"
              value={cfg?.ai_webhook_icon || ""}
              placeholder="https://…"
              onChange={(e) => set("ai_webhook_icon", e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Limites + flags */}
      <div
        className="glass-panel"
        style={{ padding: 24, borderRadius: 22, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div className="section-title">
          <h3 style={{ margin: 0 }}>Límites y comportamiento</h3>
        </div>

        <div className="config-item inline-check">
          <div>
            <div style={{ fontWeight: 700 }}>Multimodal (imágenes/PDF)</div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Permite a la IA leer adjuntos del usuario.
            </div>
          </div>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!cfg?.ai_imagine_enabled}
              onChange={(e) => set("ai_imagine_enabled", e.target.checked ? 1 : 0)}
            />
            <span className="slider" />
          </label>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Máx. requests por usuario</label>
            <input
              type="number"
              min="1"
              max="500"
              value={cfg?.ai_limit_requests ?? 50}
              onChange={(e) => set("ai_limit_requests", parseInt(e.target.value))}
            />
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Ventana del límite (horas)</label>
            <input
              type="number"
              min="1"
              max="72"
              value={cfg?.ai_limit_hours ?? 12}
              onChange={(e) => set("ai_limit_hours", parseInt(e.target.value))}
            />
          </div>
        </div>
      </div>

      <div className={`save-bar-container ${dirty ? "visible" : ""}`}>
        <div className="save-bar">
          <span style={{ color: "var(--muted)", fontSize: "0.88rem" }}>
            Cambios sin guardar
          </span>
          <div className="save-bar-actions">
            <button className="btn-secondary" onClick={load} disabled={saving}>
              Descartar
            </button>
            <button className="btn-primary btn-save" onClick={save} disabled={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
