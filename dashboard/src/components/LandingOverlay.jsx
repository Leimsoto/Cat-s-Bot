import { useEffect, useRef } from "react";
import CatLogo from "./CatLogo";

export default function LandingOverlay({ guilds, onSelectGuild, onDismiss }) {
  const dialogRef = useRef(null);
  useEffect(() => { dialogRef.current?.showModal(); }, []);
  const guildIcon = (guild) => guild.icon?.startsWith("http") ? guild.icon : guild.icon ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64` : null;
  return (
    <dialog ref={dialogRef} className="server-picker" aria-labelledby="server-picker-title" onCancel={(event) => { event.preventDefault(); onDismiss?.(); }}>
      <div className="server-picker-head"><CatLogo size={52} /><div><h2 id="server-picker-title">Tu comunidad, en un lugar</h2><p>Elige el servidor que quieres configurar.</p></div>{onDismiss && <button className="btn-icon server-picker-close" aria-label="Cerrar selector" onClick={onDismiss}><i className="fa-solid fa-xmark" aria-hidden="true" /></button>}</div>
      {guilds.length === 0 ? <div className="dashboard-empty-state"><h3>Sin servidores disponibles</h3><p>Cat's Bot aún no está en ninguno de tus servidores de administrador.</p><a href={`https://discord.com/oauth2/authorize?client_id=${import.meta.env.VITE_DISCORD_CLIENT_ID || ""}&permissions=8&scope=bot+applications.commands`} className="btn-primary" target="_blank" rel="noreferrer">Invitar a Cat's Bot <i className="fa-solid fa-arrow-up-right-from-square" aria-hidden="true" /></a></div> : <div className="server-picker-list">{guilds.map((guild) => <button className="server-picker-option" key={guild.id} onClick={() => onSelectGuild(guild.id)}>{guildIcon(guild) ? <img src={guildIcon(guild)} alt="" /> : <span className="server-picker-initial">{guild.name?.slice(0, 2).toUpperCase()}</span>}<span className="server-picker-option-copy"><strong>{guild.name}</strong>{guild.memberCount > 0 && <small>{guild.memberCount.toLocaleString("es")} miembros</small>}</span><i className="fa-solid fa-arrow-right" aria-hidden="true" /></button>)}</div>}
    </dialog>
  );
}
