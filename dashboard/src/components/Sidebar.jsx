import { useState, useRef, useEffect } from "react";

const NAV_SECTIONS = [
  {
    label: "General",
    items: [
      { id: "overview", icon: "fa-chart-pie", label: "Resumen" },
      { id: "moderation", icon: "fa-gavel", label: "Moderación" },
      { id: "logs", icon: "fa-stream", label: "Registros" },
    ],
  },
  {
    label: "Módulos",
    items: [
      { id: "ia", icon: "fa-brain", label: "Inteligencia Artificial" },
      { id: "radio", icon: "fa-radio", label: "Radio / Música" },
      { id: "voice-gen", icon: "fa-headphones", label: "Canales de Voz Auto" },
      { id: "tickets", icon: "fa-ticket", label: "Tickets" },
      { id: "levels", icon: "fa-star", label: "Niveles" },
      { id: "autoroles", icon: "fa-user-plus", label: "Autoroles" },
      { id: "giveaways", icon: "fa-gift", label: "Sorteos" },
      { id: "tags", icon: "fa-tags", label: "Tags" },
      { id: "invites", icon: "fa-paper-plane", label: "Invitaciones" },
    ],
  },
  {
    label: "Herramientas",
    items: [
      { id: "embeds", icon: "fa-palette", label: "Creador de Embeds" },
      { id: "reports", icon: "fa-flag", label: "Reportes" },
      { id: "schedules", icon: "fa-clock", label: "Horarios" },
      { id: "welcome", icon: "fa-hand-wave", label: "Bienvenidas" },
      { id: "suggestions", icon: "fa-lightbulb", label: "Sugerencias" },
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
    window.location.href = "/panel/login";
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
        <div className="sidebar-brand-block">
          <p className="sidebar-kicker">Panel de Control</p>
          <h2 className="brand-text-glow">BOT ES</h2>
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
