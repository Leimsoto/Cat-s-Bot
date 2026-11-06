import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPut, apiPatch, apiDelete } from "../lib/api";
import { useSaveBar } from "../lib/SaveBarContext";
import SearchableSelect from "./ui/SearchableSelect";
import Schedules from "./Schedules";
import "./ChannelSettings.css";

const DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const ROLE_MODES = [
  ["inherit", "Heredar requisito global"],
  ["additional", "Exigir también un rol de este canal"],
  ["override", "Sustituir por los roles de este canal"],
  ["off", "Sin requisito de rol en este canal"],
];
const CONDITIONS = [
  ["any_message", "Cualquier mensaje"], ["contains_text", "Contiene una palabra o frase"],
  ["has_link", "Contiene un enlace"], ["no_media", "No contiene multimedia"],
  ["missing_role", "No tiene ninguno de estos roles"],
];
const PERMISSION_LABELS = {
  view_channel: "Ver canal", send_messages: "Enviar mensajes", send_messages_in_threads: "Enviar en hilos",
  create_public_threads: "Crear hilos públicos", create_private_threads: "Crear hilos privados",
  attach_files: "Adjuntar archivos", embed_links: "Insertar enlaces", add_reactions: "Añadir reacciones",
  read_message_history: "Leer historial", mention_everyone: "Mencionar @everyone", use_external_emojis: "Usar emojis externos",
};

function Field({ label, children, help, wide = false }) {
  return <div className={`cs-field ${wide ? "wide" : ""}`} role="group" aria-label={label}><label>{label}</label>{children}{help ? <span className="cs-help">{help}</span> : null}</div>;
}

function Check({ children, checked, onChange, disabled = false }) {
  return <label className="cs-check"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span>{children}</span></label>;
}

function Lines({ value, onChange, label, placeholder }) {
  // Keep blank draft lines while typing; normalize only at the save boundary.
  return <textarea aria-label={label} value={value.join("\n")} placeholder={placeholder} onChange={(e) => onChange(e.target.value.split("\n"))} />;
}

