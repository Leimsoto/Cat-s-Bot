import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { useSaveBar } from "../lib/SaveBarContext";

export default function AIMessageCategories({ guildId }) {
  const [data, setData] = useState(null);
  const [saved, setSaved] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const version = useRef(0);
  const path = `/api/guilds/${guildId}/ai-messages`;
  const dirty = data !== null && JSON.stringify(data.categories) !== JSON.stringify(saved?.categories);
  const load = useCallback(async () => {
    const current = ++version.current;
    setLoading(true);
    setError("");
    try {
      const next = await apiGet(path, { cache: false });
      if (current !== version.current) return;
      setData(next);
      setSaved(next);
      setFeedback("");
    } catch (e) {
      if (current === version.current) setError(e.message || "No pudimos cargar los avisos gestionados por IA.");
    } finally {
      if (current === version.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => { load(); return () => { version.current += 1; }; }, [load]);
  const save = async () => {
    if (!dirty || saving || loading) return;
    const current = version.current;
    setSaving(true);
    setError("");
    try {
      const next = await apiPatch(path, { categories: data.categories });
      if (current !== version.current) return;
      setData(next);
      setSaved(next);
      setFeedback("Preferencias de avisos guardadas.");
    } catch (e) {
      if (current === version.current) setError(e.message || "No pudimos guardar los avisos.");
    } finally {
      if (current === version.current) setSaving(false);
    }
  };
  useSaveBar({ dirty, saving, onSave: save, onRevert: load });
  return <section className="glass-panel cr-ai-notices" aria-labelledby="ai-notices-title">
    <h3 id="ai-notices-title">Avisos del bot gestionados por IA</h3>
    <p className="muted-text">Elige qué módulos pueden adaptar sus avisos con la personalidad del servidor. Están desactivados por defecto. Las plantillas editables tienen su propia opción «Gestionado por IA»; esta selección no cambia su modo manual.</p>
    <p className="muted-text">Se conserva la información del aviso y se usa el texto habitual si la IA no está disponible. Los registros y las sanciones no cambian.</p>
    {loading && <p role="status">Cargando preferencias…</p>}
    {error && <p role="alert">{error} <button type="button" className="btn-secondary" onClick={load} disabled={saving}>Recargar preferencias</button></p>}
    {feedback && <p role="status">{feedback}</p>}
    <fieldset disabled={saving || loading || !data} className="cr-ai-category-grid"><legend className="sr-only">Módulos con avisos gestionados por IA</legend>{Object.entries(data?.categories || {}).map(([key, enabled]) => <label className="cr-check-row" key={key}><input type="checkbox" checked={enabled} onChange={(event) => { setData((previous) => ({ ...previous, categories: { ...previous.categories, [key]: event.target.checked } })); setFeedback(""); }} /><span>{data.labels?.[key] || key}</span></label>)}</fieldset>
  </section>;
}
