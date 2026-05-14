import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";

export default function VoiceGen({ selectedGuild: guildId }) {
  const [cfg, setCfg] = useState(null);
  const [activeVCs, setActiveVCs] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [tab, setTab] = useState("config");

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const [cfgData, vcData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/voice-gen/config`),
        apiGet(`/api/guilds/${guildId}/voice-gen/channels`).catch(() => ({
          active_channels: []})),
      ]);
      setCfg(cfgData.config || {});
      setActiveVCs(vcData.active_channels || []);
    } catch {
      showToast("Error cargando configuración", "error");
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
      // Solo columnas válidas. Cualquier extra se ignora server-side, pero
      // mantenerlo limpio evita confusión.
      const payload = {
        enabled: cfg?.enabled ? 1 : 0,
        generator_channel_id: cfg?.generator_channel_id ?? null,
        category_id: cfg?.category_id ?? null,
        panel_channel_id: cfg?.panel_channel_id ?? null,
        name_template: cfg?.name_template ?? null,
        default_limit: cfg?.default_limit ?? 0,
        panel_title: cfg?.panel_title ?? null,
        panel_description: cfg?.panel_description ?? null,
        panel_color: cfg?.panel_color ?? null,
        auto_send_panel: cfg?.auto_send_panel ? 1 : 0};
      await apiPatch(`/api/guilds/${guildId}/voice-gen/config`, payload);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message || "Error guardando", "error");
    } finally {
      setSaving(false);
    }
  };

  const resendPanel = async (channel_id) => {
    try {
      await apiPost(`/api/guilds/${guildId}/voice-gen/resend-panel`, {
        channel_id});
      showToast("Panel reenviado");
    } catch (e) {
      showToast(e.message || "Error reenviando panel", "error");
    }
  };

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando Generador de VCs…</p>
      </div>
    );

  // Renderers para SearchableSelect.
  const renderVoiceOption = (opt) => (
    <>
      <Icon name="voiceChannel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
    </>
  );
  const renderVoiceSelected = (opt) => (
    <>
      <Icon name="voiceChannel" /> {opt.name}
    </>
  );
  const renderTextOption = (opt) => (
    <>
      <Icon name="channel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
    </>
  );
  const renderTextSelected = (opt) => (
    <>
      <Icon name="channel" /> {opt.name}
    </>
  );
  const renderCategoryOption = (opt) => (
    <>
      <Icon name="category" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.channel_count != null ? (
        <span className="ss-option-sub">{opt.channel_count} canales</span>
      ) : null}
    </>
  );
  const renderCategorySelected = (opt) => (
    <>
      <Icon name="category" /> {opt.name}
    </>
  );

  const previewName = (cfg?.name_template || "{username}'s VC")
    .replace("{username}", "yessid")
    .replace("{user}", "yessid#0");

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
            gap: 12}}
        >
          <div>
            <h2
              style={{
                margin: 0}}
            >
              Generador de VCs
            </h2>
            <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: "0.88rem" }}>
              Cada usuario que entre al canal Hub recibe su propio canal de voz
              privado con panel de control personalizable.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>Sistema</span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!cfg?.enabled}
                onChange={(e) => set("enabled", e.target.checked ? 1 : 0)}
              />
              <span className="slider" />
            </label>
            <span
              style={{
                fontSize: "0.8rem",
                fontWeight: 700,
                color: cfg?.enabled ? "#34d399" : "var(--muted)"}}
            >
              {cfg?.enabled ? "Activo" : "Inactivo"}
            </span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs-container" style={{ marginBottom: 20 }}>
        {[
          ["config", "Configuración"],
          ["panel", "Panel"],
          ["active", `VCs activos (${activeVCs.length})`],
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

      {/* ── Configuración ── */}
      {tab === "config" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="glass-panel" style={{ padding: 24 }}>
            <div
              style={{
                fontWeight: 800,
                fontSize: "1rem",
                borderBottom: "1px solid rgba(139,92,246,0.15)",
                paddingBottom: 12,
                marginBottom: 18}}
            >
              Canal Hub — Punto de entrada
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                gap: 16}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal de voz Hub</label>
                <SearchableSelect
                  value={cfg?.generator_channel_id || ""}
                  onChange={setId("generator_channel_id")}
                  endpoint={`/api/guilds/${guildId}/channels?type=voice`}
                  itemsKey="channels"
                  placeholder="Selecciona el canal Hub…"
                  renderOption={renderVoiceOption}
                  renderSelected={renderVoiceSelected}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  El usuario que entre aquí recibirá un VC propio.
                </span>
              </div>

              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Categoría destino</label>
                <SearchableSelect
                  value={cfg?.category_id || ""}
                  onChange={setId("category_id")}
                  endpoint={`/api/guilds/${guildId}/categories`}
                  itemsKey="categories"
                  placeholder="Sin categoría…"
                  renderOption={renderCategoryOption}
                  renderSelected={renderCategorySelected}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  Dónde se crearán los canales generados.
                </span>
              </div>

              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal del panel</label>
                <SearchableSelect
                  value={cfg?.panel_channel_id || ""}
                  onChange={setId("panel_channel_id")}
                  endpoint={`/api/guilds/${guildId}/channels?type=text`}
                  itemsKey="channels"
                  placeholder="Sin panel…"
                  renderOption={renderTextOption}
                  renderSelected={renderTextSelected}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  Donde se publican los botones de control.
                </span>
              </div>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: 24 }}>
            <div
              style={{
                fontWeight: 800,
                fontSize: "1rem",
                borderBottom: "1px solid rgba(139,92,246,0.15)",
                paddingBottom: 12,
                marginBottom: 18}}
            >
              Personalización del nombre
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 16}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Plantilla de nombre</label>
                <input
                  type="text"
                  value={cfg?.name_template || "{username}'s VC"}
                  onChange={(e) => set("name_template", e.target.value)}
                  placeholder="{username}'s VC"
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  Variables: <code style={{ color: "#a78bfa" }}>{"{username}"}</code>{" "}
                  <code style={{ color: "#a78bfa" }}>{"{user}"}</code>
                </span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Límite de usuarios por defecto</label>
                <input
                  type="number"
                  min="0"
                  max="99"
                  value={cfg?.default_limit ?? 0}
                  onChange={(e) => set("default_limit", parseInt(e.target.value))}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  0 = ilimitado
                </span>
              </div>
            </div>
            <div
              style={{
                marginTop: 16,
                padding: "10px 14px",
                borderRadius: "var(--radius-md)",
                background: "var(--accent-light)",
                border: "1px solid var(--border-accent)",
                fontSize: "0.84rem"}}
            >
              <span style={{ color: "var(--text-muted)", marginRight: 8 }}>Preview:</span>
              <strong style={{ color: "#c4b5fd" }}>
                <Icon name="voiceChannel" /> {previewName}
              </strong>
            </div>
          </div>
        </div>
      )}

      {/* ── Panel personalizable ── */}
      {tab === "panel" && (
        <div className="glass-panel" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div
            style={{
              fontWeight: 800,
              fontSize: "1rem",
              borderBottom: "1px solid rgba(139,92,246,0.15)",
              paddingBottom: 12}}
          >
            Personalización del panel
          </div>

          <div className="config-item inline-check" style={{ marginBottom: 0 }}>
            <div>
              <div style={{ fontWeight: 700 }}>Envío automático</div>
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                Si está activo, el panel se publica automáticamente al crear un VC.
                Si está apagado, el dueño debe pedirlo con <code>/vc panel</code> o
                desde la pestaña "VCs activos".
              </div>
            </div>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!cfg?.auto_send_panel}
                onChange={(e) => set("auto_send_panel", e.target.checked ? 1 : 0)}
              />
              <span className="slider" />
            </label>
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Título del panel</label>
            <input
              type="text"
              value={cfg?.panel_title || ""}
              placeholder="Tu canal de voz está listo"
              onChange={(e) => set("panel_title", e.target.value)}
            />
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Descripción</label>
            <textarea
              rows={4}
              value={cfg?.panel_description || ""}
              placeholder="**{owner}** — Bienvenido a **{channel}**…"
              onChange={(e) => set("panel_description", e.target.value)}
              style={{
                width: "100%",
                resize: "vertical",
                padding: "10px 12px",
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-md)",
                color: "var(--text)",
                fontFamily: "var(--font-main)",
                fontSize: "0.9rem"}}
            />
            <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
              Variables: <code>{"{channel}"}</code> <code>{"{owner}"}</code>
            </span>
          </div>

          <div className="config-item" style={{ marginBottom: 0, maxWidth: 200 }}>
            <label>Color (hex)</label>
            <input
              type="text"
              value={cfg?.panel_color || ""}
              placeholder="#7c3aed"
              onChange={(e) => set("panel_color", e.target.value)}
            />
          </div>
        </div>
      )}

      {/* ── VCs activos ── */}
      {tab === "active" && (
        <div className="glass-panel" style={{ overflow: "hidden" }}>
          {activeVCs.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <Icon name="voiceChannel" size="xl" />
              <h3 style={{ margin: "12px 0 8px" }}>Sin canales activos</h3>
              <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.85rem" }}>
                Los canales aparecerán aquí cuando los usuarios entren al Hub.
              </p>
            </div>
          ) : (
            <table
              style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}
            >
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
                  {["Canal", "Dueño", "Creado", ""].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "12px 16px",
                        textAlign: "left",
                        fontWeight: 700,
                        color: "var(--muted)",
                        fontSize: "0.75rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em"}}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activeVCs.map((vc, i) => (
                  <tr
                    key={vc.channel_id || i}
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                  >
                    <td
                      style={{
                        padding: "10px 16px",
                        fontFamily: "monospace",
                        fontSize: "0.78rem"}}
                    >
                      <Icon name="voiceChannel" /> {vc.channel_id}
                    </td>
                    <td
                      style={{
                        padding: "10px 16px",
                        fontFamily: "monospace",
                        fontSize: "0.78rem",
                        color: "var(--muted)"}}
                    >
                      {vc.owner_id}
                    </td>
                    <td
                      style={{
                        padding: "10px 16px",
                        fontSize: "0.76rem",
                        color: "var(--muted)"}}
                    >
                      {vc.created_at
                        ? new Date(vc.created_at * 1000).toLocaleString("es")
                        : "—"}
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <button
                        className="btn-secondary"
                        onClick={() => resendPanel(vc.channel_id)}
                        style={{ padding: "6px 12px", fontSize: "0.78rem" }}
                      >
                        <Icon name="send" /> Reenviar panel
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}


    </div>
  );
}
