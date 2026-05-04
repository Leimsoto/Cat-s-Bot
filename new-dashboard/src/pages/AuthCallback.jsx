import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      localStorage.setItem('botES_token', token);
      navigate('/panel/', { replace: true });
    } else {
      navigate('/panel/login', { replace: true });
    }
  }, [navigate]);

  return (
    <div className="login-body">
      <div className="login-card glass-panel" style={{ textAlign: 'center' }}>
        <div className="loading-orb" style={{ margin: '0 auto 20px' }}>
          <span>B</span>
        </div>
        <p>Autenticando con Discord...</p>
      </div>
    </div>
  );
}
