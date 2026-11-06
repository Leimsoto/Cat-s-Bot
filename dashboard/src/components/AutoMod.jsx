import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiPatch } from "../lib/api";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";
import AutoModLLM from "./AutoModLLM";
import IdentityBadge from "./IdentityBadge";
import ModerationReason from "./ModerationReason";
import { Icon } from "../lib/icons";
import "./DashboardPanels.css";

const LLM_OUTCOMES = {
  none: "Sin sanción",
  delete: "Mensaje eliminado",
  delete_failed: "No se pudo eliminar el mensaje",
  deletion_notice_failed: "Aviso en el canal no entregado",
  error_no_action: "Error de IA: sin sanción",
  partial_coverage: "Contenido analizado parcialmente",
  skipped_queue_full: "Omitido: cola llena",
  skipped_stale_queue: "Omitido: espera excesiva",
  skipped_superseded: "Omitido: evaluación reemplazada",
  skipped_changed: "Omitido: mensaje modificado",
  skipped_unreadable_content: "Omitido: contenido no disponible",
  enforcement_not_confirmed: "Sanción no confirmada",
};

const RULE_META = {
  spam: {
    label: "Anti-Spam",
    desc: "Detecta mensajes repetidos o envíos masivos",
    icon: "fa-ban",
    color: "#ef4444"},
  mentions: {
    label: "Menciones masivas",
    desc: "Limita la cantidad de menciones por mensaje",
    icon: "fa-at",
    color: "#f97316"},
  caps: {
    label: "Mayúsculas",
    desc: "Limita el % de mayúsculas en un mensaje",
    icon: "fa-font",
    color: "#eab308"},
  links: {
    label: "Anti-Links",
    desc: "Bloquea enlaces no autorizados",
    icon: "fa-link",
    color: "#3b82f6"},
  banned_words: {
    label: "Palabras prohibidas",
    desc: "Filtra mensajes con palabras de la lista negra",
    icon: "fa-comment-slash",
    color: "#8b5cf6"},
  duplicate: {
    label: "Mensajes repetidos",
    desc: "Detecta repetición del mismo contenido en una ventana corta",
    icon: "fa-copy",
    color: "#ec4899"},
  emoji_spam: {
    label: "Spam de emojis",
    desc: "Limita mensajes con demasiados emojis",
    icon: "fa-face-grin-stars",
    color: "#22c55e"}};

export default function AutoMod({ selectedGuild: guildId, onNavigate }) {
  return <AutoModSettings key={guildId} guildId={guildId} onNavigate={onNavigate} />;
}

