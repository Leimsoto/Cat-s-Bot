import "./DashboardPanels.css";

export default function IdentityBadge({ item, prefix = "target", compact = false }) {
  const user = item?.[`${prefix}_user`] || item?.user || {};
  const id = user.id || item?.[`${prefix}_id`] || (prefix !== "moderator" ? item?.user_id : null);
  const display = item?.[`${prefix}_display`] || user.display || user.name || item?.[`${prefix}_tag`] || user.tag || (id ? "Usuario desconocido" : "—");
  const tag = item?.[`${prefix}_tag`] || user.tag;
  const avatar = item?.[`${prefix}_avatar_url`] || user.avatar_url;
  return <div className={`cr-identity${compact ? " cr-identity-compact" : ""}`}>
    <span className="cr-identity-avatar">{display.slice(0, 1).toUpperCase()}{avatar && <img key={avatar} src={avatar} alt="" onError={(event) => { event.currentTarget.hidden = true; }} />}</span>
    <div><strong>{display}</strong>{tag && tag !== display && <span>{tag}</span>}{id && <code>UID: {id}</code>}</div>
  </div>;
}
