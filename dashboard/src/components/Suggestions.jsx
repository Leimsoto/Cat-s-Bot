import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch } from '../lib/api';
import Toast from './Toast';

const STATUS_LABEL = { PENDING: 'Pendiente', ACCEPTED: 'Aprobada', DENIED: 'Denegada' };
const STATUS_COLOR = { PENDING: '#f59e0b', ACCEPTED: '#10b981', DENIED: '#f43f5e' };

export default function Suggestions({ selectedGuild: guildId }) {
  const [tab, setTab] = useState('config');
  const [cfg, setCfg] = useState(null);
  const [stats, setStats] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingSugg, setLoadingSugg] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');

  const showToast = (msg, type = 'success') => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [sData, chData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/suggestions`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
      ]);
      setCfg(sData.config || {});
      setStats(sData.stats || {});
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    } catch { showToast('Error cargando sugerencias', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  const loadSuggestions = useCallback(async (status) => {
    if (!guildId) return;
    setLoadingSugg(true);
    try {
      const url = status && status !== 'all'
        ? `/api/guilds/${guildId}/suggestions/list?status=${status}`
        : `/api/guilds/${guildId}/suggestions/list`;
      const data = await apiGet(url, { cache: false });
      setSuggestions(data.suggestions || []);
    } catch { setSuggestions([]); }
    finally { setLoadingSugg(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === 'list') loadSuggestions(statusFilter); }, [tab, statusFilter, loadSuggestions]);

  const set = (k, v) => { setCfg(p => ({ ...p, [k]: v })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/suggestions`, cfg);
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando sugerencias…</p></div>;

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', margin: 0 }}>
              💡 Sistema de Sugerencias
            </h2>
            <p style={{ color: 'var(--muted)', margin: '4px 0 0', fontSize: '0.88rem' }}>
              {stats?.total || 0} sugerencias total · {stats?.pending || 0} pendientes
            </p>
          </div>
          {/* Stats chips */}
          {stats && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {[['PENDING', '⏳', stats.pending, '#f59e0b'], ['ACCEPTED', '✅', stats.accepted, '#10b981'], ['DENIED', '❌', stats.denied, '#f43f5e']].map(([s, e, c, color]) => (
                <span key={s} style={{ padding: '5px 12px', borderRadius: 999, fontSize: '0.75rem', fontWeight: 700, background: `${color}18`, color, border: `1px solid ${color}33` }}>
                  {e} {c} {STATUS_LABEL[s]}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="tabs-container">
        {[['config', '⚙️ Configuración'], ['list', '📋 Sugerencias']].map(([id, label]) => (
          <button key={id} className={`tab-btn ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'config' && cfg && (
        <>
          <div className="glass-panel mod-section" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="section-title"><h3 style={{ margin: 0 }}>📡 Canales del Sistema</h3></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 14 }}>
              {[
                ['submit_channel_id', '📥 Canal de Envío', 'Donde los usuarios envían sugerencias'],
                ['review_channel_id', '🛡️ Canal de Revisión (Staff)', 'Canal privado donde staff aprueba/deniega'],
                ['public_channel_id', '📢 Canal Público', 'Donde se muestran sugerencias aprobadas con votos'],
              ].map(([key, label, desc]) => (
                <div key={key} className="config-item" style={{ marginBottom: 0 }}>
                  <label>{label}</label>
                  <select value={cfg[key] || ''} onChange={e => set(key, e.target.value ? parseInt(e.target.value) : null)}>
                    <option value="">— Sin canal —</option>
                    {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
                  </select>
                  <span style={{ fontSize: '0.73rem', color: 'var(--muted)' }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
          <div className={`save-bar-container ${dirty ? 'visible' : ''}`}>
            <div className="save-bar">
              <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>Cambios sin guardar</span>
              <div className="save-bar-actions">
                <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
                <button className="btn-primary btn-save" onClick={save} disabled={saving}>{saving ? 'Guardando…' : '💾 Guardar'}</button>
              </div>
            </div>
          </div>
        </>
      )}

      {tab === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="tabs-container">
            {[['all', 'Todas'], ['PENDING', 'Pendientes'], ['ACCEPTED', 'Aprobadas'], ['DENIED', 'Denegadas']].map(([f, l]) => (
              <button key={f} className={`tab-btn ${statusFilter === f ? 'active' : ''}`} onClick={() => setStatusFilter(f)} style={{ fontSize: '0.8rem' }}>{l}</button>
            ))}
          </div>
          {loadingSugg ? (
            <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando…</p></div>
          ) : suggestions.length === 0 ? (
            <div className="glass-panel" style={{ padding: '48px', textAlign: 'center' }}>
              <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>💡</div>
              <h3 style={{ margin: '0 0 8px' }}>Sin sugerencias</h3>
              <p style={{ color: 'var(--muted)', margin: 0 }}>No hay sugerencias con este filtro.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {suggestions.map(s => (
                <div key={s.id} className="glass-panel" style={{ padding: '16px 20px', display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: '0.72rem', fontWeight: 700, background: `${STATUS_COLOR[s.status] || '#6366f1'}18`, color: STATUS_COLOR[s.status] || '#818cf8', border: `1px solid ${STATUS_COLOR[s.status] || '#6366f1'}33` }}>
                        {STATUS_LABEL[s.status] || s.status}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                        #{s.id} · ID de usuario: {s.user_id}
                      </span>
                      <span style={{ fontSize: '0.72rem', color: 'var(--dim)', marginLeft: 'auto' }}>
                        {s.created_at ? new Date(s.created_at).toLocaleDateString('es') : '—'}
                      </span>
                    </div>
                    <p style={{ margin: 0, fontSize: '0.9rem', lineHeight: 1.5 }}>{s.content}</p>
                    {(s.upvotes > 0 || s.downvotes > 0) && (
                      <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: '0.78rem' }}>
                        <span style={{ color: '#10b981' }}>👍 {s.upvotes || 0}</span>
                        <span style={{ color: '#f43f5e' }}>👎 {s.downvotes || 0}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
