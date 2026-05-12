import { useEffect } from "react";
import { Icon } from "../lib/icons";

export default function Toast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, 3500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast]);

  if (!toast) return null;

  const isError = toast.type === "error";

  return (
    <div
      className={`toast-notification toast--${toast.type || "success"}`}
      role="alert"
      aria-live="polite"
    >
      <span className="toast-icon">
        <Icon name={isError ? "error" : "success"} />
      </span>
      <span className="toast-msg">{toast.msg}</span>
    </div>
  );
}
