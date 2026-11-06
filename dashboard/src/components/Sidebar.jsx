import { useState, useRef, useEffect } from "react";
import { ICONS } from "../lib/icons";
import CatLogo from "./CatLogo";
import { useSaveBarState } from "../lib/SaveBarContext";

const NAV_SECTIONS = [
  {
    label: "General",
    items: [
      { id: "overview", icon: ICONS.overview, label: "Resumen" },
      { id: "endpoints", icon: ICONS.server, label: "Endpoints" },
    ]},
  {
    label: "Moderación",
    items: [
      { id: "moderation", icon: ICONS.moderation, label: "Moderación" },
      { id: "channel-settings", icon: ICONS.channel, label: "Ajustes por canal" },
      { id: "automod", icon: ICONS.automod, label: "Automoderación" },
      { id: "logs", icon: ICONS.logs, label: "Registros" },
    ]},
  {
    label: "Módulos",
    items: [
      { id: "ia", icon: ICONS.ia, label: "Inteligencia Artificial" },
      { id: "radio", icon: ICONS.radio, label: "Radio / Música" },
      { id: "voice-gen", icon: ICONS.voiceGen, label: "Generador de VCs" },
      { id: "tickets", icon: ICONS.tickets, label: "Tickets" },
      { id: "levels", icon: ICONS.levels, label: "Niveles" },
      { id: "giveaways", icon: ICONS.giveaways, label: "Sorteos" },
    ]},
  {
    label: "Automatización",
    items: [
      { id: "autoroles", icon: ICONS.autoroles, label: "Autoroles" },
      { id: "autoresponses", icon: ICONS.autoresponses, label: "Auto-Respuestas" },
      { id: "autoreactions", icon: "fa-face-smile", label: "Autorreacciones" },
      { id: "custom-commands", icon: ICONS.customCommands, label: "Comandos Custom" },
    ]},
  {
    label: "Herramientas",
    items: [
      { id: "embeds", icon: ICONS.embeds, label: "Creador de Embeds" },
      { id: "reports", icon: ICONS.reports, label: "Reportes" },
      { id: "tags", icon: ICONS.tags, label: "Tags" },
      { id: "schedules", icon: ICONS.schedules, label: "Horarios" },
      { id: "welcome", icon: ICONS.welcome, label: "Mensajes" },
      { id: "suggestions", icon: ICONS.suggestions, label: "Sugerencias" },
    ]},
];

const getGuildIcon = (guild) => {
  if (!guild?.icon) return null;
  if (guild.icon.startsWith("http")) return guild.icon;
  return `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`;
};

