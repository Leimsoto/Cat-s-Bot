import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPut } from '../lib/api';
import Toast from './Toast';

// ─── Diagramas de flujo visual ───────────────────────────────────────────────
function FlowDiagram() {
  const steps = [
    { icon: '👤', label: 'Usuario entra', sub: 'al canal Hub' },
    { icon: '⚡', label: 'Bot detecta', sub: 'el evento' },
    { icon: '🔊', label: 'Crea VC', sub: '"yessid\'s VC"' },
    { icon: '📨', label: 'Envía panel', sub: 'de control' },
    { icon: '🗑️', label: 'Auto-elimina', sub: 'cuando vacío' },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap', justifyContent: 'center' }}>
      {steps.map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ textAlign: 'center', minWidth: 80 }}>
            <div style={{ fontSize: '1.6rem', marginBottom: 4 }}>{s.icon}</div>
            <div style={{ fontSize: '0.75rem', fontWeight: 800, color: '#c4b5fd' }}>{s.label}</div>
            <div style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>{s.sub}</div>
          </div>
          {i < steps.length - 1 && (
            <div style={{ margin: '0 8px', color: 'rgba(139,92,246,0.5)', fontSize: '1.2rem', marginBottom: 16 }}>→</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Control de panel visual (preview de botones) ────────────────────────────
function PanelPreview() {
  const buttons = [
    ['🔒', 'Bloquear'], ['🔓', 'Desbloquear'], ['🫥', 'Ocultar'], ['👁️', 'Mostrar'],
    ['👥', 'Límite'],   ['📩', 'Invitar'],     ['🚫', 'Banear'],  ['✅', 'Permitir'],
    ['✏️', 'Renombrar'],['🎵', 'Bitrate'],    ['🌍', 'Región'],
    ['👑', 'Ceder'],    ['🏴', 'Reclamar'],
  ];
  return (
    <div style={{
      background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(88,101,242,0.3)',
      borderRadius: 14, padding: '16px', fontFamily: 'sans-serif',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12,
        padding: '10px 14px', background: 'rgba(88,101,242,0.12)', borderRadius: 10,
        fontSize: '0.84rem', color: '#c4b5fd',
      }}>
        <span>🔊</span>
        <div>
          <div style={{ fontWeight: 800 }}>Tu canal de voz está listo</div>
          <div style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
            Usa los botones de abajo para configurar tu canal.
          </div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
        {buttons.map(([icon, label]) => (
          <div key={label} style={{
            padding: '6px 4px', borderRadius: 8, textAlign: 'center',
            background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)',
            fontSize: '0.7rem', color: 'var(--muted)', cursor: 'default',
          }}>
            <div style={{ fontSize: '1rem', marginBottom: 2 }}>{icon}</div>
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Componente principal ────────────────────────────────────────────────────
export default function VoiceGen({ selectedGuild: guildId }) {
  const [cfg, setCfg]           = useState(null);
  const [channels, setChannels] = useState({ voice: [], text: [], category: [] });
  const [activeVCs, setActiveVCs] = useState([]);
  const [dirty, setDirty]       = useState(false);
  const [saving, setSaving]     = useState(false);
  const [loading, setLoading]   = useState(true);
  const [toast, setToast]       = useState(null);
  const [tab, setTab]           = useState('config');

  const showToast = (msg, type = 'success') => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [cfgData, chData, vcData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/voice-gen/config`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
        apiGet(`/api/guilds/${guildId}/voice-gen/channels`).catch(() => ({ active_channels: [] })),
      ]);
      setCfg(cfgData.config || {});
      const all = chData.channels || [];
      setChannels({
        voice:    all.filter(c => c.type === 'voice'),
        text:     all.filter(c => c.type === 'text'),
        category: all.filter(c => c.type === 'category'),
      });
      setActiveVCs(vcData.active_channels || []);
    } catch { showToast('Error cargando configuración', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => { setCfg(p => ({ ...p, [k]: v })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      await apiPut(`/api/guilds/${guildId}/voice-gen/config`, cfg);
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message || 'Error guardando', 'error'); }
    finally { setSaving(false); }
  };

  if (loading) return (
    <div className="dashboard-empty-state">
      <div className="loading-spinner" />
      <p>Cargando Voice Gen…</p>
    </div>
  );

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      {/* Header */}
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', margin: 0 }}>
              Canales de Voz Automáticos
            </h2>
            <p style={{ color: 'var(--muted)', margin: '4px 0 0', fontSize: '0.88rem' }}>
              Join To Create — cada usuario recibe su propio canal de voz privado.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Sistema</span>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!cfg?.enabled} onChange={e => set('enabled', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: cfg?.enabled ? '#34d399' : 'var(--muted)' }}>
              {cfg?.enabled ? 'Activo' : 'Inactivo'}
            </span>
          </div>
        </div>
      </div>

      {/* Flujo visual */}
      <div className="glass-panel" style={{ padding: '20px 24px', marginBottom: 20 }}>
        <div style={{ fontSize: '0.72rem', fontWeight: 800, letterSpacing: '0.1em', color: '#a78bfa', textTransform: 'uppercase', marginBottom: 14 }}>
          Flujo del sistema
        </div>
        <FlowDiagram />
      </div>

      {/* Tabs */}
      <div className="tabs-container" style={{ marginBottom: 20 }}>
        {[['config', 'Configuración'], ['preview', 'Panel de control'], ['active', `VCs activos (${activeVCs.length})`]].map(([id, label]) => (
          <button key={id} className={`tab-btn ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Tab: Configuración ── */}
      {tab === 'config' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

          {/* Canal Hub (generador) */}
          <div className="glass-panel" style={{ padding: 24 }}>
            <div style={{ fontWeight: 800, fontSize: '1rem', borderBottom: '1px solid rgba(139,92,246,0.15)', paddingBottom: 12, marginBottom: 18 }}>
              Canal Hub — Punto de entrada
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal de voz Hub</label>
                <select value={cfg?.generator_channel_id || ''} onChange={e => set('generator_channel_id', e.target.value ? parseInt(e.target.value) : null)}>
                  <option value="">— Seleccionar canal —</option>
                  {channels.voice.map(c => <option key={c.id} value={c.id}>🔊 {c.name}</option>)}
                </select>
                <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                  El usuario que entre aquí recibirá un VC propio
                </span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Categoría para los VCs</label>
                <select value={cfg?.category_id || ''} onChange={e => set('category_id', e.target.value ? parseInt(e.target.value) : null)}>
                  <option value="">— Sin categoría —</option>
                  {channels.category.map(c => <option key={c.id} value={c.id}>📁 {c.name}</option>)}
                </select>
                <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                  Dónde se crearán los canales generados
                </span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal del panel de control</label>
                <select value={cfg?.panel_channel_id || ''} onChange={e => set('panel_channel_id', e.target.value ? parseInt(e.target.value) : null)}>
                  <option value="">— Sin panel —</option>
                  {channels.text.map(c => <option key={c.id} value={c.id}># {c.name}</option>)}
                </select>
                <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                  Donde el bot envía los botones de control
                </span>
              </div>
            </div>
          </div>

          {/* Personalización */}
          <div className="glass-panel" style={{ padding: 24 }}>
            <div style={{ fontWeight: 800, fontSize: '1rem', borderBottom: '1px solid rgba(139,92,246,0.15)', paddingBottom: 12, marginBottom: 18 }}>
              Personalización
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Plantilla de nombre</label>
                <input
                  type="text"
                  value={cfg?.name_template || "{username}'s VC"}
                  onChange={e => set('name_template', e.target.value)}
                  placeholder="{username}'s VC"
                />
                <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                  Variables: <code style={{ color: '#a78bfa' }}>{'{username}'}</code>  <code style={{ color: '#a78bfa' }}>{'{user}'}</code>
                </span>
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Límite de usuarios por defecto</label>
                <input
                  type="number" min="0" max="99"
                  value={cfg?.default_limit ?? 0}
                  onChange={e => set('default_limit', parseInt(e.target.value))}
                />
                <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>0 = ilimitado</span>
              </div>
            </div>

            {/* Preview del nombre */}
            {cfg?.name_template && (
              <div style={{
                marginTop: 16, padding: '10px 14px', borderRadius: 10,
                background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.2)',
                fontSize: '0.84rem',
              }}>
                <span style={{ color: 'var(--muted)', marginRight: 8 }}>Preview:</span>
                <strong style={{ color: '#c4b5fd' }}>
                  🔊 {(cfg.name_template || "{username}'s VC").replace('{username}', 'yessid').replace('{user}', 'yessid#0')}
                </strong>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Preview del panel ── */}
      {tab === 'preview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div className="glass-panel" style={{ padding: 24 }}>
            <div style={{ fontWeight: 800, marginBottom: 16 }}>Panel de control (vista previa)</div>
            <PanelPreview />
            <p style={{ fontSize: '0.78rem', color: 'var(--muted)', marginTop: 12, lineHeight: 1.6 }}>
              Este panel se enviará al canal configurado cuando un usuario cree su VC.
              Solo el <strong style={{ color: '#c4b5fd' }}>dueño del canal</strong> puede usar los botones.
            </p>
          </div>
          <div className="glass-panel" style={{ padding: 24 }}>
            <div style={{ fontWeight: 800, marginBottom: 16 }}>Controles disponibles</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                ['🔒/🔓', 'Bloquear / Desbloquear', 'Controla quién puede conectarse'],
                ['🫥/👁️', 'Ocultar / Mostrar', 'Hace el canal invisible al resto'],
                ['👥', 'Límite de usuarios', 'Establece el máximo de personas'],
                ['📩', 'Invitar', 'Genera un enlace de invitación (1h, 10 usos)'],
                ['🚫', 'Banear usuario', 'Expulsa y bloquea a un miembro'],
                ['✅', 'Permitir usuario', 'Acceso explícito a un miembro'],
                ['✏️', 'Renombrar', 'Cambia el nombre del canal'],
                ['🎵', 'Bitrate', 'Calidad de audio (8–384 kbps)'],
                ['🌍', 'Región', 'Servidor de voz regional o automático'],
                ['👑', 'Ceder propiedad', 'Transfiere el canal a otro usuario'],
                ['🏴', 'Reclamar', 'Reclama un canal cuyo dueño se fue'],
              ].map(([icon, name, desc]) => (
                <div key={name} style={{ display: 'flex', gap: 10, padding: '8px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.03)' }}>
                  <span style={{ fontSize: '0.85rem', minWidth: 28 }}>{icon}</span>
                  <div>
                    <div style={{ fontSize: '0.82rem', fontWeight: 700 }}>{name}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>{desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab: VCs activos ── */}
      {tab === 'active' && (
        <div className="glass-panel" style={{ overflow: 'hidden' }}>
          {activeVCs.length === 0 ? (
            <div style={{ padding: 48, textAlign: 'center' }}>
              <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🔊</div>
              <h3 style={{ margin: '0 0 8px' }}>Sin canales activos</h3>
              <p style={{ color: 'var(--muted)', margin: 0, fontSize: '0.85rem' }}>
                Los canales aparecerán aquí cuando los usuarios se conecten al Hub.
              </p>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                  {['Canal ID', 'Dueño ID', 'Creado'].map(h => (
                    <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 700, color: 'var(--muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activeVCs.map((vc, i) => (
                  <tr key={vc.channel_id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: '0.78rem' }}>🔊 {vc.channel_id}</td>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--muted)' }}>{vc.owner_id}</td>
                    <td style={{ padding: '10px 16px', fontSize: '0.76rem', color: 'var(--muted)' }}>
                      {vc.created_at ? new Date(vc.created_at * 1000).toLocaleString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Save Bar */}
      <div className={`save-bar-container ${dirty ? 'visible' : ''}`}>
        <div className="save-bar">
          <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>Cambios sin guardar</span>
          <div className="save-bar-actions">
            <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
            <button className="btn-primary btn-save" onClick={save} disabled={saving}>
              {saving ? 'Guardando…' : '💾 Guardar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
