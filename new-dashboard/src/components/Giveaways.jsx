import { useEffect, useState, useCallback } from 'react';
import { apiGet, apiPost } from '../lib/api';

const STATUS_COLOR = { active: '#34d399', ended: '#7a9bb5', cancelled: '#ef4444' };
const STATUS_LABEL = { active: 'Activo', ended: 'Finalizado', cancelled: 'Cancelado' };

const EMPTY_FORM = { prize: '', winners: 1, duration_hours: 24, channel_id: '' };

export default function Giveaways({ selectedGuild }) {
  const [giveaways, setGiveaways] = useState([]);
  const [channels, setChannels]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [filter, setFilter]       = useState('all');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm]           = useState(EMPTY_FORM);
  const [creating, setCreating]   = useState(false);
  const [toast, setToast]         = useState(null);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(() => {
    if (!selectedGuild) return;
    setLoading(true);
    Promise.all([
      apiGet(`/api/guilds/${selectedGuild}/giveaways`).catch(() => ({ giveaways: [] })),
      apiGet(`/api/guilds/${selectedGuild}/channels`).catch(() => ({ channels: [] })),
    ]).then(([gData, chData]) => {
      setGiveaways(gData?.giveaways || []);
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
    }).finally(() => setLoading(false));
  }, [selectedGuild]);

  useEffect(() => { load(); }, [load]);

  const filtered = filter === 'all' ? giveaways : giveaways.filter(g => g.status === filter);

  function timeRemaining(endsAt) {
    const diff = new Date(endsAt) - Date.now();
    if (diff <= 0) return 'Finalizado';
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    return h > 0 ? `${h}h ${m}m restantes` : `${m}m restantes`;
  }

  const createGiveaway = async () => {
    if (!form.prize.trim()) return showToast('El premio es requerido', 'error');
    if (!form.channel_id)   return showToast('Selecciona un canal', 'error');
    setCreating(true);
    try {
      await apiPost(`/api/guilds/${selectedGuild}/giveaways`, {
        prize:          form.prize.trim(),
        winner_count:   parseInt(form.winners),
        duration_hours: parseInt(form.duration_hours),
        channel_id:     parseInt(form.channel_id),
      });
      showToast('✅ Sorteo creado exitosamente');
      setForm(EMPTY_FORM);
      setShowCreate(false);
      load();
    } catch (e) { showToast(e.message || 'Error al crear sorteo', 'error'); }
    finally { setCreating(false); }
  };

  if (loading) return (
    <div className="dashboard-empty-state">
      <div className="loading-spinner" />
      <p>Cargando sorteos…</p>
    </div>
  );

  return (
    <div className="ov-container animate-fade-in">
      {toast && (
        <div style={{
          position:'fixed',top:22,right:22,zIndex:9999,padding:'12px 20px',borderRadius:14,
          background:toast.type==='error'?'rgba(244,63,94,0.18)':'rgba(99,102,241,0.22)',
          border:`1px solid ${toast.type==='error'?'rgba(244,63,94,0.4)':'rgba(139,92,246,0.4)'}`,
          backdropFilter:'blur(16px)',color:'var(--text)',fontWeight:700,
        }}>{toast.msg}</div>
      )}

      {/* Header */}
      <div className="section-header" style={{marginBottom:24}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:12}}>
          <div>
            <h2 style={{background:'linear-gradient(90deg,#c4b5fd,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',margin:0}}>
              Sorteos
            </h2>
            <p style={{color:'var(--muted)',margin:'4px 0 0',fontSize:'0.88rem'}}>
              {giveaways.filter(g => g.status === 'active').length} sorteo(s) activo(s)
            </p>
          </div>
          <button
            onClick={() => setShowCreate(s => !s)}
            className="btn-primary"
            style={{padding:'10px 20px',borderRadius:12,display:'flex',alignItems:'center',gap:8,fontSize:'0.9rem'}}
          >
            <span style={{fontSize:'1.1rem'}}>{showCreate ? '✕' : '+'}</span>
            {showCreate ? 'Cancelar' : 'Crear sorteo'}
          </button>
        </div>
      </div>

      {/* Formulario de creación */}
      {showCreate && (
        <div className="glass-panel animate-fade-in" style={{padding:24,marginBottom:24}}>
          <div style={{fontWeight:800,fontSize:'1rem',borderBottom:'1px solid rgba(139,92,246,0.15)',paddingBottom:12,marginBottom:20}}>
            Nuevo Sorteo
          </div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:16}}>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Premio</label>
              <input
                type="text" placeholder="Nitro Classic, Rol especial…"
                value={form.prize}
                onChange={e => setForm(p => ({...p, prize: e.target.value}))}
              />
            </div>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Canal</label>
              <select value={form.channel_id} onChange={e => setForm(p => ({...p, channel_id: e.target.value}))}>
                <option value="">— Seleccionar canal —</option>
                {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Ganadores</label>
              <input
                type="number" min="1" max="20"
                value={form.winners}
                onChange={e => setForm(p => ({...p, winners: e.target.value}))}
              />
            </div>
            <div className="config-item" style={{marginBottom:0}}>
              <label>Duración (horas)</label>
              <input
                type="number" min="1" max="720"
                value={form.duration_hours}
                onChange={e => setForm(p => ({...p, duration_hours: e.target.value}))}
              />
            </div>
          </div>
          <div style={{display:'flex',gap:10,marginTop:20,justifyContent:'flex-end'}}>
            <button className="btn-secondary" onClick={() => { setShowCreate(false); setForm(EMPTY_FORM); }}>
              Cancelar
            </button>
            <button className="btn-primary btn-save" onClick={createGiveaway} disabled={creating} style={{padding:'10px 24px',borderRadius:12}}>
              {creating ? 'Creando…' : '🎉 Crear sorteo'}
            </button>
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="tabs-container" style={{marginBottom:20}}>
        {[['all','Todos'],['active','Activos'],['ended','Finalizados'],['cancelled','Cancelados']].map(([f,l]) => (
          <button key={f} className={`tab-btn ${filter===f?'active':''}`} onClick={() => setFilter(f)}>
            {l}
            <span style={{marginLeft:5,fontSize:'0.72rem',opacity:0.7}}>
              ({f==='all' ? giveaways.length : giveaways.filter(g=>g.status===f).length})
            </span>
          </button>
        ))}
      </div>

      {/* Lista */}
      {filtered.length === 0 ? (
        <div className="glass-panel" style={{padding:'48px',textAlign:'center'}}>
          <div style={{fontSize:'2.5rem',marginBottom:12}}>🎉</div>
          <h3 style={{margin:'0 0 8px'}}>Sin sorteos {filter!=='all'?STATUS_LABEL[filter]?.toLowerCase()+'s':''}</h3>
          <p style={{color:'var(--muted)',margin:0,fontSize:'0.85rem'}}>
            Crea un sorteo con el botón de arriba.
          </p>
        </div>
      ) : (
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))',gap:16}}>
          {filtered.map(g => (
            <div key={g.id} className="glass-panel" style={{padding:20}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:12}}>
                <div style={{
                  width:40,height:40,borderRadius:12,
                  background:`${STATUS_COLOR[g.status]||'#7a9bb5'}18`,
                  display:'flex',alignItems:'center',justifyContent:'center',fontSize:'1.3rem',
                }}>🎁</div>
                <span style={{
                  background:`${STATUS_COLOR[g.status]||'#7a9bb5'}22`,
                  color:STATUS_COLOR[g.status]||'#7a9bb5',
                  padding:'3px 10px',borderRadius:999,fontSize:'0.72rem',fontWeight:700,
                }}>{STATUS_LABEL[g.status]||g.status}</span>
              </div>
              <h3 style={{margin:'0 0 6px',fontSize:'1rem'}}>{g.prize||'Sin descripción'}</h3>
              <p style={{margin:'0 0 10px',fontSize:'0.78rem',color:'var(--muted)'}}>
                {g.winner_count||1} ganador(es) · {g.entries||0} participantes
              </p>
              {g.ends_at && (
                <p style={{margin:0,fontSize:'0.76rem',color:'var(--muted)'}}>
                  {g.status==='active' ? timeRemaining(g.ends_at) : new Date(g.ends_at).toLocaleString('es')}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
