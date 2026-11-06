import { useState, useEffect, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import LandingOverlay from "../components/LandingOverlay";
import { apiGet, apiPreload } from "../lib/api";
import CatLogo from "../components/CatLogo";
import Toast from "../components/Toast";
import { SaveBarProvider, useSaveBarState } from "../lib/SaveBarContext";

const Overview = lazy(() => import("../components/Overview"));
const Endpoints = lazy(() => import("../components/Endpoints"));
const IAConfig = lazy(() => import("../components/IAConfig"));
const Radio = lazy(() => import("../components/Radio"));
const Tickets = lazy(() => import("../components/Tickets"));
const Moderation = lazy(() => import("../components/Moderation"));
const ChannelSettings = lazy(() => import("../components/ChannelSettings"));
const EmbedBuilder = lazy(() => import("../components/EmbedBuilder"));
const Levels = lazy(() => import("../components/Levels"));
const Autoroles = lazy(() => import("../components/Autoroles"));
const Giveaways = lazy(() => import("../components/Giveaways"));
const Tags = lazy(() => import("../components/Tags"));
const Reports = lazy(() => import("../components/Reports"));
const Schedules = lazy(() => import("../components/Schedules"));
const Logs = lazy(() => import("../components/Logs"));
const VoiceGen = lazy(() => import("../components/VoiceGen"));
const Welcome = lazy(() => import("../components/Welcome"));
const Suggestions = lazy(() => import("../components/Suggestions"));
const AutoMod = lazy(() => import("../components/AutoMod"));
const AutoResponses = lazy(() => import("../components/AutoResponses"));
const AutoReactions = lazy(() => import("../components/AutoReactions"));
const CustomCommands = lazy(() => import("../components/CustomCommands"));

const PANELS = {
  overview: Overview,
  ia: IAConfig,
  endpoints: Endpoints,
  radio: Radio,
  tickets: Tickets,
  moderation: Moderation,
  "channel-settings": ChannelSettings,
  embeds: EmbedBuilder,
  levels: Levels,
  autoroles: Autoroles,
  giveaways: Giveaways,
  tags: Tags,
  reports: Reports,
  schedules: Schedules,
  logs: Logs,
  "voice-gen": VoiceGen,
  welcome: Welcome,
  suggestions: Suggestions,
  automod: AutoMod,
  autoresponses: AutoResponses,
  autoreactions: AutoReactions,
  "custom-commands": CustomCommands,
};

const PAGE_TITLES = {
  overview: "Resumen del servidor",
  ia: "Inteligencia artificial",
  endpoints: "Endpoints",
  radio: "Radio y música",
  tickets: "Tickets",
  moderation: "Moderación",
  "channel-settings": "Ajustes por canal",
  embeds: "Creador de embeds",
  levels: "Niveles",
  autoroles: "Autoroles",
  giveaways: "Sorteos",
  tags: "Tags",
  reports: "Reportes",
  schedules: "Mensajes programados",
  logs: "Registros",
  "voice-gen": "Canales de voz",
  welcome: "Bienvenidas y boosters",
  suggestions: "Sugerencias",
  automod: "Automoderación",
  autoresponses: "Auto-respuestas",
  autoreactions: "Autorreacciones",
  "custom-commands": "Comandos personalizados",
};

const GUILD_KEY = "botES_guild_id";
const GUILDS_KEY = "botES_guilds_cache";
const USER_KEY = "botES_user_cache";

function readCache(key, fallback) {
  try {
    return JSON.parse(sessionStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function LoadingScreen() {
  return (
    <div className="loading-stage" role="status" aria-live="polite">
      <div className="loading-orb loading-orb--cat">
        <CatLogo size={56} />
      </div>
      <div className="loading-copy">
        <p className="topbar-eyebrow">Cat's Bot · Panel</p>
        <h1>Cargando tu panel</h1>
        <p>Verificando sesión y servidores.</p>
      </div>
      <div className="loading-steps">
        <span>Sesión</span>
        <span>Servidores</span>
        <span>Módulos</span>
      </div>
    </div>
  );
}

function PanelFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        padding: "48px 24px",
        textAlign: "center",
        color: "var(--text-muted)",
        font: '500 0.875rem "DM Sans", system-ui, sans-serif',
      }}
    >
      Cargando módulo…
    </div>
  );
}

