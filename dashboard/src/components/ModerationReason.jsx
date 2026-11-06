export default function ModerationReason({ entry }) {
  const status = { failed: "Acción fallida", applying: "Aplicación pendiente de confirmar" }[entry.status];
  return <div className="cr-event-reason">{status && <strong role="status">{status}</strong>}<span>{entry.reason_display || entry.reason || "Sin motivo registrado"}</span>{(entry.rule_text || entry.rule_label) && <small>Regla: {entry.rule_text || entry.rule_label}</small>}{entry.message_id && <details><summary>Detalle técnico</summary><code>ID del mensaje: {entry.message_id}</code></details>}</div>;
}
