import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPatch } from '../lib/api';
import { Icon } from '../lib/icons';
import { SearchableSelect } from './ui';
import { useSaveBar } from '../lib/SaveBarContext';

// ─── Cassette decorativo ────────────────────────────────────────────────────
function CassetteArt({ spinning = false, stationName = 'Lofi Radio 24/7' }) {
  return (
    <div className="cassette-wrap">
      <div className="cassette-card">
        <div className="cassette-screws">
          <div className="cassette-screw cassette-screw-tl">+</div>
          <div className="cassette-screw cassette-screw-tr">+</div>
          <div className="cassette-screw cassette-screw-bl">+</div>
          <div className="cassette-screw cassette-screw-br">+</div>
        </div>
        <div className="cassette-label">
          <div className="cassette-label-line" />
          <div className="cassette-reel-row">
            <div className="cassette-reel-asm">
              <div className={`cassette-wheel${spinning ? ' spinning' : ''}`} />
              <div className="cassette-tape-window" />
              <div className={`cassette-wheel${spinning ? ' spinning' : ''}`} />
            </div>
            <div className="cassette-station-num" style={{fontSize:'0.62rem',maxWidth:58,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
              {stationName.slice(0,10)}
            </div>
          </div>
          <div className="cassette-label-bottom">
            <span className="cassette-time-txt">RADIO · ES</span>
          </div>
        </div>
        <div className="cassette-bottom">
          <div className="cassette-plug" />
          <div className="cassette-plug" />
        </div>
      </div>
    </div>
  );
}

// ─── Endpoint de búsqueda en radio-browser ──────────────────────────────────
const RADIO_BROWSER = 'https://de1.api.radio-browser.info/json/stations/search';

async function searchRadioBrowser(query) {
  const params = new URLSearchParams({
    name: query, limit: '12', hidebroken: 'true',
    order: 'clickcount', reverse: 'true',
  });
  const res = await fetch(`${RADIO_BROWSER}?${params}`);
  if (!res.ok) throw new Error('Error de red');
  return res.json();
}

// ─── Componente principal ───────────────────────────────────────────────────
export default function Radio({ selectedGuild }) {
  const guildId = selectedGuild;

  const [cfg, setCfg]           = useState(null);
  const [dirty, setDirty]       = useState(false);
  const [saving, setSaving]     = useState(false);
  const [loading, setLoading]   = useState(true);
  const [toast, setToast]       = useState(null);

  // Radio search
  const [searchQ, setSearchQ]         = useState('');
  const [searching, setSearching]     = useState(false);
  const [results, setResults]         = useState([]);
  const [searchErr, setSearchErr]     = useState(null);
  const debounceRef = useRef(null);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const rData = await apiGet(`/api/guilds/${guildId}/radio/config`);
      setCfg(rData?.radio_config || {});
    } catch { showToast('Error cargando configuración', 'error'); }
    finally { setLoading(false); }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => { setCfg(p => ({ ...p, [k]: v })); setDirty(true); };
  // IMPORTANTE: los IDs de Discord son de 64 bits y superan Number.MAX_SAFE_INTEGER.
  // Deben mantenerse como strings para evitar pérdida de precisión en JS.
  const setId = (k) => (v) => set(k, v ? String(v) : null);

  const save = async () => {
    setSaving(true);
    try {
      // channel_id se envía como string para preservar precisión de 64 bits;
      // el backend lo convierte a int en Python donde no hay overflow.
      const payload = {
        enabled: cfg?.enabled ? 1 : 0,
        channel_id: cfg?.channel_id ? String(cfg.channel_id) : null,
        stream_url: cfg?.stream_url ?? null,
        station_name: cfg?.station_name ?? null,
        volume: cfg?.volume ?? 50,
        auto_reconnect: cfg?.auto_reconnect ? 1 : 0,
        pause_on_empty: cfg?.pause_on_empty ? 1 : 0,
      };
      await apiPatch(`/api/guilds/${guildId}/radio/config`, payload);
      setDirty(false);
      showToast('Configuración guardada');
    } catch (e) { showToast(e.message || 'Error guardando', 'error'); }
    finally { setSaving(false); }
  };

  // Búsqueda con debounce 400ms
  const handleSearch = (q) => {
    setSearchQ(q);
    setSearchErr(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) { setResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await searchRadioBrowser(q.trim());
        setResults(data || []);
      } catch { setSearchErr('No se pudo conectar a la API de radios.'); setResults([]); }
      finally { setSearching(false); }
    }, 400);
  };

  const applyStation = (station) => {
    const url = station.url_resolved || station.url || '';
    const name = station.name || 'Emisora desconocida';
    set('stream_url', url);
    set('station_name', name);
    setResults([]);
    setSearchQ('');
    showToast(`Estación seleccionada: ${name}`);
  };

  const resetToLofi = () => {
    set('stream_url', 'http://lofi.stream.laut.fm/lofi');
    set('station_name', 'Lofi Radio 24/7');
    showToast('Estación reseteada a Lofi');
  };

  const isPlaying = cfg?.enabled && cfg?.channel_id;
  const stationName = cfg?.station_name || 'Lofi Radio 24/7';

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading) return (
    <div className="dashboard-empty-state">
      <div className="loading-spinner" />
      <p>Cargando radio…</p>
    </div>
  );

  return (
    <div className="ov-container animate-fade-in">
      {toast && (
        <div style={{
          position:'fixed',top:22,right:22,zIndex:9999,padding:'12px 20px',borderRadius:14,
          background:toast.type==='error'?'rgba(244,63,94,0.18)':'rgba(99,102,241,0.22)',
          border:`1px solid ${toast.type==='error'?'rgba(244,63,94,0.4)':'rgba(139,92,246,0.4)'}`,
          backdropFilter:'blur(16px)',color:'var(--text)',fontWeight:700,boxShadow:'0 8px 32px rgba(0,0,0,0.3)',
        }}>{toast.msg}</div>
      )}

      {/* ── Header ── */}
      <div className="section-header" style={{marginBottom:24}}>
        <h2 style={{background:'linear-gradient(90deg,#c4b5fd,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',margin:0}}>
          Radio / Música
        </h2>
        <p style={{color:'var(--muted)',margin:'4px 0 0',fontSize:'0.88rem'}}>
          Radio 24/7 — conecta al bot a un canal de voz con streaming continuo.
        </p>
      </div>

      {/* ── Hero / Estado ── */}
      <div className="glass-panel radio-hero" style={{marginBottom:24}}>
        <CassetteArt spinning={!!isPlaying} stationName={stationName} />
        <div className="radio-hero-info">
          <div style={{flex:1}}>
            <div style={{fontSize:'0.7rem',fontWeight:800,letterSpacing:'0.1em',color:'#a78bfa',textTransform:'uppercase',marginBottom:4}}>
              RADIO EN TIEMPO REAL
            </div>
            <div style={{fontWeight:900,fontSize:'1.4rem',marginBottom:4}}>
              {isPlaying ? stationName : 'Sin reproducción activa'}
            </div>
            <div style={{color:'var(--muted)',fontSize:'0.84rem',marginBottom:10}}>
              {isPlaying
                ? `Transmitiendo en el canal configurado`
                : 'Cuando el radio esté activo, verás el estado aquí.'}
            </div>
            <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
              <span style={{
                padding:'4px 12px',borderRadius:999,fontSize:'0.72rem',fontWeight:700,
                background:cfg?.enabled?'rgba(52,211,153,0.15)':'rgba(255,255,255,0.07)',
                color:cfg?.enabled?'#34d399':'var(--muted)',
                border:`1px solid ${cfg?.enabled?'rgba(52,211,153,0.3)':'rgba(255,255,255,0.1)'}`,
              }}>
                {cfg?.enabled ? '● activo' : '○ inactivo'}
              </span>
              <span style={{
                padding:'4px 12px',borderRadius:999,fontSize:'0.72rem',fontWeight:700,
                background:'rgba(255,255,255,0.05)',color:'var(--muted)',
                border:'1px solid rgba(255,255,255,0.08)',
              }}>
                {cfg?.volume ?? 50}% volumen
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Grid 2 columnas ── */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20,marginBottom:20}}>

        {/* Columna izq: Configuración */}
        <div className="glass-panel" style={{padding:24,display:'flex',flexDirection:'column',gap:18}}>
          <div style={{fontWeight:800,fontSize:'1rem',borderBottom:'1px solid rgba(139,92,246,0.15)',paddingBottom:12}}>
            Configuración
          </div>

          {/* Toggle habilitado */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <div>
              <div style={{fontWeight:700,fontSize:'0.9rem'}}>Radio habilitada</div>
              <div style={{fontSize:'0.76rem',color:'var(--muted)'}}>El bot se conecta automáticamente al iniciar</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!cfg?.enabled} onChange={e => set('enabled', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>

          {/* Canal de voz */}
          <div className="config-item" style={{marginBottom:0}}>
            <label>Canal de voz</label>
            <SearchableSelect
              value={cfg?.channel_id || ''}
              onChange={setId('channel_id')}
              endpoint={`/api/guilds/${guildId}/channels?type=voice,stage_voice`}
              itemsKey="channels"
              placeholder="Selecciona un canal de voz…"
              renderOption={(opt) => (
                <>
                  <Icon name="voiceChannel" />
                  <span className="ss-option-label">{opt.name}</span>
                  {opt.category ? <span className="ss-option-sub">{opt.category}</span> : null}
                </>
              )}
              renderSelected={(opt) => (
                <><Icon name="voiceChannel" /> {opt.name}</>
              )}
            />
            <span style={{fontSize:'0.74rem',color:'var(--muted)'}}>
              Solo se listan canales de voz. Filtrado server-side.
            </span>
          </div>

          {/* Estación actual */}
          <div className="config-item" style={{marginBottom:0}}>
            <label>Estación actual</label>
            <div style={{
              padding:'10px 14px',borderRadius:12,
              background:'rgba(139,92,246,0.08)',
              border:'1px solid rgba(139,92,246,0.2)',
              fontSize:'0.85rem',fontWeight:700,
              display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,
            }}>
              <span style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                {stationName}
              </span>
              {stationName !== 'Lofi Radio 24/7' && (
                <button onClick={resetToLofi} style={{
                  flexShrink:0,background:'rgba(255,255,255,0.07)',border:'1px solid rgba(255,255,255,0.1)',
                  borderRadius:8,padding:'4px 10px',color:'var(--muted)',cursor:'pointer',fontSize:'0.74rem',
                }}>Lofi</button>
              )}
            </div>
          </div>
        </div>

        {/* Columna der: Audio */}
        <div className="glass-panel" style={{padding:24,display:'flex',flexDirection:'column',gap:18}}>
          <div style={{fontWeight:800,fontSize:'1rem',borderBottom:'1px solid rgba(139,92,246,0.15)',paddingBottom:12}}>
            Audio
          </div>

          {/* Volumen */}
          <div className="config-item" style={{marginBottom:0}}>
            <label style={{display:'flex',justifyContent:'space-between'}}>
              <span>Volumen</span>
              <span style={{color:'#c4b5fd',fontWeight:800}}>{cfg?.volume ?? 50}%</span>
            </label>
            <input
              type="range" min="0" max="150" step="5"
              value={cfg?.volume ?? 50}
              onChange={e => set('volume', parseInt(e.target.value))}
              style={{width:'100%',accentColor:'#8b5cf6'}}
            />
            <div style={{display:'flex',justifyContent:'space-between',fontSize:'0.72rem',color:'var(--muted)'}}>
              <span>0%</span><span>50%</span><span>100%</span>
            </div>
          </div>

          {/* Reconexión */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <div>
              <div style={{fontWeight:700,fontSize:'0.88rem'}}>Reconexión automática</div>
              <div style={{fontSize:'0.74rem',color:'var(--muted)'}}>Se reconecta si se desconecta del canal</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!cfg?.auto_reconnect} onChange={e => set('auto_reconnect', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>

          {/* Pausar en silencio */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <div>
              <div style={{fontWeight:700,fontSize:'0.88rem'}}>Pausar en silencio</div>
              <div style={{fontSize:'0.74rem',color:'var(--muted)'}}>No reproduce si el canal está vacío</div>
            </div>
            <label className="toggle-switch">
              <input type="checkbox" checked={!!cfg?.pause_on_empty} onChange={e => set('pause_on_empty', e.target.checked ? 1 : 0)} />
              <span className="slider" />
            </label>
          </div>
        </div>
      </div>

      {/* ── Buscador de Radios (radio-browser.info) ── */}
      <div className="glass-panel" style={{padding:24,marginBottom:20}}>
        <div style={{fontWeight:800,fontSize:'1rem',marginBottom:16,borderBottom:'1px solid rgba(139,92,246,0.15)',paddingBottom:12,display:'flex',alignItems:'center',gap:10}}>
          <span>Buscar emisora global</span>
          <span style={{fontSize:'0.7rem',fontWeight:600,color:'var(--muted)',background:'rgba(255,255,255,0.05)',padding:'2px 8px',borderRadius:99}}>
            radio-browser.info
          </span>
        </div>

        {/* Input de búsqueda */}
        <div style={{position:'relative',marginBottom:16}}>
          <div style={{
            display:'flex',alignItems:'center',gap:10,
            background:'rgba(0,0,0,0.3)',border:'1px solid rgba(139,92,246,0.25)',
            borderRadius:14,padding:'12px 16px',
            transition:'border-color 0.2s',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input
              type="text"
              placeholder="Buscar por nombre, género o país (ej: lofi, jazz, México)…"
              value={searchQ}
              onChange={e => handleSearch(e.target.value)}
              style={{
                flex:1,background:'transparent',border:'none',outline:'none',
                color:'var(--text)',fontSize:'0.9rem',fontFamily:'var(--font-main)',
              }}
            />
            {searching && (
              <div className="loading-spinner" style={{width:16,height:16,borderWidth:2}} />
            )}
            {searchQ && !searching && (
              <button
                onClick={() => { setSearchQ(''); setResults([]); }}
                aria-label="Limpiar búsqueda"
                style={{
                  background:'none',border:'none',cursor:'pointer',color:'var(--muted)',fontSize:'1rem',padding:0,
                }}>
                <Icon name="close" />
              </button>
            )}
          </div>
        </div>

        {/* Preset Lofi */}
        {!searchQ && (
          <div style={{display:'flex',gap:10,flexWrap:'wrap'}}>
            <button
              onClick={() => {
                set('stream_url', 'http://lofi.stream.laut.fm/lofi');
                set('station_name', 'Lofi Radio 24/7');
                showToast('Estación Lofi activada');
              }}
              style={{
                display:'flex',alignItems:'center',gap:8,
                padding:'10px 18px',borderRadius:12,border:'1px solid rgba(139,92,246,0.3)',
                background:'linear-gradient(135deg,rgba(99,102,241,0.15),rgba(139,92,246,0.1))',
                color:'#c4b5fd',cursor:'pointer',fontWeight:700,fontSize:'0.85rem',
                transition:'all 0.2s',
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
              </svg>
              Lofi Radio 24/7
            </button>
            <div style={{fontSize:'0.8rem',color:'var(--muted)',alignSelf:'center'}}>
              O escribe para buscar cualquier emisora del mundo
            </div>
          </div>
        )}

        {/* Error de búsqueda */}
        {searchErr && (
          <div style={{padding:'10px 14px',borderRadius:10,background:'rgba(244,63,94,0.1)',border:'1px solid rgba(244,63,94,0.25)',color:'#fda4af',fontSize:'0.84rem'}}>
            {searchErr}
          </div>
        )}

        {/* Resultados */}
        {results.length > 0 && (
          <div style={{display:'flex',flexDirection:'column',gap:8,maxHeight:320,overflowY:'auto',scrollbarWidth:'thin',scrollbarColor:'rgba(139,92,246,0.3) transparent'}}>
            {results.map((s, i) => (
              <button
                key={s.stationuuid || i}
                onClick={() => applyStation(s)}
                style={{
                  display:'flex',alignItems:'center',gap:14,padding:'12px 14px',
                  borderRadius:12,border:'1px solid rgba(139,92,246,0.15)',
                  background:'rgba(255,255,255,0.02)',cursor:'pointer',
                  textAlign:'left',transition:'all 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.background='rgba(139,92,246,0.1)'}
                onMouseLeave={e => e.currentTarget.style.background='rgba(255,255,255,0.02)'}
              >
                {s.favicon ? (
                  <img src={s.favicon} alt="" style={{width:32,height:32,borderRadius:8,objectFit:'cover',flexShrink:0}}
                    onError={e => e.target.style.display='none'} />
                ) : (
                  <div style={{width:32,height:32,borderRadius:8,background:'rgba(139,92,246,0.2)',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                  </div>
                )}
                <div style={{flex:1,minWidth:0}}>
                  <div style={{fontWeight:700,fontSize:'0.88rem',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                    {s.name}
                  </div>
                  <div style={{fontSize:'0.74rem',color:'var(--muted)',marginTop:2}}>
                    {[s.country, s.tags?.split(',')[0]].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <span style={{flexShrink:0,fontSize:'0.72rem',fontWeight:700,color:'#a78bfa',padding:'3px 10px',borderRadius:99,background:'rgba(139,92,246,0.12)',border:'1px solid rgba(139,92,246,0.2)'}}>
                  Usar
                </span>
              </button>
            ))}
          </div>
        )}
        {searchQ && !searching && results.length === 0 && !searchErr && (
          <div style={{textAlign:'center',padding:24,color:'var(--muted)',fontSize:'0.85rem'}}>
            Sin resultados para "{searchQ}"
          </div>
        )}
      </div>


    </div>
  );
}
