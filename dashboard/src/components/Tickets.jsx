import { useState, useEffect, useCallback, useMemo } from "react";
import { apiGet, apiPatch, apiPost, apiDelete, apiPut } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";
import MessageEditor, { EMPTY_MESSAGE, normalizeMessage } from "./MessageEditor";
import EmojiPicker from "./EmojiPicker";

const TEMPLATE_PRESETS = [
  {
    key: "panel_select",
    name: "Panel de selección",
    desc: "Embed que verá el usuario en el canal del panel para elegir categoría de ticket.",
    seed: {
      content: "",
      enabled: true,
      embed: {
        title: "🎫 Crear un ticket",
        description: "Selecciona una categoría en el menú de abajo para abrir un ticket. El staff te atenderá en breve.",
        color: "#6366f1",
      },
    },
  },
  {
    key: "panel_inside",
    name: "Panel dentro del ticket",
    desc: "Embed inicial que aparece dentro del ticket recién creado, con el resumen y los botones del staff.",
    seed: {
      content: "",
      enabled: true,
      embed: {
        title: "Ticket abierto",
        description: "Hola {username}, gracias por abrir un ticket en **{server}**. Un miembro del staff llegará pronto.",
        color: "#22c55e",
      },
    },
  },
  {
    key: "msg_open",
    name: "Mensaje al abrir",
    desc: "Mensaje automático extra que se envía justo después de crear el ticket (texto plano o embed).",
    seed: {
      content: "@here Nuevo ticket de {username}",
      enabled: false,
      embed: EMPTY_MESSAGE.embed,
    },
  },
  {
    key: "msg_close",
    name: "Mensaje al cerrar",
    desc: "Mensaje que se enviará al cerrar el ticket (útil para encuesta de satisfacción o despedida).",
    seed: {
      content: "",
      enabled: true,
      embed: {
        title: "Ticket cerrado",
        description: "Gracias por contactar al staff. Si necesitas algo más, abre otro ticket.",
        color: "#ef4444",
      },
    },
  },
];

function templateToMessage(json) {
  try {
    const parsed = typeof json === "string" ? JSON.parse(json) : json;
    if (!parsed || typeof parsed !== "object") return normalizeMessage(EMPTY_MESSAGE);
    // Acepta formato MessageEditor o formato Discord embed crudo.
    if (parsed.embed || parsed.content) return normalizeMessage(parsed);
    // Embed crudo (Discord shape): mapear top-level a {embed:…}.
    return normalizeMessage({
      content: "",
      enabled: true,
      embed: {
        title: parsed.title || "",
        description: parsed.description || "",
        color: typeof parsed.color === "number" ? "#" + parsed.color.toString(16).padStart(6, "0") : parsed.color || "#6366f1",
        footer: parsed.footer?.text || parsed.footer || "",
        footer_icon: parsed.footer?.icon_url || "",
        image: parsed.image?.url || parsed.image || "",
        thumbnail: parsed.thumbnail?.url || parsed.thumbnail || "",
        author: parsed.author?.name || parsed.author || "",
        author_icon: parsed.author?.icon_url || "",
        author_url: parsed.author?.url || "",
      },
    });
  } catch {
    return normalizeMessage(EMPTY_MESSAGE);
  }
}

const DEFAULT_CAT = {
  name: "",
  emoji: "",
  description: "",
  questions: "¿En qué podemos ayudarte?"};

