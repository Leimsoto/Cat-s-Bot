/**
 * components/Autoroles.jsx
 * ────────────────────────
 * Configuración de Autoroles con dos modos:
 *   • Al unirse  — roles que se asignan automáticamente cuando alguien entra.
 *   • Por reacción — paneles emoji↔rol asociados a un mensaje.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/autoroles/join
 *   POST   /api/guilds/{g}/autoroles/join                {role_id}
 *   DELETE /api/guilds/{g}/autoroles/join/{role_id}
 *   GET    /api/guilds/{g}/autoroles/reactions
 *   POST   /api/guilds/{g}/autoroles/reactions           {message_id, channel_id, mapping_data}
 *   DELETE /api/guilds/{g}/autoroles/reactions/{msg_id}
 */

import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";

const TABS = [
  { id: "join", label: "Al unirse", icon: "user" },
  { id: "reactions", label: "Por reacción", icon: "tags" },
];

export default function Autoroles({ selectedGuild, onToast }) {
  const guildId = selectedGuild;
  const [tab, setTab] = useState("join");

  const [joinRoles, setJoinRoles] = useState([]);
  const [panels, setPanels] = useState([]);
  const [loading, setLoading] = useState(true);

  const [allRoles, setAllRoles] = useState([]);
  const [allChannels, setAllChannels] = useState([]);

  const [newJoinRoleId, setNewJoinRoleId] = useState(null);
  const [adding, setAdding] = useState(false);

  // Form para nuevo panel reaction
  const [panelMsgId, setPanelMsgId] = useState("");
  const [panelChannelId, setPanelChannelId] = useState(null);
  const [panelMapping, setPanelMapping] = useState('{\n  "👍": 0\n}');
  const [savingPanel, setSavingPanel] = useState(false);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const load = async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [joinData, panelData, rolesData, channelsData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/autoroles/join`).catch(() => ({ join_roles: [] })),
        apiGet(`/api/guilds/${guildId}/autoroles/reactions`).catch(() => ({ panels: [] })),
        apiGet(`/api/guilds/${guildId}/roles`).catch(() => ({ roles: [] })),
        apiGet(`/api/guilds/${guildId}/channels?type=text`).catch(() => ({ channels: [] })),
      ]);
      setJoinRoles(joinData?.join_roles || []);
      setPanels(panelData?.panels || []);
      setAllRoles(rolesData?.roles || []);
      setAllChannels(channelsData?.channels || []);
    } catch (e) {
      console.error(e);
      toast("error", "Error cargando autoroles");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [guildId]);

  const roleNameById = useMemo(() => {
    const m = new Map();
    for (const r of allRoles) m.set(String(r.id), r);
    return m;
  }, [allRoles]);

  const channelNameById = useMemo(() => {
    const m = new Map();
    for (const c of allChannels) m.set(String(c.id), c);
    return m;
  }, [allChannels]);

  // ── Join roles ──────────────────────────────────────────────────────────────
  const addJoinRole = async () => {
    if (!newJoinRoleId) return;
    setAdding(true);
    try {
      await apiPost(`/api/guilds/${guildId}/autoroles/join`, { role_id: Number(newJoinRoleId) });
      setNewJoinRoleId(null);
      toast("success", "Rol agregado a auto-asignación");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error agregando rol");
    } finally {
      setAdding(false);
    }
  };

  const removeJoinRole = async (roleId) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/autoroles/join/${roleId}`);
      toast("success", "Rol eliminado");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error eliminando rol");
    }
  };

  // ── Reaction panels ─────────────────────────────────────────────────────────
  const savePanel = async () => {
    const msgId = String(panelMsgId).trim();
    if (!msgId || !panelChannelId) {
      toast("error", "ID de mensaje y canal son requeridos");
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(panelMapping);
      if (typeof parsed !== "object" || Array.isArray(parsed) || !parsed) {
        throw new Error("debe ser objeto JSON");
      }
    } catch (e) {
      toast("error", "Mapping inválido: " + (e.message || ""));
      return;
    }
    setSavingPanel(true);
    try {
      await apiPost(`/api/guilds/${guildId}/autoroles/reactions`, {
        message_id: Number(msgId),
        channel_id: Number(panelChannelId),
        mapping_data: JSON.stringify(parsed),
      });
      toast("success", "Panel guardado");
      setPanelMsgId("");
      setPanelChannelId(null);
      setPanelMapping('{\n  "👍": 0\n}');
      await load();
    } catch (e) {
      toast("error", e?.message || "Error guardando panel");
    } finally {
      setSavingPanel(false);
    }
  };

  const deletePanel = async (msgId) => {
    try {
      await apiDelete(`/api/guilds/${guildId}/autoroles/reactions/${msgId}`);
      toast("success", "Panel eliminado");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error eliminando panel");
    }
  };

  if (loading) return <div className="loader">Cargando autoroles…</div>;

  return (
    <div className="automod-container animate-fade-in">
      <div className="automod-header">
        <div className="header-info">
          <h2 className="glow-text">Autoroles</h2>
          <p className="subtitle">
            Asignación automática de roles al unirse, o paneles de roles por reacción.
          </p>
        </div>
      </div>

      <div className="tab-bar">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab-btn ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            <Icon name={t.icon} /> {t.label}
          </button>
        ))}
      </div>

      {tab === "join" && (
        <div className="automod-grid">
          <div className="glass-panel mod-section full-width">
            <div className="section-title">
              <Icon name="add" />
              <h3>Agregar rol al unirse</h3>
            </div>
            <p className="hint">
              Cuando un usuario nuevo entre al servidor, se le asignarán todos los
              roles de esta lista. El rol del bot debe estar por encima.
            </p>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <div style={{ flex: 1 }}>
                <SearchableSelect
                  value={newJoinRoleId}
                  onChange={setNewJoinRoleId}
                  options={allRoles
                    .filter((r) => !joinRoles.some((jr) => String(jr.role_id) === String(r.id)))
                    .map((r) => ({ id: r.id, name: r.name, color: r.color }))}
                  placeholder="Seleccionar rol…"
                />
              </div>
              <button
                className="btn-save"
                onClick={addJoinRole}
                disabled={adding || !newJoinRoleId}
              >
                {adding ? "Agregando…" : <><Icon name="add" /> Agregar</>}
              </button>
            </div>
          </div>

          <div className="glass-panel mod-section full-width">
            <div className="section-title">
              <Icon name="users" />
              <h3>Roles configurados ({joinRoles.length})</h3>
            </div>
            {joinRoles.length === 0 ? (
              <div className="empty-mini">
                <Icon name="user" />
                <span>Aún no hay roles configurados.</span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {joinRoles.map((r) => {
                  const meta = roleNameById.get(String(r.role_id));
                  return (
                    <div
                      key={r.role_id}
                      className="action-row"
                      style={{ display: "flex", alignItems: "center", gap: 12 }}
                    >
                      <div
                        className="ov-activity-badge"
                        style={{
                          background: meta?.color
                            ? `${meta.color}22`
                            : "rgba(88,101,242,0.15)",
                          color: meta?.color || "#5865f2",
                          flexShrink: 0,
                        }}
                      >
                        <Icon name="role" />
                      </div>
                      <div style={{ flex: 1 }}>
                        <strong>@{meta?.name || `ID:${r.role_id}`}</strong>
                        {r.created_at && (
                          <p
                            className="ov-subtitle"
                            style={{ margin: 0, fontSize: "0.78rem" }}
                          >
                            Agregado: {new Date(r.created_at).toLocaleDateString("es")}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => removeJoinRole(r.role_id)}
                        className="btn-danger"
                      >
                        <Icon name="delete" /> Eliminar
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "reactions" && (
        <div className="automod-grid">
          <div className="glass-panel mod-section full-width">
            <div className="section-title">
              <Icon name="add" />
              <h3>Crear / actualizar panel</h3>
            </div>
            <p className="hint">
              Asocia emojis a roles en un mensaje específico. El usuario obtiene el rol
              al reaccionar y lo pierde al quitar la reacción.
            </p>
            <div className="form-grid">
              <div className="form-field">
                <label>Canal del mensaje</label>
                <SearchableSelect
                  value={panelChannelId}
                  onChange={setPanelChannelId}
                  options={allChannels.map((c) => ({ id: c.id, name: `#${c.name}` }))}
                  placeholder="Seleccionar canal…"
                />
              </div>
              <div className="form-field">
                <label>ID del mensaje</label>
                <input
                  type="text"
                  value={panelMsgId}
                  onChange={(e) => setPanelMsgId(e.target.value)}
                  placeholder="Ej: 1234567890"
                  inputMode="numeric"
                />
              </div>
              <div className="form-field full-width">
                <label>Mapping JSON (emoji → role_id)</label>
                <textarea
                  value={panelMapping}
                  onChange={(e) => setPanelMapping(e.target.value)}
                  rows={6}
                  spellCheck={false}
                  style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
                />
                <p className="hint" style={{ marginTop: 4 }}>
                  Usa el emoji como clave (ej: <code>"👍"</code>) o el nombre del emoji
                  custom. El valor es el ID numérico del rol.
                </p>
              </div>
            </div>
            <button
              className="btn-save"
              onClick={savePanel}
              disabled={savingPanel || !panelMsgId || !panelChannelId}
            >
              {savingPanel ? "Guardando…" : <><Icon name="save" /> Guardar panel</>}
            </button>
          </div>

          <div className="glass-panel mod-section full-width">
            <div className="section-title">
              <Icon name="tags" />
              <h3>Paneles existentes ({panels.length})</h3>
            </div>
            {panels.length === 0 ? (
              <div className="empty-mini">
                <Icon name="tags" />
                <span>Aún no hay paneles de reacción.</span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {panels.map((p) => {
                  let mapping = {};
                  try {
                    mapping = JSON.parse(p.mapping_data || "{}");
                  } catch {
                    /* noop */
                  }
                  const ch = channelNameById.get(String(p.channel_id));
                  return (
                    <div
                      key={p.message_id}
                      className="action-row"
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 12,
                        flexDirection: "column",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 12, width: "100%" }}>
                        <div
                          className="ov-activity-badge"
                          style={{
                            background: "rgba(88,101,242,0.15)",
                            color: "#5865f2",
                            flexShrink: 0,
                          }}
                        >
                          <Icon name="tags" />
                        </div>
                        <div style={{ flex: 1 }}>
                          <strong>Mensaje #{p.message_id}</strong>
                          <p className="ov-subtitle" style={{ margin: 0, fontSize: "0.78rem" }}>
                            Canal: #{ch?.name || `ID:${p.channel_id}`}
                          </p>
                        </div>
                        <button
                          onClick={() => deletePanel(p.message_id)}
                          className="btn-danger"
                        >
                          <Icon name="delete" /> Eliminar
                        </button>
                      </div>
                      <div style={{ paddingLeft: 56, fontSize: "0.85rem", color: "var(--text-muted)" }}>
                        {Object.entries(mapping).map(([emoji, rid]) => {
                          const role = roleNameById.get(String(rid));
                          return (
                            <span
                              key={emoji}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 6,
                                marginRight: 12,
                              }}
                            >
                              <span style={{ fontSize: "1.1em" }}>{emoji}</span>
                              <span style={{ color: role?.color || "inherit" }}>
                                @{role?.name || `ID:${rid}`}
                              </span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
