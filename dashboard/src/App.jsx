import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const AuthCallback = lazy(() => import('./pages/AuthCallback'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Tos = lazy(() => import('./pages/Tos'));

function loginPath() {
  return window.location.pathname.startsWith('/panel') ? '/panel/login' : '/';
}

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('botES_token');
  if (!token) return <Navigate to={loginPath()} replace />;
  return children;
}

function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        background: '#0b0a10',
        color: '#94a3b8',
        font: '500 0.875rem "DM Sans", system-ui, sans-serif'}}
    >
      Cargando…
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/tos" element={<Tos />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/panel/login" element={<Login />} />
          <Route path="/panel/auth/callback" element={<AuthCallback />} />
          <Route path="/panel" element={<Navigate to="/panel/dashboard" replace />} />
          <Route
            path="/panel/dashboard/*"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
