import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch, apiPost, apiDelete } from '../lib/api';

export default function Tickets({ selectedGuild: guildId }) {
  const [tab, setTab] = useState('config');
  const [cfg, setCfg] = useState(null);
  const [categories, setCategories] = useState([]);
  const [channels, setChannels] = useState([]);
  const [roles, setRoles] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [newCat, setNewCat] = useState({ name: '', emoji: '🎫', questions: '' });
  const [addingCat, setAddingCat] = useState(false);
  const [panelChannel, setPanelChannel] = useState('');
  const [sendingPanel, setSendingPanel] = useState(false);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [tData, chData, rolesData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/tickets`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
        apiGet(`/api/guilds/${guildId}/roles`).catch(() => ({ roles: [] })),
      ]);
      setCfg(tData.config || {});
      setCategories(tData.categories || []);
      setChannels((chData.channels || []).filter(c => ['text', 'category'].includes(c.type)));
      setRoles(rolesData.roles || []);
    } catch { showToast('Error cargando tickets', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => { setCfg(p => ({ ...p, [k]: v })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/tickets`, cfg);
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  const addCategory = async () => {
    if (!newCat.name.trim()) return showToast('El nombre es requerido', 'error');
    setAddingCat(true);
    try {
      const qs = newCat.questions ? newCat.questions.split(',').map(q => q.trim()).filter(Boolean) : ['¿En qué podemos ayudarte?'];
      await apiPost(`/api/guilds/${guildId}/tickets/categories`, { name: newCat.name.trim(), emoji: newCat.emoji || '🎫', questions: qs });
      setNewCat({ name: '', emoji: '🎫', questions: '' });
      const data = await apiGet(`/api/guilds/${guildId}/tickets`, { cache: false });
      setCategories(data.categories || []);
      showToast('✅ Categoría añadida');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setAddingCat(false); }
  };

  const deleteCat = async (catId) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/tickets/categories/${catId}`);
      setCategories(c => c.filter(x => x.id !== catId));
      showToast('Categoría eliminada');
    } catch (e) { showToast(e.message, 'error'); }
  };

  const sendPanel = async () => {
    if (!panelChannel) return showToast('Selecciona un canal', 'error');
    setSendingPanel(true);
    try {
      await apiPost(`/api/guilds/${guildId}/tickets/send-panel`, { channel_id: parseInt(panelChannel) });
      showToast('✅ Panel de tickets enviado al canal');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSendingPanel(false); }
  };

  const textChannels = channels.filter(c => c.type === 'text');
  const categoryChannels = channels.filter(c => c.type === 'category');

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando tickets…</p></div>;

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

      <div className="section-header">
        <h2 style={{background:'linear-gradient(90deg,#c4b5fd,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent'}}>
          🎫 Sistema de Tickets
        </h2>
      </div>

      <div className="tabs-container">
        {[['config','⚙️ Configuración'],['categories','📂 Categorías'],['panel','📨 Panel']].map(([id,label])=>(
          <button key={id} className={`tab-btn ${tab===id?'active':''}`} onClick={()=>setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'config' && cfg && (
        <>
          <div className="glass-panel mod-section" style={{padding:24,borderRadius:22,display:'flex',flexDirection:'column',gap:16}}>
            <div className="section-title"><h3 style={{margin:0}}>🔧 Canales y Roles</h3></div>
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))',gap:14}}>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Categoría de Discord</label>
                <select value={cfg.category_id||''} onChange={e=>set('category_id',e.target.value?parseInt(e.target.value):null)} style={{padding:'10px 12px'}}>
                  <option value="">— Ninguna —</option>
                  {categoryChannels.map(c=><option key={c.id} value={c.id}>📁 {c.name}</option>)}
                </select>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Canal de Logs</label>
                <select value={cfg.log_channel_id||''} onChange={e=>set('log_channel_id',e.target.value?parseInt(e.target.value):null)} style={{padding:'10px 12px'}}>
                  <option value="">— Sin logs —</option>
                  {textChannels.map(c=><option key={c.id} value={c.id}>#{c.name}</option>)}
                </select>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Rol de Staff (puede ver tickets)</label>
                <select value={(()=>{try{return JSON.parse(cfg.allowed_roles||'[]')[0]||''}catch{return ''}})()}
                  onChange={e=>set('allowed_roles',JSON.stringify(e.target.value?[parseInt(e.target.value)]:[]))} style={{padding:'10px 12px'}}>
                  <option value="">— Sin rol —</option>
                  {roles.map(r=><option key={r.id} value={r.id}>@{r.name}</option>)}
                </select>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Rol Inmune (admin senior)</label>
                <select value={(()=>{try{return JSON.parse(cfg.immune_roles||'[]')[0]||''}catch{return ''}})()}
                  onChange={e=>set('immune_roles',JSON.stringify(e.target.value?[parseInt(e.target.value)]:[]))} style={{padding:'10px 12px'}}>
                  <option value="">— Sin rol —</option>
                  {roles.map(r=><option key={r.id} value={r.id}>@{r.name}</option>)}
                </select>
              </div>
            </div>
          </div>

          <div className="glass-panel mod-section" style={{padding:24,borderRadius:22,display:'flex',flexDirection:'column',gap:14}}>
            <div className="section-title"><h3 style={{margin:0}}>⚡ Límites</h3></div>
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(200px,1fr))',gap:14}}>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Máx. tickets por usuario</label>
                <input type="number" min="0" max="20" value={cfg.max_tickets_per_user??0} onChange={e=>set('max_tickets_per_user',parseInt(e.target.value))}/>
                <span style={{fontSize:'0.74rem',color:'var(--muted)'}}>0 = ilimitado</span>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Cooldown entre tickets (seg)</label>
                <input type="number" min="0" max="86400" step="60" value={cfg.ticket_cooldown_seconds??0} onChange={e=>set('ticket_cooldown_seconds',parseInt(e.target.value))}/>
                <span style={{fontSize:'0.74rem',color:'var(--muted)'}}>0 = sin espera</span>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Plantilla de nombre de canal</label>
                <input type="text" value={cfg.channel_name_template||''} placeholder="⚒️{username}-{number}" onChange={e=>set('channel_name_template',e.target.value)}/>
              </div>
            </div>
          </div>

          <div className={`save-bar-container ${dirty?'visible':''}`}>
            <div className="save-bar">
              <span style={{color:'var(--muted)',fontSize:'0.88rem'}}>Cambios sin guardar</span>
              <div className="save-bar-actions">
                <button className="btn-secondary" onClick={load} disabled={saving}>Descartar</button>
                <button className="btn-primary btn-save" onClick={save} disabled={saving}>{saving?'Guardando…':'💾 Guardar'}</button>
              </div>
            </div>
          </div>
        </>
      )}

      {tab === 'categories' && (
        <div style={{display:'flex',flexDirection:'column',gap:16}}>
          <div className="glass-panel mod-section" style={{padding:20,borderRadius:22}}>
            <div className="section-title"><h3 style={{margin:0}}>➕ Nueva Categoría</h3></div>
            <div style={{display:'grid',gridTemplateColumns:'60px 1fr',gap:12,marginBottom:12}}>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Emoji</label>
                <input type="text" maxLength={4} value={newCat.emoji} onChange={e=>setNewCat(p=>({...p,emoji:e.target.value}))} style={{textAlign:'center'}}/>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Nombre</label>
                <input type="text" placeholder="Soporte General" value={newCat.name} onChange={e=>setNewCat(p=>({...p,name:e.target.value}))}/>
              </div>
            </div>
            <div className="config-item">
              <label>Preguntas del ticket (separadas por comas)</label>
              <input type="text" placeholder="¿En qué podemos ayudarte?, ¿Cuál es tu usuario?" value={newCat.questions} onChange={e=>setNewCat(p=>({...p,questions:e.target.value}))}/>
            </div>
            <button className="btn-primary" onClick={addCategory} disabled={addingCat} style={{padding:'10px 22px',borderRadius:12,marginTop:4}}>
              {addingCat?'Añadiendo…':'+ Añadir categoría'}
            </button>
          </div>

          <div className="glass-panel mod-section" style={{padding:20,borderRadius:22}}>
            <div className="section-title"><h3 style={{margin:0}}>📂 Categorías ({categories.length})</h3></div>
            {categories.length === 0 && <div className="no-results"><p>No hay categorías. ¡Añade una arriba!</p></div>}
            <div style={{display:'grid',gap:10}}>
              {categories.map(cat=>(
                <div key={cat.id} style={{
                  display:'flex',alignItems:'center',gap:14,padding:'14px 16px',
                  borderRadius:14,background:'rgba(255,255,255,0.02)',
                  border:'1px solid rgba(139,92,246,0.14)',
                }}>
                  <span style={{fontSize:'1.4rem'}}>{cat.emoji||'🎫'}</span>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:800}}>{cat.name}</div>
                    <div style={{fontSize:'0.78rem',color:'var(--muted)'}}>
                      {(()=>{try{const q=JSON.parse(cat.questions||'[]');return q.length?`${q.length} pregunta${q.length>1?'s':''}`:' Sin preguntas';}catch{return 'Sin preguntas';}})()}
                    </div>
                  </div>
                  <button onClick={()=>deleteCat(cat.id)} style={{
                    background:'rgba(244,63,94,0.12)',border:'1px solid rgba(244,63,94,0.25)',
                    borderRadius:8,padding:'6px 12px',color:'#f43f5e',cursor:'pointer',fontSize:'0.82rem',fontWeight:700,
                  }}>✕</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'panel' && (
        <div className="glass-panel mod-section" style={{padding:28,borderRadius:22,display:'flex',flexDirection:'column',gap:20}}>
          <div className="section-title"><h3 style={{margin:0}}>📨 Enviar Panel de Tickets</h3></div>
          <p style={{color:'var(--muted)',margin:0,lineHeight:1.6}}>
            Selecciona el canal donde quieres publicar el panel de tickets con el menú de selección de categorías.
          </p>
          {categories.length === 0 && (
            <div style={{padding:16,borderRadius:14,background:'rgba(245,158,11,0.1)',border:'1px solid rgba(245,158,11,0.3)',color:'#fcd34d',fontWeight:600}}>
              ⚠️ Necesitas crear al menos una categoría antes de enviar el panel.
            </div>
          )}
          <div className="config-item" style={{marginBottom:0}}>
            <label>Canal donde enviar el panel</label>
            <select value={panelChannel} onChange={e=>setPanelChannel(e.target.value)} style={{padding:'10px 12px'}}>
              <option value="">— Seleccionar canal —</option>
              {textChannels.map(c=><option key={c.id} value={c.id}>#{c.name}</option>)}
            </select>
          </div>
          <button
            className="btn-primary btn-save"
            onClick={sendPanel}
            disabled={sendingPanel || !panelChannel || categories.length === 0}
            style={{alignSelf:'flex-start',padding:'12px 28px',borderRadius:14,fontSize:'1rem'}}
          >
            {sendingPanel ? '📨 Enviando…' : '📨 Enviar Panel'}
          </button>
          <div style={{fontSize:'0.8rem',color:'var(--muted)'}}>
            Categorías activas: <strong style={{color:'var(--text)'}}>{categories.length}</strong>
          </div>
        </div>
      )}
    </div>
  );
}
