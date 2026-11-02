import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../lib/api";
import { useSaveBar } from "../lib/SaveBarContext";
import EmojiPicker from "./EmojiPicker";
import SearchableSelect from "./ui/SearchableSelect";
import Toast from "./Toast";

function reactions(row) {
  try {
    const values = JSON.parse(row.auto_react || "[]");
    return Array.isArray(values) ? values.filter((value) => typeof value === "string" && value) : [];
  } catch { return []; }
}

export default function AutoReactions({ selectedGuild: guildId }) {
  const [items, setItems] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(null);
  const [initialForm, setInitialForm] = useState(null);
  const [toast, setToast] = useState(null);
  const endpoint = `/api/guild/${guildId}/channels`;

  useEffect(() => {
    let active = true;
    Promise.all([
      apiGet(`/api/guild/${guildId}/channels`, { cache: false }),
      apiGet(`/api/guilds/${guildId}/channels?type=text,news&limit=500`),
    ]).then(([config, available]) => {
      if (!active) return;
      setItems((config.channels || []).filter((row) => reactions(row).length));
      setChannels(available.channels || []);
    }).catch((error) => { if (active) setLoadError(error.message || "No se pudieron cargar las autorreacciones."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [guildId]);

  const edit = (row) => {
    const next = row
      ? { channel_id: row.channel_id, emojis: reactions(row), enabled: Boolean(row.auto_react_enabled ?? 1), existing: true }
      : { channel_id: "", emojis: ["✅"], enabled: true, existing: false };
    setForm(next);
    setInitialForm(next);
  };
  const dirty = form !== null && JSON.stringify(form) !== JSON.stringify(initialForm);
  const save = async () => {
    if (saving || !form) return;
    if (!form.channel_id) {
      setToast({ type: "error", msg: "Elige el canal donde quieres añadir la reacción." });
      return false;
    }
    if (!form.existing && items.some((row) => row.channel_id === form.channel_id)) {
      setToast({ type: "error", msg: "Ese canal ya tiene una autorreacción. Edítala en la lista." });
      return false;
    }
    setSaving(true);
    try {
      const result = await apiPut(`${endpoint}/${form.channel_id}`, {
        ...(!form.existing || JSON.stringify(form.emojis) !== JSON.stringify(initialForm.emojis)
          ? { auto_react: JSON.stringify(form.emojis) } : {}),
        auto_react_enabled: form.enabled,
      });
      setItems((current) => [...current.filter((row) => row.channel_id !== result.channel.channel_id), result.channel]);
      setForm(null);
      setInitialForm(null);
      setToast({ type: "success", msg: "Autorreacción guardada." });
      return true;
    } catch (error) {
      setToast({ type: "error", msg: error.message || "No se pudo guardar. Tus cambios siguen aquí." });
      return false;
    } finally { setSaving(false); }
  };
  const remove = async (row) => {
    if (saving || !window.confirm("¿Quitar la autorreacción de este canal?")) return;
    setSaving(true);
    try {
      await apiPut(`${endpoint}/${row.channel_id}`, { auto_react: "[]", auto_react_enabled: false });
      setItems((current) => current.filter((item) => item.channel_id !== row.channel_id));
      setToast({ type: "success", msg: "Autorreacción eliminada." });
    } catch (error) { setToast({ type: "error", msg: error.message || "No se pudo eliminar." }); }
    finally { setSaving(false); }
  };
  useSaveBar({ dirty, saving, onSave: save, onRevert: () => { setForm(null); setInitialForm(null); } });

  if (loading) return <div className="dashboard-empty-state" role="status">Cargando autorreacciones…</div>;
  if (loadError) return <div className="glass-panel" role="alert" style={{ padding: 24 }}>{loadError}</div>;
  const channelName = (id) => channels.find((channel) => channel.id === id)?.name || id;

  return <div className="ov-container animate-fade-in">
    <Toast toast={toast} onDismiss={() => setToast(null)} />
    <div className="section-header" style={{ marginBottom: 20 }}>
      <h2>Autorreacciones</h2>
      <p>Elige un emoji para cada canal. El bot reaccionará a los mensajes nuevos de usuarios solo en los canales configurados.</p>
      <p className="muted">No incluye bots, webhooks ni los hilos del canal. Necesita Ver canal, Leer historial y Añadir reacciones.</p>
      {!form && <button className="btn-primary" disabled={saving} onClick={() => edit(null)}><i className="fa-solid fa-plus" aria-hidden="true" /> Añadir canal</button>}
    </div>
    {form && <div className="glass-panel" style={{ padding: 24, marginBottom: 20 }}>
      <h3>{form.existing ? `Editar #${channelName(form.channel_id)}` : "Configurar un canal"}</h3>
      <fieldset disabled={saving} style={{ border: 0, padding: 0, margin: 0 }}>
        <div className="form-grid">
          <div className="config-item">
            <label>Canal</label>
            <SearchableSelect value={form.channel_id} disabled={form.existing || saving}
              options={channels.filter((channel) => form.existing || !items.some((row) => row.channel_id === channel.id))}
              onChange={(value) => setForm((current) => ({ ...current, channel_id: String(value || "") }))}
              placeholder="Elige un canal" renderOption={(option) => <span># {option.name}</span>}
              renderSelected={(option) => <span># {option.name}</span>} />
          </div>
          <div className="config-item">
            <EmojiPicker guildId={guildId} value={form.emojis[0]} disabled={saving} label="Reacción"
              onChange={(emoji) => setForm((current) => ({ ...current, emojis: [emoji] }))} />
            {form.emojis.length > 1 && <p>Este canal conserva {form.emojis.length} reacciones anteriores: {form.emojis.join(" ")}. Elegir un emoji las sustituirá por esa única reacción.</p>}
          </div>
        </div>
        <label className="inline-check"><input type="checkbox" checked={form.enabled}
          onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))} /> Autorreacción activa</label>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
          <button className="btn-secondary" onClick={() => { setForm(null); setInitialForm(null); }}>Cancelar</button>
          <button className="btn-primary" onClick={save}>{saving ? "Guardando…" : "Guardar"}</button>
        </div>
      </fieldset>
    </div>}
    {!items.length && !form && <div className="glass-panel" style={{ padding: 32 }}><h3>Sin canales configurados</h3><p>Añade un canal y elige su emoji para empezar.</p></div>}
    <div style={{ display: "grid", gap: 12 }}>
      {items.map((row) => <div className="glass-panel" key={row.channel_id} style={{ padding: 20, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 180 }}><strong># {channelName(row.channel_id)}</strong><p style={{ marginBottom: 0 }}>{reactions(row).join(" ")} · {row.auto_react_enabled ? "Activa" : "Pausada"}</p></div>
        <button className="btn-secondary" disabled={saving || Boolean(form)} onClick={() => edit(row)} aria-label={`Editar autorreacción de ${channelName(row.channel_id)}`}>Editar</button>
        <button className="btn-secondary" disabled={saving || Boolean(form)} onClick={() => remove(row)} aria-label={`Quitar autorreacción de ${channelName(row.channel_id)}`}>Quitar</button>
      </div>)}
    </div>
  </div>;
}
