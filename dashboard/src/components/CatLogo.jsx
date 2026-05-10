/**
 * CatLogo — Brand mark (Cats Bots).
 * Inline SVG cat-paw on a violet/fuchsia gradient tile.
 *
 * Props:
 *   size      — px size of square box (default 40)
 *   ariaLabel — accessibility label
 *   className — additional className
 *   rounded   — apply rounded corners (default true)
 *   variant   — "tile" (default, full gradient bg) | "glyph" (paw only, transparent bg)
 */
export default function CatLogo({
  size = 40,
  ariaLabel = "Cats Bots",
  className = "",
  rounded = true,
  variant = "tile",
}) {
  const uid = `cl-${Math.random().toString(36).slice(2, 9)}`;
  const bgId = `${uid}-bg`;
  const shineId = `${uid}-shine`;
  const glowId = `${uid}-glow`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={ariaLabel}
      className={`cat-logo ${rounded ? "cat-logo--rounded" : ""} ${className}`}
      style={{ display: "block", width: size, height: size }}
    >
      <defs>
        <linearGradient id={bgId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#a855f7" />
          <stop offset="55%" stopColor="#7c3aed" />
          <stop offset="100%" stopColor="#d946ef" />
        </linearGradient>
        <linearGradient id={shineId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.55)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </linearGradient>
        <radialGradient id={glowId} cx="50%" cy="55%" r="55%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.32)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </radialGradient>
      </defs>

      {variant === "tile" && (
        <>
          <rect x="2" y="2" width="60" height="60" rx="16" fill={`url(#${bgId})`} />
          <rect
            x="2"
            y="2"
            width="60"
            height="30"
            rx="16"
            fill={`url(#${shineId})`}
            opacity="0.5"
          />
          <circle cx="32" cy="36" r="22" fill={`url(#${glowId})`} />
        </>
      )}

      <g fill={variant === "glyph" ? "#c084fc" : "#ffffff"}>
        <ellipse cx="32" cy="42" rx="11" ry="9.5" />
        <ellipse cx="20" cy="29" rx="4.6" ry="6" />
        <ellipse cx="44" cy="29" rx="4.6" ry="6" />
        <ellipse cx="27" cy="20" rx="3.6" ry="5" />
        <ellipse cx="37" cy="20" rx="3.6" ry="5" />
      </g>
      <g fill={variant === "glyph" ? "#7c3aed" : "#7c3aed"} opacity="0.95">
        <ellipse cx="32" cy="42" rx="3.6" ry="3" />
        <ellipse cx="20" cy="29" rx="1.5" ry="1.9" />
        <ellipse cx="44" cy="29" rx="1.5" ry="1.9" />
        <ellipse cx="27" cy="20" rx="1.2" ry="1.6" />
        <ellipse cx="37" cy="20" rx="1.2" ry="1.6" />
      </g>
    </svg>
  );
}
