const helpStyle = { color: "var(--text-muted)", fontSize: "0.875rem", margin: "6px 0 0" };

export default function AutoModLLM({ rule, disabled, onChange, onNavigate }) {
  return (
    <fieldset className="cr-editor-panel cr-llm" disabled={disabled} aria-labelledby="automod-llm-heading">
      <h2 id="automod-llm-heading">Moderación IA</h2>
      <label style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input type="checkbox" checked={!!rule.enabled} onChange={(e) => onChange("enabled", e.target.checked)} />
        Activar moderación IA
      </label>
      <p style={helpStyle}>La conexión Strata se configura en Endpoints y se comparte con la conversación y los mensajes gestionados por IA. Activar la moderación es independiente; sus exenciones globales se configuran en la pestaña Excepciones.</p>

      <div className="config-item" style={{ marginTop: 24 }}>
        <label htmlFor="automod-llm-rules">Reglas del servidor e instrucciones de sanción</label>
        <textarea id="automod-llm-rules" rows={8} maxLength={12000} value={rule.rules_text || ""}
          placeholder="Describe las conductas prohibidas. La IA elegirá la sanción y su duración según estas reglas. Puedes indicar límites o criterios de gravedad."
          onChange={(e) => onChange("rules_text", e.target.value)}
          style={{ width: "100%", boxSizing: "border-box", resize: "vertical" }} />
        <p style={helpStyle}>Obligatorias para activar. Según estas reglas y el contexto, la IA elige si no actuar, solo eliminar el mensaje (delete), advertir (warn), silenciar (mute), expulsar (kick) o banear (ban), y la duración cuando corresponda. Puedes añadir límites de sanción o duración.</p>
        <p style={helpStyle}>Silencios: entre 1 minuto y 28 días; requieren un rol de mute configurado. Bans: permanentes o temporales, hasta 365 días. Delete, warn y kick no tienen duración. Cuando se elimina un mensaje, se menciona al autor y se explica el motivo en ese mismo canal o hilo; también queda en el historial.</p>
      </div>

      <div className="cr-form-grid">
        <div className="config-item">
          <label htmlFor="automod-llm-count">Mensajes anteriores (0–50)</label>
          <input id="automod-llm-count" type="number" min={0} max={50} step={1} value={rule.context_messages ?? 10}
            onChange={(e) => onChange("context_messages", e.target.value === "" ? "" : Number(e.target.value))} />
          <p style={helpStyle}>Se añaden al mensaje actual, siempre en el mismo canal. Con 0 solo se evalúa el mensaje actual, sin recuperar el texto de mensajes respondidos.</p>
        </div>
        <div className="config-item">
          <label htmlFor="automod-llm-context">Contexto de conversación</label>
          <select id="automod-llm-context" value={rule.context_mode || "user"} onChange={(e) => onChange("context_mode", e.target.value)}>
            <option value="user">Solo mensajes del usuario</option>
            <option value="channel">Mensajes recientes del canal</option>
          </select>
          <p style={helpStyle}>El modo usuario busca sus mensajes entre los últimos 500 del canal; puede encontrar menos de los solicitados. Se conserva qué mensaje responde a cuál. Con historial activo también se incluye, cuando está disponible, el texto respondido del mismo canal, aunque sea de otro autor o quede fuera de los mensajes seleccionados. El historial aporta texto.</p>
        </div>
      </div>

      <button type="button" className="btn-secondary" onClick={() => onNavigate?.("endpoints")}>Configurar conexión en Endpoints</button>
      <p style={{ ...helpStyle, marginTop: 20 }}>El texto y el contexto seleccionados se envían a este proveedor. Las decisiones y los medios no analizados quedan en Registro. Los errores del proveedor y las respuestas inválidas no aplican sanciones; las decisiones válidas se ejecutan automáticamente y pueden equivocarse.</p>
    </fieldset>
  );
}
