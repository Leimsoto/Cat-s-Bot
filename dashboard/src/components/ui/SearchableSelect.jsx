/**
 * components/ui/SearchableSelect.jsx
 * ──────────────────────────────────
 * Componente de selección con búsqueda en tiempo real.
 *
 * Reemplazo del <select> nativo: filtrado dinámico, navegación por teclado,
 * soporte single/multi, fuente local o endpoint remoto con debounce.
 *
 * Modos:
 *   • Lista local — pasar `options` (array). Filtrado client-side por substring +
 *     score de relevancia (prefix > substring > fuzzy básico).
 *   • Endpoint remoto — pasar `endpoint` (string). El componente hace fetch a
 *     `${endpoint}?search=<q>&limit=<n>` con debounce. La respuesta debe ser
 *     `{[itemsKey]: [...]}` (default itemsKey = "items"; configurable).
 *
 * Cada opción debe tener al menos `{ id, name }`. Campos extra
 * (`color`, `avatar`, `subtitle`) habilitan render enriquecido.
 *
 * Props principales:
 *   value          string|number|null|array — id(s) seleccionado(s)
 *   onChange       (newValue) => void
 *   options        array (modo local)
 *   endpoint       string (modo remoto)
 *   itemsKey       clave de la respuesta remota que contiene el array (default "items")
 *   placeholder    string
 *   multiple       bool — selección múltiple
 *   disabled       bool
 *   maxResults     int — visibles a la vez (default 50)
 *   renderOption   (opt) => ReactNode — render custom de cada item
 *   renderSelected (opt) => ReactNode — render custom del valor seleccionado
 *   minSearchChars int — para endpoint, no fetch hasta tener N chars (default 0)
 *   debounceMs     int — default 200
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiGet } from "../../lib/api";
import "./SearchableSelect.css";

// ── Helpers ──────────────────────────────────────────────────────────────────

function scoreMatch(name, query) {
  if (!query) return 0;
  const n = String(name || "").toLowerCase();
  const q = query.toLowerCase();
  if (n === q) return 1000;
  if (n.startsWith(q)) return 500;
  const idx = n.indexOf(q);
  if (idx >= 0) return 300 - idx;
  // fuzzy básico: todas las letras del query aparecen en orden
  let pos = 0;
  for (const c of q) {
    pos = n.indexOf(c, pos);
    if (pos < 0) return -1;
    pos += 1;
  }
  return 50;
}

function filterLocal(options, query, max) {
  if (!query) return options.slice(0, max);
  const scored = options
    .map((opt) => ({ opt, score: scoreMatch(opt.name || opt.label, query) }))
    .filter((x) => x.score >= 0)
    .sort((a, b) => b.score - a.score);
  return scored.slice(0, max).map((x) => x.opt);
}

function useDebounce(value, ms) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

// ── Default renderers ────────────────────────────────────────────────────────

function defaultOptionRenderer(opt) {
  const swatch = opt.color ? (
    <span
      className="ss-swatch"
      style={{ background: opt.color }}
      aria-hidden="true"
    />
  ) : null;
  const avatar = opt.avatar ? (
    <img
      className="ss-avatar"
      src={opt.avatar}
      alt=""
      loading="lazy"
      aria-hidden="true"
    />
  ) : null;
  return (
    <>
      {swatch}
      {avatar}
      <span className="ss-option-label">{opt.name}</span>
      {opt.subtitle ? <span className="ss-option-sub">{opt.subtitle}</span> : null}
    </>
  );
}

// ── Componente ───────────────────────────────────────────────────────────────

export default function SearchableSelect({
  value,
  onChange,
  options = null,
  endpoint = null,
  itemsKey = "items",
  placeholder = "Buscar…",
  multiple = false,
  disabled = false,
  maxResults = 50,
  renderOption,
  renderSelected,
  minSearchChars = 0,
  debounceMs = 200,
  emptyMessage = "Sin resultados.",
  loadingMessage = "Cargando…",
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [remoteOptions, setRemoteOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const [popoverPos, setPopoverPos] = useState(null);

  const debouncedQuery = useDebounce(query, debounceMs);

  // Calcula la posición del popover (portal-friendly, evita overflow del card padre).
  const recalcPos = useCallback(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const margin = 8;
    const maxH = 320;
    const spaceBelow = window.innerHeight - r.bottom - margin;
    const spaceAbove = r.top - margin;
    const placeAbove = spaceBelow < 220 && spaceAbove > spaceBelow;
    const top = placeAbove
      ? Math.max(margin, r.top - Math.min(maxH, spaceAbove) - 4)
      : r.bottom + 4;
    setPopoverPos({
      top,
      left: r.left,
      width: r.width,
      maxHeight: placeAbove ? Math.min(maxH, spaceAbove) : Math.min(maxH, spaceBelow),
    });
  }, []);

  // Modo: si hay endpoint, modo remoto. Si no, local.
  const isRemote = Boolean(endpoint);

  // Fetch remoto debounced.
  useEffect(() => {
    if (!isRemote || !open) return;
    if (debouncedQuery.length < minSearchChars && minSearchChars > 0) {
      setRemoteOptions([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const sep = endpoint.includes("?") ? "&" : "?";
    const url = `${endpoint}${sep}search=${encodeURIComponent(debouncedQuery)}&limit=${maxResults}`;
    apiGet(url, { cache: false })
      .then((data) => {
        if (cancelled) return;
        const arr = Array.isArray(data?.[itemsKey])
          ? data[itemsKey]
          : Array.isArray(data)
          ? data
          : [];
        setRemoteOptions(arr);
      })
      .catch(() => {
        if (!cancelled) setRemoteOptions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, endpoint, isRemote, itemsKey, maxResults, minSearchChars, open]);

  // Lista visible.
  const visibleOptions = useMemo(() => {
    if (isRemote) return remoteOptions;
    return filterLocal(options || [], query, maxResults);
  }, [isRemote, remoteOptions, options, query, maxResults]);

  // Mapa id -> opt (para mostrar selección sin fetch adicional).
  const knownById = useMemo(() => {
    const m = new Map();
    for (const o of options || []) m.set(String(o.id), o);
    for (const o of remoteOptions) m.set(String(o.id), o);
    return m;
  }, [options, remoteOptions]);

  // Cerrar al hacer click fuera (también considera el popover en portal).
  useEffect(() => {
    if (!open) return;
    function onDoc(e) {
      const inRoot = rootRef.current && rootRef.current.contains(e.target);
      const inPop = popoverRef.current && popoverRef.current.contains(e.target);
      if (!inRoot && !inPop) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Recalcular posición al abrir / scroll / resize.
  useEffect(() => {
    if (!open) {
      setPopoverPos(null);
      return;
    }
    recalcPos();
    const onMove = () => recalcPos();
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open, recalcPos]);

  // Reset activeIndex cuando cambia el query.
  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  // Auto-focus en input al abrir.
  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);

  // Auto-scroll al item activo.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${activeIndex}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open, visibleOptions]);

  // Selección.
  const handleSelect = useCallback(
    (opt) => {
      if (multiple) {
        const arr = Array.isArray(value) ? value.map(String) : [];
        const id = String(opt.id);
        const next = arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id];
        onChange(next);
        // mantener abierto en multi
      } else {
        onChange(String(opt.id));
        setOpen(false);
        setQuery("");
      }
    },
    [multiple, onChange, value],
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (!open) {
        if (e.key === "Enter" || e.key === "ArrowDown" || e.key === " ") {
          e.preventDefault();
          setOpen(true);
        }
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, visibleOptions.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const opt = visibleOptions[activeIndex];
        if (opt) handleSelect(opt);
      } else if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    },
    [open, visibleOptions, activeIndex, handleSelect],
  );

  const renderOpt = renderOption || defaultOptionRenderer;
  const renderSel = renderSelected || ((opt) => opt.name);

  // Selección actual (solo single para preview principal — multi se muestra como chips abajo).
  const selectedSingle =
    !multiple && value != null && value !== ""
      ? knownById.get(String(value)) || { id: value, name: `#${value}` }
      : null;

  const selectedMulti = multiple && Array.isArray(value)
    ? value.map((v) => knownById.get(String(v)) || { id: v, name: `#${v}` })
    : [];

  return (
    <div
      ref={rootRef}
      className={`ss-root ${open ? "ss-open" : ""} ${disabled ? "ss-disabled" : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="ss-trigger"
        onClick={() => !disabled && setOpen((v) => !v)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="ss-trigger-label">
          {multiple
            ? selectedMulti.length === 0
              ? <span className="ss-placeholder">{placeholder}</span>
              : (
                <span className="ss-chips">
                  {selectedMulti.slice(0, 3).map((opt) => (
                    <span key={opt.id} className="ss-chip">{renderSel(opt)}</span>
                  ))}
                  {selectedMulti.length > 3 ? (
                    <span className="ss-chip ss-chip-more">
                      +{selectedMulti.length - 3}
                    </span>
                  ) : null}
                </span>
              )
            : selectedSingle
              ? <span className="ss-selected-single">{renderSel(selectedSingle)}</span>
              : <span className="ss-placeholder">{placeholder}</span>}
        </span>
        <span className="ss-caret" aria-hidden="true">▾</span>
      </button>

      {open && popoverPos
        ? createPortal(
            <div
              ref={popoverRef}
              className="ss-popover"
              role="listbox"
              style={{
                position: "fixed",
                top: popoverPos.top,
                left: popoverPos.left,
                width: popoverPos.width,
                maxHeight: popoverPos.maxHeight,
              }}
            >
              <div className="ss-search">
                <input
                  ref={inputRef}
                  type="text"
                  className="ss-search-input"
                  value={query}
                  placeholder={placeholder}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <div className="ss-list" ref={listRef}>
                {loading && visibleOptions.length === 0 ? (
                  <div className="ss-empty">{loadingMessage}</div>
                ) : visibleOptions.length === 0 ? (
                  <div className="ss-empty">{emptyMessage}</div>
                ) : (
                  visibleOptions.map((opt, idx) => {
                    const id = String(opt.id);
                    const isSelected = multiple
                      ? Array.isArray(value) && value.map(String).includes(id)
                      : String(value) === id;
                    return (
                      <button
                        key={id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        data-idx={idx}
                        className={`ss-option ${idx === activeIndex ? "ss-active" : ""} ${
                          isSelected ? "ss-selected" : ""
                        }`}
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => handleSelect(opt)}
                      >
                        {renderOpt(opt)}
                        {isSelected ? <span className="ss-check">✓</span> : null}
                      </button>
                    );
                  })
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