export default function Tickets({ selectedGuild: guildId }) {
  const [tab, setTab] = useState("config");
  const [cfg, setCfg] = useState(null);
  const [categories, setCategories] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  // Estado UI: nueva categoría / editar plantilla
  const [newCat, setNewCat] = useState(DEFAULT_CAT);
  const [addingCat, setAddingCat] = useState(false);
  const [tplDraft, setTplDraft] = useState({ key: "panel_select", name: "", json: "{}" });
  const [savingTpl, setSavingTpl] = useState(false);

  // Envío del panel
  const [panelChannel, setPanelChannel] = useState("");
  const [sendingPanel, setSendingPanel] = useState(false);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const [tData, tplData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/tickets`),
        apiGet(`/api/guilds/${guildId}/tickets/templates`).catch(() => ({
          templates: []})),
      ]);
      setCfg(tData.config || {});
      setCategories(tData.categories || []);
      setTemplates(tplData.templates || []);
    } catch {
      showToast("Error cargando tickets", "error");
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
        panel_channel_id: cfg.panel_channel_id ?? null,
        category_id: cfg.category_id ?? null,
        log_channel_id: cfg.log_channel_id ?? null,
        allowed_roles: cfg.allowed_roles ?? "[]",
        immune_roles: cfg.immune_roles ?? "[]",
        channel_name_template: cfg.channel_name_template ?? "{username}-{number}",
        max_tickets_per_user: cfg.max_tickets_per_user ?? 0,
        ticket_cooldown_seconds: cfg.ticket_cooldown_seconds ?? 0,
        panel_select_template: cfg.panel_select_template ?? null,
        panel_inside_template: cfg.panel_inside_template ?? null,
        msg_open_template: cfg.msg_open_template ?? null,
        msg_close_template: cfg.msg_close_template ?? null};
      await apiPatch(`/api/guilds/${guildId}/tickets`, payload);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  // ── Categorías ─────────────────────────────────────────────────────────────
  const addCategory = async () => {
    if (!newCat.name.trim()) return showToast("El nombre es requerido", "error");
    setAddingCat(true);
    try {
      const qs = newCat.questions
        ? newCat.questions
            .split("\n")
            .map((q) => q.trim())
            .filter(Boolean)
        : ["¿En qué podemos ayudarte?"];
      await apiPost(`/api/guilds/${guildId}/tickets/categories`, {
        name: newCat.name.trim(),
        emoji: newCat.emoji || "",
        description: newCat.description || "",
        questions: qs});
      setNewCat(DEFAULT_CAT);
      const data = await apiGet(`/api/guilds/${guildId}/tickets`, { cache: false });
      setCategories(data.categories || []);
      showToast("Categoría añadida");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setAddingCat(false);
    }
  };

  const deleteCat = async (catId) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/tickets/categories/${catId}`);
      setCategories((c) => c.filter((x) => x.id !== catId));
      showToast("Categoría eliminada");
    } catch (e) {
      showToast(e.message, "error");
    }
  };

  const patchCategory = async (catId, payload) => {
    try {
      await apiPatch(
        `/api/guilds/${guildId}/tickets/categories/${catId}`,
        payload,
      );
      const data = await apiGet(`/api/guilds/${guildId}/tickets`, { cache: false });
      setCategories(data.categories || []);
      showToast("Categoría actualizada");
    } catch (e) {
      showToast(e.message, "error");
    }
  };

  // ── Plantillas ─────────────────────────────────────────────────────────────
  const saveTemplate = async () => {
    let parsed;
    try {
      parsed = JSON.parse(tplDraft.json || "{}");
    } catch {
      return showToast("JSON inválido en el embed", "error");
    }
    setSavingTpl(true);
    try {
      await apiPut(
        `/api/guilds/${guildId}/tickets/templates/${tplDraft.key}`,
        { embed_data: parsed, name: tplDraft.name || null },
      );
      const data = await apiGet(
        `/api/guilds/${guildId}/tickets/templates`,
        { cache: false },
      );
      setTemplates(data.templates || []);
      showToast("Plantilla guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSavingTpl(false);
    }
  };

  const deleteTemplate = async (key) => {
    if (!confirm(`Borrar plantilla "${key}"?`)) return;
    try {
      await apiDelete(
        `/api/guilds/${guildId}/tickets/templates/${key}`,
      );
      setTemplates((t) => t.filter((x) => x.template_key !== key));
      showToast("Plantilla borrada");
    } catch (e) {
      showToast(e.message, "error");
    }
  };

  const loadTemplateInDraft = (tpl) => {
    setTplDraft({
      key: tpl.template_key,
      name: tpl.name || "",
      json: JSON.stringify(tpl.embed_data || {}, null, 2)});
  };

  // Mensaje renderizado desde el JSON crudo (para MessageEditor).
  const draftMessage = useMemo(() => templateToMessage(tplDraft.json), [tplDraft.json]);
  const [tplEditorTab, setTplEditorTab] = useState("embed-content");

  const setDraftMessage = (next) => {
    setTplDraft((p) => ({ ...p, json: JSON.stringify(next) }));
  };

  const applyPreset = (preset) => {
    setTplDraft({
      key: preset.key,
      name: preset.name,
      json: JSON.stringify(preset.seed, null, 2),
    });
    setTplEditorTab(preset.seed.enabled ? "embed-content" : "content");
  };

  // ── Panel ──────────────────────────────────────────────────────────────────
  const sendPanel = async () => {
    if (!panelChannel) return showToast("Selecciona un canal", "error");
    setSendingPanel(true);
    try {
      await apiPost(`/api/guilds/${guildId}/tickets/send-panel`, {
        channel_id: parseInt(panelChannel)});
      showToast("Panel enviado");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSendingPanel(false);
    }
  };

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando tickets…</p>
      </div>
    );

  // Renderers SearchableSelect
  const renderTextChannel = (opt) => (
    <>
      <Icon name="channel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
    </>
  );
  const renderCategory = (opt) => (
    <>
      <Icon name="category" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.channel_count != null ? (
        <span className="ss-option-sub">{opt.channel_count} canales</span>
      ) : null}
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
  const renderTemplate = (opt) => (
    <>
      <Icon name="edit" />
      <span className="ss-option-label">{opt.name || opt.id}</span>
      <span className="ss-option-sub">{opt.id}</span>
    </>
  );

  // Plantillas como opciones para SearchableSelect (id = template_key)
  const tplOptions = templates.map((t) => ({
    id: t.template_key,
    name: t.name || t.template_key}));
  // Añadir entrada "Sin plantilla" virtual
  const tplOptionsWithNone = [{ id: "", name: "(Sin plantilla)" }, ...tplOptions];

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <h2
          style={{
          }}
        >
          Tickets
        </h2>
      </div>

      <div className="tabs-container">
        {[
          ["config", "Configuración"],
          ["categories", `Categorías (${categories.length})`],
          ["templates", `Plantillas (${templates.length})`],
          ["panel", "Panel"],
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

      {/* ── Config ── */}
      {tab === "config" && cfg && (
        <>
          <div className="glass-panel" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Canales y permisos</h3>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))",
                gap: 16}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal del panel</label>
                <SearchableSelect
                  value={cfg.panel_channel_id || ""}
                  onChange={setId("panel_channel_id")}
                  endpoint={`/api/guilds/${guildId}/channels?type=text`}
                  itemsKey="channels"
                  placeholder="Selecciona canal de texto…"
                  renderOption={renderTextChannel}
                  renderSelected={(opt) => (
                    <><Icon name="channel" /> {opt.name}</>
                  )}
                />
              </div>

              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Categoría destino de tickets</label>
                <SearchableSelect
                  value={cfg.category_id || ""}
                  onChange={setId("category_id")}
                  endpoint={`/api/guilds/${guildId}/categories`}
                  itemsKey="categories"
                  placeholder="Selecciona categoría…"
                  renderOption={renderCategory}
                  renderSelected={(opt) => (
                    <><Icon name="category" /> {opt.name}</>
                  )}
                />
              </div>

              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal de logs</label>
                <SearchableSelect
                  value={cfg.log_channel_id || ""}
                  onChange={setId("log_channel_id")}
                  endpoint={`/api/guilds/${guildId}/channels?type=text`}
                  itemsKey="channels"
                  placeholder="Selecciona canal de logs…"
                  renderOption={renderTextChannel}
                  renderSelected={(opt) => (
                    <><Icon name="channel" /> {opt.name}</>
                  )}
                />
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                gap: 16}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Plantilla nombre del canal</label>
                <input
                  type="text"
                  value={cfg.channel_name_template ?? ""}
                  placeholder="{username}-{number}"
                  onChange={(e) => set("channel_name_template", e.target.value)}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                  Variables: <code>{"{username}"}</code> <code>{"{number}"}</code>
                </span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Máx. tickets por usuario</label>
                <input
                  type="number"
                  min="0"
                  value={cfg.max_tickets_per_user ?? 0}
                  onChange={(e) => set("max_tickets_per_user", parseInt(e.target.value))}
                />
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>0 = sin límite</span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Cooldown entre tickets (seg)</label>
                <input
                  type="number"
                  min="0"
                  value={cfg.ticket_cooldown_seconds ?? 0}
                  onChange={(e) => set("ticket_cooldown_seconds", parseInt(e.target.value))}
                />
              </div>
            </div>
          </div>

          <div
            className="glass-panel"
            style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Plantillas asociadas</h3>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                Asigna plantillas predefinidas para el panel y los mensajes
                automáticos. Crea las plantillas en la pestaña "Plantillas".
              </p>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                gap: 16}}
            >
              {[
                ["panel_select_template", "Panel de selección"],
                ["panel_inside_template", "Panel dentro del ticket"],
                ["msg_open_template", "Mensaje al abrir"],
                ["msg_close_template", "Mensaje al cerrar"],
              ].map(([k, label]) => (
                <div key={k} className="config-item" style={{ marginBottom: 0 }}>
                  <label>{label}</label>
                  <SearchableSelect
                    value={cfg[k] || ""}
                    onChange={(v) => set(k, v || null)}
                    options={tplOptionsWithNone}
                    placeholder="(Sin plantilla)"
                    renderOption={renderTemplate}
                    renderSelected={(opt) => (
                      <><Icon name="edit" /> {opt.name}</>
                    )}
                  />
                </div>
              ))}
            </div>
          </div>


        </>
      )}

      {/* ── Categorías ── */}
      {tab === "categories" && (
        <>
          <div className="glass-panel" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Nueva categoría</h3>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "120px 1fr 1fr",
                gap: 12,
                alignItems: "end"}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Emoji</label>
                <EmojiPicker
                  guildId={guildId}
                  value={newCat.emoji}
                  onChange={(v) => setNewCat({ ...newCat, emoji: v })}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Nombre</label>
                <input
                  type="text"
                  value={newCat.name}
                  placeholder="Soporte general"
                  onChange={(e) => setNewCat({ ...newCat, name: e.target.value })}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Descripción</label>
                <input
                  type="text"
                  value={newCat.description}
                  placeholder="Aparece en el selector"
                  onChange={(e) => setNewCat({ ...newCat, description: e.target.value })}
                />
              </div>
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Preguntas (una por línea)</label>
              <textarea
                rows={3}
                value={newCat.questions}
                placeholder="¿En qué podemos ayudarte?\n¿Has revisado las FAQs?"
                onChange={(e) => setNewCat({ ...newCat, questions: e.target.value })}
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  background: "var(--panel)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--text)",
                  fontFamily: "var(--font-main)",
                  fontSize: "0.9rem",
                  resize: "vertical"}}
              />
            </div>
            <div>
              <button
                className="btn-primary"
                disabled={addingCat}
                onClick={addCategory}
              >
                <Icon name="add" /> {addingCat ? "Añadiendo…" : "Añadir categoría"}
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
            {categories.length === 0 ? (
              <div className="no-results">
                <p>No hay categorías. Añade una arriba.</p>
              </div>
            ) : (
              categories.map((cat) => (
                <CategoryRow
                  key={cat.id}
                  category={cat}
                  templates={tplOptionsWithNone}
                  guildId={guildId}
                  onSave={(payload) => patchCategory(cat.id, payload)}
                  onDelete={() => deleteCat(cat.id)}
                  renderTemplate={renderTemplate}
                  renderRole={renderRole}
                />
              ))
            )}
          </div>
        </>
      )}

      {/* ── Plantillas ── */}
      {tab === "templates" && (
        <>
          <div className="glass-panel" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 14 }}>
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Editor de plantillas</h3>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                Cada plantilla se identifica por una clave única en este servidor.
                Las claves canónicas son <code>panel_select</code>,{" "}
                <code>panel_inside</code>, <code>msg_open</code>,{" "}
                <code>msg_close</code>. Puedes usar <code>custom_*</code> para libres.
              </p>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Clave</label>
                <input
                  type="text"
                  value={tplDraft.key}
                  placeholder="panel_select"
                  onChange={(e) => setTplDraft({ ...tplDraft, key: e.target.value })}
                />
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                  {TEMPLATE_PRESETS.map((p) => (
                    <button
                      key={p.key}
                      onClick={() => setTplDraft({ ...tplDraft, key: p.key, name: p.name })}
                      title={p.desc}
                      style={{
                        padding: "4px 10px",
                        fontSize: "0.74rem",
                        borderRadius: 999,
                        border: "1px solid var(--border)",
                        background:
                          tplDraft.key === p.key ? "var(--accent-light)" : "transparent",
                        color: "var(--text)",
                        cursor: "pointer"}}
                    >
                      {p.key}
                    </button>
                  ))}
                </div>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Nombre legible</label>
                <input
                  type="text"
                  value={tplDraft.name}
                  placeholder="Selector principal"
                  onChange={(e) => setTplDraft({ ...tplDraft, name: e.target.value })}
                />
              </div>
            </div>

            <div style={{ background: "rgba(99,102,241,0.06)", border: "1px solid rgba(139,92,246,0.18)", padding: 12, borderRadius: 12 }}>
              <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginBottom: 8 }}>
                💡 Plantillas predefinidas — pulsa para cargar una base profesional y editarla:
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {TEMPLATE_PRESETS.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    title={p.desc}
                    onClick={() => applyPreset(p)}
                    className="btn-secondary"
                    style={{ fontSize: "0.76rem", padding: "5px 12px" }}
                  >
                    📋 {p.name}
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 6, fontSize: "0.72rem", color: "var(--muted)" }}>
                <strong style={{ color: "var(--text)" }}>
                  {TEMPLATE_PRESETS.find((p) => p.key === tplDraft.key)?.name || "Plantilla personalizada"}
                </strong>
                {" — "}
                {TEMPLATE_PRESETS.find((p) => p.key === tplDraft.key)?.desc ||
                  "Usa una clave libre (ej. custom_*) para plantillas adicionales."}
              </div>
            </div>

            <MessageEditor
              value={draftMessage}
              onChange={setDraftMessage}
              mode="both"
              tab={tplEditorTab}
              setTab={setTplEditorTab}
              variablesHelp={"Variables: {username}, {number}, {server}, {channel}. Usa el modo 'Mensaje' para texto plano fuera del embed."}
              placeholders={{
                title: "Título del embed",
                description: "Descripción enriquecida…",
                content: "Mensaje opcional fuera del embed (ej. @here)",
              }}
              showJson
            />

            <div>
              <button
                className="btn-primary"
                disabled={savingTpl}
                onClick={saveTemplate}
              >
                <Icon name="save" /> {savingTpl ? "Guardando…" : "Guardar plantilla"}
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
            {templates.length === 0 ? (
              <div className="no-results">
                <p>Aún no hay plantillas. Crea una arriba.</p>
              </div>
            ) : (
              templates.map((t) => (
                <div
                  key={t.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                    background: "var(--panel)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)"}}
                >
                  <code style={{ color: "var(--accent)" }}>{t.template_key}</code>
                  <span style={{ flex: 1, color: "var(--text)" }}>
                    {t.name || <span style={{ color: "var(--muted)" }}>(sin nombre)</span>}
                  </span>
                  <button
                    className="btn-secondary"
                    onClick={() => loadTemplateInDraft(t)}
                    style={{ padding: "6px 12px", fontSize: "0.78rem" }}
                  >
                    <Icon name="edit" /> Editar
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => deleteTemplate(t.template_key)}
                    style={{
                      padding: "6px 12px",
                      fontSize: "0.78rem",
                      color: "var(--danger)"}}
                  >
                    <Icon name="delete" /> Borrar
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}

      {/* ── Panel send ── */}
      {tab === "panel" && (
        <div className="glass-panel" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="section-title">
            <h3 style={{ margin: 0 }}>Enviar panel</h3>
            <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
              Selecciona el canal donde quieres publicar el panel de selección
              de tickets. Usará la plantilla{" "}
              <code>panel_select_template</code> si está asignada.
            </p>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 12,
              alignItems: "end"}}
          >
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Canal</label>
              <SearchableSelect
                value={panelChannel}
                onChange={(v) => setPanelChannel(v || "")}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="Selecciona canal…"
                renderOption={renderTextChannel}
                renderSelected={(opt) => (
                  <><Icon name="channel" /> {opt.name}</>
                )}
              />
            </div>
            <button
              className="btn-primary"
              disabled={sendingPanel}
              onClick={sendPanel}
            >
              <Icon name="send" /> {sendingPanel ? "Enviando…" : "Enviar panel"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Subcomponente: fila de categoría editable ────────────────────────────────
function CategoryRow({ category, templates, guildId, onSave, onDelete, renderTemplate, renderRole }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({
    name: category.name || "",
    emoji: category.emoji || "",
    description: category.description || "",
    questions: (() => {
      try {
        return JSON.parse(category.questions || "[]").join("\n");
      } catch {
        return "";
      }
    })(),
    welcome_embed_template_key: category.welcome_embed_template_key || "",
    staff_role_id: category.staff_role_id || ""});

  const handleSave = () => {
    const payload = {
      name: draft.name,
      emoji: draft.emoji,
      description: draft.description,
      questions: draft.questions
        .split("\n")
        .map((q) => q.trim())
        .filter(Boolean),
      welcome_embed_template_key: draft.welcome_embed_template_key || null,
      staff_role_id: draft.staff_role_id ? parseInt(draft.staff_role_id) : null};
    onSave(payload);
    setOpen(false);
  };

  return (
    <div
      style={{
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden"}}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 14px"}}
      >
        <span style={{ fontSize: "1.1rem", minWidth: 24 }}>{category.emoji || ""}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700 }}>{category.name}</div>
          {category.description ? (
            <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
              {category.description}
            </div>
          ) : null}
        </div>
        <button
          className="btn-secondary"
          onClick={() => setOpen(!open)}
          style={{ padding: "6px 12px", fontSize: "0.78rem" }}
        >
          <Icon name={open ? "chevronUp" : "edit"} /> {open ? "Cerrar" : "Editar"}
        </button>
        <button
          className="btn-secondary"
          onClick={onDelete}
          style={{
            padding: "6px 12px",
            fontSize: "0.78rem",
            color: "var(--danger)"}}
        >
          <Icon name="delete" /> Borrar
        </button>
      </div>

      {open && (
        <div
          style={{
            borderTop: "1px solid var(--border)",
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12,
            background: "var(--bg-2)"}}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr 1fr",
              gap: 12}}
          >
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Emoji</label>
              <input
                type="text"
                maxLength={4}
                value={draft.emoji}
                onChange={(e) => setDraft({ ...draft, emoji: e.target.value })}
              />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Nombre</label>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Descripción</label>
              <input
                type="text"
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </div>
          </div>

          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Preguntas (una por línea)</label>
            <textarea
              rows={3}
              value={draft.questions}
              onChange={(e) => setDraft({ ...draft, questions: e.target.value })}
              style={{
                width: "100%",
                padding: "10px 12px",
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-md)",
                color: "var(--text)",
                fontFamily: "var(--font-main)",
                fontSize: "0.9rem",
                resize: "vertical"}}
            />
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12}}
          >
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Plantilla de bienvenida</label>
              <SearchableSelect
                value={draft.welcome_embed_template_key}
                onChange={(v) =>
                  setDraft({ ...draft, welcome_embed_template_key: v || "" })
                }
                options={templates}
                placeholder="(Sin plantilla)"
                renderOption={renderTemplate}
                renderSelected={(opt) => (
                  <><Icon name="edit" /> {opt.name}</>
                )}
              />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label>Rol de staff específico</label>
              <SearchableSelect
                value={draft.staff_role_id || ""}
                onChange={(v) => setDraft({ ...draft, staff_role_id: v || "" })}
                endpoint={`/api/guilds/${guildId}/roles`}
                itemsKey="roles"
                placeholder="(Hereda del global)"
                renderOption={renderRole}
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

          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn-primary" onClick={handleSave}>
              <Icon name="save" /> Guardar cambios
            </button>
            <button className="btn-secondary" onClick={() => setOpen(false)}>
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
