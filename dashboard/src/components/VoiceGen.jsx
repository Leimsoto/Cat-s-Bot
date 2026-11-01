import { useState, useEffect, useCallback, useMemo } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";
import MessageEditor, { normalizeMessage } from "./MessageEditor";

export default function VoiceGen({ selectedGuild: guildId }) {
  const [cfg, setCfg] = useState(null);
  const [activeVCs, setActiveVCs] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [publishingPanel, setPublishingPanel] = useState(false);
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
    } catch (e) {
      showToast(e?.message || "Error cargando configuración", "error");
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
  const setId = (k) => (v) => set(k, v ? String(v) : null);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        enabled: cfg?.enabled ? 1 : 0,
        generator_channel_id: cfg?.generator_channel_id ?? null,
        category_id: cfg?.category_id ?? null,
        panel_channel_id: cfg?.panel_channel_id ?? null,
        name_template: cfg?.name_template ?? null,
        default_limit: cfg?.default_limit ?? 0,
        // Legacy: se siguen guardando para retrocompatibilidad si alguien
        // editaba antes; el cog prefiere panel_embed_data si está presente.
        panel_title: cfg?.panel_title ?? null,
        panel_description: cfg?.panel_description ?? null,
        panel_color: cfg?.panel_color ?? null,
        panel_embed_data: cfg?.panel_embed_data ?? null,
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

  // Parsea panel_embed_data → forma de MessageEditor.
  // Si está vacío, sintetiza desde campos legacy (title/description/color) para
  // que el editor arranque con algo razonable y migre al primer guardado.
  const panelMessage = useMemo(() => {
    const raw = cfg?.panel_embed_data;
    if (raw) {
      try {
        return normalizeMessage(typeof raw === "string" ? JSON.parse(raw) : raw);
      } catch {
        /* cae al sintetizado */
      }
    }
    return normalizeMessage({
      content: "",
      enabled: true,
      embed: {
        title: cfg?.panel_title || "",
        description: cfg?.panel_description || "",
        color: cfg?.panel_color || "#7c3aed",
      },
    });
  }, [cfg?.panel_embed_data, cfg?.panel_title, cfg?.panel_description, cfg?.panel_color]);

  const [panelEditorTab, setPanelEditorTab] = useState("embed-content");
  const handlePanelMessage = (next) => {
    set("panel_embed_data", JSON.stringify(next));
  };

  const publishPanel = async () => {
    setPublishingPanel(true);
    try {
      await apiPost(`/api/guilds/${guildId}/voice-gen/resend-panel`, {});
      showToast("Panel permanente publicado o actualizado");
    } catch (e) {
      showToast(e.message || "Error publicando el panel", "error");
    } finally {
      setPublishingPanel(false);
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
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%,260px),1fr))",
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
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%,240px),1fr))",
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
                Mantiene un único mensaje permanente en el canal configurado. No
                crea un panel nuevo por cada VC o usuario.
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

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 16,
              padding: "12px 14px",
              borderRadius: "var(--radius-md)",
              background: "rgba(139,92,246,0.08)",
              border: "1px solid rgba(139,92,246,0.2)",
            }}
          >
            <div>
              <div style={{ fontWeight: 700 }}>Panel permanente compartido</div>
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                Los botones controlan el VC generado donde esté su propietario.
                Guarda los cambios antes de actualizar el mensaje.
              </div>
            </div>
            <button
              className="btn-secondary"
              onClick={publishPanel}
              disabled={dirty || publishingPanel || !cfg?.panel_channel_id}
              title={dirty ? "Guarda los cambios antes de publicar" : undefined}
              style={{ whiteSpace: "nowrap" }}
            >
              <Icon name="send" /> {publishingPanel ? "Publicando…" : "Publicar / actualizar"}
            </button>
          </div>

          <MessageEditor
            value={panelMessage}
            onChange={handlePanelMessage}
            mode="both"
            tab={panelEditorTab}
            setTab={setPanelEditorTab}
            variablesHelp={"Variable disponible: {guild}. Las variables antiguas de canal/owner se muestran de forma genérica."}
            placeholders={{
              title: "Panel de control de VoiceChat",
              description: "Entra en tu VC temporal y usa los botones para configurarlo…",
              content: "Mensaje opcional fuera del embed…",
            }}
            showJson
          />
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
                  {["Canal", "Dueño", "Creado"].map((h) => (
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
