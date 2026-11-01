import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import { Icon } from "../lib/icons";
import "./DashboardPanels.css";

const SERIES = [
  ["commands", "Comandos", "var(--accent)"],
  ["automod", "AutoMod", "var(--success, #91d6b0)"],
  ["security", "Seguridad", "var(--danger, #efa1b1)"],
  ["moderation", "Moderación", "var(--warning, #edc37d)"],
];

export default function Overview({ selectedGuild, onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [visible, setVisible] = useState(SERIES.map(([key]) => key));

  useEffect(() => {
    let current = true;
    setLoading(true);
    setData(null);
    if (!selectedGuild) { setLoading(false); return; }
    apiGet(`/api/guilds/${selectedGuild}/overview`, { cache: retry === 0 })
      .then((result) => { if (current) setData(result); })
      .catch(() => { if (current) setData(null); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [selectedGuild, retry]);

  if (loading) return <div className="cr-page cr-loading" role="status"><div className="loading-spinner" /><p>Cargando la actividad de tu comunidad…</p></div>;
  if (!data) return <div className="cr-page cr-empty" role="alert"><Icon name="warning" /><h2>No pudimos cargar el resumen</h2><p>Vuelve a intentarlo para ver la actividad del servidor.</p><button className="btn-secondary" onClick={() => setRetry((value) => value + 1)}>Reintentar</button></div>;

  const metrics = data.metrics || {};
  const server = data.server || {};
  const charts = data.charts || [];
  const maximum = Math.max(1, ...charts.flatMap((point) => SERIES.filter(([key]) => visible.includes(key)).map(([key]) => point[key] || 0)));
  const statItems = [
    ["users", "Miembros", server.memberCount ?? 0, `${server.onlineCount ?? 0} en línea`],
    ["customCommands", "Comandos", metrics.totalCommands ?? 0, "Actividad registrada"],
    ["automod", "AutoMod", metrics.automodTriggers ?? 0, "Acciones registradas"],
    ["moderation", "Moderación", metrics.moderationActions ?? 0, "Acciones registradas"],
  ];

  return <div className="cr-page cr-overview">
    <header className="cr-heading"><div><span className="cr-eyebrow">Tu comunidad</span><h1>{server.name || "Resumen del servidor"}</h1><p>Lo que pasa en tu comunidad, a primera vista.</p></div></header>
    <section className="cr-brand-band"><div><h2>Tu comunidad tiene quien la cuide.</h2><p>Revisa tus reglas, recibe a los nuevos y dale espacio a cada conversación.</p>{onNavigate && <button className="btn-primary" onClick={() => onNavigate("automod")}><Icon name="automod" /> Revisar protección <Icon name="arrowRight" /></button>}</div><img src={`${import.meta.env.BASE_URL}logo.png`} alt="Gato original de Cat's Bot con auricular" /></section>
    <div className="cr-metric-strip">{statItems.map(([icon, label, value, context]) => <div className="cr-metric" key={label}><span><Icon name={icon} />{label}</span><strong>{Number(value).toLocaleString("es")}</strong><small>{context}</small></div>)}</div>
    <div className="cr-overview-middle">
      <section className="cr-activity"><header className="cr-section-heading"><div><h2>El pulso del servidor</h2><p>Actividad de los últimos 7 días</p></div></header>
        {charts.length ? <div className="cr-chart" role="img" aria-label="Actividad diaria de comandos, AutoMod, seguridad y moderación"><div className="cr-chart-scale"><span>{maximum}</span><span>{Math.round(maximum / 2)}</span><span>0</span></div><div className="cr-chart-days">{charts.map((point, index) => <div className="cr-chart-day" key={`${point.label}-${index}`}><div className="cr-chart-bars">{SERIES.filter(([key]) => visible.includes(key)).map(([key, label, color]) => <span key={key} style={{ height: `${((point[key] || 0) / maximum) * 100}%`, "--cr-series": color }} aria-label={`${point.label}: ${point[key] || 0} ${label}`} title={`${point.label}: ${point[key] || 0} ${label}`} />)}</div><span>{point.label}</span></div>)}</div></div> : <p className="cr-empty-inline">Todavía no hay actividad para mostrar en este período.</p>}
        <div className="cr-chart-legend">{SERIES.map(([key, label, color]) => <button key={key} type="button" aria-pressed={visible.includes(key)} onClick={() => setVisible((values) => values.includes(key) ? values.filter((value) => value !== key) : [...values, key])}><i style={{ background: color }} />{label}</button>)}</div>
      </section>
      <section><header className="cr-section-heading"><h2>Lo último que pasó</h2><span>{data.recentEvents?.length || 0} eventos</span></header><div className="cr-event-list">{(data.recentEvents || []).map((event, index) => <article className="cr-event" key={event.id || index}><span className="cr-row-icon"><Icon name="logs" /></span><div><h3>{event.type}</h3><p>{event.summary}</p><small>{event.createdAt ? new Date(event.createdAt).toLocaleString("es") : "Fecha no disponible"}</small></div></article>)}{!data.recentEvents?.length && <p className="cr-empty-inline">Sin eventos recientes. Aquí aparecerá la próxima actividad registrada.</p>}</div></section>
    </div>
    <div className="cr-overview-bottom"><section><header className="cr-section-heading"><h2>Tu servidor, a tu manera</h2></header>{[["automod", "Automoderación", "Reglas, excepciones y registro de acciones", "Ajustar"], ["welcome", "Bienvenidas", "Mensajes, boosters e invitaciones", "Editar"], ["tickets", "Tickets", "Categorías, plantillas y atención privada", "Configurar"]].map(([id, title, description, action]) => <div className="cr-module-row" key={id}><span className="cr-row-icon"><Icon name={id} /></span><div><h3>{title}</h3><p>{description}</p></div>{onNavigate && <button className="cr-text-button" onClick={() => onNavigate(id)}>{action}<Icon name="arrowRight" /></button>}</div>)}<div className="cr-server-facts"><span><Icon name="lock" />{metrics.securityAlerts ?? 0} alertas de seguridad</span><span><Icon name="giveaways" />Boost nivel {server.boostLevel ?? 0} · {server.boostCount ?? 0} boosts</span></div></section>
      <section><header className="cr-section-heading"><h2>Casos de moderación</h2><span>Historial reciente</span></header>{(data.recentCases || []).map((entry, index) => <article className="cr-event" key={entry.caseId || index}><span className="cr-row-icon"><Icon name="moderation" /></span><div><h3>Caso #{entry.caseId} · {entry.action}</h3><p>{entry.userId}</p><small>{entry.date ? new Date(entry.date).toLocaleString("es") : "Fecha no disponible"}</small></div></article>)}{!data.recentCases?.length && <p className="cr-empty-inline">Sin casos recientes.</p>}</section></div>
  </div>;
}
