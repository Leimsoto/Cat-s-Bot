import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet } from '../lib/api';

const ACTION_META = {
  ban:        { label: 'Ban',         color: '#ef4444', icon: '🔨' },
  kick:       { label: 'Kick',        color: '#f97316', icon: '👢' },
  mute:       { label: 'Mute',        color: '#eab308', icon: '🔇' },
  warn:       { label: 'Warn',        color: '#f59e0b', icon: '⚠️' },
  unban:      { label: 'Unban',       color: '#34d399', icon: '✅' },
  unmute:     { label: 'Unmute',      color: '#34d399', icon: '🔊' },
  timeout:    { label: 'Timeout',     color: '#a78bfa', icon: '⏱️' },
  note:       { label: 'Nota',        color: '#60a5fa', icon: '📝' },
};

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

  const [cases, setCases]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState('all');
  const [search, setSearch]     = useState('');
  const [page, setPage]         = useState(0);
  const [autoRefresh, setAuto]  = useState(false);
  const timerRef = useRef(null);
  const PER_PAGE = 20;

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

  useEffect(() => { load(); }, [load]);

  // Auto-refresh cada 30 segundos
  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(load, 30000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [autoRefresh, load]);

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

  // Contar por tipo
  const counts = cases.reduce((acc, c) => {
    acc[c.action] = (acc[c.action] || 0) + 1;
    return acc;
  }, {});

  const types = [...new Set(cases.map(c => c.action))].filter(Boolean);

  if (loading) return (
    <div className="dashboard-empty-state">
      <div className="loading-spinner" />
      <p>Cargando registros…</p>
    </div>
  );

  return (
    <div className="ov-container animate-fade-in">

      {/* Header */}
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', margin: 0 }}>
              Registros de Moderación
            </h2>
            <p style={{ color: 'var(--muted)', margin: '4px 0 0', fontSize: '0.88rem' }}>
              {cases.length} acción(es) registradas
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', color: 'var(--muted)', cursor: 'pointer' }}>
              <span className="toggle-switch" style={{ transform: 'scale(0.8)' }}>
                <input type="checkbox" checked={autoRefresh} onChange={e => setAuto(e.target.checked)} />
                <span className="slider" />
              </span>
              Auto-refresh 30s
            </label>
            <button
              onClick={load}
              style={{
                padding: '8px 16px', borderRadius: 10, border: '1px solid rgba(139,92,246,0.25)',
                background: 'rgba(139,92,246,0.1)', color: '#c4b5fd', cursor: 'pointer',
                fontSize: '0.82rem', fontWeight: 700,
              }}
            >
              ↻ Actualizar
            </button>
          </div>
        </div>
      </div>

      {/* Resumen rápido por tipo */}
      {cases.length > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
          {Object.entries(counts).map(([action, count]) => {
            const meta = ACTION_META[action] || { label: action, color: '#7a9bb5', icon: '📋' };
            return (
              <button
                key={action}
                onClick={() => { setFilter(f => f === action ? 'all' : action); setPage(0); }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '6px 14px', borderRadius: 99,
                  border: `1px solid ${filter === action ? meta.color + '55' : 'rgba(255,255,255,0.08)'}`,
                  background: filter === action ? meta.color + '18' : 'rgba(255,255,255,0.04)',
                  color: filter === action ? meta.color : 'var(--muted)',
                  cursor: 'pointer', fontSize: '0.78rem', fontWeight: 700,
                  transition: 'all 0.15s',
                }}
              >
                <span>{meta.icon}</span>
                <span>{meta.label}</span>
                <span style={{ fontWeight: 400, opacity: 0.7 }}>({count})</span>
              </button>
            );
          })}
          {filter !== 'all' && (
            <button
              onClick={() => { setFilter('all'); setPage(0); }}
              style={{
                padding: '6px 14px', borderRadius: 99,
                border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.05)',
                color: 'var(--muted)', cursor: 'pointer', fontSize: '0.78rem',
              }}
            >
              ✕ Quitar filtro
            </button>
          )}
        </div>
      )}

      {/* Búsqueda */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16,
        background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(139,92,246,0.18)',
        borderRadius: 14, padding: '10px 16px',
      }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2.5" strokeLinecap="round">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          placeholder="Buscar por usuario, moderador o razón…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(0); }}
          style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text)', fontSize: '0.88rem', fontFamily: 'var(--font-main)' }}
        />
        {search && <button onClick={() => setSearch('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)' }}>✕</button>}
      </div>

      {/* Lista de casos */}
      {filtered.length === 0 ? (
        <div className="glass-panel" style={{ padding: '48px', textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📋</div>
          <h3 style={{ margin: '0 0 8px' }}>Sin registros</h3>
          <p style={{ color: 'var(--muted)', margin: 0, fontSize: '0.85rem' }}>
            {search ? 'No hay resultados para tu búsqueda.' : 'No hay acciones de moderación registradas.'}
          </p>
        </div>
      ) : (
        <>
          <div className="glass-panel" style={{ overflow: 'hidden', marginBottom: 16 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                  {['#', 'Acción', 'Usuario', 'Moderador', 'Razón', 'Fecha'].map(h => (
                    <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 700, color: 'var(--muted)', fontSize: '0.75rem', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paged.map((c, i) => {
                  const meta = ACTION_META[c.action] || { label: c.action, color: '#7a9bb5', icon: '📋' };
                  return (
                    <tr
                      key={c.id || i}
                      style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', transition: 'background 0.15s' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(139,92,246,0.06)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '10px 16px', color: 'var(--muted)', fontFamily: 'monospace', fontSize: '0.78rem' }}>
                        #{c.id || page * PER_PAGE + i + 1}
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: 5,
                          padding: '3px 10px', borderRadius: 99, fontSize: '0.74rem', fontWeight: 700,
                          background: meta.color + '18', color: meta.color,
                          border: `1px solid ${meta.color}30`,
                        }}>
                          {meta.icon} {meta.label}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: '0.78rem' }}>
                        {c.target_tag || c.target_id || '—'}
                      </td>
                      <td style={{ padding: '10px 16px', color: 'var(--muted)', fontFamily: 'monospace', fontSize: '0.78rem' }}>
                        {c.moderator_tag || c.moderator_id || '—'}
                      </td>
                      <td style={{ padding: '10px 16px', maxWidth: 220 }}>
                        <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: c.reason ? 'var(--text)' : 'var(--muted)', fontSize: '0.82rem' }}>
                          {c.reason || 'Sin razón'}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px', color: 'var(--muted)', fontSize: '0.76rem', whiteSpace: 'nowrap' }}>
                        {relativeTime(c.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Paginación */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8, alignItems: 'center' }}>
              <button
                disabled={page === 0}
                onClick={() => setPage(p => p - 1)}
                style={{ padding: '7px 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'var(--text)', cursor: page === 0 ? 'not-allowed' : 'pointer', opacity: page === 0 ? 0.4 : 1 }}
              >
                ← Anterior
              </button>
              <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>
                {page + 1} / {totalPages} ({filtered.length} resultados)
              </span>
              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage(p => p + 1)}
                style={{ padding: '7px 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'var(--text)', cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer', opacity: page >= totalPages - 1 ? 0.4 : 1 }}
              >
                Siguiente →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
