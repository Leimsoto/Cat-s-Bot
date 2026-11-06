import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";
import { useSaveBar } from "../lib/SaveBarContext";
import MessageEditor, { normalizeMessage } from "./MessageEditor";
import "./DashboardPanels.css";

const TABS = [["welcome", "Bienvenidas", "welcome"], ["boost", "Boosters", "giveaways"], ["invites", "Invitaciones", "invites"]];
const ENDPOINTS = { welcome: "welcome", boost: "welcome/boost", invites: "welcome/invites" };
const parseMessage = (raw, fallback) => {
  if (raw) { try { return normalizeMessage(typeof raw === "string" ? JSON.parse(raw) : raw); } catch { /* Un mensaje heredado inválido conserva una propuesta editable. */ } }
  return normalizeMessage(fallback);
};

export default function Welcome({ selectedGuild, onToast }) {
  return <WelcomeSettings key={selectedGuild} guildId={selectedGuild} onToast={onToast} />;
}

function WelcomeSettings({ guildId, onToast }) {
  const [tab, setTab] = useState("welcome");
  const [data, setData] = useState(null);
  const [changed, setChanged] = useState({});
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [leaderboard, setLeaderboard] = useState([]);
  const [inviteStatus, setInviteStatus] = useState("idle");
  const [inviteError, setInviteError] = useState("");
  const [wTab, setWTab] = useState("content");
  const [bTab, setBTab] = useState("embed-content");
  const requestVersion = useRef(0);
  const inviteVersion = useRef(0);
  const dirty = Object.keys(changed).length > 0;
  const toast = (type, message) => onToast?.({ type, message });

  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);setError("");
    try {
      const result = await apiGet(`/api/guilds/${guildId}/welcome`, { cache: false });
      if (version !== requestVersion.current) return;
      setData(result);setChanged({});
    } catch (failure) { if (version === requestVersion.current) setError(failure.message || "No pudimos cargar los mensajes del servidor."); }
    finally { if (version === requestVersion.current) setLoading(false); }
  }, [guildId]);
  useEffect(() => { load(); return () => { requestVersion.current += 1; inviteVersion.current += 1; }; }, [load]);

  const loadInvites = useCallback(async () => {
    const version = ++inviteVersion.current;
    setInviteStatus("loading");setInviteError("");
    try {
      const result = await apiGet(`/api/guilds/${guildId}/invites`, { cache: false });
      if (version !== inviteVersion.current) return;
      setLeaderboard(result?.leaderboard || []);setInviteStatus("loaded");
    } catch (failure) { if (version === inviteVersion.current) { setInviteError(failure.message || "No pudimos cargar las invitaciones.");setInviteStatus("error"); } }
  }, [guildId]);
  const changeTab = (next) => {
    setTab(next);
    if (next === "invites" && inviteStatus === "idle") loadInvites();
  };

  const setSection = (section, key, value) => {
    setData((previous) => ({ ...previous, [section]: { ...previous[section], [key]: value } }));
    setChanged((previous) => ({ ...previous, [section]: true }));setError("");
  };
  const save = async () => {
    if (!data || saving || !dirty) return;
    const version = requestVersion.current;
    const sections = Object.keys(changed);
    const snapshot = data;
    setSaving(true);setError("");
    const results = await Promise.allSettled(sections.map((section) => apiPatch(`/api/guilds/${guildId}/${ENDPOINTS[section]}`, snapshot[section] || {})));
    if (version !== requestVersion.current) return;
    const failed = sections.filter((_, index) => results[index].status === "rejected");
    setChanged((previous) => Object.fromEntries(Object.entries(previous).filter(([section]) => !sections.includes(section) || failed.includes(section))));
    setSaving(false);
    if (failed.length) {
      const names = failed.map((section) => TABS.find(([id]) => id === section)[1]).join(", ");
      const reasons = results.filter((result) => result.status === "rejected").map((result) => result.reason?.message).filter(Boolean).join(" · ");
      const message = `Quedan cambios sin guardar en ${names}.${reasons ? ` ${reasons}` : " Vuelve a intentarlo."}`;
      setError(message);toast("error",message);
    } else toast("success","Mensajes guardados en todas las secciones modificadas.");
  };
  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading) return <div className="cr-page cr-loading" role="status"><div className="loading-spinner" /><p>Cargando mensajes de tu comunidad…</p></div>;
  if (!data) return <div className="cr-page cr-empty" role="alert"><Icon name="warning" /><h2>No pudimos cargar las bienvenidas</h2><p>{error}</p><button className="btn-secondary" onClick={load}>Reintentar</button></div>;

  const welcomeMessage = parseMessage(data.welcome?.embed_data, { enabled: true, embed: { title: "¡Bienvenido a {server}!", description: "{user}, eres el miembro número **{count}**.", color: "#b58ce0" } });
  const boostMessage = parseMessage(data.boost?.embed_data, { enabled: true, embed: { title: "¡Nuevo Booster!", description: "Gracias {user} por mejorar nuestro servidor.", color: "#b58ce0" } });
  const channelField = (section, label) => <div className="cr-field"><label>{label}</label><SearchableSelect ariaLabel={label} value={data[section]?.channel_id || null} onChange={(value) => setSection(section, "channel_id", value ? String(value) : null)} endpoint={`/api/guilds/${guildId}/channels?type=text`} itemsKey="channels" placeholder="Seleccionar canal…" renderOption={(option) => <span>#{option.name}</span>} renderSelected={(option) => <span>#{option.name}</span>} /></div>;

  return <div className="cr-page cr-welcome"><header className="cr-heading"><span className="cr-heading-icon"><Icon name="welcome" /></span><div><span className="cr-eyebrow">Comunidad</span><h1>Bienvenidas</h1><p>El primer mensaje también habla de tu comunidad.</p></div></header>
    <nav className="cr-tabs" aria-label="Mensajes de comunidad">{TABS.map(([id, label, icon]) => <button key={id} type="button" aria-pressed={tab === id} onClick={() => changeTab(id)}><Icon name={icon} />{label}{changed[id] && <span className="cr-unsaved-dot" aria-label="Cambios sin guardar" />}</button>)}</nav>
    {error && <p className="cr-inline-error" role="alert">{error}</p>}
    <fieldset className="cr-fieldset" disabled={saving}>
      {tab === "welcome" && <><div className="cr-status-strip"><div><h2>Recibir a nuevos miembros</h2><p>Publica un saludo cuando alguien se une al servidor.</p></div><label className="cr-switch"><input type="checkbox" aria-label="Activar bienvenidas" checked={!!data.welcome?.enabled} onChange={(event) => setSection("welcome","enabled",event.target.checked ? 1 : 0)} /><span aria-hidden="true" /></label></div>{channelField("welcome","Canal de bienvenida")}<MessageEditor value={welcomeMessage} onChange={(next) => setSection("welcome","embed_data",JSON.stringify(next))} mode="both" tab={wTab} setTab={setWTab} variablesHelp="Variables: {user}, {username}, {server}, {count}." placeholders={{title:"¡Bienvenido a {server}!",description:"{user}, eres el miembro número **{count}**.",content:"Mensaje opcional fuera del embed"}} showJson /></>}
      {tab === "boost" && <><div className="cr-status-strip"><div><h2>Agradecer a tus boosters</h2><p>Un mensaje para quienes mejoran el servidor.</p></div><label className="cr-switch"><input type="checkbox" aria-label="Activar agradecimiento a boosters" checked={!!data.boost?.enabled} onChange={(event) => setSection("boost","enabled",event.target.checked ? 1 : 0)} /><span aria-hidden="true" /></label></div><div className="cr-form-grid">{channelField("boost","Canal de boosters")}<label className="cr-field"><span>URL del GIF animado</span><input type="url" value={data.boost?.gif_url || ""} placeholder="https://media.giphy.com/…" onChange={(event) => setSection("boost","gif_url",event.target.value)} /><small>Se mostrará en el mensaje de agradecimiento.</small></label></div><MessageEditor value={boostMessage} onChange={(next) => setSection("boost","embed_data",JSON.stringify(next))} mode="both" tab={bTab} setTab={setBTab} variablesHelp="Variables: {user}, {username}, {server}. El GIF de arriba reemplaza la imagen del embed." showJson /></>}
      {tab === "invites" && <><div className="cr-status-strip"><div><h2>Registro de invitaciones</h2><p>Registra quién invitó a cada miembro y sus salidas.</p></div><label className="cr-switch"><input type="checkbox" aria-label="Activar registro de invitaciones" checked={!!data.invites?.enabled} onChange={(event) => setSection("invites","enabled",event.target.checked ? 1 : 0)} /><span aria-hidden="true" /></label></div>{channelField("invites","Canal de registro de invitaciones")}<section className="cr-invites"><header className="cr-section-heading"><h2>Top invitadores</h2><button type="button" className="btn-secondary" disabled={inviteStatus === "loading"} onClick={loadInvites}><Icon name="refresh" />Actualizar</button></header>{inviteStatus === "loading" && <p role="status">Cargando invitaciones…</p>}{inviteError && <p className="cr-inline-error" role="alert">{inviteError}</p>}{inviteStatus === "loaded" && !leaderboard.length && <p className="cr-empty-inline">Aún no hay invitaciones registradas.</p>}{leaderboard.map((entry,index) => <div className="cr-invite-row" key={entry.user_id}><span className="cr-rank">{index+1}</span>{entry.avatar ? <img src={entry.avatar} alt="" /> : <span className="cr-row-icon"><Icon name="user" /></span>}<div><h3>{entry.username}</h3><small>{entry.user_id}</small></div><strong>{entry.total}<small>invitaciones</small></strong></div>)}</section></>}
    </fieldset>
  </div>;
}
