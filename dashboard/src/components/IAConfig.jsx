import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch } from '../lib/api';

const MODELS = [
  { value: 'gemini-2.5-pro-exp', label: 'Gemini 2.5 Pro Exp', badge: 'Recomendado' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', badge: 'Rápido' },
  { value: 'gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash Lite', badge: 'Ligero' },
  { value: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro', badge: null },
  { value: 'gemma-3-27b-it', label: 'Gemma 3 27B IT', badge: 'Open' },
  { value: 'gemma-3-12b-it', label: 'Gemma 3 12B IT', badge: 'Open' },
];

export default function IAConfig({ selectedGuild: guildId }) {
  const [cfg, setCfg] = useState(null);
  const [channels, setChannels] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [iaCfg, chData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/ia`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
      ]);
      setCfg(iaCfg || {});
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    } catch (e) {
      showToast('Error cargando configuración IA', 'error');
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const set = (key, val) => {
    setCfg(prev => ({ ...prev, [key]: val }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/ia`, cfg);
      setDirty(false);
      showToast('✅ Configuración IA guardada');
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="dashboard-empty-state">
      <div className="loading-spinner" />
      <p>Cargando módulo IA…</p>
    </div>
  );

  return (
    <div className="ov-container animate-fade-in">
      {toast && (
        <div className={`save-toast ${toast.type}`} style={{
          position: 'fixed', top: 22, right: 22, zIndex: 9999,
          padding: '12px 20px', borderRadius: 14,
          background: toast.type === 'error' ? 'rgba(244,63,94,0.18)' : 'rgba(99,102,241,0.22)',
          border: `1px solid ${toast.type === 'error' ? 'rgba(244,63,94,0.4)' : 'rgba(139,92,246,0.4)'}`,
          backdropFilter: 'blur(16px)', color: 'var(--text)', fontWeight: 700,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        }}>
          {toast.msg}
        </div>
      )}

      <div className="section-header">
        <h2 style={{ background: 'linear-gradient(90deg,#c4b5fd,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          🤖 Inteligencia Artificial
        </h2>
        <p className="muted-text">Configura el comportamiento del asistente IA de tu servidor.</p>
      </div>

      {/* Main toggle + model */}
      <div className="glass-panel" style={{ padding: 24, borderRadius: 22, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="config-item inline-check" style={{ marginBottom: 0 }}>
          <div>
            <div style={{ fontWeight: 800, marginBottom: 3 }}>Módulo IA</div>
            <div style={{ fontSize: '0.82rem', color: 'var(--muted)' }}>Activa/desactiva el asistente de IA en el servidor</div>
          </div>
          <label className="toggle-switch">
            <input type="checkbox" checked={!!cfg?.enabled} onChange={e => set('enabled', e.target.checked ? 1 : 0)} />
            <span className="slider" />
          </label>
        </div>

        <div className="config-item" style={{ marginBottom: 0 }}>
          <label>Modelo</label>
          <select value={cfg?.model_name || ''} onChange={e => set('model_name', e.target.value)} style={{ padding: '10px 12px' }}>
            <option value="">-- Seleccionar modelo --</option>
            {MODELS.map(m => (
              <option key={m.value} value={m.value}>{m.label}{m.badge ? ` (${m.badge})` : ''}</option>
            ))}
          </select>
        </div>

        <div className="config-item" style={{ marginBottom: 0 }}>
          <label>Canal de IA</label>
          <select value={cfg?.channel_id || ''} onChange={e => set('channel_id', e.target.value ? parseInt(e.target.value) : null)} style={{ padding: '10px 12px' }}>
            <option value="">🌐 Cualquier canal</option>
            {channels.map(ch => (
              <option key={ch.id} value={ch.id}>#{ch.name}</option>
            ))}
          </select>
          <span style={{ fontSize: '0.76rem', color: 'var(--muted)' }}>Si seleccionas un canal, la IA solo responde en ese canal.</span>
        </div>
      </div>

      {/* Personalidad */}
      <div className="glass-panel" style={{ padding: 24, borderRadius: 22 }}>
        <div className="section-title"><i className="ph ph-sparkle" /><h3 style={{ margin: 0 }}>Personalidad</h3></div>

        <div className="config-item">
          <label>Nombre del bot IA</label>
          <input type="text" value={cfg?.bot_name || ''} placeholder="Bot ES" onChange={e => set('bot_name', e.target.value)} />
        </div>

        <div className="config-item">
          <label>Prompt del sistema</label>
          <textarea
            rows={6}
            value={cfg?.system_prompt || ''}
            placeholder="Eres un asistente amigable del servidor..."
            onChange={e => set('system_prompt', e.target.value)}
            style={{
              width: '100%', resize: 'vertical', padding: '10px 12px',
              background: 'linear-gradient(135deg,rgba(255,255,255,0.04),rgba(99,102,241,0.03))',
              border: '1px solid rgba(139,92,246,0.22)', borderRadius: 10,
              color: 'var(--text)', fontFamily: 'var(--font-main)', fontSize: '0.9rem',
            }}
          />
        </div>

        <div className="config-item">
          <label>URL Avatar del Webhook</label>
          <input type="url" value={cfg?.webhook_avatar || ''} placeholder="https://..." onChange={e => set('webhook_avatar', e.target.value)} />
        </div>
      </div>

      {/* Comportamiento */}
      <div className="glass-panel" style={{ padding: 24, borderRadius: 22, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="section-title"><i className="ph ph-sliders" /><h3 style={{ margin: 0 }}>Comportamiento</h3></div>

        <div className="config-item inline-check">
          <div>
            <div style={{ fontWeight: 700 }}>Modo RAG (contexto del servidor)</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>La IA conoce los canales y roles de tu servidor</div>
          </div>
          <label className="toggle-switch">
            <input type="checkbox" checked={!!cfg?.rag_enabled} onChange={e => set('rag_enabled', e.target.checked ? 1 : 0)} />
            <span className="slider" />
          </label>
        </div>

        <div className="config-item inline-check">
          <div>
            <div style={{ fontWeight: 700 }}>Modo Solo Mención</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>La IA solo responde cuando la mencionan directamente</div>
          </div>
          <label className="toggle-switch">
            <input type="checkbox" checked={!!cfg?.mention_only} onChange={e => set('mention_only', e.target.checked ? 1 : 0)} />
            <span className="slider" />
          </label>
        </div>

        <div className="config-item inline-check">
          <div>
            <div style={{ fontWeight: 700 }}>Modo Imagen (Multimodal)</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Permite analizar imágenes adjuntas</div>
          </div>
          <label className="toggle-switch">
            <input type="checkbox" checked={!!cfg?.image_enabled} onChange={e => set('image_enabled', e.target.checked ? 1 : 0)} />
            <span className="slider" />
          </label>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Temperatura (creatividad)</label>
            <input type="number" min="0" max="2" step="0.1" value={cfg?.temperature ?? 1.0} onChange={e => set('temperature', parseFloat(e.target.value))} />
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Máx. tokens respuesta</label>
            <input type="number" min="100" max="8192" step="100" value={cfg?.max_output_tokens ?? 1024} onChange={e => set('max_output_tokens', parseInt(e.target.value))} />
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Historial (turnos)</label>
            <input type="number" min="0" max="50" value={cfg?.history_limit ?? 20} onChange={e => set('history_limit', parseInt(e.target.value))} />
          </div>
          <div className="config-item" style={{ marginBottom: 0 }}>
            <label>Cooldown respuesta (seg)</label>
            <input type="number" min="0" max="300" value={cfg?.cooldown_seconds ?? 3} onChange={e => set('cooldown_seconds', parseInt(e.target.value))} />
          </div>
        </div>
      </div>

      {/* Save bar */}
      <div className={`save-bar-container ${dirty ? 'visible' : ''}`}>
        <div className="save-bar">
          <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>Tienes cambios sin guardar</span>
          <div className="save-bar-actions">
            <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
            <button className="btn-primary btn-save" onClick={save} disabled={saving}>
              {saving ? 'Guardando…' : '💾 Guardar cambios'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
