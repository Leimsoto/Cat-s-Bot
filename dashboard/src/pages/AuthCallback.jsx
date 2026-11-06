import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import CatLogo from '../components/CatLogo';

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    localStorage.removeItem('botES_token');
    localStorage.removeItem('botES_guild_id');
    sessionStorage.removeItem('botES_guilds_cache');
    sessionStorage.removeItem('botES_user_cache');

    fetch('/api/auth/me', {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (cancelled) return;
        navigate(
          response.ok
            ? '/panel/dashboard'
            : (window.location.pathname.startsWith('/panel') ? '/panel/login' : '/'),
          { replace: true },
        );
      })
      .catch(() => {
        if (!cancelled) {
          navigate(
            window.location.pathname.startsWith('/panel') ? '/panel/login' : '/',
            { replace: true },
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="auth-cb-shell">
      <div className="auth-cb-card glass-panel">
        <div className="auth-cb-logo">
          <CatLogo size={56} />
        </div>
        <h2>Autenticando con Discord</h2>
        <p>Procesando tu sesión de Cat's Bot...</p>
        <div className="auth-cb-loader" aria-hidden="true">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