function NativePermissions({ guildId, channelId, roles, onToast }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [type, setType] = useState("role");
  const [target, setTarget] = useState(null);
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);
  const endpoint = `/api/guilds/${guildId}/channel-settings/${channelId}/permissions`;
  const load = useCallback(async () => {
    setError("");
    try { setData(await apiGet(endpoint, { cache: false })); }
    catch (e) { setError(e.message || "No se pudieron cargar los permisos."); }
  }, [endpoint]);
  useEffect(() => { load(); }, [load]);
  const current = data?.overwrites.find((o) => o.target_type === type && o.target_id === target)?.permissions || {};
  const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => value !== (current[key] ?? null)));
  const chooseTarget = (nextType, id) => {
    if (Object.keys(changes).length && !window.confirm("¿Descartar los cambios de permisos sin aplicar?")) return;
    setType(nextType); setTarget(id); setDraft({});
  };
  const save = async () => {
    setSaving(true);
    try {
      const result = await apiPatch(endpoint, { target_type: type, target_id: target, permissions: changes });
      setData((prev) => ({ ...prev, overwrites: [...prev.overwrites.filter((o) => o.target_type !== type || o.target_id !== target), result.overwrite] }));
      setDraft({});
      onToast?.({ type: "success", message: "Permisos actualizados en Discord." });
    } catch (e) { onToast?.({ type: "error", message: e.message || "No se pudieron aplicar los permisos." }); }
    finally { setSaving(false); }
  };
  if (error) return <section className="cs-section" role="alert"><h3>Permisos nativos de Discord</h3><p>{error}</p><button className="btn-secondary" onClick={load}>Reintentar permisos</button></section>;
  if (!data) return <section className="cs-section" role="status">Cargando permisos de Discord…</section>;
  const memberOptions = data.overwrites.filter((o) => o.target_type === "member").map((o) => ({ id: o.target_id, name: o.name }));
  return <section className="cs-section"><h3>Permisos nativos de Discord</h3><p className="cs-help">Se aplican directamente en Discord, por separado de las reglas del bot. Cada cambio conserva los demás permisos de este destino y los otros overwrites.</p>
    <p className="cs-note">Permitir o denegar aquí es una sobrescritura del canal. El acceso efectivo también depende de los otros roles, del permiso Administrador y de Discord. Cambiar estos permisos puede desvincular la sincronización con la categoría.</p>
    {!data.can_manage ? <p className="cs-warning">El usuario o el bot no tienen los permisos necesarios para gestionar este canal.</p> : null}
    <fieldset disabled={saving}><div className="cs-fields"><Field label="Tipo de destino"><select aria-label="Tipo de destino de permisos" value={type} onChange={(e) => chooseTarget(e.target.value, null)}><option value="role">Rol</option><option value="member">Usuario</option></select></Field>
      <Field label={type === "role" ? "Rol" : "Usuario"}><SearchableSelect value={target} onChange={(id) => chooseTarget(type, id)} options={type === "role" ? [{ id: guildId, name: "@everyone" }, ...roles] : memberOptions} endpoint={type === "member" ? `/api/guilds/${guildId}/members` : null} itemsKey="members" placeholder={type === "role" ? "Seleccionar rol…" : "Buscar miembro…"} /></Field></div>
      {data.overwrites.length ? <div className="cs-rule"><strong>Destinos con permisos propios</strong><div className="cs-days">{data.overwrites.map((o) => <button type="button" className={`tab-btn ${target === o.target_id && type === o.target_type ? "active" : ""}`} key={`${o.target_type}:${o.target_id}`} onClick={() => chooseTarget(o.target_type, o.target_id)}>{o.name} · {o.target_type === "role" ? "Rol" : "Usuario"}</button>)}</div></div> : null}
      {target ? <><table className="cs-permissions"><thead><tr><th scope="col">Permiso</th><th scope="col">Sobrescritura</th></tr></thead><tbody>{data.available_permissions.map((key) => <tr key={key}><th scope="row">{PERMISSION_LABELS[key] || key}</th><td><select disabled={!data.can_manage} aria-label={PERMISSION_LABELS[key] || key} value={String(Object.hasOwn(draft, key) ? draft[key] : current[key] ?? null)} onChange={(e) => setDraft((prev) => ({ ...prev, [key]: e.target.value === "null" ? null : e.target.value === "true" }))}><option value="null">Heredar</option><option value="true">Permitir</option><option value="false">Denegar</option></select></td></tr>)}</tbody></table><div className="cs-actions"><button className="btn-secondary" disabled={!Object.keys(changes).length} onClick={() => setDraft({})}>Descartar permisos</button><button className="btn-primary" disabled={!data.can_manage || !Object.keys(changes).length} onClick={save}>{saving ? "Aplicando…" : "Aplicar permisos en Discord"}</button></div></> : <p className="cs-help">Elige un rol o usuario para consultar sus sobrescrituras.</p>}
    </fieldset>
  </section>;
}

