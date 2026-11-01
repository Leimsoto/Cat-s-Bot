import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { endpointPayload, aiConnectionPayload, GEMINI_MODELS } from "../lib/endpointConfig";
import { useSaveBar } from "../lib/SaveBarContext";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import "./DashboardPanels.css";

const REASONING = [
  { id: "none", name: "Off · sin razonamiento" },
  { id: "auto", name: "Auto · decide Strata" },
  { id: "low", name: "Low" },
  { id: "medium", name: "Medium" },
  { id: "high", name: "High" },
  { id: "max", name: "Max" },
];

export default function Endpoints({ selectedGuild: guildId, onNavigate }) {
  return <EndpointSettings key={guildId} guildId={guildId} onNavigate={onNavigate} />;
}

function EndpointSettings({ guildId, onNavigate }) {
  const [llm, setLlm] = useState(null);
  const [ai, setAi] = useState(null);
  const [saved, setSaved] = useState(null);
  const [keyAssignment, setKeyAssignment] = useState(null);
  const [keyError, setKeyError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const version = useRef(0);
  const inFlight = useRef(false);
  const form = useRef(null);
  const warning = useRef(null);
  const llmChanged = saved && JSON.stringify(endpointPayload(llm, "", false)) !== JSON.stringify(endpointPayload(saved.llm, "", false));
  const aiChanged = saved && JSON.stringify(aiConnectionPayload(ai)) !== JSON.stringify(aiConnectionPayload(saved.ai));
  const dirty = Boolean(llmChanged || aiChanged || apiKey || clearApiKey);

  const load = useCallback(async () => {
    const current = ++version.current;
    setLoading(true);
    setToast(null);
    setConfirmation(null);
    setApiKey("");
    setClearApiKey(false);
    setKeyError("");
    try {
      const [connection, config, key] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/endpoints`, { cache: false }),
        apiGet(`/api/guilds/${guildId}/ia`, { cache: false }),
        apiGet(`/api/guilds/${guildId}/ia/key`, { cache: false }).catch(() => ({ failed: true })),
      ]);
      if (current !== version.current) return;
      const nextLlm = { api_type: "chat_completions", context_window_tokens: 262144, chat_reasoning_effort: "auto", web_reasoning_effort: "auto", ...connection.llm };
      const nextAi = aiConnectionPayload(config);
      setLlm(nextLlm);
      setAi(nextAi);
      setSaved({ llm: nextLlm, ai: nextAi });
      setKeyAssignment(key.assigned || null);
      if (key.failed) setKeyError("No se pudo consultar la clave Gemini asignada. No se ha cambiado su configuración.");
    } catch (error) {
      if (current === version.current) setToast({ msg: error.message || "No se pudieron cargar las conexiones", type: "error" });
    } finally {
      if (current === version.current) setLoading(false);
    }
  }, [guildId]);

  useEffect(() => { load(); return () => { version.current += 1; }; }, [load]);
  useEffect(() => { if (confirmation) warning.current?.focus(); }, [confirmation]);

  const setConnection = (field, value) => {
    setLlm((previous) => ({ ...previous, [field]: value, ...(field === "endpoint_url" ? { insecure_http_confirmed_url: "", private_endpoint_confirmed_url: "" } : {}) }));
    if (field === "endpoint_url") setConfirmation(null);
  };
  const setIntegration = (field, value) => setAi((previous) => ({ ...previous, [field]: value }));

  const save = async ({ source, clickCount = 0 } = {}) => {
    if (loading || inFlight.current || !saved) return;
    const invalid = form.current?.querySelector(":invalid");
    if (invalid) { invalid.reportValidity(); return; }
    const current = version.current;
    const payload = endpointPayload(llm, apiKey, clearApiKey);
    const endpoint = payload.llm.endpoint_url;
    if (llmChanged || apiKey || clearApiKey) {
      let http = false;
      if (endpoint) {
        try {
          const url = new URL(endpoint);
          if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.port === "0") throw new Error();
          http = url.protocol === "http:";
        } catch {
          setToast({ msg: "Introduce una URL HTTP o HTTPS válida, sin credenciales, parámetros ni fragmentos.", type: "error" });
          return;
        }
      }
      const needsHttp = http && llm.insecure_http_confirmed_url !== endpoint;
      const needsPrivate = confirmation?.url === endpoint && confirmation.private && llm.private_endpoint_confirmed_url !== endpoint;
      if (needsHttp || needsPrivate) {
        if (clickCount > 1) return;
        if (source !== "button" || confirmation?.url !== endpoint) {
          if (source === "button") setConfirmation({ url: endpoint, http, private: false });
          else setToast({ msg: "Vuelve al panel y pulsa Guardar para revisar la conexión antes de salir.", type: "error" });
          return;
        }
        if (needsHttp) payload.llm.insecure_http_confirmed_url = endpoint;
        if (needsPrivate) payload.llm.private_endpoint_confirmed_url = endpoint;
      }
    }
    inFlight.current = true;
    setSaving(true);
    setToast(null);
    let savedConnection = false;
    try {
      if (llmChanged || apiKey || clearApiKey) {
        const result = await apiPatch(`/api/guilds/${guildId}/endpoints`, payload);
        if (current !== version.current) return;
        setLlm(result.llm);
        setSaved((previous) => ({ ...previous, llm: result.llm }));
        setApiKey("");
        setClearApiKey(false);
        setConfirmation(null);
        savedConnection = true;
      }
      if (aiChanged) {
        await apiPatch(`/api/guilds/${guildId}/ia`, aiConnectionPayload(ai));
        if (current !== version.current) return;
        setSaved((previous) => ({ ...previous, ai: aiConnectionPayload(ai) }));
      }
      setToast({ msg: "Conexiones guardadas", type: "success" });
    } catch (error) {
      if (current !== version.current) return;
      if (source === "button" && error.status === 409 && error.endpointUrl === endpoint && error.code) {
        const required = error.requiredConfirmations || [];
        setConfirmation({ url: endpoint, http: required.includes("http") || error.code === "http_confirmation_required", private: required.includes("private") || error.code === "private_confirmation_required" });
      } else setToast({ msg: `${savedConnection ? "Strata se ha guardado; las demás conexiones siguen pendientes. " : ""}${error.message || "No se pudo guardar"}`, type: "error" });
    } finally {
      inFlight.current = false;
      if (current === version.current) setSaving(false);
    }
  };

  useSaveBar({ dirty: dirty && !loading, saving, onSave: save, onRevert: load });

  return <div className="cr-page cr-endpoints" ref={form}>
    <Toast toast={toast} onDismiss={() => setToast(null)} />
    <header className="cr-heading"><span className="cr-heading-icon"><Icon name="server" /></span><div><span className="cr-eyebrow">Conexiones</span><h1>Endpoints</h1><p>APIs y webhook del servidor, en un solo lugar.</p></div></header>
    {loading ? <div className="dashboard-empty-state" role="status"><div className="loading-spinner" /><p>Cargando conexiones…</p></div> : !llm || !ai ? <p role="alert" className="cr-inline-error">No se pudieron cargar las conexiones. <button className="btn-secondary" onClick={load}>Reintentar</button></p> : <fieldset disabled={saving} className="cr-fieldset" style={{ display: "grid", gap: 24 }}>
      <section className="cr-editor-panel">
        <h2>IA conversacional</h2>
        <div className="config-item"><label htmlFor="endpoint-provider">Proveedor</label><select id="endpoint-provider" value={ai.ai_provider} onChange={(e) => setIntegration("ai_provider", e.target.value)}><option value="auto">Automático · Strata si está configurado</option><option value="strata">Strata</option><option value="gemini">Gemini</option></select></div>
        <p className="cr-hint">Strata comparte su conexión con Moderación IA y los mensajes gestionados por IA, aunque la moderación esté apagada. La personalidad, memoria y herramientas se ajustan en Inteligencia Artificial.</p>
        <button type="button" className="btn-secondary" onClick={() => onNavigate?.("ia")}>Ajustar comportamiento de la IA</button>
      </section>
      <section className="cr-editor-panel">
        <h2>Strata · API compatible</h2>
        <div className="cr-form-grid">
          <div className="config-item"><label htmlFor="endpoint-api-type">Tipo de API</label><select id="endpoint-api-type" value={llm.api_type} onChange={(e) => setConnection("api_type", e.target.value)}><option value="chat_completions">Chat Completions</option><option value="responses">Responses</option></select></div>
          <div className="config-item"><label htmlFor="endpoint-model">Modelo</label><input id="endpoint-model" maxLength={200} value={llm.model || ""} onChange={(e) => setConnection("model", e.target.value)} /></div>
        </div>
        <div className="config-item"><label htmlFor="endpoint-url">URL del endpoint</label><input id="endpoint-url" type="url" maxLength={2048} value={llm.endpoint_url || ""} placeholder="https://proveedor.example/v1" onChange={(e) => setConnection("endpoint_url", e.target.value)} /><p className="cr-hint">Admite una URL base, como https://proveedor.example/v1, o la ruta completa de la API elegida. Sin credenciales, parámetros ni fragmentos. HTTP y los destinos privados requieren confirmación al guardar. La conexión sale del equipo del bot.</p></div>
        {confirmation && <div ref={warning} className="cr-inline-error" role="alert" tabIndex={-1}>
          <strong>Revisa esta conexión antes de guardarla</strong>
          {confirmation.http && <p>HTTP envía los mensajes, contexto y API key sin cifrar. Alguien con acceso al tráfico podría leerlos o modificarlos.</p>}
          {confirmation.private && <p>Este destino puede acceder a la red privada del equipo del bot y recibirá los datos y la API key configurados. Confirma solo si controlas o confías en el destino.</p>}
          <p>Para aceptar y guardar exactamente <code style={{ overflowWrap: "anywhere" }}>{confirmation.url}</code>, pulsa de nuevo <strong>Guardar</strong>. La conexión aún no se ha guardado.</p>
          <button type="button" className="btn-secondary" onClick={() => setConfirmation(null)}>Cancelar confirmación</button>
        </div>}
        <div className="config-item"><label htmlFor="endpoint-key">API key (opcional)</label><input id="endpoint-key" type="password" autoComplete="new-password" maxLength={4096} value={apiKey} disabled={clearApiKey || saving} onChange={(e) => setApiKey(e.target.value)} /><p className="cr-hint">{llm.api_key_configured ? "Hay una clave guardada. Dejar este campo vacío la conserva, también al cambiar la URL. Escribe una nueva para reemplazarla." : "No hay clave guardada. Deja el campo vacío si tu proveedor no necesita autenticación."} La clave guardada nunca se muestra. Al cambiar de URL, revisa que confías en el destino antes de enviarle la clave.</p>{llm.api_key_configured && <label className="cr-check-row"><input type="checkbox" checked={clearApiKey} onChange={(e) => { setClearApiKey(e.target.checked); setApiKey(""); }} />Eliminar la clave guardada al guardar</label>}</div>
        <div className="config-item"><label htmlFor="endpoint-context">Ventana de contexto (tokens)</label><input id="endpoint-context" type="number" required min={4096} max={1048576} step={1} value={llm.context_window_tokens ?? 262144} onChange={(e) => setConnection("context_window_tokens", e.target.value === "" ? "" : Number(e.target.value))} /><div style={{ display: "flex", gap: 10, marginTop: 8 }}><button type="button" className="btn-secondary" onClick={() => setConnection("context_window_tokens", 262144)}>256K · 262144</button><button type="button" className="btn-secondary" onClick={() => setConnection("context_window_tokens", 524288)}>512K · 524288</button></div><p className="cr-hint">Entre 4096 y 1048576 tokens. Indica la capacidad real del modelo: se reserva espacio para instrucciones, herramientas, imágenes y respuesta. Aumentarla puede enviar más contexto y consumir más tokens; no amplía la capacidad del proveedor.</p></div>
        <div className="cr-form-grid">
          <div className="config-item"><label>Razonamiento · Chat</label><SearchableSelect ariaLabel="Razonamiento Chat" options={REASONING} value={llm.chat_reasoning_effort || "auto"} onChange={(value) => setConnection("chat_reasoning_effort", value)} disabled={saving} /></div>
          <div className="config-item"><label>Razonamiento · Búsqueda web</label><SearchableSelect ariaLabel="Razonamiento Búsqueda web" options={REASONING} value={llm.web_reasoning_effort || "auto"} onChange={(value) => setConnection("web_reasoning_effort", value)} disabled={saving} /></div>
        </div>
        <p className="cr-hint">Cada opción controla una fase independiente. Más razonamiento puede aumentar el tiempo y el consumo; el proveedor debe admitir el nivel elegido.</p>
        <label className="cr-check-row"><input type="checkbox" checked={!!llm.supports_images} onChange={(e) => setConnection("supports_images", e.target.checked)} />El modelo admite imágenes</label>
        <p className="cr-hint">Permite enviar imágenes al proveedor desde la conversación y Moderación IA. Hasta 4 imágenes y 8 MiB por consulta. Los permisos y el comportamiento de cada módulo siguen aplicándose.</p>
      </section>
      <section className="cr-editor-panel"><h2>Gemini</h2><div className="config-item"><label>Modelo Gemini</label><SearchableSelect ariaLabel="Modelo Gemini" options={GEMINI_MODELS} value={ai.ai_model || ""} onChange={(value) => setIntegration("ai_model", value || null)} placeholder="Modelo predeterminado del bot" disabled={saving} /></div>
        {keyError ? <p className="cr-inline-error" role="alert">{keyError} </p> : <p className="cr-hint" role="status">{keyAssignment ? `Clave asignada: ${keyAssignment.label || "Sin etiqueta"}${keyAssignment.active ? " · activa" : " · inactiva"}.` : "Sin clave dedicada asignada. Usará GEMINI_API_KEY del bot si está configurada."} Las asignaciones del pool las gestiona el administrador del bot.</p>}
      </section>
      <section className="cr-editor-panel"><h2>Webhook de respuestas de Gemini</h2><p className="cr-hint">Identidad del webhook que Gemini usa para responder en Discord. Strata responde con la identidad del bot. El bot crea y gestiona el webhook; no necesitas introducir su URL ni su token.</p><div className="cr-form-grid"><div className="config-item"><label htmlFor="endpoint-webhook-name">Nombre del webhook</label><input id="endpoint-webhook-name" maxLength={80} value={ai.ai_webhook_name || ""} placeholder="Cat's Bot IA" onChange={(e) => setIntegration("ai_webhook_name", e.target.value)} /></div><div className="config-item"><label htmlFor="endpoint-webhook-icon">Avatar del webhook (URL)</label><input id="endpoint-webhook-icon" type="url" maxLength={2048} value={ai.ai_webhook_icon || ""} placeholder="https://…" onChange={(e) => setIntegration("ai_webhook_icon", e.target.value)} /></div></div></section>
    </fieldset>}
  </div>;
}
