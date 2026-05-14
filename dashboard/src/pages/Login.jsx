import { useEffect, useMemo, useRef, useState } from "react";
import CatLogo from "../components/CatLogo";

const LOGIN_URL = "/api/auth/login";

function DiscordIcon({ size = 18 }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M20.317 4.369A19.79 19.79 0 0 0 16.558 3a14.86 14.86 0 0 0-.65 1.328 18.27 18.27 0 0 0-5.487 0A12.5 12.5 0 0 0 9.77 3a19.74 19.74 0 0 0-3.76 1.37C2.4 9.59 1.5 14.67 1.96 19.68a19.94 19.94 0 0 0 5.99 3.02c.48-.66.92-1.36 1.3-2.1a12.94 12.94 0 0 1-2.04-.98c.17-.13.34-.26.5-.39a14.27 14.27 0 0 0 12.58 0c.16.13.33.26.5.39-.65.39-1.34.71-2.04.98.38.74.82 1.44 1.3 2.1a19.91 19.91 0 0 0 5.99-3.02c.55-5.92-.91-10.95-3.72-15.31zM8.02 16.27c-1.18 0-2.16-1.08-2.16-2.42 0-1.33.96-2.42 2.16-2.42 1.2 0 2.18 1.09 2.16 2.42 0 1.34-.97 2.42-2.16 2.42zm7.96 0c-1.18 0-2.16-1.08-2.16-2.42 0-1.33.96-2.42 2.16-2.42 1.2 0 2.18 1.09 2.16 2.42 0 1.34-.96 2.42-2.16 2.42z" />
    </svg>
  );
}

const FEATURES = [
  {
    icon: "fa-microchip",
    title: "IA Conversacional",
    text: "Modelo de lenguaje integrado con memoria por canal, comandos y respuestas contextuales en español.",
    color: "#a78bfa"},
  {
    icon: "fa-shield-halved",
    title: "Moderación Avanzada",
    text: "AutoMod con detección de spam, palabras prohibidas, raid protection y casos persistentes.",
    color: "#f43f5e"},
  {
    icon: "fa-ticket",
    title: "Sistema de Tickets",
    text: "Categorías personalizables, transcripciones automáticas y panel para staff.",
    color: "#38bdf8"},
  {
    icon: "fa-music",
    title: "Radio & Música",
    text: "Streaming 24/7, lofi, estaciones globales y comandos de cola.",
    color: "#34d399"},
  {
    icon: "fa-chart-line",
    title: "Niveles & XP",
    text: "Sistema de progresión con recompensas de rol, leaderboard y multiplicadores.",
    color: "#f59e0b"},
  {
    icon: "fa-door-open",
    title: "Bienvenidas & Boosters",
    text: "Mensajes con embeds dinámicos, imágenes generadas y reconocimiento de boosts.",
    color: "#22d3ee"},
  {
    icon: "fa-gift",
    title: "Sorteos",
    text: "Giveaways programados con condiciones, ganadores múltiples y reroll.",
    color: "#ec4899"},
  {
    icon: "fa-headset",
    title: "Canales de Voz Auto",
    text: "Crea canales temporales bajo demanda, controla permisos y límites.",
    color: "#818cf8"},
  {
    icon: "fa-clock",
    title: "Mensajes Programados",
    text: "Envía recordatorios y avisos en intervalos cron, sin perder el ritmo.",
    color: "#fbbf24"},
  {
    icon: "fa-code",
    title: "Embed Builder",
    text: "Constructor visual con preview en vivo, plantillas y envío por API.",
    color: "#67e8f9"},
  {
    icon: "fa-flag",
    title: "Reportes",
    text: "Sistema de reportes con seguimiento, asignación y resolución.",
    color: "#fb7185"},
  {
    icon: "fa-link",
    title: "Tracking de Invites",
    text: "Quién invitó a quién, ranking, leaderboard y rewards por invitaciones.",
    color: "#60a5fa"},
];

