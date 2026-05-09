import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost } from '../lib/api';

const EMPTY_EMBED = {
  title: '', description: '', color: '#6366f1',
  footer: '', footer_icon: '',
  image: '', thumbnail: '',
  author: '', author_icon: '', author_url: '',
};

const EMPTY_WEBHOOK = { name: '', icon_url: '' };

export default function EmbedBuilder({ selectedGuild }) {
  const [embed, setEmbed]         = useState(EMPTY_EMBED);
  const [webhook, setWebhook]     = useState(EMPTY_WEBHOOK);
  const [channelId, setChannelId] = useState('');
  const [channels, setChannels]   = useState([]);
  const [sending, setSending]     = useState(false);
  const [toast, setToast]         = useState(null);
  const [tab, setTab]             = useState('content');

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const loadChannels = useCallback(async () => {
    if (!selectedGuild) return;
    try {
      const data = await apiGet(`/api/guilds/${selectedGuild}/channels`);
      setChannels((data.channels || []).filter(c => c.type === 'text'));
    } catch { setChannels([]); }
  }, [selectedGuild]);

  useEffect(() => { loadChannels(); }, [loadChannels]);

  const setE = (k, v) => setEmbed(p => ({ ...p, [k]: v }));
  const setW = (k, v) => setWebhook(p => ({ ...p, [k]: v }));

  const sendEmbed = async () => {
    if (!channelId) return showToast('Selecciona un canal destino.', 'error');
    if (!embed.title && !embed.description) return showToast('El embed necesita título o descripción.', 'error');
    setSending(true);
    try {
      await apiPost(`/api/guilds/${selectedGuild}/embeds/send`, {
        channel_id: channelId,
        embed,
        webhook_name: webhook.name || undefined,
        webhook_avatar: webhook.icon_url || undefined,
      });
      showToast('✅ Embed enviado correctamente!');
    } catch (e) { showToast(e.message || 'Error al enviar el embed.', 'error'); }
    finally { setSending(false); }
  };

  const colorHex = embed.color || '#6366f1';

  const TABS = [['content','✏️ Contenido'],['author','👤 Autor/Footer'],['webhook','🤖 Webhook'],['media','🖼️ Imágenes']];

  return (
    <div className="automod-container animate-fade-in">
      {toast && (
        <div style={{
          position:'fixed',top:22,right:22,zIndex:9999,padding:'12px 20px',borderRadius:14,
          background: toast.type==='error'?'rgba(244,63,94,0.18)':'rgba(99,102,241,0.22)',
          border:`1px solid ${toast.type==='error'?'rgba(244,63,94,0.4)':'rgba(139,92,246,0.4)'}`,
          backdropFilter:'blur(16px)',color:'var(--text)',fontWeight:700,
          boxShadow:'0 8px 32px rgba(0,0,0,0.4)',
        }}>{toast.msg}</div>
      )}

      <div className="automod-header">
        <div className="header-info">
          <h2 className="glow-text" style={{background:'linear-gradient(90deg,#c4b5fd,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent'}}>
            ✏️ Creador de Embeds
          </h2>
          <p className="subtitle">Diseña mensajes enriquecidos y envíalos a cualquier canal del servidor.</p>
        </div>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 420px',gap:22,alignItems:'start'}}>
        {/* Editor */}
        <div style={{display:'flex',flexDirection:'column',gap:14}}>
          {/* Tabs */}
          <div className="tabs-container">
            {TABS.map(([id,label])=>(
              <button key={id} className={`tab-btn ${tab===id?'active':''}`} onClick={()=>setTab(id)}>{label}</button>
            ))}
          </div>

          <div className="glass-panel mod-section" style={{padding:22,borderRadius:22,display:'flex',flexDirection:'column',gap:14}}>
            {tab === 'content' && (<>
              <div className="config-item"><label>Título</label><input type="text" value={embed.title} placeholder="Título del embed" onChange={e=>setE('title',e.target.value)}/></div>
              <div className="config-item"><label>Descripción</label>
                <textarea rows={5} value={embed.description} placeholder="Contenido principal del embed..." onChange={e=>setE('description',e.target.value)}
                  style={{width:'100%',resize:'vertical',padding:'10px 12px',background:'linear-gradient(135deg,rgba(255,255,255,0.04),rgba(99,102,241,0.03))',border:'1px solid rgba(139,92,246,0.22)',borderRadius:10,color:'var(--text)',fontFamily:'var(--font-main)',fontSize:'0.9rem'}}/>
              </div>
              {/* Color picker dock magnético */}
              <div className="config-item" style={{marginBottom:0}}>
                <label>Color del borde</label>
                <div className="embed-color-dock" style={{transform:'perspective(600px)'}}>
                  {['#ef4444','#f472b6','#f97316','#facc15','#84cc16','#10b981','#0ea5e9','#6366f1','#8b5cf6','#a78bfa'].map(c=>(
                    <button key={c} className={`ecd-swatch${embed.color===c?' ecd-selected':''}`}
                      style={{'--swatch-color':c}} onClick={()=>setE('color',c)}
                      title={c} aria-label={c} data-hex={c}/>
                  ))}
                </div>
                <div style={{display:'flex',gap:10,alignItems:'center',marginTop:10}}>
                  <input type="color" value={colorHex} onChange={e=>setE('color',e.target.value)} style={{height:38,width:48,cursor:'pointer',borderRadius:8,border:'1px solid rgba(139,92,246,0.22)',padding:2,background:'transparent'}}/>
                  <input type="text" value={colorHex} onChange={e=>setE('color',e.target.value)} placeholder="#6366f1" style={{flex:1,fontFamily:'monospace'}}/>
                  <button style={{height:38,padding:'0 12px',borderRadius:8,background:'var(--material-soft)',border:'1px solid rgba(139,92,246,0.14)',color:'var(--muted)',cursor:'pointer',fontSize:'0.82rem',flexShrink:0}} onClick={()=>setEmbed(EMPTY_EMBED)}>🗑</button>
                </div>
              </div>
            </>)}


            {tab === 'author' && (<>
              <div style={{padding:12,borderRadius:12,background:'rgba(99,102,241,0.06)',border:'1px solid rgba(139,92,246,0.12)',marginBottom:4}}>
                <p style={{margin:0,fontSize:'0.82rem',color:'var(--muted)'}}>📝 El <strong style={{color:'var(--text)'}}>Autor</strong> aparece en la parte superior del embed. El <strong style={{color:'var(--text)'}}>Footer</strong> aparece en la parte inferior.</p>
              </div>
              <div className="config-item"><label>Nombre del Autor</label><input type="text" value={embed.author} placeholder="Nombre del autor" onChange={e=>setE('author',e.target.value)}/></div>
              <div className="config-item"><label>Icono del Autor (URL)</label><input type="url" value={embed.author_icon} placeholder="https://cdn.discordapp.com/..." onChange={e=>setE('author_icon',e.target.value)}/></div>
              <div className="config-item"><label>URL del Autor (enlace clickeable)</label><input type="url" value={embed.author_url} placeholder="https://..." onChange={e=>setE('author_url',e.target.value)}/></div>
              <hr style={{borderColor:'rgba(139,92,246,0.15)'}}/>
              <div className="config-item"><label>Texto del Footer</label><input type="text" value={embed.footer} placeholder="Texto del footer" onChange={e=>setE('footer',e.target.value)}/></div>
              <div className="config-item"><label>Icono del Footer (URL)</label><input type="url" value={embed.footer_icon} placeholder="https://..." onChange={e=>setE('footer_icon',e.target.value)}/></div>
            </>)}

            {tab === 'webhook' && (<>
              <div style={{padding:12,borderRadius:12,background:'rgba(99,102,241,0.06)',border:'1px solid rgba(139,92,246,0.12)',marginBottom:4}}>
                <p style={{margin:0,fontSize:'0.82rem',color:'var(--muted)'}}>🤖 Personaliza el <strong style={{color:'var(--text)'}}>nombre y avatar</strong> con que aparecerá el mensaje. Si no configuras nada, se usa el nombre e icono del bot.</p>
              </div>
              <div className="config-item"><label>Nombre del Webhook</label><input type="text" value={webhook.name} placeholder="Bot ES" onChange={e=>setW('name',e.target.value)}/></div>
              <div className="config-item"><label>URL del Icono/Avatar</label><input type="url" value={webhook.icon_url} placeholder="https://cdn.discordapp.com/..." onChange={e=>setW('icon_url',e.target.value)}/></div>
              {webhook.icon_url && (
                <div style={{display:'flex',alignItems:'center',gap:12,padding:12,borderRadius:12,background:'rgba(255,255,255,0.02)',border:'1px solid rgba(139,92,246,0.12)'}}>
                  <img src={webhook.icon_url} alt="avatar preview" onError={e=>e.target.style.display='none'} style={{width:40,height:40,borderRadius:'50%',objectFit:'cover',border:'2px solid rgba(139,92,246,0.3)'}}/>
                  <div><div style={{fontWeight:700}}>{webhook.name||'Cats Bots'}</div><div style={{fontSize:'0.75rem',color:'var(--muted)'}}>Vista previa del avatar</div></div>
                </div>
              )}
            </>)}

            {tab === 'media' && (<>
              <div className="config-item"><label>Imagen Grande (URL)</label><input type="url" value={embed.image} placeholder="https://..." onChange={e=>setE('image',e.target.value)}/></div>
              <div className="config-item"><label>Miniatura (URL — esquina superior derecha)</label><input type="url" value={embed.thumbnail} placeholder="https://..." onChange={e=>setE('thumbnail',e.target.value)}/></div>
            </>)}
          </div>

          {/* Send bar */}
          <div className="glass-panel mod-section" style={{padding:18,borderRadius:18,display:'flex',gap:12,flexWrap:'wrap',alignItems:'center'}}>
            <div style={{flex:1,minWidth:180}}>
              <select value={channelId} onChange={e=>setChannelId(e.target.value)} style={{width:'100%',padding:'10px 12px'}}>
                <option value="">📨 Seleccionar canal destino</option>
                {channels.map(c=><option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
            <button className="btn-primary btn-save" onClick={sendEmbed} disabled={sending} style={{flexShrink:0,padding:'10px 22px',borderRadius:12}}>
              {sending ? 'Enviando…' : '📨 Enviar Embed'}
            </button>
          </div>
        </div>

        {/* Preview */}
        <div style={{position:'sticky',top:80}}>
          <p className="sidebar-kicker" style={{marginBottom:10}}>VISTA PREVIA</p>
          <div style={{background:'#313338',borderRadius:16,padding:20,fontFamily:'Whitney,system-ui,sans-serif',minHeight:120}}>
            {/* Webhook author row */}
            <div style={{display:'flex',gap:12,marginBottom:10,alignItems:'center'}}>
              <img
                src={webhook.icon_url || 'https://cdn.discordapp.com/embed/avatars/0.png'}
                onError={e=>{ e.target.src='https://cdn.discordapp.com/embed/avatars/0.png'; }}
                alt="" style={{width:36,height:36,borderRadius:'50%',objectFit:'cover'}}
              />
              <div>
                <strong style={{color:'#fff',fontSize:'0.9rem'}}>{webhook.name||'Cats Bots'}</strong>
                <span style={{background:'#5865f2',color:'#fff',fontSize:'0.62rem',fontWeight:700,padding:'1px 5px',borderRadius:4,marginLeft:6}}>BOT</span>
              </div>
            </div>
            {/* Embed */}
            <div style={{borderLeft:`4px solid ${colorHex}`,background:'#2b2d31',borderRadius:'0 6px 6px 0',padding:'12px 16px',maxWidth:440}}>
              {embed.thumbnail && <img src={embed.thumbnail} alt="" style={{float:'right',width:64,height:64,borderRadius:4,objectFit:'cover',marginLeft:12}} onError={e=>e.target.style.display='none'}/>}
              {(embed.author || embed.author_icon) && (
                <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:6}}>
                  {embed.author_icon && <img src={embed.author_icon} alt="" style={{width:20,height:20,borderRadius:'50%'}} onError={e=>e.target.style.display='none'}/>}
                  {embed.author && <p style={{color:'#dbdee1',fontSize:'0.82rem',margin:0,fontWeight:700}}>{embed.author}</p>}
                </div>
              )}
              {embed.title && <p style={{color:'#fff',fontWeight:700,margin:'0 0 6px',fontSize:'1rem'}}>{embed.title}</p>}
              {embed.description && <p style={{color:'#dbdee1',fontSize:'0.875rem',margin:'0 0 8px',whiteSpace:'pre-wrap',lineHeight:1.5}}>{embed.description}</p>}
              {embed.image && <img src={embed.image} alt="" style={{width:'100%',borderRadius:4,marginTop:8,objectFit:'cover',maxHeight:200}} onError={e=>e.target.style.display='none'}/>}
              {(embed.footer||embed.footer_icon) && (
                <div style={{display:'flex',alignItems:'center',gap:6,marginTop:10}}>
                  {embed.footer_icon && <img src={embed.footer_icon} alt="" style={{width:16,height:16,borderRadius:'50%'}} onError={e=>e.target.style.display='none'}/>}
                  {embed.footer && <p style={{color:'#80848e',fontSize:'0.72rem',margin:0}}>{embed.footer}</p>}
                </div>
              )}
            </div>
          </div>

          {/* JSON export */}
          <details style={{marginTop:14}}>
            <summary style={{color:'var(--muted)',fontSize:'0.82rem',cursor:'pointer',fontWeight:700,padding:'8px 0'}}>Ver JSON del embed</summary>
            <pre style={{
              marginTop:8,padding:'12px 14px',borderRadius:12,fontSize:'0.75rem',
              background:'rgba(0,0,0,0.4)',border:'1px solid rgba(139,92,246,0.2)',
              color:'#c4b5fd',overflow:'auto',maxHeight:220,whiteSpace:'pre-wrap',
            }}>{JSON.stringify({embed,webhook_name:webhook.name,webhook_avatar:webhook.icon_url},null,2)}</pre>
          </details>
        </div>
      </div>
    </div>
  );
}
