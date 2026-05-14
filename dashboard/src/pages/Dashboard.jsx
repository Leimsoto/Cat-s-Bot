import { useState, useEffect, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import LandingOverlay from "../components/LandingOverlay";
import { apiGet, apiPreload } from "../lib/api";
import CatLogo from "../components/CatLogo";
import { SaveBarProvider, useSaveBarState } from "../lib/SaveBarContext";

const Overview = lazy(() => import("../components/Overview"));
const IAConfig = lazy(() => import("../components/IAConfig"));
const Radio = lazy(() => import("../components/Radio"));
const Tickets = lazy(() => import("../components/Tickets"));
const Moderation = lazy(() => import("../components/Moderation"));
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
const CustomCommands = lazy(() => import("../components/CustomCommands"));

const PANELS = {
  overview: Overview,
  ia: IAConfig,
  radio: Radio,
  tickets: Tickets,
  moderation: Moderation,
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
  "custom-commands": CustomCommands,
};

const PAGE_TITLES = {
  overview: "Resumen del servidor",
  ia: "Inteligencia artificial",
  radio: "Radio y música",
  tickets: "Tickets",
  moderation: "Moderación",
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
  invites: "Invitaciones",
  automod: "Automoderación",
  autoresponses: "Auto-respuestas",
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

function TopBar({
  activePage,
  mobileMenuOpen,
  setMobileMenuOpen,
  selectedGuild,
  user,
  requiresGuild,
  setShowLanding,
}) {
  const { dirty, saving, onSave, onRevert } = useSaveBarState();

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button
          className="mobile-only"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Abrir menú"
          style={{
            background: "none",
            border: "none",
            color: "var(--text)",
            fontSize: "1.4rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            minWidth: 44,
            minHeight: 44,
            justifyContent: "center",
          }}
        >
          <i className="fa-solid fa-bars" aria-hidden="true" />
        </button>
        <div className="topbar-title-wrap">
          <p className="topbar-eyebrow">Cat's Bot · Panel</p>
          <h1 style={{ margin: 0 }}>{PAGE_TITLES[activePage] || "Panel"}</h1>
        </div>
      </div>
      <div className="topbar-actions">
        {dirty && (
          <div className="topbar-save-group">
            <button
              className="btn-secondary btn-topbar-revert"
              onClick={onRevert}
              disabled={saving}
            >
              <i className="fa-solid fa-rotate-left" aria-hidden="true" />
              <span>Descartar</span>
            </button>
            <button
              className="btn-primary btn-topbar-save"
              onClick={onSave}
              disabled={saving}
            >
              <i className="fa-solid fa-floppy-disk" aria-hidden="true" />
              <span>{saving ? "Guardando…" : "Guardar"}</span>
            </button>
          </div>
        )}
        {selectedGuild && user && (
          <button
            className="mobile-guild-selector mobile-only"
            type="button"
            aria-label="Cambiar de servidor"
            onClick={() => {
              localStorage.removeItem(GUILD_KEY);
              setShowLanding(true);
            }}
          >
            <img
              src={
                user.allowedGuilds.find((g) => g.id === selectedGuild)?.icon ||
                "https://cdn.discordapp.com/embed/avatars/0.png"
              }
              alt=""
            />
            <span>
              {user.allowedGuilds.find((g) => g.id === selectedGuild)?.name ||
                "Servidor"}
            </span>
          </button>
        )}
        {requiresGuild && (
          <button
            className="btn-icon"
            onClick={() => window.location.reload()}
            title="Recargar"
            aria-label="Recargar"
          >
            <i className="fa-solid fa-rotate-right" aria-hidden="true" />
          </button>
        )}
      </div>
    </header>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const cachedGuilds = readCache(GUILDS_KEY, []);
  const cachedUser = readCache(USER_KEY, null);
  const savedGuildId = localStorage.getItem(GUILD_KEY);
  const initialGuildId = cachedGuilds.some((g) => g.id === savedGuildId)
    ? savedGuildId
    : null;

  const [user, setUser] = useState({
    username: cachedUser?.username || "Cargando…",
    avatar:
      cachedUser?.avatar || "https://cdn.discordapp.com/embed/avatars/0.png",
    allowedGuilds: cachedGuilds,
  });
  const [selectedGuild, setSelectedGuild] = useState(initialGuildId);
  const [activePage, setActivePage] = useState("overview");
  const [showLanding, setShowLanding] = useState(
    cachedGuilds.length > 0 && !initialGuildId,
  );
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [loading, setLoading] = useState(cachedGuilds.length === 0);

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const data = await apiGet("/api/guilds");
        const guilds = (data.guilds || []).filter((g) => g.has_bot !== false);
        const profile = data.user || {};
        const nextUser = {
          id: profile.id,
          username: profile.username || "Usuario Discord",
          avatar:
            profile.avatar || "https://cdn.discordapp.com/embed/avatars/0.png",
        };
        sessionStorage.setItem(GUILDS_KEY, JSON.stringify(guilds));
        sessionStorage.setItem(USER_KEY, JSON.stringify(nextUser));
        setUser({ ...nextUser, allowedGuilds: guilds });

        const saved = localStorage.getItem(GUILD_KEY);
        if (saved && guilds.some((g) => g.id === saved)) {
          setSelectedGuild(saved);
          setShowLanding(false);
        } else {
          localStorage.removeItem(GUILD_KEY);
          setShowLanding(true);
        }
      } catch {
        navigate("/");
      } finally {
        setLoading(false);
      }
    };
    bootstrap();
  }, [navigate]);

  const handleGuildSelect = (guildId) => {
    localStorage.setItem(GUILD_KEY, guildId);
    setSelectedGuild(guildId);
    setShowLanding(false);
    ["overview", "config", "radio", "ia"].forEach((s) =>
      apiPreload(`/api/guilds/${guildId}/${s}`),
    );
  };

  const requiresGuild = !["docs"].includes(activePage);

  if (loading) return <LoadingScreen />;

  const ActivePanel = PANELS[activePage];

  return (
    <SaveBarProvider>
      <div className="app-container">
        {showLanding && (
          <LandingOverlay
            guilds={user.allowedGuilds}
            onSelectGuild={handleGuildSelect}
          />
        )}

        <Sidebar
          user={user}
          selectedGuild={selectedGuild}
          onSelectGuild={handleGuildSelect}
          activePage={activePage}
          setActivePage={setActivePage}
          mobileMenuOpen={mobileMenuOpen}
          setMobileMenuOpen={setMobileMenuOpen}
        />

        <div className="main-content">
          <TopBar
            activePage={activePage}
            mobileMenuOpen={mobileMenuOpen}
            setMobileMenuOpen={setMobileMenuOpen}
            selectedGuild={selectedGuild}
            user={user}
            requiresGuild={requiresGuild}
            setShowLanding={setShowLanding}
          />

          <div className="content-area">
            {!showLanding && (!requiresGuild || selectedGuild) && ActivePanel && (
              <Suspense fallback={<PanelFallback />}>
                <ActivePanel selectedGuild={selectedGuild} />
              </Suspense>
            )}

            {!showLanding && requiresGuild && !selectedGuild && (
              <div className="dashboard-empty-state">
                <div className="dashboard-empty-icon">
                  <i
                    className="fa-solid fa-building-shield"
                    aria-hidden="true"
                  />
                </div>
                <h2>Elige un servidor</h2>
                <p>
                  Selecciona uno de tus servidores para configurarlo.
                </p>
                <button
                  className="btn-primary"
                  onClick={() => {
                    localStorage.removeItem(GUILD_KEY);
                    setShowLanding(true);
                  }}
                >
                  Elegir servidor
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </SaveBarProvider>
  );
}