export default function Sidebar({ user, selectedGuild, onSelectGuild, activePage, setActivePage, mobileMenuOpen, setMobileMenuOpen }) {
  const { requestNavigation, saving } = useSaveBarState();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [expanded, setExpanded] = useState(["General", "Moderación"]);
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 1023px)").matches);
  const dropdownRef = useRef(null);
  const sidebarRef = useRef(null);
  const closeRef = useRef(null);
  const currentGuild = user?.allowedGuilds?.find((g) => g.id === selectedGuild);
  const close = () => setMobileMenuOpen(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const update = () => { setMobile(media.matches); if (!media.matches) setMobileMenuOpen(false); };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [setMobileMenuOpen]);

  useEffect(() => {
    if (!mobileMenuOpen || !mobile) return;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const handleKey = (event) => {
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") { setMobileMenuOpen(false); return; }
      if (event.key !== "Tab") return;
      const buttons = [...sidebarRef.current.querySelectorAll('button:not(:disabled), a[href]')].filter((element) => element.getClientRects().length);
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, [mobileMenuOpen, mobile, setMobileMenuOpen]);

  useEffect(() => {
    const outside = (event) => { if (!dropdownRef.current?.contains(event.target)) setDropdownOpen(false); };
    const escape = (event) => { if (event.key === "Escape") setDropdownOpen(false); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, []);

  const logout = async () => {
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "include", headers: { Accept: "application/json" } }); }
    finally {
      localStorage.removeItem("botES_token"); localStorage.removeItem("botES_guild_id");
      sessionStorage.removeItem("botES_guilds_cache"); sessionStorage.removeItem("botES_user_cache");
      window.location.href = "/";
    }
  };

  return (
    <>
      {mobileMenuOpen && mobile && <button className="sidebar-scrim" aria-label="Cerrar menú" tabIndex={-1} onClick={close} />}
      <nav ref={sidebarRef} id="dashboard-navigation" aria-label="Panel del servidor" className={`sidebar ${mobileMenuOpen ? "mobile-open" : ""}`} inert={mobile && !mobileMenuOpen}>
        <div className="sidebar-header dashboard-sidebar-header">
          <a className="sidebar-brand-block sidebar-brand-row" href="/panel/dashboard" onClick={(event) => { event.preventDefault(); setActivePage("overview"); }}>
            <CatLogo size={42} /><span className="brand-text-glow">Cat's Bot</span>
          </a>
          <button ref={closeRef} className="btn-icon mobile-only" aria-label="Cerrar menú" onClick={close}><i className="fa-solid fa-xmark" aria-hidden="true" /></button>
        </div>
        <div className="guild-picker" ref={dropdownRef}>
          <button className="guild-selector" aria-expanded={dropdownOpen} aria-controls="guild-options" disabled={saving} onClick={() => setDropdownOpen(!dropdownOpen)}>
            {getGuildIcon(currentGuild) ? <img src={getGuildIcon(currentGuild)} alt="" className="guild-icon" /> : <span className="guild-icon guild-initial">{currentGuild?.name?.slice(0, 2).toUpperCase() || "#"}</span>}
            <span className="guild-selector-copy"><strong>{currentGuild?.name || "Selecciona un servidor"}</strong><small>Tu servidor</small></span>
            <i className="fa-solid fa-chevron-down" aria-hidden="true" />
          </button>
          {dropdownOpen && <div id="guild-options" className="guild-dropdown active" aria-label="Servidores disponibles">
            {(user?.allowedGuilds || []).map((guild) => <button key={guild.id} className="guild-option" aria-pressed={guild.id === selectedGuild} onClick={() => { onSelectGuild(guild.id); setDropdownOpen(false); }}>
              {getGuildIcon(guild) ? <img src={getGuildIcon(guild)} className="guild-icon" alt="" /> : <span className="guild-icon guild-initial">{guild.name?.slice(0, 2).toUpperCase()}</span>}
              <span>{guild.name}</span>{guild.id === selectedGuild && <i className="fa-solid fa-check" aria-hidden="true" />}
            </button>)}
          </div>}
        </div>
        <div className="sidebar-sections">
          {NAV_SECTIONS.map((section) => {
            const isOpen = expanded.includes(section.label) || section.items.some((item) => item.id === activePage);
            return <section className="sidebar-section" key={section.label}>
              <button className="sidebar-section-label" aria-expanded={isOpen} aria-controls={`nav-${section.label}`} onClick={() => setExpanded((current) => current.includes(section.label) ? current.filter((label) => label !== section.label) : [...current, section.label])}>
                {section.label}<i className={`fa-solid fa-chevron-${isOpen ? "up" : "down"}`} aria-hidden="true" />
              </button>
              {isOpen && <ul className="nav-links" id={`nav-${section.label}`}>
                {section.items.map((item) => <li key={item.id} className={activePage === item.id ? "active" : ""}>
                  <button type="button" aria-current={activePage === item.id ? "page" : undefined} disabled={saving} onClick={() => setActivePage(item.id)}><i className={`fa-solid ${item.icon}`} aria-hidden="true" /><span>{item.label}</span></button>
                </li>)}
              </ul>}
            </section>;
          })}
        </div>
        <div className="user-profile">
          <img src={user?.avatar || "https://cdn.discordapp.com/embed/avatars/0.png"} alt="" className="user-avatar" />
          <div className="user-info"><h4>{user?.username || "Usuario Discord"}</h4><button className="logout-btn" disabled={saving} onClick={() => requestNavigation(logout)}>Cerrar sesión</button></div>
        </div>
      </nav>
    </>
  );
}
