/**
 * CatLogo — Brand logo (Cats Bots).
 * Renders the official PNG asset hosted at /logo.png with consistent sizing.
 *
 * Props:
 *   size      — px size of square box (default 40)
 *   ariaLabel — accessibility label
 *   className — additional className
 *   rounded   — apply rounded corners (default true)
 */
export default function CatLogo({
  size = 40,
  ariaLabel = "Cats Bots",
  className = "",
  rounded = true,
}) {
  return (
    <img
      src="/logo.png"
      width={size}
      height={size}
      alt={ariaLabel}
      decoding="async"
      loading="eager"
      draggable={false}
      className={`cat-logo ${rounded ? "cat-logo--rounded" : ""} ${className}`}
      style={{
        width: size,
        height: size,
        display: "block",
        objectFit: "contain",
      }}
    />
  );
}
