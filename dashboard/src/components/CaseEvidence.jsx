import { useEffect, useId, useRef, useState } from "react";
import { apiGet, apiUpload } from "../lib/api";
import "./CaseEvidence.css";

const DEFAULT_LIMITS = {
  max_file_bytes: 8 * 1024 * 1024,
  max_upload_bytes: 24 * 1024 * 1024,
  max_files: 6,
  max_case_bytes: 64 * 1024 * 1024,
};
const STATUS_LABELS = {
  available: "Disponible",
  partial: "Captura parcial",
  failed: "Captura fallida",
};
const PREVIEW_IMAGES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const ERROR_LABELS = {
  file_too_large: "El archivo supera el tamaño permitido.",
  unsupported_media: "Este formato de archivo no está admitido.",
  invalid_attachment_url: "No se pudo verificar el origen del adjunto.",
  attachment_unavailable: "El adjunto ya no está disponible o no se pudo descargar.",
  snapshot_unavailable: "No se pudo generar la captura de los mensajes.",
  too_many_files: "Se alcanzó el límite de archivos de la captura.",
  capture_budget_exceeded: "Se alcanzó el límite de tamaño o tiempo de la captura.",
  source_wrong_guild: "El mensaje de origen pertenece a otro servidor.",
  source_access_changed: "El acceso al canal cambió durante la captura; se descartaron los archivos para proteger su privacidad.",
  channel_unavailable: "El canal de origen ya no está disponible.",
  channel_access_denied: "El bot no tiene acceso al canal de origen.",
  private_thread_access_denied: "El bot no tiene acceso al hilo privado de origen.",
  invalid_message_source: "No se pudo identificar el mensaje de origen.",
  context_unavailable: "No se pudo recuperar el contexto de los mensajes.",
};

function sizeLabel(bytes) {
  return `${(bytes / (1024 * 1024)).toLocaleString("es", { maximumFractionDigits: 2 })} MiB`;
}