function AutoModSettings({ guildId, onNavigate }) {
  const [cfg, setCfg] = useState(null);
  const [logs, setLogs] = useState([]);
  const [tab, setTab] = useState("rules");
  const [selectedRule, setSelectedRule] = useState("mentions");
  const [logError, setLogError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const saveInFlight = useRef(false);
  const requestVersion = useRef(0);

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    const version = ++requestVersion.current;
    setLoading(true);
    setDirty(false);
    setCfg(null);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/automod`, { cache: false });
      if (version !== requestVersion.current) return;
      setCfg(data || { enabled: 1, rules: {} });
    } catch (e) {
      if (version !== requestVersion.current) return;
      showToast(e?.message || "Error cargando automod", "error");
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [guildId]);

  const loadLogs = useCallback(async () => {
    if (!guildId) return;
    const version = requestVersion.current;
    setLogError("");
    try {
      const data = await apiGet(`/api/guilds/${guildId}/automod/log?limit=50`, {
        cache: false});
      if (version !== requestVersion.current) return;
      setLogs(Array.isArray(data) ? data : data.logs || []);
    } catch (error) {
      if (version === requestVersion.current) setLogError(error.message || "No pudimos cargar el registro.");
    }
  }, [guildId]);

  useEffect(() => {
    load();
    return () => { requestVersion.current += 1; };
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
      const next = { ...rule, [field]: value };
      return { ...prev, rules: { ...rules, [ruleName]: next } };
    });
    setDirty(true);
  };

  const save = async () => {
    if (!cfg || saving || loading || saveInFlight.current) return;
    const invalid = document.querySelector(".cr-automod :is(input,textarea,select):invalid");
    if (invalid) { invalid.reportValidity(); return; }
    const numericFields = ["max_mentions", "min_percent", "warn_threshold", "threshold", "max_emojis"];
    const invalidRule = Object.entries(cfg.rules || {}).find(([, rule]) => numericFields.some((field) => rule?.[field] === ""));
    if (invalidRule) { setSelectedRule(invalidRule[0]); setTab("rules"); showToast("Completa el límite de la regla antes de guardar.", "error"); return; }
    const rules = typeof cfg.rules === "string" ? JSON.parse(cfg.rules || "{}") : cfg.rules || {};
    const llm = { ...rules.llm };
    if (llm.enabled && !llm.rules_text?.trim()) {
      setTab("llm");
      showToast("Completa las reglas antes de activar la moderación IA.", "error");
      return;
    }
    // Las conexiones se guardan por separado para no pisar cambios de Endpoints.
    const behavior = Object.fromEntries(["enabled", "rules_text", "context_messages", "context_mode"].filter((key) => llm[key] !== undefined).map((key) => [key, llm[key]]));
    const version = requestVersion.current;
    saveInFlight.current = true;
    setSaving(true);
    try {
      const payload = {
        ...cfg,
        rules: { ...rules, llm: behavior }};
      const data = await apiPatch(`/api/guilds/${guildId}/automod`, payload);
      if (version !== requestVersion.current) return;
      if (data?.config) setCfg(data.config);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      if (version === requestVersion.current) showToast(e.message, "error");
    } finally {
      saveInFlight.current = false;
      if (version === requestVersion.current) setSaving(false);
    }
  };

  useSaveBar({ dirty: dirty && !loading, saving, onSave: save, onRevert: load });

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
    <div className="cr-page cr-automod">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <header className="cr-heading"><span className="cr-heading-icon"><Icon name="automod" /></span><div><span className="cr-eyebrow">Protección</span><h1>Automoderación</h1><p>Tus reglas, con el efecto siempre a la vista.</p></div>{cfg && <span className="cr-state-label">{Object.keys(RULE_META).filter((key) => rules[key]?.enabled).length} de 7 reglas activas</span>}</header>
      {!cfg && <p className="cr-inline-error" role="alert">No pudimos cargar la configuración. <button className="btn-secondary" onClick={load}>Reintentar</button></p>}
      <nav className="cr-tabs" aria-label="Opciones de automoderación">{[["rules","Reglas","settings"],["exceptions","Excepciones","users"],["llm","Moderación IA","ia"],["log","Registro","logs"]].map(([id,label,icon]) => <button key={id} type="button" aria-pressed={tab === id} disabled={saving} onClick={() => setTab(id)}><Icon name={icon} />{label}</button>)}</nav>
      {tab === "llm" && cfg && <AutoModLLM rule={rules.llm || {}} disabled={saving} onChange={(field,value) => setRule("llm",field,value)} onNavigate={onNavigate} />}
      {tab === "exceptions" && cfg && <fieldset className="cr-fieldset cr-exceptions" disabled={saving}><section className="cr-editor-panel"><h2>Exenciones globales</h2><p className="cr-hint">Estos miembros quedan fuera de las reglas clásicas y de la moderación IA.</p><label className="cr-check-row"><input type="checkbox" checked={rules.ignored?.exempt_admins ?? true} onChange={(event) => setRule("ignored","exempt_admins",event.target.checked)} />Excluir administradores</label><label className="cr-check-row"><input type="checkbox" checked={rules.ignored?.exempt_bots ?? true} onChange={(event) => setRule("ignored","exempt_bots",event.target.checked)} />Excluir mensajes de bots</label></section><aside className="cr-context-note"><Icon name="info" /><h3>Espacio para tu equipo</h3><p>Revisa las excepciones junto con las reglas. Afectan a toda la automoderación, incluida la IA.</p></aside></fieldset>}
      {tab === "rules" && cfg && <fieldset className="cr-fieldset" disabled={saving}>
        <div className="cr-status-strip"><div><h2>Sistema de automoderación</h2><p>{cfg.enabled ? "Activado para revisar los mensajes del servidor." : "Pausado. Las reglas clásicas no se aplicarán."}</p></div><label className="cr-switch"><input type="checkbox" aria-label="Activar automoderación" checked={!!cfg.enabled} onChange={(event) => set("enabled",event.target.checked ? 1 : 0)} /><span aria-hidden="true" /></label></div>
        <div className="cr-rule-layout"><div className="cr-rule-navigation"><label className="cr-field cr-rule-mobile"><span>Regla que quieres ajustar</span><select value={selectedRule} onChange={(event) => setSelectedRule(event.target.value)}>{Object.entries(RULE_META).map(([key,meta]) => <option key={key} value={key}>{meta.label}</option>)}</select></label><div className="cr-rule-list">{Object.entries(RULE_META).map(([key,meta]) => <div className="cr-rule-row" key={key}><button type="button" aria-pressed={selectedRule === key} onClick={() => setSelectedRule(key)}><Icon name={meta.icon} /><span><strong>{meta.label}</strong><small>{rules[key]?.enabled ? "Activa" : "Pausada"}</small></span></button><label className="cr-switch"><input type="checkbox" aria-label={`Activar ${meta.label}`} checked={!!rules[key]?.enabled} onChange={(event) => setRule(key,"enabled",event.target.checked)} /><span aria-hidden="true" /></label></div>)}</div></div>
          {Object.entries(RULE_META).filter(([key]) => key === selectedRule).map(([key,meta]) => {const rule = rules[key] || {};return <section key={key} className="cr-rule-editor"><div className="cr-section-heading"><h2>{meta.label}</h2><label className="cr-switch"><input type="checkbox" aria-label={`Activar ${meta.label}`} checked={!!rule.enabled} onChange={(event) => setRule(key,"enabled",event.target.checked)} /><span aria-hidden="true" /></label></div><p className="cr-hint">{meta.desc}</p>
            {key === "mentions" && <label className="cr-field"><span>Menciones permitidas por mensaje</span><input type="number" min="1" max="50" required value={rule.max_mentions ?? 5} onChange={(event) => setRule(key,"max_mentions",event.target.value === "" ? "" : Number(event.target.value))} /><small>Se cuentan personas y roles. Con un límite de 5, la regla actúa desde 6 menciones.</small></label>}
            {key === "caps" && <label className="cr-field"><span>Porcentaje mínimo de mayúsculas para actuar</span><input type="number" min="30" max="100" required value={rule.min_percent ?? 70} onChange={(event) => setRule(key,"min_percent",event.target.value === "" ? "" : Number(event.target.value))} /><small>Porcentaje del contenido que activará la regla.</small></label>}
            {key === "banned_words" && <label className="cr-field"><span>Palabras prohibidas</span><textarea rows={5} value={(rule.words || []).join(", ")} onChange={(event) => setRule(key,"words",event.target.value.split(",").map((word) => word.trim()).filter(Boolean))} /><small>Separa las palabras con comas.</small></label>}
            {key === "spam" && <label className="cr-field"><span>Mensajes en la ventana antes de avisar</span><input type="number" min="2" max="20" required value={rule.warn_threshold ?? 5} onChange={(event) => setRule(key,"warn_threshold",event.target.value === "" ? "" : Number(event.target.value))} /><small>La regla actúa al alcanzar este número de mensajes.</small></label>}
            {key === "links" && <><label className="cr-check-row"><input type="checkbox" checked={rule.block_invites ?? true} onChange={(event) => setRule(key,"block_invites",event.target.checked)} />Bloquear invitaciones de Discord</label><label className="cr-check-row"><input type="checkbox" checked={!!rule.block_all_urls} onChange={(event) => setRule(key,"block_all_urls",event.target.checked)} />Bloquear todos los enlaces salvo los permitidos</label></>}
            {key === "duplicate" && <label className="cr-field"><span>Repeticiones máximas</span><input type="number" min="2" max="20" required value={rule.threshold ?? 3} onChange={(event) => setRule(key,"threshold",event.target.value === "" ? "" : Number(event.target.value))} /></label>}
            {key === "emoji_spam" && <label className="cr-field"><span>Emojis permitidos por mensaje</span><input type="number" min="3" max="100" required value={rule.max_emojis ?? 10} onChange={(event) => setRule(key,"max_emojis",event.target.value === "" ? "" : Number(event.target.value))} /></label>}
            <div className="cr-rule-state"><Icon name={rule.enabled ? "automod" : "info"} /><p>{rule.enabled ? "Esta regla se aplicará con la configuración guardada cuando AutoMod esté activado." : "Esta regla está pausada. Puedes ajustar sus opciones antes de activarla."}</p></div>
          </section>;})}
        </div>
      </fieldset>}
      {tab === "log" && <section className="cr-log-section"><header className="cr-section-heading"><div><h2>Registro de acciones</h2><p>Resultados registrados por AutoMod.</p></div><button className="btn-secondary" onClick={loadLogs}><Icon name="refresh" />Actualizar</button></header>{logError && <p className="cr-inline-error" role="alert">{logError}</p>}{!logs.length ? <p className="cr-empty-inline">{logError ? "El registro no está disponible." : "No hay acciones de automoderación registradas."}</p> : <div className="cr-table-scroll"><table className="cr-data-table"><thead><tr>{["Regla","Usuario","Acción y motivo","Fecha"].map((title) => <th key={title}>{title}</th>)}</tr></thead><tbody>{logs.map((entry,index) => <tr key={entry.id || index}><td data-label="Regla">{entry.rule_label || (entry.rule === "llm" ? "Moderación IA" : RULE_META[entry.rule]?.label || entry.rule)}</td><td data-label="Usuario"><IdentityBadge item={entry} /></td><td data-label="Acción y motivo">{entry.action_label || LLM_OUTCOMES[entry.action_taken] || entry.action_taken}<ModerationReason entry={entry} /></td><td data-label="Fecha">{entry.created_at ? new Date(entry.created_at).toLocaleString("es") : "—"}</td></tr>)}</tbody></table></div>}</section>}
    </div>
  );
}
