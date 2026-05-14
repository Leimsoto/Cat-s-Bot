/**
 * CatLogo — Brand mark (Cats Bots).
 * Renders the new brand SVG logo.
 *
 * Props:
 *   size      — px size of square box (default 40)
 *   ariaLabel — accessibility label
 *   className — additional className
 *   rounded   — apply rounded corners (default true)
 */
import logoSvg from "../assets/logo.svg";

export default function CatLogo({
  size = 40,
  ariaLabel = "Cats Bots",
  className = "",
  rounded = true}) {
  return (
    <img
      src={logoSvg}
      alt={ariaLabel}
      width={size}
      height={size}
      className={`cat-logo ${rounded ? "cat-logo--rounded" : ""} ${className}`}
      style={{ display: "block", width: size, height: size, objectFit: "contain" }}
    />
  );
}
