import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import { useSaveBar } from "../lib/SaveBarContext";

export default function Moderation({ selectedGuild: guildId }) {
  const [tab, setTab] = useState("config");
  const [cfg, setCfg] = useState(null);
  const [cases, setCases] = useState([]);
  const [appeals, setAppeals] = useState([]);
  const [appealFilter, setAppealFilter] = useState("PENDING");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creatingMuteRole, setCreatingMuteRole] = useState(false);
  const [toast, setToast] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    setDirty(false);
    try {
      const modCfg = await apiGet(`/api/guilds/${guildId}/moderation`);
      setCfg(modCfg || {});
    } catch {
      showToast("Error cargando configuración", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  const loadCases = useCallback(async () => {
    if (!guildId) return;
    try {
      const data = await apiGet(`/api/moderation/${guildId}/cases?limit=100`, {
        cache: false});
      setCases(Array.isArray(data) ? data : data.cases || []);
    } catch {
      setCases([]);
    }
  }, [guildId]);

  const loadAppeals = useCallback(async () => {
    if (!guildId) return;
    try {
      const query = appealFilter === "ALL" ? "" : `?status=${appealFilter}`;
      const data = await apiGet(
        `/api/moderation/${guildId}/appeals${query}`,
        { cache: false }
      );
      setAppeals(Array.isArray(data) ? data : []);
    } catch {
      setAppeals([]);
    }
  }, [guildId, appealFilter]);

  const createMuteRole = async () => {
    if (!guildId || creatingMuteRole) return;
    setCreatingMuteRole(true);
    try {
      const res = await apiPost(`/api/guilds/${guildId}/moderation/mute-role`);
      if (res?.id) {
        setCfg((p) => ({ ...p, mute_role_id: res.id }));
        setDirty(true);
        showToast(`Rol "${res.name}" listo. Recuerda guardar los cambios.`);
      }
    } catch (e) {
      showToast(e.message || "No se pudo crear el rol", "error");
    } finally {
      setCreatingMuteRole(false);
    }
  };

  const resolveAppeal = async (id, status, autoRemove) => {
    try {
      await apiPatch(`/api/moderation/${guildId}/appeals/${id}`, {
        status,
        auto_remove: autoRemove,
      });
      showToast(`Apelación ${status === "ACCEPTED" ? "aceptada" : "rechazada"}`);
      loadAppeals();
    } catch (e) {
      showToast(e.message || "Error procesando apelación", "error");
    }
  };

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (tab === "cases") loadCases();
    if (tab === "appeals") loadAppeals();
  }, [tab, loadCases, loadAppeals]);

  const set = (k, v) => {
    setCfg((p) => ({ ...p, [k]: v }));
    setDirty(true);
  };

  // Wrapper para que SearchableSelect (que devuelve string) entregue al estado
  // un int o null, manteniendo compatibilidad con el resto de la página.
  const setId = (k) => (v) => set(k, v ? parseInt(v, 10) : null);

  const save = async () => {
    setSaving(true);
    try {
      await apiPatch(`/api/guilds/${guildId}/moderation`, cfg);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const filteredCases = cases.filter((c) => {
    if (filter !== "all" && c.action_type !== filter) return false;
    if (
      search &&
      !JSON.stringify(c).toLowerCase().includes(search.toLowerCase())
    )
      return false;
    return true;
  });

  const COLORS = {
    WARN: "#f59e0b",
    MUTE: "#8b5cf6",
    KICK: "#f97316",
    BAN: "#ef4444",
    UNMUTE: "#10b981",
    UNBAN: "#10b981"};

  useSaveBar({ dirty, saving, onSave: save, onRevert: load });

  if (loading)
    return (
      <div className="dashboard-empty-state">
        <div className="loading-spinner" />
        <p>Cargando…</p>
      </div>
    );

  // Renderizadores enriquecidos para SearchableSelect.
  const renderChannelOption = (opt) => (
    <>
      <Icon name="channel" />
      <span className="ss-option-label">{opt.name}</span>
      {opt.category ? (
        <span className="ss-option-sub">{opt.category}</span>
      ) : null}
    </>
  );
  const renderChannelSelected = (opt) => (
    <>
      <Icon name="channel" /> {opt.name}
    </>
  );
  const renderRoleOption = (opt) => (
    <>
      {opt.color ? (
        <span
          className="ss-swatch"
          style={{ background: opt.color }}
          aria-hidden="true"
        />
      ) : (
        <Icon name="role" />
      )}
      <span className="ss-option-label">{opt.name}</span>
    </>
  );
  const renderRoleSelected = (opt) => (
    <>
      {opt.color ? (
        <span
          className="ss-swatch"
          style={{ background: opt.color }}
          aria-hidden="true"
        />
      ) : (
        <Icon name="role" />
      )}{" "}
      {opt.name}
    </>
  );

  return (
    <div className="ov-container animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="section-header">
        <h2
          style={{
          }}
        >
          Moderación
        </h2>
      </div>

      <div className="tabs-container">
        {[
          ["config", "Configuración"],
          ["cases", "Casos"],
          ["appeals", "Apelaciones"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={`tab-btn ${tab === id ? "active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "config" && cfg && (
        <>
          <div
            className="glass-panel mod-section"
            style={{
              padding: 24,
              borderRadius: 22,
              display: "flex",
              flexDirection: "column",
              gap: 16}}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Canales y roles</h3>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))",
                gap: 16}}
            >
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Canal de mod-logs</label>
                <SearchableSelect
                  value={cfg.modlog_channel || ""}
                  onChange={setId("modlog_channel")}
                  endpoint={`/api/guilds/${guildId}/channels`}
                  itemsKey="channels"
                  placeholder="Selecciona un canal de texto…"
                  renderOption={renderChannelOption}
                  renderSelected={renderChannelSelected}
                />
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>
                  Rol de mute
                  {!cfg.mute_role_id && (
                    <span style={{ marginLeft: 8, fontSize: "0.7rem", color: "#f59e0b" }}>
                      sin configurar → auto-mute no funcionará
                    </span>
                  )}
                </label>
                <SearchableSelect
                  value={cfg.mute_role_id || ""}
                  onChange={setId("mute_role_id")}
                  endpoint={`/api/guilds/${guildId}/roles`}
                  itemsKey="roles"
                  placeholder="Selecciona un rol…"
                  renderOption={renderRoleOption}
                  renderSelected={renderRoleSelected}
                />
                {!cfg.mute_role_id && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={createMuteRole}
                    disabled={creatingMuteRole}
                    style={{ marginTop: 8, fontSize: "0.8rem", padding: "6px 12px" }}
                  >
                    {creatingMuteRole ? "Creando…" : "🪄 Crear rol Muted automáticamente"}
                  </button>
                )}
              </div>
              <div className="config-item" style={{ marginBottom: 0 }}>
                <label>Rol de moderador</label>
                <SearchableSelect
                  value={cfg.mod_role_id || ""}
                  onChange={setId("mod_role_id")}
                  endpoint={`/api/guilds/${guildId}/roles`}
                  itemsKey="roles"
                  placeholder="Selecciona un rol…"
                  renderOption={renderRoleOption}
                  renderSelected={renderRoleSelected}
                />
              </div>
            </div>
            <div
              className="config-item inline-check"
              style={{ marginBottom: 0 }}
            >
              <div>
                <div style={{ fontWeight: 700 }}>
                  Logs de moderación activos
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!cfg.modlog_enabled}
                  onChange={(e) =>
                    set("modlog_enabled", e.target.checked ? 1 : 0)
                  }
                />
                <span className="slider" />
              </label>
            </div>
          </div>

          <div
            className="glass-panel mod-section"
            style={{ padding: 24, borderRadius: 22 }}
          >
            <div className="section-title">
              <h3 style={{ margin: 0 }}>Sistema de warns</h3>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                gap: 14}}
            >
              {[
                ["warn_mute_enabled", "warn_mute_threshold", "Auto-mute", true],
                ["warn_kick_enabled", "warn_kick_threshold", "Auto-kick", false],
                ["warn_ban_enabled", "warn_ban_threshold", "Auto-ban", false],
              ].map(([enK, thrK, lbl, hasDur]) => (
                <div
                  key={enK}
                  style={{
                    padding: 16,
                    borderRadius: 16,
                    display: "flex",
                    flexDirection: "column",
                    gap: 12,
                    background: cfg[enK]
                      ? "rgba(99,102,241,0.1)"
                      : "rgba(255,255,255,0.02)",
                    border: `1px solid ${cfg[enK] ? "rgba(139,92,246,0.3)" : "rgba(139,92,246,0.1)"}`}}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center"}}
                  >
                    <span style={{ fontWeight: 800 }}>{lbl}</span>
                    <label className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={!!cfg[enK]}
                        onChange={(e) => set(enK, e.target.checked ? 1 : 0)}
                      />
                      <span className="slider" />
                    </label>
                  </div>
                  <div className="config-item" style={{ marginBottom: 0 }}>
                    <label>Warns necesarios</label>
                    <input
                      type="number"
                      min="1"
                      max="50"
                      value={cfg[thrK] ?? 3}
                      onChange={(e) => set(thrK, parseInt(e.target.value))}
                      disabled={!cfg[enK]}
                      style={{ opacity: cfg[enK] ? 1 : 0.4 }}
                    />
                  </div>
                  {hasDur && (
                    <div className="config-item" style={{ marginBottom: 0 }}>
                      <label>Duración mute (seg)</label>
                      <input
                        type="number"
                        min="60"
                        max="604800"
                        step="60"
                        value={cfg.warn_mute_duration ?? 600}
                        onChange={(e) =>
                          set("warn_mute_duration", parseInt(e.target.value))
                        }
                        disabled={!cfg[enK]}
                        style={{ opacity: cfg[enK] ? 1 : 0.4 }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>


        </>
      )}

      {tab === "cases" && (
        <div className="moderation-container">
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <div
              className="search-bar-container"
              style={{ flex: 1, minWidth: 200 }}
            >
              <input
                className="search-input"
                placeholder="Buscar…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ border: "none", background: "transparent" }}
              />
            </div>
            <div className="tabs-container">
              {["all", "WARN", "MUTE", "KICK", "BAN"].map((f) => (
                <button
                  key={f}
                  className={`tab-btn ${filter === f ? "active" : ""}`}
                  onClick={() => setFilter(f)}
                  style={{ fontSize: "0.8rem", padding: "8px 14px" }}
                >
                  {f === "all" ? "Todos" : f}
                </button>
              ))}
            </div>
          </div>
          <div className="cases-list">
            {filteredCases.length === 0 && (
              <div className="no-results">
                <p>Sin casos con este filtro.</p>
              </div>
            )}
            {filteredCases.map((c, i) => (
              <div
                key={c.id || i}
                className="case-row"
                style={{
                  padding: 16,
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  flexWrap: "wrap"}}
              >
                <span
                  style={{
                    padding: "5px 11px",
                    borderRadius: 999,
                    fontSize: "0.75rem",
                    fontWeight: 900,
                    background: `${COLORS[c.action_type] || "#6366f1"}22`,
                    color: COLORS[c.action_type] || "#818cf8",
                    border: `1px solid ${COLORS[c.action_type] || "#6366f1"}44`}}
                >
                  {c.action_type}
                </span>
                <div style={{ flex: 1, minWidth: 140 }}>
                  <div style={{ fontWeight: 700 }}>Usuario: {c.user_id}</div>
                  <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                    {c.reason || "Sin razón"}
                  </div>
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  {c.created_at
                    ? new Date(c.created_at).toLocaleDateString()
                    : "—"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "appeals" && (
        <div className="moderation-container">
          <div className="tabs-container" style={{ marginBottom: 12 }}>
            {[
              ["PENDING", "Pendientes"],
              ["ACCEPTED", "Aceptadas"],
              ["REJECTED", "Rechazadas"],
              ["ALL", "Todas"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={`tab-btn ${appealFilter === id ? "active" : ""}`}
                onClick={() => setAppealFilter(id)}
                style={{ fontSize: "0.8rem", padding: "8px 14px" }}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="cases-list">
            {appeals.length === 0 && (
              <div className="no-results">
                <p>No hay apelaciones en este filtro.</p>
              </div>
            )}
            {appeals.map((a) => {
              const status = (a.status || "PENDING").toUpperCase();
              const statusColor = {
                PENDING: "#f59e0b",
                ACCEPTED: "#10b981",
                REJECTED: "#ef4444",
              }[status] || "#6366f1";
              return (
                <div
                  key={a.id}
                  className="case-row"
                  style={{
                    padding: 16,
                    borderRadius: 14,
                    background: "rgba(255,255,255,0.02)",
                    border: `1px solid ${statusColor}33`,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                    <span
                      style={{
                        padding: "4px 10px",
                        borderRadius: 999,
                        fontSize: "0.72rem",
                        fontWeight: 900,
                        background: `${statusColor}22`,
                        color: statusColor,
                        border: `1px solid ${statusColor}55`,
                      }}
                    >
                      {status}
                    </span>
                    <span
                      style={{
                        padding: "4px 10px",
                        borderRadius: 999,
                        fontSize: "0.72rem",
                        fontWeight: 800,
                        background: `${COLORS[a.action_type] || "#6366f1"}22`,
                        color: COLORS[a.action_type] || "#818cf8",
                      }}
                    >
                      {a.action_type}
                    </span>
                    <div style={{ fontWeight: 700 }}>Usuario: {a.user_id}</div>
                    <div style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--muted)" }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : "—"}
                    </div>
                  </div>
                  <div style={{ fontSize: "0.86rem" }}>
                    <strong>Razón original:</strong> {a.reason || "—"}
                  </div>
                  <div style={{ fontSize: "0.86rem" }}>
                    <strong>Defensa:</strong>{" "}
                    <span style={{ color: "var(--muted)" }}>
                      {a.appeal_text || "—"}
                    </span>
                  </div>
                  {status === "PENDING" && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        className="btn btn-success"
                        style={{ fontSize: "0.78rem", padding: "6px 12px" }}
                        onClick={() => resolveAppeal(a.id, "ACCEPTED", true)}
                      >
                        ✅ Aceptar y revertir sanción
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ fontSize: "0.78rem", padding: "6px 12px" }}
                        onClick={() => resolveAppeal(a.id, "ACCEPTED", false)}
                      >
                        Aceptar (sin revertir)
                      </button>
                      <button
                        className="btn btn-danger"
                        style={{ fontSize: "0.78rem", padding: "6px 12px" }}
                        onClick={() => resolveAppeal(a.id, "REJECTED", false)}
                      >
                        ❌ Rechazar
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
