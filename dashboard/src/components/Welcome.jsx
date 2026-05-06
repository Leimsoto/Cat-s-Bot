import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch } from '../lib/api';
import Toast from './Toast';

export default function Welcome({ selectedGuild: guildId }) {
  const [tab, setTab] = useState('welcome');
  const [data, setData] = useState(null);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (msg, type = 'success') => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [wData, chData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/welcome`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
      ]);
      setData(wData);
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    } catch { showToast('Error cargando configuración', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      if (tab === 'welcome') {
        await apiPatch(`/api/guilds/${guildId}/welcome`, data.welcome);
      } else if (tab === 'boost') {
        await apiPatch(`/api/guilds/${guildId}/welcome/boost`, data.boost);
      } else if (tab === 'invites') {
        await apiPatch(`/api/guilds/${guildId}/welcome/invites`, data.invites);
      }
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  const setW = (k, v) => { setData(p => ({ ...p, welcome: { ...p.welcome, [k]: v } })); setDirty(true); };
  const setB = (k, v) => { setData(p => ({ ...p, boost: { ...p.boost, [k]: v } })); setDirty(true); };
  const setI = (k, v) => { setData(p => ({ ...p, invites: { ...p.invites, [k]: v } })); setDirty(true); };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando bienvenidas…</p></div>;

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          👋 Bienvenidas & Boosters
        </h2>
        <p style={{ color: 'var(--muted)', fontSize: '0.88rem', marginTop: 4 }}>
          Configura los mensajes de bienvenida, agradecimiento a boosters y el canal de invitaciones.
        </p>
      </div>

      <div className="tabs-container">
        {[['welcome', '👋 Bienvenidas'], ['boost', '⚡ Boosters'], ['invites', '📨 Invitaciones']].map(([id, label]) => (
          <button key={id} className={`tab-btn ${tab === id ? 'active' : ''}`} onClick={() => { setTab(id); setDirty(false); }}>{label}</button>
        ))}
      </div>

      {tab === 'welcome' && data?.welcome && (
        <div className="glass-panel mod-section" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="config-item inline-check">
            <div>
              <div style={{ fontWeight: 800 }}>Sistema de Bienvenidas</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Envía un mensaje cuando alguien se une al servidor</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!data.welcome.enabled} onChange={e => setW('enabled', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Canal de Bienvenidas</label>
            <select value={data.welcome.channel_id || ''} onChange={e => setW('channel_id', e.target.value ? parseInt(e.target.value) : null)}>
              <option value="">— Seleccionar canal —</option>
              {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
            </select>
          </div>
          <div style={{ padding: 14, borderRadius: 12, background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(139,92,246,0.2)' }}>
            <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--muted)' }}>
              💡 El mensaje de bienvenida usa el embed configurado con <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>/configurar bienvenidas</code>. Variables disponibles: <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>{'{user}'}</code>, <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>{'{server}'}</code>, <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>{'{count}'}</code>
            </p>
          </div>
        </div>
      )}

      {tab === 'boost' && data?.boost && (
        <div className="glass-panel mod-section" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="config-item inline-check">
            <div>
              <div style={{ fontWeight: 800 }}>Agradecimiento a Boosters</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Envía un mensaje cuando alguien hace boost</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!data.boost.enabled} onChange={e => setB('enabled', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Canal de Boosters</label>
            <select value={data.boost.channel_id || ''} onChange={e => setB('channel_id', e.target.value ? parseInt(e.target.value) : null)}>
              <option value="">— Seleccionar canal —</option>
              {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
            </select>
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>URL del GIF animado</label>
            <input type="text" placeholder="https://media.giphy.com/..." value={data.boost.gif_url || ''} onChange={e => setB('gif_url', e.target.value)} />
            <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>GIF que se mostrará en el mensaje de agradecimiento</span>
          </div>
          <div style={{ padding: 14, borderRadius: 12, background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.2)' }}>
            <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--muted)' }}>
              💡 El diseño del mensaje se configura con <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>/configurar boosters</code>. Variable disponible: <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4 }}>{'{user}'}</code>
            </p>
          </div>
        </div>
      )}

      {tab === 'invites' && data?.invites && (
        <div className="glass-panel mod-section" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="config-item inline-check">
            <div>
              <div style={{ fontWeight: 800 }}>Log de Invitaciones</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Registra quién invitó a cada nuevo miembro en un canal</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!data.invites.enabled} onChange={e => setI('enabled', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Canal de Log de Invitaciones</label>
            <select value={data.invites.channel_id || ''} onChange={e => setI('channel_id', e.target.value ? parseInt(e.target.value) : null)}>
              <option value="">— Seleccionar canal —</option>
              {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
            </select>
            <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>Recomendado: #invitaciones</span>
          </div>
        </div>
      )}

      {/* Save bar */}
      <div className={`save-bar-container ${dirty ? 'visible' : ''}`}>
        <div className="save-bar">
          <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>Cambios sin guardar</span>
          <div className="save-bar-actions">
            <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
            <button className="btn-primary btn-save" onClick={save} disabled={saving}>{saving ? 'Guardando…' : '💾 Guardar'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
