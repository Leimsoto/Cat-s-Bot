import { useEffect, useState } from 'react';
import { apiGet } from '../lib/api';

export default function Reports({ selectedGuild }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!selectedGuild) return;
    setLoading(true);
    apiGet(`/api/guilds/${selectedGuild}/reports`)
      .then(d => setReports(d?.reports || []))
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  }, [selectedGuild]);

  if (loading) return <div className="loader">Cargando reportes...</div>;

  return (
    <div className="automod-container animate-fade-in">
      <div className="automod-header">
        <div className="header-info">
          <h2 className="glow-text">Reportes de Usuarios</h2>
          <p className="subtitle">Reportes enviados por los miembros del servidor.</p>
          <div className="runtime-note"><i className="fa-solid fa-flag" /> {reports.length} reportes registrados</div>
        </div>
      </div>
      <div className="glass-panel" style={{ overflow: 'hidden' }}>
        <div className="ops-table">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                {['ID', 'Reportado', 'Reportador', 'Razón', 'Estado', 'Fecha'].map(h => (
                  <th key={h} style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--muted)', fontWeight: 600, fontSize: '0.82rem' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reports.length === 0 && <tr><td colSpan="6" style={{ padding: '36px', textAlign: 'center', color: 'var(--muted)' }}>No hay reportes registrados.</td></tr>}
              {reports.map(r => (
                <tr key={r.id} className="ops-list-row">
                  <td style={{ padding: '12px 18px', color: 'var(--accent)', fontWeight: 700 }}>#{r.id}</td>
                  <td style={{ padding: '12px 18px', fontFamily: 'monospace', fontSize: '0.82rem' }}>{r.reported_id}</td>
                  <td style={{ padding: '12px 18px', color: 'var(--muted)', fontSize: '0.82rem' }}>{r.reporter_id}</td>
                  <td style={{ padding: '12px 18px', color: 'var(--muted)', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.reason || '—'}</td>
                  <td style={{ padding: '12px 18px' }}>
                    <span style={{ background: r.status === 'pending' ? 'rgba(245,158,11,0.15)' : 'rgba(52,211,153,0.15)', color: r.status === 'pending' ? '#f59e0b' : '#34d399', padding: '3px 10px', borderRadius: '999px', fontSize: '0.72rem', fontWeight: 700 }}>
                      {r.status === 'pending' ? 'Pendiente' : 'Revisado'}
                    </span>
                  </td>
                  <td style={{ padding: '12px 18px', color: 'var(--dim)', fontSize: '0.78rem' }}>{r.created_at ? new Date(r.created_at).toLocaleString('es') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
