import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch } from '../lib/api';
import Toast from './Toast';

export default function InviteTracker({ selectedGuild: guildId }) {
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
      const [iData, chData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/invites`, { cache: false }),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
      ]);
      setData(iData);
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    } catch { showToast('Error cargando invitaciones', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const setC = (k, v) => { setData(p => ({ ...p, config: { ...p.config, [k]: v } })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/invites`, data.config);
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando invitaciones…</p></div>;

  const leaderboard = data?.leaderboard || [];

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          📨 Rastreador de Invitaciones
        </h2>
        <p style={{ color: 'var(--muted)', fontSize: '0.88rem', marginTop: 4 }}>
          Ve quién ha traído más miembros al servidor.
        </p>
      </div>

      {/* Config */}
      {data?.config && (
        <div className="glass-panel mod-section" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="section-title"><h3 style={{ margin: 0 }}>⚙️ Configuración</h3></div>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="config-item" style={{ marginBottom: 0, flex: 1, minWidth: 200 }}>
              <label>Canal de Log de Invitaciones</label>
              <select value={data.config.channel_id || ''} onChange={e => setC('channel_id', e.target.value ? parseInt(e.target.value) : null)}>
                <option value="">— Sin canal —</option>
                {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingBottom: 2 }}>
              <label className="toggle-switch">
                <input type="checkbox" checked={!!data.config.enabled} onChange={e => setC('enabled', e.target.checked ? 1 : 0)} />
                <span className="slider" />
              </label>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Activo</span>
            </div>
          </div>
          {dirty && (
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
              <button className="btn-primary" onClick={save} disabled={saving}>{saving ? 'Guardando…' : '💾 Guardar'}</button>
            </div>
          )}
        </div>
      )}

      {/* Leaderboard */}
      <div className="glass-panel" style={{ overflow: 'hidden' }}>
        <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '1rem' }}>🏆 Top Invitadores</h3>
          <button className="btn-icon" onClick={load} title="Recargar"><i className="fa-solid fa-rotate-right" /></button>
        </div>
        {leaderboard.length === 0 ? (
          <div className="no-results"><p>Aún no hay datos de invitaciones registrados.</p></div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {leaderboard.map((entry, i) => (
              <div key={entry.user_id} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 20px', borderBottom: i < leaderboard.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <div style={{
                  width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontWeight: 900, fontSize: '0.85rem',
                  background: i === 0 ? 'rgba(251,191,36,0.15)' : i === 1 ? 'rgba(156,163,175,0.15)' : i === 2 ? 'rgba(180,107,55,0.15)' : 'rgba(255,255,255,0.04)',
                  color: i === 0 ? '#fbbf24' : i === 1 ? '#9ca3af' : i === 2 ? '#b46b37' : 'var(--muted)',
                  border: `1px solid ${i === 0 ? 'rgba(251,191,36,0.3)' : i === 1 ? 'rgba(156,163,175,0.2)' : i === 2 ? 'rgba(180,107,55,0.2)' : 'var(--border)'}`,
                }}>#{i + 1}</div>
                {entry.avatar ? (
                  <img src={entry.avatar} alt="" style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0 }} />
                ) : (
                  <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: 'var(--accent-light)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', fontWeight: 700 }}>
                    {entry.username?.[0]?.toUpperCase() || '?'}
                  </div>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>{entry.username}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>ID: {entry.user_id}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: 900, fontSize: '1.1rem', color: 'var(--accent)', fontFamily: 'var(--font-heading)' }}>{entry.total}</div>
                  <div style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>invitaciones</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
