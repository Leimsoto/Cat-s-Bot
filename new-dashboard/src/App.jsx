import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import AuthCallback from './pages/AuthCallback';

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('botES_token');
  if (!token) return <Navigate to="/panel/login" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/panel/login" element={<Login />} />
        <Route path="/panel/auth/callback" element={<AuthCallback />} />
        <Route
          path="/panel/*"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/panel/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
