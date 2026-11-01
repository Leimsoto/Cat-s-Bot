import { useId, useMemo, useState } from "react";
import { Icon } from "../lib/icons";
import "./DashboardPanels.css";

export const EMPTY_MESSAGE = { content: "", enabled: true, ai_managed: false, embed: { title: "", description: "", color: "#6366f1", footer: "", footer_icon: "", image: "", thumbnail: "", author: "", author_icon: "", author_url: "" } };
export function normalizeMessage(raw) {
  return { content: raw?.content ?? "", enabled: raw?.enabled !== false, ai_managed: raw?.ai_managed === true, embed: { ...EMPTY_MESSAGE.embed, ...(raw?.embed || {}) } };
}
const SWATCHES = ["#ef4444", "#f472b6", "#f97316", "#facc15", "#84cc16", "#10b981", "#0ea5e9", "#6366f1", "#8b5cf6", "#a78bfa"];

export default function MessageEditor({ value, onChange, mode = "embed", compact = false, showJson = false, placeholders = {}, variablesHelp = "", tab, setTab }) {
  const v = useMemo(() => normalizeMessage(value), [value]);
  const [localTab, setLocalTab] = useState(mode === "both" || mode === "plain" ? "content" : "embed-content");
  const id = useId();
  const tabs = [...(mode !== "embed" ? [["content", "Mensaje", "autoresponses"]] : []), ...(mode !== "plain" ? [["embed-content", "Embed", "embeds"], ["author", "Autor y pie", "user"], ["media", "Imágenes", "eye"]] : [])];
  const requested = tab || localTab;
  const activeTab = tabs.some(([key]) => key === requested) ? requested : tabs[0][0];
  const setEmbed = (key, next) => onChange({ ...v, embed: { ...v.embed, [key]: next } });
  const variables = [...new Set(variablesHelp.match(/\{\w+\}/g) || [])];
  const editorField = (key, label, type = "text") => <label className="cr-field" key={key} htmlFor={`${id}-${key}`}><span>{label}</span><input id={`${id}-${key}`} type={type} value={v.embed[key]} onChange={(event) => setEmbed(key, event.target.value)} /></label>;

  return <div className={`cr-message-editor${compact ? " cr-message-compact" : ""}`}>
    <div className="cr-message-controls">
      <div className="cr-editor-panel"><label className="cr-check-row" htmlFor={`${id}-ai-managed`}><input id={`${id}-ai-managed`} type="checkbox" checked={v.ai_managed} onChange={(event) => onChange({ ...v, ai_managed: event.target.checked })} /><strong>Gestionado por IA</strong></label><p className="cr-hint">{v.ai_managed ? "La IA adapta este mensaje al enviarlo usando la personalidad del servidor. Tu plantilla se conserva como base y se usa si la IA no está disponible." : "Se enviará tu plantilla manual. Activa esta opción solo si quieres que la IA adapte su redacción."}</p></div>
      {mode === "both" && <label className="cr-check-row"><input type="checkbox" checked={v.enabled} onChange={(event) => onChange({ ...v, enabled: event.target.checked })} /><span>Incluir un embed en el mensaje</span></label>}
      <div className="cr-editor-panel"><nav className="cr-editor-tabs" aria-label="Partes del mensaje">{tabs.map(([key, label, icon]) => <button key={key} type="button" aria-pressed={activeTab === key} onClick={() => (setTab || setLocalTab)(key)}><Icon name={icon} />{label}</button>)}</nav>
        {activeTab === "content" && <label className="cr-field" htmlFor={`${id}-content`}><span>Contenido del mensaje</span><textarea id={`${id}-content`} rows={6} value={v.content} placeholder={placeholders.content || "Escribe el mensaje…"} onChange={(event) => onChange({ ...v, content: event.target.value })} /></label>}
        {activeTab === "embed-content" && <><label className="cr-field" htmlFor={`${id}-title`}><span>Título del embed</span><input id={`${id}-title`} value={v.embed.title} placeholder={placeholders.title || "Título del embed"} onChange={(event) => setEmbed("title", event.target.value)} /></label><label className="cr-field" htmlFor={`${id}-description`}><span>Descripción</span><textarea id={`${id}-description`} rows={6} value={v.embed.description} placeholder={placeholders.description || "Contenido principal del embed…"} onChange={(event) => setEmbed("description", event.target.value)} /></label><div className="cr-field"><span>Color del embed</span><div className="cr-color-swatches">{SWATCHES.map((color) => <button key={color} type="button" aria-label={`Usar color ${color}`} aria-pressed={v.embed.color === color} style={{ "--cr-swatch": color }} onClick={() => setEmbed("color", color)} />)}</div><div className="cr-color-inputs"><input type="color" aria-label="Elegir color del embed" value={/^#[0-9a-f]{6}$/i.test(v.embed.color) ? v.embed.color : "#6366f1"} onChange={(event) => setEmbed("color", event.target.value)} /><input aria-label="Color hexadecimal del embed" value={v.embed.color} placeholder="#6366f1" onChange={(event) => setEmbed("color", event.target.value)} /></div></div></>}
        {activeTab === "author" && <>{editorField("author", "Nombre del autor")}{editorField("author_icon", "Icono del autor (URL)", "url")}{editorField("author_url", "Enlace del autor (URL)", "url")}<hr />{editorField("footer", "Texto del pie")}{editorField("footer_icon", "Icono del pie (URL)", "url")}</>}
        {activeTab === "media" && <>{editorField("image", "Imagen grande (URL)", "url")}{editorField("thumbnail", "Miniatura (URL)", "url")}<p className="cr-hint">Las imágenes se mostrarán con el mensaje en Discord.</p></>}
        {variablesHelp && <div className="cr-variables"><p>{variablesHelp}</p>{variables.length > 0 && <div>{variables.map((variable) => <button type="button" key={variable} onClick={() => activeTab === "content" ? onChange({ ...v, content: v.content + variable }) : setEmbed("description", v.embed.description + variable)}>{variable}</button>)}</div>}</div>}
      </div>
    </div>
    {!compact && <div className="cr-message-preview-column"><details className="cr-preview-disclosure" open><summary>{v.ai_managed ? "Plantilla base en Discord" : "Vista previa en Discord"}</summary><MessagePreview value={v} /></details>{variablesHelp && <p className="cr-hint">Las variables se completan al enviar el mensaje.</p>}{showJson && <details className="cr-json"><summary>Ver JSON del mensaje</summary><pre>{JSON.stringify(v, null, 2)}</pre></details>}</div>}
  </div>;
}

export function MessagePreview({ value }) {
  const v = normalizeMessage(value), embed = v.embed;
  return <div className="cr-discord-preview"><div className="cr-discord-message"><img className="cr-bot-avatar" src={`${import.meta.env.BASE_URL}logo.png`} alt="" /><div className="cr-discord-body"><div className="cr-bot-name">Cat's Bot <span>APP</span></div>{v.content && <p className="cr-discord-content">{v.content}</p>}{v.enabled && (embed.title || embed.description || embed.image || embed.author || embed.footer) && <div className="cr-discord-embed" style={{ borderLeftColor: embed.color || "#6366f1" }}>
    {embed.thumbnail && <img key={embed.thumbnail} src={embed.thumbnail} className="cr-embed-thumbnail" alt="Miniatura del mensaje" onError={(event) => { event.currentTarget.hidden = true; }} />}
    {(embed.author || embed.author_icon) && <div className="cr-embed-byline">{embed.author_icon && <img key={embed.author_icon} src={embed.author_icon} alt="" onError={(event) => { event.currentTarget.hidden = true; }} />}<strong>{embed.author}</strong></div>}
    {embed.title && <h3>{embed.title}</h3>}{embed.description && <p>{embed.description}</p>}{embed.image && <img key={embed.image} className="cr-embed-image" src={embed.image} alt="Imagen del mensaje" onError={(event) => { event.currentTarget.hidden = true; }} />}
    {(embed.footer || embed.footer_icon) && <div className="cr-embed-footer">{embed.footer_icon && <img key={embed.footer_icon} src={embed.footer_icon} alt="" onError={(event) => { event.currentTarget.hidden = true; }} />}<span>{embed.footer}</span></div>}
    </div>}{!v.content && (!v.enabled || !(embed.title || embed.description || embed.image || embed.author || embed.footer)) && <p className="cr-hint">Tu mensaje aparecerá aquí mientras lo escribes.</p>}</div></div></div>;
}