function TopBar({ activePage, mobileMenuOpen, setMobileMenuOpen, selectedGuild, user, requiresGuild, openGuildPicker, theme, setTheme }) {
  const { dirty, saving, canSave, onSave, onRevert, requestNavigation } = useSaveBarState();
  const currentGuild = user.allowedGuilds.find((guild) => guild.id === selectedGuild);
  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="btn-icon mobile-only" onClick={() => setMobileMenuOpen(!mobileMenuOpen)} aria-label={mobileMenuOpen ? "Cerrar menú" : "Abrir menú"} aria-expanded={mobileMenuOpen} aria-controls="dashboard-navigation"><i className="fa-solid fa-bars" aria-hidden="true" /></button>
        <div className="topbar-title-wrap"><p className="topbar-eyebrow"><i className="fa-solid fa-hashtag" aria-hidden="true" /> {currentGuild?.name || "Panel del servidor"}</p><h1>{PAGE_TITLES[activePage] || "Panel"}</h1></div>
      </div>
      <div className="topbar-actions">
        <span className={`topbar-save-status ${dirty ? "is-dirty" : ""}`} role="status">{saving ? "Guardando…" : dirty ? "Cambios pendientes" : "Panel del servidor"}</span>
        {dirty && <div className="topbar-save-group">
          <button className="btn-secondary btn-topbar-revert" aria-label="Descartar" onClick={onRevert} disabled={saving} title="Descartar cambios"><i className="fa-solid fa-rotate-left" aria-hidden="true" /><span>Descartar</span></button>
          {canSave && <button className="btn-primary btn-topbar-save" aria-label={saving ? "Guardando…" : "Guardar"} onClick={onSave} disabled={saving}><i className="fa-solid fa-floppy-disk" aria-hidden="true" /><span>{saving ? "Guardando…" : "Guardar"}</span></button>}
        </div>}
        <button className="btn-icon theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`Activar tema ${theme === "dark" ? "claro" : "oscuro"}`} title={`Tema ${theme === "dark" ? "claro" : "oscuro"}`}><i className={`fa-solid fa-${theme === "dark" ? "sun" : "moon"}`} aria-hidden="true" /></button>
        {selectedGuild && <button className="btn-icon mobile-only" disabled={saving} aria-label="Cambiar de servidor" onClick={openGuildPicker}><i className="fa-solid fa-server" aria-hidden="true" /></button>}
        {requiresGuild && <button className="btn-icon" disabled={saving} onClick={() => requestNavigation(() => window.location.reload())} title="Recargar" aria-label="Recargar"><i className="fa-solid fa-rotate-right" aria-hidden="true" /></button>}
      </div>
    </header>
  );
}

export default function Dashboard() {
  return <SaveBarProvider><DashboardContent /></SaveBarProvider>;
}

