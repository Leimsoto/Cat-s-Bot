export default function Login() {
  const handleLogin = () => {
    window.location.href = '/api/auth/login';
  };

  return (
    <div className="login-body">
      <div className="login-card glass-panel">
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: '80px', height: '80px', margin: '0 auto 20px auto',
          background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.3)',
          borderRadius: '24px', boxShadow: '0 0 30px rgba(56,189,248,0.2)'
        }}>
          <span style={{
            fontSize: '3rem', fontWeight: '900', fontFamily: "'Plus Jakarta Sans',sans-serif",
            lineHeight: 1, background: 'linear-gradient(135deg,#38bdf8,#2563eb)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent'
          }}>B</span>
        </div>
        <h2 className="brand-text-glow" style={{ margin: 0, paddingBottom: '6px' }}>BOT ES</h2>
        <p style={{ color: 'var(--muted)', marginBottom: '28px' }}>Panel de Control &amp; Administración</p>
        <button onClick={handleLogin} className="btn-discord" style={{ width: '100%' }}>
          <i className="fa-brands fa-discord" />
          Iniciar sesión con Discord
        </button>
        <p style={{ color: 'var(--dim)', fontSize: '0.78rem', marginTop: '18px' }}>
          Solo acceso para administradores y dueños de servidores
        </p>
      </div>
    </div>
  );
}