function Editor({ selectedGuild: guildId, onToast }) {
  const [data, setData] = useState(null);
  const [channels, setChannels] = useState([]);
  const [roles, setRoles] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [config, setConfig] = useState(null);
  const [original, setOriginal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("rules");
  const [search, setSearch] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const endpoint = `/api/guilds/${guildId}/channel-settings`;
  const dirty = config && JSON.stringify(config) !== JSON.stringify(original);
  const notify = (type, message) => onToast?.({ type, message });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [policy, channelData, roleData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/channel-settings`, { cache: false }),
        apiGet(`/api/guilds/${guildId}/channels?limit=500`),
        apiGet(`/api/guilds/${guildId}/roles?limit=500&include_managed=true`),
      ]);
      if (!alive.current) return;
      setData(policy);
      setChannels((channelData.channels || []).filter((c) => !["category", "public_thread", "private_thread", "news_thread", "stage_voice", "4", "10", "11", "12", "13"].includes(String(c.type))));
      setRoles(roleData.roles || []);
    } catch (e) {
      if (alive.current) setError(e.message || "No se pudieron cargar los ajustes.");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [guildId]);
  useEffect(() => { load(); }, [load]);

  const choose = (ids) => {
    if (dirty && !window.confirm("Tienes cambios sin guardar. ¿Descartarlos y cambiar de selección?")) return;
    const value = ids.length ? data.channels.find((c) => c.channel_id === ids[0])?.config || data.default_config : null;
    setSelectedIds(ids);
    setConfig(value ? structuredClone(value) : null);
    setOriginal(value ? structuredClone(value) : null);
  };
  const update = (section, key, value) => setConfig((prev) => section
    ? { ...prev, [section]: { ...prev[section], [key]: value } }
    : { ...prev, [key]: value });

  const save = async () => {
    if (!selectedIds.length || !config || saving) return;
    if (["additional", "override"].includes(config.role.mode) && !config.role.role_ids.length) return notify("error", "Selecciona al menos un rol para el requisito local.");
    if (["additional", "override"].includes(config.role.mode) && !config.role.notice.trim()) return notify("error", "Escribe el aviso público del requisito de rol.");
    if (config.triggers.some((t) => t.notify_staff) && !config.staff_channel_id) return notify("error", "Selecciona el canal de avisos para el equipo.");
    if (config.triggers.some((t) => !t.name.trim())) return notify("error", "Escribe un nombre para cada trigger.");
    if (config.triggers.some((t) => ["contains_text", "missing_role"].includes(t.condition) && !t.values.some((v) => v.trim()))) return notify("error", "Selecciona roles o escribe frases para cada condición de trigger.");
    if (config.triggers.some((t) => !t.delete && !t.response.trim() && !t.notify_staff)) return notify("error", "Cada trigger necesita una acción: borrar, responder o avisar.");
    if (config.schedule.enabled && (!config.schedule.windows.length || config.schedule.windows.some((w) => !w.days.length || w.start === w.end))) return notify("error", "Cada franja necesita días y horas de inicio y fin distintas.");
    const payload = structuredClone(config);
    payload.restrictions.blocked_words = payload.restrictions.blocked_words.map((w) => w.trim()).filter(Boolean);
    payload.triggers = payload.triggers.map((t) => ({ ...t, values: t.values.map((v) => v.trim()).filter(Boolean) }));
    setSaving(true);
    try {
      const result = await apiPut(endpoint, { channel_ids: selectedIds, config: payload });
      if (!alive.current) return;
      setData(result);
      const saved = result.channels.find((c) => c.channel_id === selectedIds[0])?.config || payload;
      setConfig(structuredClone(saved));
      setOriginal(structuredClone(saved));
      notify("success", `Ajustes guardados en ${selectedIds.length} ${selectedIds.length === 1 ? "canal" : "canales"}.`);
    } catch (e) {
      if (alive.current) notify("error", e.message || "No se pudieron guardar los ajustes.");
    } finally {
      if (alive.current) setSaving(false);
    }
  };
  const remove = async () => {
    if (!window.confirm(`¿Eliminar los ajustes propios de ${selectedIds.length} canal(es) y volver a heredar la configuración global?`)) return;
    setSaving(true);
    const removed = [];
    try {
      for (const id of selectedIds) { await apiDelete(`${endpoint}/${id}`); removed.push(id); }
      const result = await apiGet(endpoint, { cache: false });
      if (!alive.current) return;
      setData(result);
      setConfig(structuredClone(result.default_config));
      setOriginal(structuredClone(result.default_config));
      notify("success", "Los canales vuelven a heredar la configuración global.");
    } catch (e) {
      if (alive.current) {
        setData((prev) => ({ ...prev, channels: prev.channels.filter((c) => !removed.includes(c.channel_id)) }));
        notify("error", `${e.message}. Eliminados: ${removed.length} de ${selectedIds.length}; los demás se conservan.`);
      }
    } finally { if (alive.current) setSaving(false); }
  };
  useSaveBar({ dirty: !!dirty, saving, onSave: save, onRevert: () => setConfig(structuredClone(original)) });

  if (loading) return <div className="dashboard-empty-state" role="status"><div className="loading-spinner" /><p>Cargando ajustes por canal…</p></div>;
  if (error) return <div className="cs-empty" role="alert"><h2>No se pudieron cargar los canales</h2><p>{error}</p><button className="btn-secondary" onClick={load}>Reintentar</button></div>;
  const roleName = (id) => roles.find((r) => r.id === id)?.name || `Rol ${id}`;
  const configured = new Map(data.channels.map((c) => [c.channel_id, c.config]));
  const selectedChannels = channels.filter((c) => selectedIds.includes(c.id));
  const textChannels = channels.filter((c) => ["text", "news", "announcement", "0", "5"].includes(String(c.type)));
  const visibleChannels = channels.filter((c) => `${c.name} ${c.category || ""}`.toLowerCase().includes(search.toLowerCase()));
  const global = data.global_role;
  const changeTrigger = (index, key, value) => update(null, "triggers", config.triggers.map((t, i) => i === index ? { ...t, [key]: value } : t));

  return <div className="channel-settings animate-fade-in">
    <div className="section-header"><h2>Ajustes por canal</h2><p>Personaliza las reglas de uno o varios canales. Cada canal conserva su propia configuración.</p></div>
    <div className="cs-layout">
      <aside className="cs-list" aria-label="Canales del servidor">
        <div className="cs-heading"><strong>Canales</strong><small>{configured.size} configurados</small></div>
        <input type="text" aria-label="Buscar canales" placeholder="Buscar un canal…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="cs-channel-list">
          {visibleChannels.map((c) => <button key={c.id} type="button" className={`cs-channel ${selectedIds.includes(c.id) ? "active" : ""}`} aria-pressed={selectedIds.includes(c.id)} disabled={saving} onClick={() => choose([c.id])}>
            <span># {c.name}</span><small>{configured.has(c.id) ? configured.get(c.id).enabled ? "Propio" : "Pausado" : "Heredado"}</small>
          </button>)}
          {!visibleChannels.length ? <p className="cs-help">No hay canales que coincidan.</p> : null}
        </div>
        <p className="cs-help">Los hilos heredan las reglas de su canal padre.</p>
      </aside>
      <div className="cs-editor">
        <div className="cs-note"><strong>Requisito global: </strong>{global.enabled ? roleName(global.role_id) : "Desactivado"}{global.enabled ? <p>{global.notice}</p> : null}<span className="cs-help">Las reglas de Automoderación del servidor también siguen vigentes.</span></div>
        <Field label="Canales que recibirán estos ajustes" help="Selecciona varios para guardar la misma configuración en todos ellos.">
          <SearchableSelect value={selectedIds} onChange={choose} options={channels} multiple disabled={saving} placeholder="Elegir uno o varios canales…" renderSelected={(c) => `# ${c.name}`} renderOption={(c) => <span># {c.name}</span>} />
        </Field>
        {!config ? <div className="cs-empty"><h3>Elige un canal para empezar</h3><p>Consulta lo que hereda del servidor y añade sus excepciones.</p></div> : <>
          <div className="cs-heading"><h3>{selectedIds.length === 1 ? `# ${selectedChannels[0]?.name || selectedIds[0]}` : `${selectedIds.length} canales seleccionados`}</h3><span className="cs-badge">{dirty ? "Cambios sin guardar" : configured.has(selectedIds[0]) ? config.enabled ? "Configuración propia" : "Configuración pausada" : "Hereda del servidor"}</span></div>
          {selectedIds.length > 1 ? <p className="cs-note cs-warning">La ficha parte del primer canal seleccionado. Guardar reemplazará los ajustes propios de todos los canales seleccionados.</p> : null}
          <Check checked={config.enabled} onChange={(v) => update(null, "enabled", v)} disabled={saving}>Aplicar ajustes propios del canal</Check>
          {!config.enabled ? <p className="cs-help">Al guardar desactivado se conserva la configuración propia, pero se aplica el requisito global.</p> : null}
          <div className="cs-tabs" aria-label="Secciones del canal">
            {[["rules", "Reglas y acceso"], ["triggers", "Triggers"], ["hours", "Horarios"], ["permissions", "Permisos Discord"], ["messages", "Mensajes programados"]].map(([id, label]) => <button type="button" key={id} className={`tab-btn ${tab === id ? "active" : ""}`} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}
          </div>
          {tab === "rules" ? <fieldset disabled={saving || !config.enabled}>
            <section className="cs-section"><h3>Rol requerido para hablar</h3><div className="cs-fields">
              <Field label="Cómo se aplica el requisito" wide><select aria-label="Cómo se aplica el requisito" value={config.role.mode} onChange={(e) => update("role", "mode", e.target.value)}>{ROLE_MODES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
              {["additional", "override"].includes(config.role.mode) ? <Field label="Roles admitidos" help="Basta con tener cualquiera de estos roles." wide><SearchableSelect value={config.role.role_ids} onChange={(v) => update("role", "role_ids", v)} options={roles} multiple placeholder="Seleccionar roles…" /></Field> : null}
              <Field label="Aviso público al autor" wide help="El bot menciona al autor automáticamente. No hace falta incluir su mención."><textarea aria-label="Aviso público del rol" maxLength={1975} value={config.role.notice} onChange={(e) => update("role", "notice", e.target.value)} /></Field>
            </div><p className="cs-help">{config.role.mode === "additional" ? "Se exige el rol global y además uno de los roles de este canal." : config.role.mode === "override" ? "Excepción explícita: estos roles sustituyen al requisito global en este canal." : config.role.mode === "off" ? "Excepción explícita: el requisito global de rol no se exige en este canal." : "Se aplica el mismo requisito y aviso definidos en Moderación."}</p></section>
            <section className="cs-section" style={{ marginTop: 20 }}><h3>Restricciones de contenido</h3>
              {(data.legacy_channels || []).some((c) => selectedIds.includes(c.channel_id) && c.media_only) || data.channels.some((c) => selectedIds.includes(c.channel_id) && c.legacy?.media_only) ? <p className="cs-note">El módulo Canales ya exige multimedia en alguno de estos canales. Desactivar esta opción aquí no elimina aquella regla.</p> : null}
              <Check checked={config.restrictions.media_only} onChange={(v) => update("restrictions", "media_only", v)}>Solo mensajes con multimedia</Check>
              <Check checked={config.restrictions.block_links} onChange={(v) => update("restrictions", "block_links", v)}>Bloquear enlaces</Check>
              <div className="cs-fields"><Field label="Palabras o frases bloqueadas" help="Una por línea; se buscan dentro del mensaje sin distinguir mayúsculas."><Lines label="Palabras bloqueadas" value={config.restrictions.blocked_words} onChange={(v) => update("restrictions", "blocked_words", v)} placeholder="Una palabra o frase por línea" /></Field>
              <Field label="Aviso por incumplimiento"><textarea aria-label="Aviso de restricciones" maxLength={1975} value={config.restrictions.notice} onChange={(e) => update("restrictions", "notice", e.target.value)} /></Field></div>
            </section>
            <section className="cs-section" style={{ marginTop: 20 }}><h3>Excepciones a las reglas locales</h3><p className="cs-help">Estos roles y usuarios evitan el requisito de rol local, las restricciones y los triggers de esta ficha. El requisito global sigue vigente en los modos Heredar y Exigir también. Otras reglas globales o del módulo Canales conservan sus excepciones propias.</p>
              <div className="cs-fields"><Field label="Roles exentos"><SearchableSelect value={config.whitelist.role_ids} onChange={(v) => update("whitelist", "role_ids", v)} options={roles} multiple placeholder="Seleccionar roles exentos…" /></Field>
              <Field label="Usuarios exentos"><SearchableSelect value={config.whitelist.user_ids} onChange={(v) => update("whitelist", "user_ids", v)} endpoint={`/api/guilds/${guildId}/members`} itemsKey="members" multiple placeholder="Buscar miembros…" /></Field></div>
            </section>
          </fieldset> : null}
          {tab === "triggers" ? <fieldset disabled={saving || !config.enabled}><section className="cs-section"><div className="cs-heading"><h3>Acciones ante mensajes</h3><button className="btn-secondary" type="button" onClick={() => update(null, "triggers", [...config.triggers, { id: crypto.randomUUID(), name: "", condition: "contains_text", values: [], delete: false, response: "", notify_staff: false }])}>Añadir trigger</button></div><p className="cs-help">Cuando se cumple una condición, el bot puede borrar, responder y avisar al equipo. Las respuestas se limitan para evitar avisos repetidos.</p>
            <Field label="Canal de avisos al equipo"><SearchableSelect value={config.staff_channel_id} onChange={(v) => update(null, "staff_channel_id", v || null)} options={textChannels} placeholder="Seleccionar canal de staff…" /></Field>
            {!config.triggers.length ? <p>No hay triggers propios en este canal.</p> : null}
            {config.triggers.map((trigger, index) => <div key={trigger.id} className="cs-rule"><div className="cs-heading"><strong>Trigger {index + 1}</strong><button type="button" className="btn-secondary" onClick={() => update(null, "triggers", config.triggers.filter((_, i) => i !== index))}>Eliminar trigger</button></div>
              <div className="cs-fields"><Field label="Nombre"><input type="text" aria-label={`Nombre del trigger ${index + 1}`} maxLength={100} value={trigger.name} onChange={(e) => changeTrigger(index, "name", e.target.value)} /></Field><Field label="Condición"><select aria-label={`Condición del trigger ${index + 1}`} value={trigger.condition} onChange={(e) => setConfig((prev) => ({ ...prev, triggers: prev.triggers.map((t, i) => i === index ? { ...t, condition: e.target.value, values: [] } : t) }))}>{CONDITIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
              {trigger.condition === "contains_text" ? <Field label="Palabras o frases" wide><Lines label={`Frases del trigger ${index + 1}`} value={trigger.values} onChange={(v) => changeTrigger(index, "values", v)} placeholder="Una frase por línea" /></Field> : null}
              {trigger.condition === "missing_role" ? <Field label="Roles que permiten hablar" wide><SearchableSelect options={roles} value={trigger.values} onChange={(v) => changeTrigger(index, "values", v)} multiple placeholder="Seleccionar roles…" /></Field> : null}
              <Field label="Respuesta pública (opcional)" wide><textarea aria-label={`Respuesta del trigger ${index + 1}`} maxLength={1975} value={trigger.response} onChange={(e) => changeTrigger(index, "response", e.target.value)} /></Field></div>
              <div className="cs-row"><Check checked={trigger.delete} onChange={(v) => changeTrigger(index, "delete", v)}>Borrar el mensaje</Check><Check checked={trigger.notify_staff} onChange={(v) => changeTrigger(index, "notify_staff", v)}>Avisar al equipo</Check></div>
            </div>)}
          </section></fieldset> : null}
          {tab === "hours" ? <fieldset disabled={saving || !config.enabled}><section className="cs-section"><h3>Cuándo se aplican las reglas locales</h3><Check checked={config.schedule.enabled} onChange={(v) => update("schedule", "enabled", v)}>Aplicar solo dentro de estas franjas</Check><p className="cs-help">Fuera de las franjas se hereda el requisito global. Si el horario está desactivado, las reglas locales se aplican siempre. Una franja que cruza medianoche empieza en el día marcado.</p>
            {config.schedule.enabled ? <><Field label="Zona horaria IANA"><input type="text" aria-label="Zona horaria de las restricciones" value={config.schedule.timezone} placeholder="Europe/Lisbon" onChange={(e) => update("schedule", "timezone", e.target.value)} /></Field>
              {config.schedule.windows.map((window, index) => <div key={index} className="cs-rule"><div className="cs-heading"><strong>Franja {index + 1}</strong><button type="button" className="btn-secondary" onClick={() => update("schedule", "windows", config.schedule.windows.filter((_, i) => i !== index))}>Eliminar franja</button></div><div className="cs-days">{DAYS.map((day, d) => <button key={day} type="button" aria-label={`${day}, franja ${index + 1}`} aria-pressed={window.days.includes(d)} className={`tab-btn ${window.days.includes(d) ? "active" : ""}`} onClick={() => update("schedule", "windows", config.schedule.windows.map((w, i) => i === index ? { ...w, days: w.days.includes(d) ? w.days.filter((v) => v !== d) : [...w.days, d].sort() } : w))}>{day}</button>)}</div>
                <div className="cs-fields">{[["start", "Inicio"], ["end", "Fin"]].map(([key, label]) => <Field key={key} label={label}><input type="time" aria-label={`${label} de la franja ${index + 1}`} value={window[key]} onChange={(e) => update("schedule", "windows", config.schedule.windows.map((w, i) => i === index ? { ...w, [key]: e.target.value } : w))} /></Field>)}</div></div>)}
              <button type="button" className="btn-secondary" onClick={() => update("schedule", "windows", [...config.schedule.windows, { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" }])}>Añadir franja</button>
            </> : null}
          </section></fieldset> : null}
          {tab === "permissions" ? selectedIds.length === 1 ? <NativePermissions key={selectedIds[0]} guildId={guildId} channelId={selectedIds[0]} roles={roles} onToast={onToast} /> : <section className="cs-section"><h3>Permisos nativos de Discord</h3><p>Selecciona un único canal para gestionar sus permisos de rol o usuario.</p></section> : null}
          {tab === "messages" ? textChannels.some((c) => selectedIds.includes(c.id)) ? <><p className="cs-help">Estos mensajes usan el programador del servidor y se guardan por separado. Pausar las reglas de este canal no pausa sus mensajes programados. Cada mensaje tiene un único canal destino.</p><Schedules key={selectedIds.join(",")} selectedGuild={guildId} onToast={onToast} channelIds={selectedIds} channelOptions={textChannels.filter((c) => selectedIds.includes(c.id))} /></> : <section className="cs-section"><p>Los mensajes programados requieren un canal de texto o de anuncios. Selecciona uno para configurarlos.</p></section> : null}
          {["permissions", "messages"].includes(tab) ? dirty ? <p className="cs-note">También tienes cambios sin guardar en las reglas del bot. Revisa Reglas y acceso; el botón Guardar del panel guarda esas reglas.</p> : null : <div className="cs-actions"><button className="btn-secondary cs-delete" type="button" disabled={saving || !selectedIds.some((id) => configured.has(id))} onClick={remove}>Eliminar ajustes propios</button><button className="btn-secondary" type="button" disabled={saving || !dirty} onClick={() => setConfig(structuredClone(original))}>Descartar</button><button className="btn-primary" type="button" disabled={saving || !config} onClick={save}>{saving ? "Guardando…" : `Guardar${selectedIds.length > 1 ? ` en ${selectedIds.length} canales` : " ajustes"}`}</button></div>}
        </>}
      </div>
    </div>
  </div>;
}

export default function ChannelSettings(props) {
  return <Editor key={props.selectedGuild} {...props} />;
}