function DashboardContent() {
  const navigate = useNavigate();
  const { requestNavigation, saving } = useSaveBarState();
  const [initial] = useState(() => {
    const guilds = readCache(GUILDS_KEY, []);
    const profile = readCache(USER_KEY, null);
    const saved = localStorage.getItem(GUILD_KEY);
    return { guilds, profile, guildId: guilds.some((guild) => guild.id === saved) ? saved : null };
  });
  const [user, setUser] = useState({ username: initial.profile?.username || "Cargando…", avatar: initial.profile?.avatar || "https://cdn.discordapp.com/embed/avatars/0.png", allowedGuilds: initial.guilds });
  const [selectedGuild, setSelectedGuild] = useState(initial.guildId);
  const [activePage, setActivePage] = useState("overview");
  const [showLanding, setShowLanding] = useState(initial.guilds.length > 0 && !initial.guildId);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [loading, setLoading] = useState(initial.guilds.length === 0);
  const [toast, setToast] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("catsbot_dashboard_theme") === "light" ? "light" : "dark");

  useEffect(() => {
    document.documentElement.dataset.dashboardTheme = theme;
    localStorage.setItem("catsbot_dashboard_theme", theme);
    return () => { delete document.documentElement.dataset.dashboardTheme; };
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      try {
        const data = await apiGet("/api/guilds");
        if (cancelled) return;
        const guilds = (data.guilds || []).filter((guild) => guild.has_bot !== false);
        const profile = data.user || {};
        const nextUser = { id: profile.id, username: profile.username || "Usuario Discord", avatar: profile.avatar || "https://cdn.discordapp.com/embed/avatars/0.png" };
        sessionStorage.setItem(GUILDS_KEY, JSON.stringify(guilds));
        sessionStorage.setItem(USER_KEY, JSON.stringify(nextUser));
        setUser({ ...nextUser, allowedGuilds: guilds });
        const saved = localStorage.getItem(GUILD_KEY);
        if (saved && guilds.some((guild) => guild.id === saved)) { setSelectedGuild(saved); setShowLanding(false); }
        else { localStorage.removeItem(GUILD_KEY); setShowLanding(true); }
      } catch { if (!cancelled) navigate("/"); }
      finally { if (!cancelled) setLoading(false); }
    };
    bootstrap();
    return () => { cancelled = true; };
  }, [navigate]);

  const selectGuild = (guildId) => {
    const select = () => {
      localStorage.setItem(GUILD_KEY, guildId);
      setSelectedGuild(guildId); setShowLanding(false); setMobileMenuOpen(false);
      apiPreload(`/api/guilds/${guildId}/overview`);
    };
    if (guildId === selectedGuild) select();
    else requestNavigation(select);
  };
  const navigateTo = (page) => {
    if (!PANELS[page]) return;
    if (page === activePage) { setMobileMenuOpen(false); return; }
    requestNavigation(() => { setActivePage(page); setMobileMenuOpen(false); requestAnimationFrame(() => document.getElementById("dashboard-content")?.focus()); });
  };
  const openGuildPicker = () => requestNavigation(() => { setShowLanding(true); setMobileMenuOpen(false); });
  const handleToast = (payload) => { if (payload) setToast({ type: payload.type || "success", msg: payload.msg || payload.message || "Operación completada" }); };
  const requiresGuild = !["docs"].includes(activePage);
  if (loading) return <LoadingScreen />;
  const ActivePanel = PANELS[activePage];

  return (
    <div className="app-container dashboard-shell">
      <a className="dashboard-skip-link" href="#dashboard-content">Ir al contenido</a>
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      {showLanding && <LandingOverlay guilds={user.allowedGuilds} onSelectGuild={selectGuild} onDismiss={selectedGuild ? () => setShowLanding(false) : undefined} />}
      <Sidebar user={user} selectedGuild={selectedGuild} onSelectGuild={selectGuild} activePage={activePage} setActivePage={navigateTo} mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} />
      <div className="main-content" inert={mobileMenuOpen}>
        <TopBar activePage={activePage} mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} selectedGuild={selectedGuild} user={user} requiresGuild={requiresGuild} openGuildPicker={openGuildPicker} theme={theme} setTheme={setTheme} />
        <main className="content-area" id="dashboard-content" tabIndex={-1} aria-busy={saving} aria-label={PAGE_TITLES[activePage]}>
          {!showLanding && (!requiresGuild || selectedGuild) && ActivePanel && <Suspense key={`${activePage}:${selectedGuild}`} fallback={<PanelFallback />}><div className="dashboard-panel-stage" inert={saving}><ActivePanel key={`${activePage}:${selectedGuild}`} selectedGuild={selectedGuild} onToast={handleToast} onNavigate={navigateTo} /></div></Suspense>}
          {!showLanding && requiresGuild && !selectedGuild && <div className="dashboard-empty-state"><CatLogo size={64} /><h2>Elige un servidor</h2><p>Selecciona uno de tus servidores para configurarlo.</p><button className="btn-primary" onClick={openGuildPicker}>Elegir servidor</button></div>}
        </main>
      </div>
    </div>
  );
}
