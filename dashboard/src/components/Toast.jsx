import { useEffect } from 'react';

export default function Toast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, 3500);
    return () => clearTimeout(t);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div className={`toast-notification toast--${toast.type || 'success'}`} role="alert" aria-live="polite">
      <span className="toast-icon">
        {toast.type === 'error' ? '✕' : '✓'}
      </span>
      <span className="toast-msg">{toast.msg}</span>
    </div>
  );
}
