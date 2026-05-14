import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPatch } from '../lib/api';
import { SearchableSelect } from './ui';
import { Icon } from '../lib/icons';
import Toast from './Toast';
import { useSaveBar } from '../lib/SaveBarContext';

const ACTION_META = {
  ban:        { label: 'Ban',         color: '#ef4444', icon: '🔨' },
  kick:       { label: 'Kick',        color: '#f97316', icon: '👢' },
  mute:       { label: 'Mute',        color: '#eab308', icon: '🔇' },
  warn:       { label: 'Warn',        color: '#f59e0b', icon: '⚠️' },
  unban:      { label: 'Unban',       color: '#34d399', icon: '✅' },
  unmute:     { label: 'Unmute',      color: '#34d399', icon: '🔊' },
  timeout:    { label: 'Timeout',     color: '#a78bfa', icon: '⏱️' },
  note:       { label: 'Nota',        color: '#60a5fa', icon: '📝' }};

const LOG_EVENTS = [
  { key: 'message_edit', label: 'Mensajes editados', icon: 'fa-pen' },
  { key: 'message_delete', label: 'Mensajes eliminados', icon: 'fa-trash' },
  { key: 'member_join', label: 'Miembro entra', icon: 'fa-user-plus' },
  { key: 'member_leave', label: 'Miembro sale', icon: 'fa-user-minus' },
  { key: 'member_ban', label: 'Bans', icon: 'fa-gavel' },
  { key: 'voice_join', label: 'Voz: conectar', icon: 'fa-headphones' },
  { key: 'voice_leave', label: 'Voz: desconectar', icon: 'fa-phone-slash' },
  { key: 'channel_create', label: 'Canal creado', icon: 'fa-plus' },
  { key: 'channel_delete', label: 'Canal eliminado', icon: 'fa-minus' },
  { key: 'role_change', label: 'Cambios de roles', icon: 'fa-user-gear' },
];

function relativeTime(ts) {
  if (!ts) return '—';
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  const hr  = Math.floor(diff / 3600000);
  const day = Math.floor(diff / 86400000);
  if (min < 1)  return 'hace un momento';
  if (min < 60) return `hace ${min}m`;
  if (hr < 24)  return `hace ${hr}h`;
  if (day < 30) return `hace ${day}d`;
  return d.toLocaleDateString('es');
}

