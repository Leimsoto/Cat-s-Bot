import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";

export default function Overview({ selectedGuild }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!selectedGuild) return;
    setLoading(true);
    apiGet(`/api/guilds/${selectedGuild}/overview`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [selectedGuild]);

  if (loading)
    return (
      <div className="overview-loading">
        <div className="loading-spinner" />
        <p>Cargando estadísticas...</p>
      </div>
    );
  if (!data)
    return (
      <div className="overview-loading">
        <i
          className="fa-solid fa-triangle-exclamation"
          style={{ fontSize: "2rem", color: "#f59e0b", marginBottom: "12px" }}
        />
        <p>No se pudieron cargar las estadísticas. Recarga la página.</p>
      </div>
    );

  const metrics = data.metrics || {};
  const server = data.server || {};
  const charts = data.charts || [];
  const maxVal = Math.max(
    ...charts.flatMap((p) => [
      p.commands || 0,
      p.automod || 0,
      p.security || 0,
      p.moderation || 0,
    ]),
    1,
  );
  const series = [
    ["commands", "Comandos", "#38bdf8"],
    ["automod", "AutoMod", "#34d399"],
    ["security", "Seguridad", "#f97316"],
    ["moderation", "Moderación", "#a78bfa"],
  ];

  return (
    <div className="ov-container">
      <div className="ov-stats-grid">
        {[
          [
            "fa-terminal",
            "Comandos",
            metrics.totalCommands || 0,
            "rgba(56,189,248,0.12)",
            "#38bdf8",
          ],
          [
            "fa-shield-halved",
            "AutoMod",
            metrics.automodTriggers || 0,
            "rgba(103,232,249,0.12)",
            "#67e8f9",
          ],
          [
            "fa-gavel",
            "Acciones de Mod.",
            metrics.moderationActions || 0,
            "rgba(245,158,11,0.12)",
            "#f59e0b",
          ],
          [
            "fa-lock",
            "Alertas de Seguridad",
            metrics.securityAlerts || 0,
            "rgba(239,68,68,0.12)",
            "#ef4444",
          ],
          [
            "fa-users",
            "Miembros",
            server.memberCount || 0,
            "rgba(99,102,241,0.12)",
            "#818cf8",
          ],
          [
            "fa-circle",
            "En línea",
            server.onlineCount || 0,
            "rgba(16,185,129,0.12)",
            "#10b981",
          ],
          [
            "fa-bolt-lightning",
            "Nivel de Boost",
            `Nivel ${server.boostLevel || 0}${server.boostCount ? ` · ${server.boostCount} boosts` : ""}`,
            "rgba(245,158,11,0.12)",
            "#f59e0b",
          ],
        ].map(([icon, label, value, bg, color]) => (
          <div key={label} className="ov-stat-card glass-panel">
            <div className="ov-stat-icon" style={{ background: bg, color }}>
              <i className={`fa-solid ${icon}`} />
            </div>
            <div className="ov-stat-info">
              <span className="ov-stat-label">{label}</span>
              <span className="ov-stat-value">{value}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="ov-charts-row">
        <div className="ov-chart-card glass-panel">
          <div className="ov-chart-header">
            <div>
              <h3>Actividad de 7 días</h3>
              <p className="ov-subtitle">
                Comandos, moderación, automod y seguridad
              </p>
            </div>
            <div className="ov-chart-badge">
              <i className="fa-solid fa-arrow-trend-up" />
              <span>7d</span>
            </div>
          </div>
          <div className="pogy-bars">
            {charts.map((point) => (
              <div key={point.label} className="pogy-bar-day">
                <div className="pogy-bar-stack">
                  {series.map(([key, lbl, color]) => (
                    <span
                      key={key}
                      className="pogy-bar"
                      style={{
                        height: `${Math.max(((point[key] || 0) / maxVal) * 100, 4)}%`,
                        "--bar-color": color}}
                      title={`${point.label} ${lbl}: ${point[key] || 0}`}
                    />
                  ))}
                </div>
                <span>{point.label}</span>
              </div>
            ))}
          </div>
          <div className="pogy-chart-legend">
            {series.map(([key, lbl, color]) => (
              <span key={key} style={{ "--legend-color": color }}>
                <i />
                {lbl}
              </span>
            ))}
          </div>
        </div>

        <div className="ov-chart-card glass-panel">
          <div className="ov-chart-header">
            <div>
              <h3>Resumen de Protección</h3>
              <p className="ov-subtitle">Actividad del período actual</p>
            </div>
          </div>
          <div
            className="ov-ai-footer"
            style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}
          >
            {[
              [
                "fa-terminal",
                `${metrics.totalCommands || 0} comandos ejecutados`,
              ],
              ["fa-shield", `${metrics.automodTriggers || 0} alertas automod`],
              [
                "fa-lock",
                `${metrics.securityAlerts || 0} alertas de seguridad`,
              ],
              [
                "fa-gavel",
                `${metrics.moderationActions || 0} acciones de moderación`,
              ],
              [
                "fa-users",
                `${server.memberCount || 0} miembros en el servidor`,
              ],
              [
                "fa-bolt-lightning",
                `Boost nivel ${server.boostLevel || 0}${server.boostCount ? ` (${server.boostCount} boosts)` : ""}`,
              ],
            ].map(([icon, text]) => (
              <div key={text} className="ov-ai-footer-item">
                <i className={`fa-solid ${icon}`} />
                <span>{text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ov-bottom-row">
        <div className="ov-activity-card glass-panel">
          <div className="ov-chart-header">
            <h3>Eventos Recientes</h3>
            <span className="ov-activity-count">
              {data.recentEvents?.length || 0} eventos
            </span>
          </div>
          <div className="ov-activity-list">
            {(data.recentEvents || []).map((e, i) => (
              <div key={i} className="ov-activity-item">
                <div
                  className="ov-activity-badge"
                  style={{
                    background: "rgba(56,189,248,0.12)",
                    color: "#38bdf8"}}
                >
                  <i className="fa-solid fa-bolt" />
                </div>
                <div className="ov-activity-info">
                  <div className="ov-activity-top">
                    <span className="ov-activity-action">{e.type}</span>
                  </div>
                  <span className="ov-activity-target">{e.summary}</span>
                  <span className="ov-activity-time">
                    {new Date(e.createdAt).toLocaleString("es")}
                  </span>
                </div>
              </div>
            ))}
            {!data.recentEvents?.length && (
              <div className="empty-mini">Sin eventos recientes.</div>
            )}
          </div>
        </div>

        <div className="ov-ai-card glass-panel">
          <div className="ov-ai-header">
            <div className="ov-ai-title-row">
              <div className="ov-ai-icon-wrap">
                <i className="fa-solid fa-gavel" />
              </div>
              <div>
                <h3>Casos de Moderación</h3>
                <p className="ov-subtitle">Historial reciente</p>
              </div>
            </div>
          </div>
          <div className="ov-activity-list">
            {(data.recentCases || []).map((e, i) => (
              <div key={i} className="ov-activity-item">
                <div
                  className="ov-activity-badge"
                  style={{
                    background: "rgba(245,158,11,0.12)",
                    color: "#f59e0b"}}
                >
                  <i className="fa-solid fa-folder-open" />
                </div>
                <div className="ov-activity-info">
                  <div className="ov-activity-top">
                    <span className="ov-activity-action">Caso #{e.caseId}</span>
                    <span className="ov-activity-target">{e.action}</span>
                  </div>
                  <span className="ov-activity-target">{e.userId}</span>
                  <span className="ov-activity-time">
                    {new Date(e.date).toLocaleString("es")}
                  </span>
                </div>
              </div>
            ))}
            {!data.recentCases?.length && (
              <div className="empty-mini">Sin casos recientes.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