function EvidenceFiles({ guildId, caseRef, onUpdated }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [mediaErrors, setMediaErrors] = useState({});
  const active = useRef(false);
  const inputRef = useRef(null);
  const inputId = useId();
  const path = `/api/moderation/${encodeURIComponent(guildId)}/cases/${encodeURIComponent(caseRef)}/evidence`;
  const limits = { ...DEFAULT_LIMITS, ...data?.limits };
  const items = data?.items || [];

  useEffect(() => {
    let current = true;
    active.current = true;
    apiGet(path, { cache: false }).then((result) => {
      if (current) setData(result);
    }).catch((err) => {
      if (current) setError(err.message || "No se pudo cargar la evidencia.");
    });
    return () => { current = false; active.current = false; };
  }, [path]);

  const upload = async () => {
    if (uploading || !data || !files.length) return;
    setError("");
    setNotice("");
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    const storedBytes = items.reduce((sum, item) => sum + (item.inherited ? 0 : item.size || 0), 0);
    if (files.length > limits.max_files) {
      setError(`Selecciona como máximo ${limits.max_files} archivos por envío.`);
      return;
    }
    if (files.some((file) => file.size > limits.max_file_bytes)) {
      setError(`Cada archivo debe ocupar como máximo ${sizeLabel(limits.max_file_bytes)}.`);
      return;
    }
    if (totalBytes > limits.max_upload_bytes || storedBytes + totalBytes > limits.max_case_bytes) {
      setError(`Límite: ${sizeLabel(limits.max_upload_bytes)} por envío y ${sizeLabel(limits.max_case_bytes)} por caso.`);
      return;
    }
    setUploading(true);
    let saved = 0;
    const failed = [];
    const failures = [];
    for (const file of files) {
      if (!active.current) return;
      try {
        const result = await apiUpload(path, file);
        if (!active.current) return;
        setData(result);
        saved += 1;
        onUpdated?.(result);
      } catch (err) {
        if (!active.current) return;
        failed.push(file);
        failures.push(`${file.name}: ${ERROR_LABELS[err.message] || err.message || "No se pudo guardar."}`);
      }
    }
    setFiles(failed);
    if (inputRef.current) inputRef.current.value = "";
    setNotice(saved ? `${saved} archivo(s) guardado(s).` : "");
    setError(failures.join("\n"));
    setUploading(false);
  };

  return (
    <div className="case-evidence-content" aria-busy={uploading}>
      {!data && !error && <p role="status">Cargando evidencia…</p>}
      {data && items.length === 0 && <p className="case-evidence-meta">Este caso todavía no tiene archivos guardados.</p>}
      <div className="case-evidence-grid">
        {items.map((item) => {
          // Solo usar la ruta autenticada del caso; las fuentes externas se conservan como metadatos.
          const url = item.download_url === `${path}/${encodeURIComponent(item.id)}` ? item.download_url : null;
          const contentType = item.content_type?.split(";", 1)[0].toLowerCase();
          const preview = url && !mediaErrors[item.id];
          const date = item.created_at ? new Date(typeof item.created_at === "number" ? item.created_at * 1000 : item.created_at).toLocaleString("es") : "Fecha no disponible";
          return (
            <article className="case-evidence-file" key={item.id}>
              <strong>{item.filename || "Evidencia"}</strong>
              <p className="case-evidence-meta">{["upload", "moderator_attachment"].includes(item.source) ? "Adjunto del moderador" : "Captura automática"} · {date}{item.inherited ? " · Del caso de origen" : ""}</p>
              <p className="case-evidence-meta">{STATUS_LABELS[item.status] || item.status}{item.size != null ? ` · ${sizeLabel(item.size)}` : ""}</p>
              {preview && PREVIEW_IMAGES.has(contentType) && <img src={url} alt={item.filename || "Captura del caso"} loading="lazy" onError={() => setMediaErrors((prev) => ({ ...prev, [item.id]: true }))} />}
              {preview && ["video/mp4", "video/webm", "audio/mpeg", "audio/ogg", "audio/wav", "audio/flac"].includes(contentType) && (
                contentType.startsWith("video/")
                  ? <video src={url} controls preload="none" aria-label={item.filename} onError={() => setMediaErrors((prev) => ({ ...prev, [item.id]: true }))} />
                  : <audio src={url} controls preload="none" aria-label={item.filename} onError={() => setMediaErrors((prev) => ({ ...prev, [item.id]: true }))} />
              )}
              {mediaErrors[item.id] && <p role="status">Vista previa no disponible; puedes descargar el archivo.</p>}
              {item.error && <p className="case-evidence-error">{ERROR_LABELS[item.error] || "No se pudo conservar esta evidencia."}</p>}
              {item.uploader_id && <small className="case-evidence-meta">Aportado por: {item.uploader_id}</small>}
              {(item.source_message_id || item.source_channel_id) && <small className="case-evidence-meta">{item.source_message_id ? `Mensaje: ${item.source_message_id}` : ""}{item.source_channel_id ? ` · Canal: ${item.source_channel_id}` : ""}</small>}
              {url && <a href={url} download={item.filename || "evidencia"}>Descargar archivo</a>}
            </article>
          );
        })}
      </div>
      {data && <div className="case-evidence-upload">
        <label htmlFor={inputId}>Añadir archivos al caso</label>
        <small id={`${inputId}-limits`} className="case-evidence-meta">Hasta {limits.max_files} archivos por envío · {sizeLabel(limits.max_file_bytes)} por archivo · {sizeLabel(limits.max_upload_bytes)} por envío · {sizeLabel(limits.max_case_bytes)} por caso. Se guardan al pulsar «Subir archivos».</small>
        <input ref={inputRef} id={inputId} type="file" multiple accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm,audio/mpeg,audio/ogg,audio/wav,audio/flac" disabled={uploading} aria-describedby={`${inputId}-limits`} onChange={(event) => { setFiles(Array.from(event.target.files || [])); setError(""); setNotice(""); }} />
        {files.length > 0 && <p className="case-evidence-selection">{files.map((file) => file.name).join(", ")}</p>}
        <button type="button" className="btn btn-secondary" disabled={uploading || !files.length} onClick={upload}>{uploading ? "Guardando…" : "Subir archivos"}</button>
      </div>}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert" className="case-evidence-error">{error}</p>}
    </div>
  );
}

export default function CaseEvidence({ guildId, entry, onUpdated }) {
  const [open, setOpen] = useState(false);
  const caseRef = entry.case_number || entry.id;
  if (!guildId || !caseRef) return null;
  return (
    <details className="case-evidence" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Evidencia ({entry.evidence_count || 0}){entry.evidence_status && entry.evidence_status !== "none" ? ` · ${STATUS_LABELS[entry.evidence_status] || entry.evidence_status}` : ""}</summary>
      {open && <EvidenceFiles key={`${guildId}:${caseRef}`} guildId={String(guildId)} caseRef={String(caseRef)} onUpdated={onUpdated} />}
    </details>
  );
}