const ADVANTAGES = [
  {
    icon: "fa-bolt",
    title: "Rápido de verdad",
    text: "El panel responde al instante. Sin esperas, sin cargas eternas."},
  {
    icon: "fa-lock",
    title: "OAuth2 seguro",
    text: "Te logueas con tu cuenta de Discord. Solo admins y dueños del servidor entran al panel."},
  {
    icon: "fa-sliders",
    title: "Configurable por servidor",
    text: "Cada servidor tiene su propia configuración. Lo que cambies en uno no toca a los demás."},
  {
    icon: "fa-language",
    title: "100% en español",
    text: "Comandos, mensajes y dashboard en español nativo. Sin traducciones automáticas."},
  {
    icon: "fa-arrows-rotate",
    title: "Actualizaciones constantes",
    text: "Módulos nuevos cada semana, sin interrumpir tu servidor."},
  {
    icon: "fa-shield-heart",
    title: "Código abierto",
    text: "El código del bot es público en GitHub. Cualquiera puede revisar cómo modera, qué hace la IA y cómo trata tus datos."},
];

function useReveal() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const node = ref.current;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setVisible(true);
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, []);
  return [ref, visible];
}

function Reveal({ children, delay = 0, as: Tag = "div", className = "" }) {
  const [ref, visible] = useReveal();
  return (
    <Tag
      ref={ref}
      className={`reveal ${visible ? "is-visible" : ""} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

function useCounter(target, durationMs = 1400, start = false) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!start) return;
    if (!target || target <= 0) return;
    let raf = 0;
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / durationMs);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs, start]);
  return value;
}

function StatCounter({ value, label, icon, color, started }) {
  const animated = useCounter(value, 1400, started);
  return (
    <div className="ll-stat-card glass-panel">
      <span className="ll-stat-icon" style={{ color, background: `${color}1f` }}>
        <i className={`fa-solid ${icon}`} />
      </span>
      <span className="ll-stat-value">{animated.toLocaleString("es")}</span>
      <span className="ll-stat-label">{label}</span>
    </div>
  );
}

function formatUptime(seconds) {
  if (!seconds || seconds < 60) return "Iniciando";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export default function Login() {
  const error = new URLSearchParams(window.location.search).get("error");
  const [stats, setStats] = useState(null);
  const [statsReady, setStatsReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/public/stats", { credentials: "omit" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        setStats(data);
        requestAnimationFrame(() => setStatsReady(true));
      })
      .catch(() => {
        if (cancelled) return;
        setStats(null);
        setStatsReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogin = (e) => {
    e?.preventDefault?.();
    window.location.href = LOGIN_URL;
  };

  const modules = useMemo(() => stats?.modules ?? [], [stats]);
  const serverCount = stats?.server_count ?? 0;
  const memberCount = stats?.member_count ?? 0;
  const moduleCount = stats?.module_count ?? FEATURES.length;
  const channelCount = stats?.channel_count ?? 0;
  const isOnline = stats?.online ?? false;
  const uptime = formatUptime(stats?.uptime_seconds ?? 0);
  const latency = stats?.latency_ms ?? 0;

  return (
    <div className="landing-shell">
      <div className="landing-bg-grid" aria-hidden="true" />
      <div className="landing-bg-orb landing-bg-orb--a" aria-hidden="true" />
      <div className="landing-bg-orb landing-bg-orb--b" aria-hidden="true" />
      <div className="landing-bg-orb landing-bg-orb--c" aria-hidden="true" />

      <header className="landing-nav">
        <a className="landing-logo" href="#top">
          <span className="landing-logo-mark landing-logo-mark--cat">
            <CatLogo size={32} ariaLabel="Cat's Bot" />
          </span>
          <span className="landing-logo-text">
            Cat's <span>Bot</span>
          </span>
        </a>
        <nav className="landing-nav-links">
          <a href="#caracteristicas">Características</a>
          <a href="#modulos">Módulos</a>
          <a href="#ventajas">Ventajas</a>
          <a href="#estadisticas">Estadísticas</a>
        </nav>
        <button className="landing-nav-cta" onClick={handleLogin}>
          <DiscordIcon />
          Iniciar sesión
        </button>
      </header>

      <main id="top">
        <section className="landing-hero">
          <div className="landing-hero-inner">
            <span className="landing-pill">
              <span className={`landing-pill-dot ${isOnline ? "is-on" : ""}`} />
              {isOnline ? "Bot en línea" : "Conectando..."}
              {isOnline && (
                <>
                  <span className="landing-pill-sep">·</span>
                  <span>{latency} ms</span>
                  <span className="landing-pill-sep">·</span>
                  <span>uptime {uptime}</span>
                </>
              )}
            </span>

            <h1 className="landing-hero-title">
              Tu servidor de Discord, configurado{" "}
              <span className="landing-hero-accent">desde la web</span>.
            </h1>

            <p className="landing-hero-sub">
              Modera, da la bienvenida, premia con niveles, abre tickets y pon
              música sin escribir un comando. Entra al panel, marca lo que quieres
              activar y listo.
            </p>

            {error && (
              <div className="landing-error">
                <i className="fa-solid fa-circle-exclamation" />
                {error === "access_denied"
                  ? "Acceso denegado. Debes aceptar los permisos de Discord."
                  : error === "invalid_state"
                    ? "Sesión expirada. Vuelve a iniciar sesión."
                    : error === "token_failed"
                      ? "Error al obtener el token. Inténtalo de nuevo."
                      : "Error de autenticación. Inténtalo de nuevo."}
              </div>
            )}

            <div className="landing-hero-actions">
              <button className="landing-cta-primary" onClick={handleLogin}>
                <DiscordIcon size={20} />
                Acceder al panel
                <i className="fa-solid fa-arrow-right landing-cta-arrow" aria-hidden="true" />
              </button>
              <a
                className="landing-cta-secondary"
                href="https://catsbot-setup.leimsoto.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                <i className="fa-solid fa-plus" aria-hidden="true" />
                Aún no lo tienes, invítalo
              </a>
            </div>

            <p className="landing-hero-note">
              <i className="fa-solid fa-shield-halved" /> Login con Discord
              (OAuth2). Solo admins y owners entran al panel.
            </p>
          </div>

          <div className="landing-hero-card glass-panel">
            <div className="landing-hero-card-head">
              <div className="landing-hero-card-id">
                <span className="landing-hero-card-mark landing-hero-card-mark--cat">
                  <CatLogo size={42} ariaLabel="Cat's Bot" />
                </span>
                <div>
                  <strong>Cat's Bot</strong>
                  <small>Panel · v2.0</small>
                </div>
              </div>
              <span
                className={`landing-hero-status ${
                  isOnline ? "is-on" : "is-off"
                }`}
              >
                <span /> {isOnline ? "Operativo" : "Sin conexión"}
              </span>
            </div>
            <ul className="landing-hero-card-list">
              <li>
                <i className="fa-solid fa-server" />
                <span>Servidores activos</span>
                <strong>{serverCount.toLocaleString("es")}</strong>
              </li>
              <li>
                <i className="fa-solid fa-users" />
                <span>Miembros alcanzados</span>
                <strong>{memberCount.toLocaleString("es")}</strong>
              </li>
              <li>
                <i className="fa-solid fa-puzzle-piece" />
                <span>Módulos disponibles</span>
                <strong>{moduleCount}</strong>
              </li>
              <li>
                <i className="fa-solid fa-bolt" />
                <span>Latencia API</span>
                <strong>{latency} ms</strong>
              </li>
            </ul>
            <div className="landing-hero-card-foot">
              <span className="landing-hero-card-pulse" />
              Sincronizado en tiempo real
            </div>
          </div>
        </section>

        <section id="estadisticas" className="landing-section">
          <Reveal className="landing-section-head">
            <span className="landing-eyebrow">Cifras en vivo</span>
            <h2>Datos reales. No promesas.</h2>
            <p>
              Estadísticas globales del bot, calculadas desde los servidores
              donde está presente ahora mismo.
            </p>
          </Reveal>
          <div className="landing-stats-grid">
            <Reveal delay={0}>
              <StatCounter
                value={serverCount}
                label="Servidores activos"
                icon="fa-server"
                color="#818cf8"
                started={statsReady}
              />
            </Reveal>
            <Reveal delay={80}>
              <StatCounter
                value={memberCount}
                label="Miembros totales"
                icon="fa-users"
                color="#22d3ee"
                started={statsReady}
              />
            </Reveal>
            <Reveal delay={160}>
              <StatCounter
                value={channelCount}
                label="Canales gestionados"
                icon="fa-hashtag"
                color="#34d399"
                started={statsReady}
              />
            </Reveal>
            <Reveal delay={240}>
              <StatCounter
                value={moduleCount}
                label="Módulos disponibles"
                icon="fa-puzzle-piece"
                color="#f59e0b"
                started={statsReady}
              />
            </Reveal>
          </div>
        </section>

        <section id="caracteristicas" className="landing-section">
          <Reveal className="landing-section-head">
            <span className="landing-eyebrow">Características</span>
            <h2>Todo lo que tu servidor necesita en un solo lugar.</h2>
            <p>
              Cada módulo está pensado para resolver un problema real de las
              comunidades en español: orden, retención, automatización.
            </p>
          </Reveal>
          <div className="landing-features-grid">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 60}>
                <article className="landing-feature glass-panel">
                  <span
                    className="landing-feature-icon"
                    style={{ color: f.color, background: `${f.color}1c` }}
                  >
                    <i className={`fa-solid ${f.icon}`} />
                  </span>
                  <h3>{f.title}</h3>
                  <p>{f.text}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        <section id="modulos" className="landing-section">
          <Reveal className="landing-section-head">
            <span className="landing-eyebrow">Módulos disponibles</span>
            <h2>{moduleCount} módulos listos para usar.</h2>
            <p>
              Activa, desactiva y configura cada uno desde el panel. Sin tocar
              código, sin reinicios.
            </p>
          </Reveal>
          <div className="landing-modules-marquee" aria-hidden="true">
            <div className="landing-modules-track">
              {[...modules, ...modules, ...FEATURES.map((f) => ({
                key: f.title,
                name: f.title,
                icon: f.icon}))].map((m, i) => (
                <span key={`${m.key}-${i}`} className="landing-module-chip">
                  <i className={`fa-solid ${m.icon}`} />
                  {m.name}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section id="ventajas" className="landing-section">
          <Reveal className="landing-section-head">
            <span className="landing-eyebrow">Por qué Cat's Bot</span>
            <h2>Pensado por y para administradores serios.</h2>
            <p>
              Cada decisión técnica del bot está orientada a no dejarte solo
              cuando tu servidor crece.
            </p>
          </Reveal>
          <div className="landing-advantages-grid">
            {ADVANTAGES.map((a, i) => (
              <Reveal key={a.title} delay={i * 80}>
                <article className="landing-advantage glass-panel">
                  <span className="landing-advantage-icon">
                    <i className={`fa-solid ${a.icon}`} />
                  </span>
                  <div>
                    <h3>{a.title}</h3>
                    <p>{a.text}</p>
                  </div>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        <section className="landing-section landing-cta-section">
          <Reveal>
            <div className="landing-cta-card glass-panel">
              <div>
                <span className="landing-eyebrow">Listo cuando tú lo estés</span>
                <h2>
                  Inicia sesión y empieza a configurar tu servidor en minutos.
                </h2>
                <p>
                  Acceso restringido a administradores y dueños del servidor
                  mediante OAuth2 oficial de Discord.
                </p>
              </div>
              <div className="landing-cta-card-actions">
                <button className="landing-cta-primary" onClick={handleLogin}>
                  <DiscordIcon />
                  Acceder al panel
                </button>
                <small>
                  <i className="fa-solid fa-lock" /> Tus credenciales nunca se
                  almacenan
                </small>
              </div>
            </div>
          </Reveal>
        </section>
      </main>

      <footer className="landing-footer">
        <div>
          <span className="landing-logo-mark landing-logo-mark--sm landing-logo-mark--cat">
            <CatLogo size={20} ariaLabel="Cat's Bot" />
          </span>
          <span>Cat's Bot</span>
          <small>Panel de control v2.0</small>
        </div>
        <div className="landing-footer-meta">
          <span>
            <span
              className={`landing-pill-dot ${isOnline ? "is-on" : ""}`}
            />
            {isOnline ? "Servicio operativo" : "Conectando"}
          </span>
          <span>· {serverCount.toLocaleString("es")} servidores</span>
          <span>· hecho con cariño en español</span>
        </div>
      </footer>
    </div>
  );
}
