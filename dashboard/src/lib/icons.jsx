/**
 * lib/icons.js
 * ────────────
 * Mapeo central de iconografía del dashboard.
 *
 * Política:
 *   • Toda iconografía usa FontAwesome 6 (ya cargado vía CDN en index.html).
 *   • No usar emojis Unicode genéricos en UI (títulos, botones, listas).
 *   • Solo usar iconos cuando aporten información semántica real.
 *   • Mantener una sola fuente de verdad: importar nombres de icono desde aquí.
 *
 * Uso:
 *   import { Icon, ICONS } from "../lib/icons";
 *   <Icon name="check" />
 *   <Icon name={ICONS.success} />
 */

// ── Mapa semántico → clase FontAwesome ───────────────────────────────────────
// Solo añadir entradas nuevas si el icono será usado en al menos 2 lugares.
export const ICONS = {
  // Estados
  success: "fa-circle-check",
  error: "fa-circle-xmark",
  warning: "fa-triangle-exclamation",
  info: "fa-circle-info",
  loading: "fa-spinner",

  // Acciones generales
  check: "fa-check",
  close: "fa-xmark",
  edit: "fa-pen",
  delete: "fa-trash",
  save: "fa-floppy-disk",
  add: "fa-plus",
  remove: "fa-minus",
  refresh: "fa-arrows-rotate",
  search: "fa-magnifying-glass",
  copy: "fa-copy",
  send: "fa-paper-plane",

  // Navegación
  chevronUp: "fa-chevron-up",
  chevronDown: "fa-chevron-down",
  chevronLeft: "fa-chevron-left",
  chevronRight: "fa-chevron-right",
  caretDown: "fa-caret-down",
  arrowRight: "fa-arrow-right",
  externalLink: "fa-arrow-up-right-from-square",

  // Discord / dominio
  channel: "fa-hashtag",
  voiceChannel: "fa-volume-high",
  category: "fa-folder",
  role: "fa-at",
  user: "fa-user",
  users: "fa-users",
  bot: "fa-robot",
  server: "fa-server",

  // Módulos (sidebar)
  overview: "fa-chart-pie",
  moderation: "fa-gavel",
  logs: "fa-stream",
  ia: "fa-brain",
  radio: "fa-radio",
  voiceGen: "fa-headphones",
  tickets: "fa-ticket",
  levels: "fa-star",
  autoroles: "fa-user-plus",
  giveaways: "fa-gift",
  tags: "fa-tags",
  invites: "fa-paper-plane",
  embeds: "fa-palette",
  reports: "fa-flag",
  schedules: "fa-clock",
  welcome: "fa-hand-wave",
  suggestions: "fa-lightbulb",

  // Otros
  lock: "fa-lock",
  unlock: "fa-lock-open",
  eye: "fa-eye",
  eyeOff: "fa-eye-slash",
  settings: "fa-gear",
  filter: "fa-filter",
};

/**
 * Componente <Icon /> — wrapper consistente sobre FontAwesome.
 *
 * Props:
 *   name      string — alias semántico de ICONS o clase fa-* directa.
 *   variant   "solid" | "regular" | "brands" (default "solid")
 *   size      "sm" | "md" | "lg" | "xl" (opcional, mapea a fa-xs..fa-2xl)
 *   className extra classes
 *   ...       resto se pasa al <i>
 */
const SIZE_MAP = {
  sm: "fa-xs",
  md: "",
  lg: "fa-lg",
  xl: "fa-xl",
};

export function Icon({
  name,
  variant = "solid",
  size,
  className = "",
  ...rest
}) {
  // Permitir tanto alias ("success") como clase directa ("fa-check").
  const cls = ICONS[name] || name;
  const sizeCls = size ? SIZE_MAP[size] || "" : "";
  return (
    <i
      className={`fa-${variant} ${cls} ${sizeCls} ${className}`.trim()}
      aria-hidden="true"
      {...rest}
    />
  );
}
