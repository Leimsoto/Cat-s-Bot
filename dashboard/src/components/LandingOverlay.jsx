// LandingOverlay — Selector de servidor con tarjetas 3D tilt (CSS hover puro)
// El efecto de inclinación 3D se hace con CSS ::hover y sibling selectors sin JS
import CatLogo from "./CatLogo";

const TRACKERS = Array.from({ length: 9 }, (_, i) => i + 1);

function TiltCard({ guild, onSelect }) {
  return (
    <div className="guild-tilt-container noselect" onClick={() => onSelect(guild.id)}>
      <div className="guild-tilt-canvas">
        {TRACKERS.map(n => (
          <div key={n} className={`guild-tr guild-tr-${n}`} />
        ))}
        <div className="guild-tilt-card" id={`gc-${guild.id}`}>
          {/* Cyber corner elements */}
          <div className="gtc-corners">
            <span/><span/><span/><span/>
          </div>
          {/* Scan line */}
          <div className="gtc-scan" />
          {/* Glare */}
          <div className="gtc-glare" />

          {/* Content */}
          <div className="gtc-body">
            {guild.icon
              ? <img src={guild.icon} alt="" className="gtc-icon" />
              : <div className="gtc-icon gtc-icon-letter">{guild.name?.[0]?.toUpperCase() || '#'}</div>
            }
            <div className="gtc-info">
              <strong className="gtc-name">{guild.name}</strong>
              {guild.memberCount > 0 && (
                <span className="gtc-members">
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
                  {guild.memberCount.toLocaleString()} miembros
                </span>
              )}
            </div>
            <div className="gtc-arrow">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            </div>
          </div>

          {/* Hover glow orbs */}
          <div className="gtc-glow-1" />
          <div className="gtc-glow-2" />
        </div>
      </div>
    </div>
  );
}

export default function LandingOverlay({ guilds, onSelectGuild }) {
  return (
    <div className="modal-overlay" style={{ zIndex: 200 }}>
      <div style={{ maxWidth: '680px', width: '100%', padding: '24px' }}>
        <div className="glass-panel server-picker-card" style={{ padding: '40px 36px' }}>
          {/* Header */}
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <div style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 64, height: 64, borderRadius: 18, marginBottom: 18,
              boxShadow: '0 0 28px rgba(168,85,247,0.45)',
            }}>
              <CatLogo size={64} ariaLabel="Cats Bots" />
            </div>
            <p style={{ fontSize: '0.78rem', fontWeight: 800, letterSpacing: '0.15em', color: 'var(--accent)', textTransform: 'uppercase', margin: '0 0 8px' }}>
              Panel de Control · Cats Bots
            </p>
            <h2 style={{ margin: '0 0 8px', fontSize: '1.8rem', fontWeight: 900 }}>
              Selecciona un servidor
            </h2>
            <p style={{ color: 'var(--muted)', margin: 0, fontSize: '0.9rem', lineHeight: 1.6 }}>
              Elige un servidor donde seas administrador y el bot esté presente.
            </p>
          </div>

          {guilds.length === 0 ? (
            <div className="dashboard-empty-state" style={{ padding: '28px', textAlign: 'center' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
                <CatLogo size={56} ariaLabel="Cats Bots" />
              </div>
              <h3>Sin servidores disponibles</h3>
              <p style={{ color: 'var(--muted)' }}>Cats Bots aún no está en ninguno de tus servidores de administrador.</p>
              <a
                href={`https://discord.com/oauth2/authorize?client_id=${import.meta.env.VITE_DISCORD_CLIENT_ID || ''}&permissions=8&scope=bot+applications.commands`}
                className="btn-primary" target="_blank" rel="noreferrer"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8, textDecoration: 'none', marginTop: 16 }}>
                + Invitar Bot
              </a>
            </div>
          ) : (
            <div className="landing-guild-grid">
              {guilds.map(g => (
                <TiltCard key={g.id} guild={g} onSelect={onSelectGuild} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