export default function Logs({ selectedGuild }) {
  const guildId = selectedGuild;
  const [tab, setTab] = useState('cases');

  // Cases state
  const [cases, setCases]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState('all');
  const [search, setSearch]     = useState('');
  const [page, setPage]         = useState(0);
  const [autoRefresh, setAuto]  = useState(false);
  const timerRef = useRef(null);
  const PER_PAGE = 20;

  // Config state
  const [logCfg, setLogCfg]     = useState(null);
  const [cfgLoading, setCfgLoading] = useState(false);
  const [dirty, setDirty]       = useState(false);
  const [saving, setSaving]     = useState(false);
  const [toast, setToast]       = useState(null);

  const showToast = (msg, type = 'success') => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const data = await apiGet(`/api/moderation/${guildId}/cases?limit=200`);
      const raw = Array.isArray(data) ? data : (data.cases || []);
      setCases(raw.sort((a, b) => {
        const ta = typeof a.created_at === 'number' ? a.created_at : new Date(a.created_at).getTime() / 1000;
        const tb = typeof b.created_at === 'number' ? b.created_at : new Date(b.created_at).getTime() / 1000;
        return tb - ta;
      }));
    } catch { setCases([]); }
    finally { setLoading(false); }
  }, [guildId]);

  const loadConfig = useCallback(async () => {
    if (!guildId) return;
    setCfgLoading(true);
    setDirty(false);
    try {
      const data = await apiGet(`/api/guilds/${guildId}/logging`);
      // Parse log_events from JSON string or default to all enabled
      let events = {};
      if (data.log_events) {
        try { events = JSON.parse(data.log_events); } catch { events = {}; }
      }
      setLogCfg({ ...data, log_events_parsed: events });
    } catch { showToast('Error cargando config de logging', 'error'); }
    finally { setCfgLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === 'config') loadConfig(); }, [tab, loadConfig]);

  useEffect(() => {
    if (autoRefresh) { timerRef.current = setInterval(load, 30000); }
    else { clearInterval(timerRef.current); }
    return () => clearInterval(timerRef.current);
  }, [autoRefresh, load]);

  const setCfgField = (k, v) => { setLogCfg(p => ({ ...p, [k]: v })); setDirty(true); };
  const toggleEvent = (key) => {
    setLogCfg(p => {
      const events = { ...(p.log_events_parsed || {}) };
      events[key] = !events[key];
      return { ...p, log_events_parsed: events };
    });
    setDirty(true);
  };

  const saveConfig = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/logging`, {
        serverlog_channel: logCfg.serverlog_channel,
        serverlog_enabled: logCfg.serverlog_enabled,
        log_events: JSON.stringify(logCfg.log_events_parsed || {})});
      setDirty(false);
      showToast('Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  useSaveBar({ dirty, saving, onSave: saveConfig, onRevert: loadConfig });

  const filtered = cases.filter(c => {
    if (filter !== 'all' && c.action !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        String(c.target_id).includes(q) ||
        String(c.moderator_id).includes(q) ||
        (c.reason || '').toLowerCase().includes(q) ||
        (c.target_tag || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  const totalPages = Math.ceil(filtered.length / PER_PAGE);
  const paged = filtered.slice(page * PER_PAGE, (page + 1) * PER_PAGE);
  const counts = cases.reduce((acc, c) => { acc[c.action] = (acc[c.action] || 0) + 1; return acc; }, {});

  const renderChannelOption = (opt) => (
    <><Icon name="channel" /> <span className="ss-option-label">{opt.name}</span>{opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}</>
  );
  const renderChannelSelected = (opt) => (<><Icon name="channel" /> {opt.name}</>);

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header" style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>
          Registros
        </h2>
      </div>

      <div className="tabs-container" style={{ marginBottom: 20 }}>
        {[['cases', 'Casos de Moderación'], ['config', 'Configuración de Logs']].map(([id, label]) => (
          <button key={id} className={`tab-btn ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'config' && (
        cfgLoading ? (
          <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando…</p></div>
        ) : logCfg && (
          <>
            <div className="glass-panel" style={{ padding: 24, borderRadius: 22, marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                  <h3 style={{ margin: 0 }}>Server Event Logging</h3>
                  <p style={{ color: 'var(--muted)', margin: '4px 0 0', fontSize: '0.84rem' }}>
                    {logCfg.serverlog_enabled ? 'Activo' : 'Desactivado'}
                  </p>
                </div>
                <label className="toggle-switch">
                  <input type="checkbox" checked={!!logCfg.serverlog_enabled} onChange={e => setCfgField('serverlog_enabled', e.target.checked ? 1 : 0)} />
                  <span className="slider" />
                </label>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal de Server Logs</label>
                <SearchableSelect
                  value={logCfg.serverlog_channel || ''}
                  onChange={v => setCfgField('serverlog_channel', v ? parseInt(v, 10) : null)}
                  endpoint={`/api/guilds/${guildId}/channels`}
                  itemsKey="channels"
                  placeholder="Selecciona un canal…"
                  renderOption={renderChannelOption}
                  renderSelected={renderChannelSelected}
                />
              </div>
            </div>

            <div className="glass-panel" style={{ padding: 24, borderRadius: 22 }}>
              <h3 style={{ margin: '0 0 16px' }}>Eventos a registrar</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 }}>
                {LOG_EVENTS.map(ev => {
                  const on = !!(logCfg.log_events_parsed || {})[ev.key];
                  return (
                    <div key={ev.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderRadius: 12, background: on ? 'rgba(139,92,246,0.08)' : 'rgba(255,255,255,0.02)', border: `1px solid ${on ? 'rgba(139,92,246,0.25)' : 'rgba(255,255,255,0.06)'}`, transition: 'all 0.15s' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <i className={`fa-solid ${ev.icon}`} style={{ color: on ? '#c4b5fd' : 'var(--muted)', fontSize: '0.9rem' }} />
                        <span style={{ fontSize: '0.84rem', fontWeight: 600 }}>{ev.label}</span>
                      </div>
                      <label className="toggle-switch" style={{ transform: 'scale(0.8)' }}>
                        <input type="checkbox" checked={on} onChange={() => toggleEvent(ev.key)} />
                        <span className="slider" />
                      </label>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )
      )}

      {tab === 'cases' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
            <p style={{ color: 'var(--muted)', margin: 0, fontSize: '0.88rem' }}>{cases.length} acción(es) registradas</p>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', color: 'var(--muted)', cursor: 'pointer' }}>
                <span className="toggle-switch" style={{ transform: 'scale(0.8)' }}>
                  <input type="checkbox" checked={autoRefresh} onChange={e => setAuto(e.target.checked)} />
                  <span className="slider" />
                </span>
                Auto-refresh
              </label>
              <button onClick={load} style={{ padding: '8px 16px', borderRadius: 10, border: '1px solid rgba(139,92,246,0.25)', background: 'rgba(139,92,246,0.1)', color: '#c4b5fd', cursor: 'pointer', fontSize: '0.82rem', fontWeight: 700 }}>
                ↻ Actualizar
              </button>
            </div>
          </div>

          {cases.length > 0 && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
              {Object.entries(counts).map(([action, count]) => {
                const meta = ACTION_META[action] || { label: action, color: '#7a9bb5', icon: '📋' };
                return (
                  <button key={action} onClick={() => { setFilter(f => f === action ? 'all' : action); setPage(0); }}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 99, border: `1px solid ${filter === action ? meta.color + '55' : 'rgba(255,255,255,0.08)'}`, background: filter === action ? meta.color + '18' : 'rgba(255,255,255,0.04)', color: filter === action ? meta.color : 'var(--muted)', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 700, transition: 'all 0.15s' }}>
                    <span>{meta.icon}</span><span>{meta.label}</span><span style={{ fontWeight: 400, opacity: 0.7 }}>({count})</span>
                  </button>
                );
              })}
              {filter !== 'all' && (
                <button onClick={() => { setFilter('all'); setPage(0); }}
                  style={{ padding: '6px 14px', borderRadius: 99, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.05)', color: 'var(--muted)', cursor: 'pointer', fontSize: '0.78rem' }}>
                  ✕ Quitar filtro
                </button>
              )}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(139,92,246,0.18)', borderRadius: 14, padding: '10px 16px' }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            <input type="text" placeholder="Buscar por usuario, moderador o razón…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }}
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text)', fontSize: '0.88rem', fontFamily: 'var(--font-main)' }} />
            {search && <button onClick={() => setSearch('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)' }}>✕</button>}
          </div>

          {loading ? (
            <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando registros…</p></div>
          ) : filtered.length === 0 ? (
            <div className="glass-panel" style={{ padding: 48, textAlign: 'center' }}>
              <div style={{ fontSize: '2.5rem', marginBottom: 12 }}><i className="fa-solid fa-clipboard-list" aria-hidden="true" /></div>
              <h3 style={{ margin: '0 0 8px' }}>Sin registros</h3>
              <p style={{ color: 'var(--muted)', margin: 0, fontSize: '0.85rem' }}>{search ? 'No hay resultados.' : 'No hay acciones registradas.'}</p>
            </div>
          ) : (
            <>
              <div className="glass-panel" style={{ overflow: 'hidden', marginBottom: 16 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                      {['#', 'Acción', 'Usuario', 'Moderador', 'Razón', 'Fecha'].map(h => (
                        <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 700, color: 'var(--muted)', fontSize: '0.75rem', letterSpacing: '0.05em', textTransform: 'uppercase' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paged.map((c, i) => {
                      const meta = ACTION_META[c.action] || { label: c.action, color: '#7a9bb5', icon: '📋' };
                      return (
                        <tr key={c.id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', transition: 'background 0.15s' }}
                          onMouseEnter={e => e.currentTarget.style.background = 'rgba(139,92,246,0.06)'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                          <td style={{ padding: '10px 16px', color: 'var(--muted)', fontFamily: 'monospace', fontSize: '0.78rem' }}>#{c.id || page * PER_PAGE + i + 1}</td>
                          <td style={{ padding: '10px 16px' }}>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 99, fontSize: '0.74rem', fontWeight: 700, background: meta.color + '18', color: meta.color, border: `1px solid ${meta.color}30` }}>
                              {meta.icon} {meta.label}
                            </span>
                          </td>
                          <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: '0.78rem' }}>{c.target_tag || c.target_id || '—'}</td>
                          <td style={{ padding: '10px 16px', color: 'var(--muted)', fontFamily: 'monospace', fontSize: '0.78rem' }}>{c.moderator_tag || c.moderator_id || '—'}</td>
                          <td style={{ padding: '10px 16px', maxWidth: 220 }}>
                            <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: c.reason ? 'var(--text)' : 'var(--muted)', fontSize: '0.82rem' }}>{c.reason || 'Sin razón'}</span>
                          </td>
                          <td style={{ padding: '10px 16px', color: 'var(--muted)', fontSize: '0.76rem', whiteSpace: 'nowrap' }}>{relativeTime(c.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'center', gap: 8, alignItems: 'center' }}>
                  <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
                    style={{ padding: '7px 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'var(--text)', cursor: page === 0 ? 'not-allowed' : 'pointer', opacity: page === 0 ? 0.4 : 1 }}>
                    ← Anterior
                  </button>
                  <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>{page + 1} / {totalPages} ({filtered.length} resultados)</span>
                  <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
                    style={{ padding: '7px 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'var(--text)', cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer', opacity: page >= totalPages - 1 ? 0.4 : 1 }}>
                    Siguiente →
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
