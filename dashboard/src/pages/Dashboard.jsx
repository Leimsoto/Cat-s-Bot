import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import LandingOverlay from "../components/LandingOverlay";
import Overview from "../components/Overview";
import IAConfig from "../components/IAConfig";
import Radio from "../components/Radio";
import Tickets from "../components/Tickets";
import Moderation from "../components/Moderation";
import EmbedBuilder from "../components/EmbedBuilder";
import Levels from "../components/Levels";
import Autoroles from "../components/Autoroles";
import Giveaways from "../components/Giveaways";
import Tags from "../components/Tags";
import Reports from "../components/Reports";
import Schedules from "../components/Schedules";
import Logs from "../components/Logs";
import VoiceGen from "../components/VoiceGen";
import Welcome from "../components/Welcome";
import Suggestions from "../components/Suggestions";
import AutoMod from "../components/AutoMod";
import AutoResponses from "../components/AutoResponses";
import CustomCommands from "../components/CustomCommands";
import { apiGet, apiPreload } from "../lib/api";
import CatLogo from "../components/CatLogo";
import { SaveBarProvider, useSaveBarState } from "../lib/SaveBarContext";

const PAGE_TITLES = {
  overview: "Resumen del Servidor",
  ia: "Inteligencia Artificial",
  radio: "Radio / Música",
  tickets: "Sistema de Tickets",
  moderation: "Moderación",
  embeds: "Creador de Embeds",
  levels: "Sistema de Niveles",
  autoroles: "Autoroles",
  giveaways: "Sorteos",
  tags: "Tags",
  reports: "Reportes",
  schedules: "Mensajes Programados",
  logs: "Registros",
  "voice-gen": "Canales de Voz Auto",
  welcome: "Bienvenidas & Boosters",
  suggestions: "Sugerencias",
  invites: "Invitaciones",
  automod: "Automoderación",
  autoresponses: "Auto-Respuestas",
  "custom-commands": "Comandos Personalizados"};

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
    <div className="loading-stage">
      <div className="loading-orb loading-orb--cat">
        <CatLogo size={56} />
      </div>
      <div className="loading-copy">
        <p className="topbar-eyebrow">Cats Bots — Panel de Control</p>
        <h1>Sincronizando el panel</h1>
        <p>Verificando sesión, servidores y módulos disponibles.</p>
      </div>
      <div className="loading-steps">
        <span>Auth</span>
        <span>Servidores</span>
        <span>Módulos</span>
      </div>
    </div>
  );
}

const GUILD_KEY_TB = "botES_guild_id";

function TopBar({
  activePage,
  mobileMenuOpen,
  setMobileMenuOpen,
  selectedGuild,
  user,
  requiresGuild,
  setShowLanding}) {
  const { dirty, saving, onSave, onRevert } = useSaveBarState();

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button
          className="mobile-only"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          style={{
            background: "none",
            border: "none",
            color: "#DBDEE1",
            fontSize: "1.4rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center"}}
        >
          <i className="fa-solid fa-bars" />
        </button>
        <div className="topbar-title-wrap">
          <p className="topbar-eyebrow">Cats Bots — Panel</p>
          <h1 style={{ margin: 0 }}>
            {PAGE_TITLES[activePage] || "Panel"}
          </h1>
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
              <i className="fa-solid fa-rotate-left" />
              <span>Descartar</span>
            </button>
            <button
              className="btn-primary btn-topbar-save"
              onClick={onSave}
              disabled={saving}
            >
              <i className="fa-solid fa-floppy-disk" />
              <span>{saving ? "Guardando…" : "Guardar"}</span>
            </button>
          </div>
        )}
        {selectedGuild && user && (
          <div
            className="mobile-guild-selector mobile-only"
            onClick={() => {
              localStorage.removeItem(GUILD_KEY_TB);
              setShowLanding(true);
            }}
          >
            <img
              src={
                user.allowedGuilds.find((g) => g.id === selectedGuild)
                  ?.icon || "https://cdn.discordapp.com/embed/avatars/0.png"
              }
              alt=""
            />
            <span>
              {user.allowedGuilds.find((g) => g.id === selectedGuild)
                ?.name || "Servidor"}
            </span>
          </div>
        )}
        {requiresGuild && (
          <button
            className="btn-icon"
            onClick={() => window.location.reload()}
            title="Recargar datos"
            aria-label="Recargar datos"
          >
            <i className="fa-solid fa-rotate-right" />
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
    username: cachedUser?.username || "Cargando...",
    avatar:
      cachedUser?.avatar || "https://cdn.discordapp.com/embed/avatars/0.png",
    allowedGuilds: cachedGuilds});
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
            profile.avatar || "https://cdn.discordapp.com/embed/avatars/0.png"};
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
    // Preload common data
    ["overview", "config", "radio", "ia"].forEach((s) =>
      apiPreload(`/api/guilds/${guildId}/${s}`),
    );
  };

  const requiresGuild = !["docs"].includes(activePage);

  if (loading) return <LoadingScreen />;

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
          {!showLanding && (!requiresGuild || selectedGuild) && (
            <>
              {activePage === "overview" && (
                <Overview selectedGuild={selectedGuild} />
              )}
              {activePage === "ia" && (
                <IAConfig selectedGuild={selectedGuild} />
              )}
              {activePage === "radio" && (
                <Radio selectedGuild={selectedGuild} />
              )}
              {activePage === "tickets" && (
                <Tickets selectedGuild={selectedGuild} />
              )}
              {activePage === "moderation" && (
                <Moderation selectedGuild={selectedGuild} />
              )}
              {activePage === "embeds" && (
                <EmbedBuilder selectedGuild={selectedGuild} />
              )}
              {activePage === "levels" && (
                <Levels selectedGuild={selectedGuild} />
              )}
              {activePage === "autoroles" && (
                <Autoroles selectedGuild={selectedGuild} />
              )}
              {activePage === "giveaways" && (
                <Giveaways selectedGuild={selectedGuild} />
              )}
              {activePage === "tags" && <Tags selectedGuild={selectedGuild} />}
              {activePage === "reports" && (
                <Reports selectedGuild={selectedGuild} />
              )}
              {activePage === "schedules" && (
                <Schedules selectedGuild={selectedGuild} />
              )}
              {activePage === "voice-gen" && (
                <VoiceGen selectedGuild={selectedGuild} />
              )}
              {activePage === "logs" && <Logs selectedGuild={selectedGuild} />}
              {activePage === "welcome" && (
                <Welcome selectedGuild={selectedGuild} />
              )}
              {activePage === "suggestions" && (
                <Suggestions selectedGuild={selectedGuild} />
              )}
              {activePage === "automod" && (
                <AutoMod selectedGuild={selectedGuild} />
              )}
              {activePage === "autoresponses" && (
                <AutoResponses selectedGuild={selectedGuild} />
              )}
              {activePage === "custom-commands" && (
                <CustomCommands selectedGuild={selectedGuild} />
              )}
            </>
          )}

          {!showLanding && requiresGuild && !selectedGuild && (
            <div className="dashboard-empty-state glass-panel">
              <div className="dashboard-empty-icon">
                <i className="fa-solid fa-building-shield" />
              </div>
              <h2>Selecciona un Servidor</h2>
              <p>
                Elige un servidor para ver sus configuraciones, estadísticas y
                módulos.
              </p>
              <button
                className="btn-primary"
                onClick={() => {
                  localStorage.removeItem(GUILD_KEY);
                  setShowLanding(true);
                }}
              >
                Elegir Servidor
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
    </SaveBarProvider>
  );
}
