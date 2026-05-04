import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPatch, apiPost, apiDelete } from '../lib/api';

export default function Levels({ selectedGuild: guildId }) {
  const [tab, setTab] = useState('config');
  const [cfg, setCfg] = useState(null);
  const [rewards, setRewards] = useState([]);
  const [channels, setChannels] = useState([]);
  const [roles, setRoles] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [newReward, setNewReward] = useState({ level: '', role_id: '' });
  const [addingReward, setAddingReward] = useState(false);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [lvData, chData, rolesData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/levels`),
        apiGet(`/api/guilds/${guildId}/channels`).catch(() => ({ channels: [] })),
        apiGet(`/api/guilds/${guildId}/roles`).catch(() => ({ roles: [] })),
      ]);
      setCfg(lvData.config || {});
      setRewards(lvData.rewards || []);
      setChannels((chData.channels || []).filter(c => c.type === 'text'));
      setRoles(rolesData.roles || []);
    } catch { showToast('Error cargando niveles', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => { setCfg(p => ({ ...p, [k]: v })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/levels`, cfg);
      setDirty(false);
      showToast('✅ Configuración guardada');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  const addReward = async () => {
    if (!newReward.level || !newReward.role_id) return showToast('Nivel y rol son requeridos', 'error');
    setAddingReward(true);
    try {
      await apiPost(`/api/guilds/${guildId}/levels/rewards`, { level: parseInt(newReward.level), role_id: parseInt(newReward.role_id) });
      setNewReward({ level: '', role_id: '' });
      const data = await apiGet(`/api/guilds/${guildId}/levels`, { cache: false });
      setRewards(data.rewards || []);
      showToast('✅ Recompensa añadida');
    } catch (e) { showToast(e.message, 'error'); }
    finally { setAddingReward(false); }
  };

  const deleteReward = async (level) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/levels/rewards/${level}`);
      setRewards(r => r.filter(x => x.level !== level));
      showToast('Recompensa eliminada');
    } catch (e) { showToast(e.message, 'error'); }
  };

  if (loading) return <div className="dashboard-empty-state"><div className="loading-spinner" /><p>Cargando niveles…</p></div>;

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
          🌟 Sistema de Niveles
        </h2>
      </div>

      <div className="tabs-container">
        {[['config','⚙️ Configuración'],['rewards','🎁 Recompensas']].map(([id,label])=>(
          <button key={id} className={`tab-btn ${tab===id?'active':''}`} onClick={()=>setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'config' && cfg && (
        <>
          <div className="glass-panel mod-section" style={{padding:24,borderRadius:22,display:'flex',flexDirection:'column',gap:16}}>
            <div className="config-item inline-check" style={{marginBottom:0}}>
              <div><div style={{fontWeight:800}}>Sistema de XP activo</div><div style={{fontSize:'0.8rem',color:'var(--muted)'}}>Los usuarios ganan XP por enviar mensajes</div></div>
              <label className="toggle-switch">
                <input type="checkbox" checked={!!cfg.enabled} onChange={e=>set('enabled',e.target.checked?1:0)}/>
                <span className="slider"/>
              </label>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:14}}>
              <div className="config-item" style={{marginBottom:0}}>
                <label>XP Mínimo/mensaje</label>
                <input type="number" min="1" max="1000" value={cfg.xp_min??15} onChange={e=>set('xp_min',parseInt(e.target.value))}/>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>XP Máximo/mensaje</label>
                <input type="number" min="1" max="1000" value={cfg.xp_max??25} onChange={e=>set('xp_max',parseInt(e.target.value))}/>
              </div>
              <div className="config-item" style={{marginBottom:0}}>
                <label>Cooldown (segundos)</label>
                <input type="number" min="0" max="3600" value={cfg.cooldown_seconds??60} onChange={e=>set('cooldown_seconds',parseInt(e.target.value))}/>
              </div>
            </div>
          </div>

          <div className="glass-panel mod-section" style={{padding:24,borderRadius:22,display:'flex',flexDirection:'column',gap:16}}>
            <div className="section-title"><h3 style={{margin:0}}>📢 Anuncios de Nivel</h3></div>
            <div className="config-item">
              <label>Canal de anuncios</label>
              <select value={cfg.announcement_channel_id||''} onChange={e=>set('announcement_channel_id',e.target.value?parseInt(e.target.value):null)} style={{padding:'10px 12px'}}>
                <option value="">💬 Mismo canal del mensaje</option>
                {channels.map(c=><option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
            <div className="config-item">
              <label>Mensaje de subida de nivel</label>
              <input type="text" value={cfg.announcement_message||''} placeholder="¡{user} ha subido al nivel {level}! 🎉" onChange={e=>set('announcement_message',e.target.value)}/>
              <span style={{fontSize:'0.75rem',color:'var(--muted)'}}>Variables: {'{'+'user'+'}'}, {'{'+'level'+'}'}</span>
            </div>
            <div className="config-item inline-check" style={{marginBottom:0}}>
              <div><div style={{fontWeight:700}}>Apilar roles de recompensa</div><div style={{fontSize:'0.8rem',color:'var(--muted)'}}>El usuario mantiene roles anteriores al subir de nivel</div></div>
              <label className="toggle-switch">
                <input type="checkbox" checked={!!cfg.stack_rewards} onChange={e=>set('stack_rewards',e.target.checked?1:0)}/>
                <span className="slider"/>
              </label>
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

      {tab === 'rewards' && (
        <div style={{display:'flex',flexDirection:'column',gap:16}}>
          {/* Add reward */}
          <div className="glass-panel mod-section" style={{padding:20,borderRadius:22}}>
            <div className="section-title"><h3 style={{margin:0}}>➕ Añadir Recompensa</h3></div>
            <div style={{display:'flex',gap:12,flexWrap:'wrap',alignItems:'flex-end'}}>
              <div className="config-item" style={{marginBottom:0,flex:'0 0 120px'}}>
                <label>Nivel</label>
                <input type="number" min="1" max="500" placeholder="5" value={newReward.level} onChange={e=>setNewReward(p=>({...p,level:e.target.value}))}/>
              </div>
              <div className="config-item" style={{marginBottom:0,flex:1,minWidth:180}}>
                <label>Rol a otorgar</label>
                <select value={newReward.role_id} onChange={e=>setNewReward(p=>({...p,role_id:e.target.value}))} style={{padding:'10px 12px'}}>
                  <option value="">— Seleccionar rol —</option>
                  {roles.map(r=><option key={r.id} value={r.id}>@{r.name}</option>)}
                </select>
              </div>
              <button className="btn-primary" onClick={addReward} disabled={addingReward} style={{height:42,padding:'0 20px',borderRadius:12,flexShrink:0}}>
                {addingReward?'…':'+ Añadir'}
              </button>
            </div>
          </div>

          {/* Rewards list */}
          <div className="glass-panel mod-section" style={{padding:20,borderRadius:22}}>
            <div className="section-title"><h3 style={{margin:0}}>🎁 Recompensas configuradas ({rewards.length})</h3></div>
            {rewards.length === 0 && <div className="no-results"><p>No hay recompensas. ¡Añade una arriba!</p></div>}
            <div style={{display:'grid',gap:10}}>
              {[...rewards].sort((a,b)=>a.level-b.level).map(r=>{
                const roleObj = roles.find(x=>parseInt(x.id)===parseInt(r.role_id));
                return (
                  <div key={r.level} style={{
                    display:'flex',alignItems:'center',gap:14,padding:'12px 16px',
                    borderRadius:14,background:'rgba(255,255,255,0.02)',
                    border:'1px solid rgba(139,92,246,0.14)',
                  }}>
                    <div style={{
                      width:44,height:44,borderRadius:12,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0,
                      background:'linear-gradient(135deg,rgba(99,102,241,0.25),rgba(139,92,246,0.15))',
                      fontWeight:900,fontSize:'0.95rem',color:'#c4b5fd',
                    }}>Lv.{r.level}</div>
                    <div style={{flex:1}}>
                      <div style={{fontWeight:700}}>Nivel {r.level}</div>
                      <div style={{fontSize:'0.82rem',color:'var(--muted)'}}>@{roleObj?.name||r.role_id}</div>
                    </div>
                    {roleObj?.color && <div style={{width:12,height:12,borderRadius:'50%',background:roleObj.color,flexShrink:0}}/>}
                    <button onClick={()=>deleteReward(r.level)} style={{
                      background:'rgba(244,63,94,0.12)',border:'1px solid rgba(244,63,94,0.25)',
                      borderRadius:8,padding:'6px 12px',color:'#f43f5e',cursor:'pointer',fontSize:'0.82rem',fontWeight:700,
                    }}>✕</button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
