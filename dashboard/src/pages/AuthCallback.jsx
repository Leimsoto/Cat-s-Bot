import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import CatLogo from '../components/CatLogo';

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      localStorage.setItem('botES_token', token);
      navigate('/panel/dashboard', { replace: true });
    } else {
      navigate('/', { replace: true });
    }
  }, [navigate]);

  return (
    <div className="auth-cb-shell">
      <div className="auth-cb-card glass-panel">
        <div className="auth-cb-logo">
          <CatLogo size={56} />
        </div>
        <h2>Autenticando con Discord</h2>
        <p>Procesando tu sesión de Cats Bots...</p>
        <div className="auth-cb-loader" aria-hidden="true">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
