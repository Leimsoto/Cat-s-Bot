/**
 * components/Welcome.jsx
 * ──────────────────────
 * Hub unificado de Bienvenidas + Boosters + Invitaciones (merge Fase 12).
 *
 * Tabs:
 *   • Bienvenidas — canal + toggle. Embed se diseña con /configurar bienvenidas.
 *   • Boosters    — canal + GIF + toggle. Embed se diseña con /configurar boosters.
 *   • Invitaciones — canal de log + toggle + leaderboard top 20.
 *
 * Endpoints:
 *   GET  /api/guilds/{g}/welcome
 *   PATCH /api/guilds/{g}/welcome
 *   PATCH /api/guilds/{g}/welcome/boost
 *   PATCH /api/guilds/{g}/welcome/invites
 *   GET  /api/guilds/{g}/invites          (leaderboard enriquecido)
 */

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";
import { useSaveBar } from "../lib/SaveBarContext";

const TABS = [
  { id: "welcome", label: "Bienvenidas", icon: "welcome" },
  { id: "boost", label: "Boosters", icon: "giveaways" },
  { id: "invites", label: "Invitaciones", icon: "invites" },
];

export default function Welcome({ selectedGuild: guildId, onToast }) {
  const [tab, setTab] = useState("welcome");
  const [data, setData] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const wData = await apiGet(`/api/guilds/${guildId}/welcome`);
      setData(wData);
      // Leaderboard sólo cuando se mire la pestaña, pero pre-cargamos en background
      const iData = await apiGet(`/api/guilds/${guildId}/invites`, { cache: false }).catch(() => ({ leaderboard: [] }));
      setLeaderboard(iData?.leaderboard || []);
    } catch {
      toast("error", "Error cargando configuración");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!data) return;
    setSaving(true);
    try {
      if (tab === "welcome") {
        await apiPatch(`/api/guilds/${guildId}/welcome`, data.welcome || {});
      } else if (tab === "boost") {
        await apiPatch(`/api/guilds/${guildId}/welcome/boost`, data.boost || {});
      } else if (tab === "invites") {
        await apiPatch(`/api/guilds/${guildId}/welcome/invites`, data.invites || {});
      }
      setDirty(false);
      toast("success", "Configuración guardada");
    } catch (e) {
      toast("error", e?.message || "Error guardando");
    } finally {
      setSaving(false);
    }
  };

  const setW = (k, v) => { setData((p) => ({ ...p, welcome: { ...(p?.welcome || {}), [k]: v } })); setDirty(true); };
  const setB = (k, v) => { setData((p) => ({ ...p, boost: { ...(p?.boost || {}), [k]: v } })); setDirty(true); };
  const setI = (k, v) => { setData((p) => ({ ...p, invites: { ...(p?.invites || {}), [k]: v } })); setDirty(true); };

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading) return <div className="loader">Cargando bienvenidas…</div>;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header">
        <h2 className="glow-text" style={{ margin: 0 }}>Bienvenidas, Boosters & Invitaciones</h2>
        <p className="subtitle" style={{ margin: "4px 0 0" }}>
          Configura los mensajes de entrada, agradecimiento a boosters y el canal de log de invitaciones.
        </p>
      </div>

      <div className="tab-bar">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab-btn ${tab === t.id ? "active" : ""}`}
            onClick={() => { setTab(t.id); setDirty(false); }}
          >
            <Icon name={t.icon} /> {t.label}
          </button>
        ))}
      </div>

      {tab === "welcome" && data?.welcome && (
        <div className="glass-panel mod-section" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="config-item inline-check">
            <div>
              <div style={{ fontWeight: 800 }}>Sistema de Bienvenidas</div>
              <div className="hint">Envía un mensaje cuando alguien se une al servidor</div>
            </div>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!data.welcome.enabled}
                onChange={(e) => setW("enabled", e.target.checked ? 1 : 0)}
              />
              <span className="slider" />
            </label>
          </div>
          <div className="form-field">
            <label>Canal de bienvenidas</label>
            <SearchableSelect
              value={data.welcome.channel_id || null}
              onChange={(v) => setW("channel_id", v ? Number(v) : null)}
              endpoint={`/api/guilds/${guildId}/channels?type=text`}
              itemsKey="channels"
              placeholder="Seleccionar canal…"
              renderOption={(o) => <span>#{o.name}</span>}
              renderSelected={(o) => <span>#{o.name}</span>}
            />
          </div>
          <div className="callout">
            <Icon name="info" /> El embed se configura con <code>/configurar bienvenidas</code>.
            Variables: <code>{"{user}"}</code>, <code>{"{server}"}</code>, <code>{"{count}"}</code>.
          </div>
        </div>
      )}

      {tab === "boost" && data?.boost && (
        <div className="glass-panel mod-section" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="config-item inline-check">
            <div>
              <div style={{ fontWeight: 800 }}>Agradecimiento a Boosters</div>
              <div className="hint">Envía un mensaje cuando alguien hace boost</div>
            </div>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!data.boost.enabled}
                onChange={(e) => setB("enabled", e.target.checked ? 1 : 0)}
              />
              <span className="slider" />
            </label>
          </div>
          <div className="form-field">
            <label>Canal de boosters</label>
            <SearchableSelect
              value={data.boost.channel_id || null}
              onChange={(v) => setB("channel_id", v ? Number(v) : null)}
              endpoint={`/api/guilds/${guildId}/channels?type=text`}
              itemsKey="channels"
              placeholder="Seleccionar canal…"
              renderOption={(o) => <span>#{o.name}</span>}
              renderSelected={(o) => <span>#{o.name}</span>}
            />
          </div>
          <div className="form-field">
            <label>URL del GIF animado</label>
            <input
              type="text"
              placeholder="https://media.giphy.com/…"
              value={data.boost.gif_url || ""}
              onChange={(e) => setB("gif_url", e.target.value)}
            />
            <span className="hint">Se mostrará en el mensaje de agradecimiento</span>
          </div>
          <div className="callout">
            <Icon name="info" /> El diseño se configura con <code>/configurar boosters</code>.
            Variable: <code>{"{user}"}</code>.
          </div>
        </div>
      )}

      {tab === "invites" && data?.invites && (
        <>
          <div className="glass-panel mod-section" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16, marginBottom: 16 }}>
            <div className="config-item inline-check">
              <div>
                <div style={{ fontWeight: 800 }}>Log de invitaciones</div>
                <div className="hint">Registra quién invitó a cada nuevo miembro y las salidas</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!data.invites.enabled}
                  onChange={(e) => setI("enabled", e.target.checked ? 1 : 0)}
                />
                <span className="slider" />
              </label>
            </div>
            <div className="form-field">
              <label>Canal de log</label>
              <SearchableSelect
                value={data.invites.channel_id || null}
                onChange={(v) => setI("channel_id", v ? Number(v) : null)}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="Seleccionar canal…"
                renderOption={(o) => <span>#{o.name}</span>}
                renderSelected={(o) => <span>#{o.name}</span>}
              />
              <span className="hint">Recomendado: #invitaciones</span>
            </div>
          </div>

          <div className="glass-panel" style={{ overflow: "hidden" }}>
            <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0, fontSize: "1rem" }}>
                <Icon name="giveaways" /> Top invitadores
              </h3>
              <button className="btn-icon" onClick={load} title="Recargar">
                <Icon name="refresh" />
              </button>
            </div>
            {leaderboard.length === 0 ? (
              <div className="no-results"><p>Aún no hay datos de invitaciones registrados.</p></div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {leaderboard.map((entry, i) => (
                  <div
                    key={entry.user_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: "12px 20px",
                      borderBottom: i < leaderboard.length - 1 ? "1px solid var(--border)" : "none",
                    }}
                  >
                    <div
                      style={{
                        width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontWeight: 900, fontSize: "0.85rem",
                        background:
                          i === 0 ? "rgba(251,191,36,0.15)" :
                          i === 1 ? "rgba(156,163,175,0.15)" :
                          i === 2 ? "rgba(180,107,55,0.15)" :
                          "rgba(255,255,255,0.04)",
                        color:
                          i === 0 ? "#fbbf24" :
                          i === 1 ? "#9ca3af" :
                          i === 2 ? "#b46b37" :
                          "var(--muted)",
                      }}
                    >
                      #{i + 1}
                    </div>
                    {entry.avatar ? (
                      <img src={entry.avatar} alt="" style={{ width: 36, height: 36, borderRadius: "50%", flexShrink: 0 }} />
                    ) : (
                      <div
                        style={{
                          width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
                          background: "var(--accent-light)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "var(--accent)", fontWeight: 700,
                        }}
                      >
                        {entry.username?.[0]?.toUpperCase() || "?"}
                      </div>
                    )}
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: "0.9rem" }}>{entry.username}</div>
                      <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>ID: {entry.user_id}</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontWeight: 900, fontSize: "1.1rem", color: "var(--accent)" }}>{entry.total}</div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted)" }}>invitaciones</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}


    </div>
  );
}
