import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiPatch, apiDelete } from '../lib/api';
import Toast from './Toast';

const INTERVAL_PRESETS = [
  { label: '1 hora',   seconds: 3600 },
  { label: '2 horas',  seconds: 7200 },
  { label: '6 horas',  seconds: 21600 },
  { label: '12 horas', seconds: 43200 },
  { label: '24 horas', seconds: 86400 },
  { label: '1 semana', seconds: 604800 },
];

function fmtInterval(seconds) {
  if (!seconds) return '—';
  if (seconds >= 604800) return `${(seconds / 604800).toFixed(0)} sem`;
  if (seconds >= 86400)  return `${(seconds / 86400).toFixed(0)}d`;
  if (seconds >= 3600)   return `${(seconds / 3600).toFixed(0)}h`;
  return `${Math.floor(seconds / 60)}min`;
}

export default function Schedules({ selectedGuild }) {
  const [schedules, setSchedules]   = useState([]);
  const [channels, setChannels]     = useState([]);
  const [loading, setLoading]       = useState(true);
  const [toast, setToast]           = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating]     = useState(false);
  const [form, setForm] = useState({
    name: '', channel_id: '', content: '',
    interval_seconds: 3600, custom_interval: '',
  });

  const showToast = (msg, type = 'success') => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!selectedGuild) return;
    setLoading(true);
    try {
      const [sData, chData] = await Promise.all([
        apiGet(`/api/guilds/${selectedGuild}/schedules`, { cache: false }),
        apiGet(`/api/guilds/${selectedGuild}/channels`).catch(() => ({ channels: [] })),
      ]);
      setSchedules(sData.schedules || []);
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    } catch { showToast('Error cargando horarios', 'error'); }
    finally { setLoading(false); }
  }, [selectedGuild]);

  useEffect(() => { load(); }, [load]);

  const setF = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const create = async () => {
    const interval = form.custom_interval
      ? parseInt(form.custom_interval) * 60
      : form.interval_seconds;
    if (!form.name.trim()) return showToast('El nombre es requerido', 'error');
    if (!form.channel_id)  return showToast('Selecciona un canal', 'error');
    if (!form.content.trim()) return showToast('El contenido es requerido', 'error');
    setCreating(true);
    try {
      await apiPost(`/api/guilds/${selectedGuild}/schedules`, {
        name: form.name.trim(),
        channel_id: parseInt(form.channel_id),
        content: form.content.trim(),
        interval_seconds: interval,
      });
      showToast('✅ Horario creado correctamente');
      setForm({ name: '', channel_id: '', content: '', interval_seconds: 3600, custom_interval: '' });
      setShowCreate(false);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
    finally { setCreating(false); }
  };

  const toggleEnabled = async (s) => {
    try {
      await apiPatch(`/api/guilds/${selectedGuild}/schedules/${encodeURIComponent(s.name)}`, {
        enabled: s.enabled ? 0 : 1,
      });
      setSchedules(prev => prev.map(x => x.name === s.name ? { ...x, enabled: x.enabled ? 0 : 1 } : x));
    } catch (e) { showToast(e.message, 'error'); }
  };

  const deleteSchedule = async (s) => {
    if (!confirm(`¿Eliminar el horario "${s.name}"?`)) return;
    try {
      await apiDelete(`/api/guilds/${selectedGuild}/schedules/${encodeURIComponent(s.name)}`);
      setSchedules(prev => prev.filter(x => x.name !== s.name));
      showToast('Horario eliminado');
    } catch (e) { showToast(e.message, 'error'); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando horarios…</p></div>;

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="automod-header" style={{marginBottom:0}}>
        <div className="header-info">
          <h2 style={{background:'linear-gradient(90deg,#c4b5fd,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',fontSize:'1.7rem',fontWeight:900,margin:0}}>
            📅 Mensajes Programados
          </h2>
          <p className="subtitle" style={{marginTop:4}}>Mensajes automáticos que el bot enviará en los horarios configurados.</p>
        </div>
        <div style={{display:'flex',gap:12,flexWrap:'wrap',alignItems:'center'}}>
          <span style={{
            padding:'6px 14px',borderRadius:999,fontSize:'0.8rem',fontWeight:700,
            background:'rgba(99,102,241,0.15)',border:'1px solid rgba(139,92,246,0.3)',
            color:'#c4b5fd',
          }}>
            {schedules.filter(s=>s.enabled).length} activos · {schedules.length} total
          </span>
          <button className="btn-primary" onClick={()=>setShowCreate(v=>!v)} style={{padding:'10px 20px',borderRadius:12}}>
            {showCreate ? '✕ Cancelar' : '+ Nuevo horario'}
          </button>
        </div>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="glass-panel mod-section animate-fade-in" style={{padding:22,borderRadius:22,display:'flex',flexDirection:'column',gap:14}}>
          <div className="section-title"><h3 style={{margin:0}}>➕ Crear Horario</h3></div>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:14}}>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Nombre único</label>
              <input type="text" placeholder="bienvenida-diaria" value={form.name} onChange={e=>setF('name',e.target.value)}/>
            </div>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Canal destino</label>
              <select value={form.channel_id} onChange={e=>setF('channel_id',e.target.value)} style={{padding:'10px 12px'}}>
                <option value="">— Seleccionar canal —</option>
                {channels.map(c=><option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
          </div>
          <div className="config-item" style={{marginBottom:0}}>
            <label>Contenido del mensaje</label>
            <textarea rows={4} placeholder="¡Buenos días a todos! 🌅 Recuerda revisar las reglas del servidor..." value={form.content} onChange={e=>setF('content',e.target.value)}
              style={{width:'100%',resize:'vertical',padding:'10px 12px',background:'linear-gradient(135deg,rgba(255,255,255,0.04),rgba(99,102,241,0.03))',border:'1px solid rgba(139,92,246,0.22)',borderRadius:10,color:'var(--text)',fontFamily:'var(--font-main)',fontSize:'0.9rem'}}/>
          </div>
          <div className="config-item" style={{marginBottom:0}}>
            <label>Intervalo de envío</label>
            <div style={{display:'flex',gap:10,flexWrap:'wrap'}}>
              {INTERVAL_PRESETS.map(p=>(
                <button key={p.seconds}
                  onClick={()=>{ setF('interval_seconds',p.seconds); setF('custom_interval',''); }}
                  style={{
                    padding:'8px 14px',borderRadius:10,fontSize:'0.82rem',cursor:'pointer',fontWeight:700,
                    background:form.interval_seconds===p.seconds&&!form.custom_interval?'rgba(99,102,241,0.3)':'rgba(255,255,255,0.04)',
                    border:`1px solid ${form.interval_seconds===p.seconds&&!form.custom_interval?'rgba(139,92,246,0.5)':'rgba(139,92,246,0.15)'}`,
                    color:form.interval_seconds===p.seconds&&!form.custom_interval?'#c4b5fd':'var(--muted)',
                  }}>{p.label}</button>
              ))}
            </div>
            <div style={{display:'flex',alignItems:'center',gap:10,marginTop:10}}>
              <input type="number" min="1" placeholder="Personalizado (minutos)" value={form.custom_interval} onChange={e=>setF('custom_interval',e.target.value)} style={{width:220}}/>
              <span style={{fontSize:'0.8rem',color:'var(--muted)'}}>minutos</span>
            </div>
          </div>
          <button className="btn-primary btn-save" onClick={create} disabled={creating} style={{alignSelf:'flex-start',padding:'11px 26px',borderRadius:12}}>
            {creating?'Creando…':'📅 Crear horario'}
          </button>
        </div>
      )}

      {/* Schedules list */}
      {schedules.length === 0 && !showCreate && (
        <div className="dashboard-empty-state" style={{marginTop:24}}>
          <span style={{fontSize:'3rem',marginBottom:12}}>📅</span>
          <h3>Sin horarios configurados</h3>
          <p style={{color:'var(--muted)'}}>Haz clic en <strong>+ Nuevo horario</strong> para crear tu primer mensaje automático.</p>
        </div>
      )}

      <div style={{display:'flex',flexDirection:'column',gap:14}}>
        {schedules.map(s => {
          const ch = channels.find(c => parseInt(c.id) === parseInt(s.channel_id));
          return (
            <div key={s.name} className="glass-panel mod-section" style={{
              padding:'16px 20px',borderRadius:18,display:'flex',alignItems:'center',gap:16,flexWrap:'wrap',
              borderLeft:`3px solid ${s.enabled?'rgba(139,92,246,0.7)':'rgba(139,92,246,0.2)'}`,
            }}>
              <div style={{flex:1,minWidth:200}}>
                <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:4}}>
                  <span style={{fontWeight:900,fontSize:'1rem'}}>{s.name}</span>
                  <span style={{
                    padding:'2px 10px',borderRadius:999,fontSize:'0.72rem',fontWeight:800,
                    background:s.enabled?'rgba(16,185,129,0.15)':'rgba(255,255,255,0.05)',
                    border:`1px solid ${s.enabled?'rgba(16,185,129,0.4)':'rgba(255,255,255,0.1)'}`,
                    color:s.enabled?'#34d399':'var(--muted)',
                  }}>{s.enabled?'Activo':'Pausado'}</span>
                </div>
                <div style={{fontSize:'0.82rem',color:'var(--muted)',display:'flex',gap:14,flexWrap:'wrap'}}>
                  <span>📨 {ch?`#${ch.name}`:`Canal ${s.channel_id}`}</span>
                  <span>⏱ cada {fmtInterval(s.interval_seconds)}</span>
                  {s.last_sent && <span>🕐 último: {new Date(s.last_sent).toLocaleString()}</span>}
                </div>
                <div style={{marginTop:8,fontSize:'0.85rem',color:'var(--text)',opacity:0.8,
                  maxWidth:500,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                  {s.content}
                </div>
              </div>
              <div style={{display:'flex',gap:10,flexShrink:0}}>
                <label className="toggle-switch" title={s.enabled?'Pausar':'Activar'}>
                  <input type="checkbox" checked={!!s.enabled} onChange={()=>toggleEnabled(s)}/>
                  <span className="slider"/>
                </label>
                <button onClick={()=>deleteSchedule(s)} style={{
                  background:'rgba(244,63,94,0.12)',border:'1px solid rgba(244,63,94,0.25)',
                  borderRadius:8,padding:'7px 13px',color:'#f43f5e',cursor:'pointer',fontWeight:700,fontSize:'0.85rem',
                }}>✕</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
