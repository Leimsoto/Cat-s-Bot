import { useState, useRef, useEffect } from "react";
import { ICONS } from "../lib/icons";
import CatLogo from "./CatLogo";

const NAV_SECTIONS = [
  {
    label: "General",
    items: [
      { id: "overview", icon: ICONS.overview, label: "Resumen" },
      { id: "moderation", icon: ICONS.moderation, label: "Moderación" },
      { id: "logs", icon: ICONS.logs, label: "Registros" },
    ],
  },
  {
    label: "Módulos",
    items: [
      { id: "ia", icon: ICONS.ia, label: "Inteligencia Artificial" },
      { id: "radio", icon: ICONS.radio, label: "Radio / Música" },
      { id: "voice-gen", icon: ICONS.voiceGen, label: "Generador de VCs" },
      { id: "tickets", icon: ICONS.tickets, label: "Tickets" },
      { id: "levels", icon: ICONS.levels, label: "Niveles" },
      { id: "autoroles", icon: ICONS.autoroles, label: "Autoroles" },
      { id: "giveaways", icon: ICONS.giveaways, label: "Sorteos" },
      { id: "tags", icon: ICONS.tags, label: "Tags" },
    ],
  },
  {
    label: "Herramientas",
    items: [
      { id: "embeds", icon: ICONS.embeds, label: "Creador de Embeds" },
      { id: "reports", icon: ICONS.reports, label: "Reportes" },
      { id: "schedules", icon: ICONS.schedules, label: "Horarios" },
      { id: "welcome", icon: ICONS.welcome, label: "Bienvenidas e Invitaciones" },
      { id: "suggestions", icon: ICONS.suggestions, label: "Sugerencias" },
    ],
  },
];

const getGuildIcon = (guild) => {
  if (!guild?.icon) return null;
  if (guild.icon.startsWith("http")) return guild.icon;
  return `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`;
};

export default function Sidebar({
  user,
  selectedGuild,
  onSelectGuild,
  activePage,
  setActivePage,
  mobileMenuOpen,
  setMobileMenuOpen,
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const currentGuild = user?.allowedGuilds?.find((g) => g.id === selectedGuild);

  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target))
        setDropdownOpen(false);
    };
    const keyHandler = (e) => {
      if (e.key === "Escape") {
        setDropdownOpen(false);
        if (typeof setMobileMenuOpen === "function") setMobileMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", keyHandler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", keyHandler);
    };
  }, [setMobileMenuOpen]);

  const handleLogout = () => {
    localStorage.removeItem("botES_token");
    window.location.href = "/";
  };

  const close = () => {
    if (typeof setMobileMenuOpen === "function") setMobileMenuOpen(false);
  };

  return (
    <nav className={`sidebar ${mobileMenuOpen ? "mobile-open" : ""}`}>
      <div
        className="sidebar-header dashboard-sidebar-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          width: "100%",
        }}
      >
        <div className="sidebar-brand-block sidebar-brand-row">
          <CatLogo size={38} ariaLabel="Cats Bots" />
          <div>
            <p className="sidebar-kicker">Panel de Control</p>
            <h2 className="brand-text-glow">Cats Bots</h2>
          </div>
        </div>
        <button
          className="btn-icon mobile-only"
          onClick={close}
          style={{
            background: "none",
            border: "none",
            color: "#DBDEE1",
            fontSize: "1.2rem",
            cursor: "pointer",
          }}
        >
          <i className="fa-solid fa-xmark" />
        </button>
      </div>

      <div
        className="guild-selector"
        ref={dropdownRef}
        onClick={() => setDropdownOpen(!dropdownOpen)}
      >
        <img
          src={
            getGuildIcon(currentGuild) ||
            "https://cdn.discordapp.com/embed/avatars/0.png"
          }
          alt=""
          className="guild-icon"
        />
        <span className="guild-name">
          {currentGuild?.name || "Selecciona un servidor"}
        </span>
        <i className="fa-solid fa-chevron-down" />
        <div className={`guild-dropdown ${dropdownOpen ? "active" : ""}`}>
          {(user?.allowedGuilds || []).map((g) => (
            <div
              key={g.id}
              className="guild-option"
              onClick={(e) => {
                e.stopPropagation();
                onSelectGuild(g.id);
                setDropdownOpen(false);
                close();
              }}
            >
              {getGuildIcon(g) ? (
                <img src={getGuildIcon(g)} className="guild-icon" alt="" />
              ) : (
                <div
                  className="guild-icon"
                  style={{
                    background: "#5865F2",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  #
                </div>
              )}
              <span className="guild-name">{g.name}</span>
              {g.memberCount && (
                <span
                  style={{
                    fontSize: "0.72rem",
                    color: "var(--muted)",
                    marginLeft: "auto",
                  }}
                >
                  {g.memberCount} miembros
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {NAV_SECTIONS.map((section) => (
        <div key={section.label}>
          <div className="sidebar-section-label">{section.label}</div>
          <ul className="nav-links">
            {section.items.map((item) => (
              <li
                key={item.id}
                className={activePage === item.id ? "active" : ""}
                onClick={() => {
                  setActivePage(item.id);
                  close();
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    setActivePage(item.id);
                    close();
                  }
                }}
              >
                <i className={`fa-solid ${item.icon}`} />
                <span>{item.label}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="user-profile" style={{ marginTop: "auto" }}>
        <img
          src={user?.avatar || "https://cdn.discordapp.com/embed/avatars/0.png"}
          alt=""
          className="user-avatar"
        />
        <div className="user-info">
          <h4>{user?.username || "Cargando..."}</h4>
          <span className="logout-btn" onClick={handleLogout}>
            Cerrar sesión
          </span>
        </div>
      </div>
    </nav>
  );
}
