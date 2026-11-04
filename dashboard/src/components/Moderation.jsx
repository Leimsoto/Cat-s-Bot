import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { Icon } from "../lib/icons";
import { SearchableSelect } from "./ui";
import Toast from "./Toast";
import IdentityBadge from "./IdentityBadge";
import ModerationReason from "./ModerationReason";
import CaseEvidence from "./CaseEvidence";
import { useSaveBar } from "../lib/SaveBarContext";

export default function Moderation({ selectedGuild: guildId }) {
  const [tab, setTab] = useState("config");
  const [cfg, setCfg] = useState(null);
  const [cases, setCases] = useState([]);
  const [casesGuild, setCasesGuild] = useState(null);
  const casesRequest = useRef(0);
  const [activeModerations, setActiveModerations] = useState({ cases: [], pending: [] });
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
    } catch (e) {
      showToast(e?.message || "Error cargando configuración", "error");
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  const loadCases = useCallback(async () => {
    if (!guildId) return;
    const request = ++casesRequest.current;
    try {
      const data = await apiGet(`/api/moderation/${guildId}/cases?limit=100`, {
        cache: false});
      if (request !== casesRequest.current) return;
      setCases(Array.isArray(data) ? data : data.cases || []);
      setCasesGuild(guildId);
    } catch {
      if (request === casesRequest.current) setCases([]);
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

  const loadModerations = useCallback(async () => {
    if (!guildId) return;
    try {
      const data = await apiGet(`/api/moderation/${guildId}/moderations`, {
        cache: false});
      setActiveModerations({
        cases: Array.isArray(data?.cases) ? data.cases : [],
        pending: Array.isArray(data?.pending) ? data.pending : []});
    } catch {
      setActiveModerations({ cases: [], pending: [] });
    }
  }, [guildId]);

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

  const updateCase = async (c, patch) => {
    const ref = c.case_number || c.id;
    try {
      await apiPatch(`/api/moderation/${guildId}/cases/${ref}`, patch);
      showToast("Caso actualizado");
      loadCases();
    } catch (e) {
      showToast(e.message || "No se pudo actualizar el caso", "error");
    }
  };

  const editCaseReason = async (c) => {
    const value = window.prompt("Nueva razón del caso", c.reason || "");
    if (value === null) return;
    await updateCase(c, { reason: value });
  };

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (tab === "cases") loadCases();
    if (tab === "active") loadModerations();
    if (tab === "appeals") loadAppeals();
  }, [tab, loadCases, loadModerations, loadAppeals]);

  const set = (k, v) => {
    setCfg((p) => ({ ...p, [k]: v }));
    setDirty(true);
  };

  // Los snowflakes de Discord exceden Number.MAX_SAFE_INTEGER; mantenerlos como string.
  const setId = (k) => (v) => set(k, v ? String(v) : null);

  const save = async () => {
    if (cfg.message_role_enabled && (!cfg.message_role_id || !cfg.message_role_notice?.trim())) {
      showToast("Selecciona el rol requerido y escribe el texto del aviso.", "error");
      return;
    }
    setSaving(true);
    try {
      const res = await apiPatch(`/api/guilds/${guildId}/moderation`, cfg);
      if (res?.config) setCfg(res.config);
      setDirty(false);
      showToast("Configuración guardada");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const filteredCases = (casesGuild === guildId ? cases : []).filter((c) => {
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
    AUTO_MUTE: "#8b5cf6",
    HARDMUTE: "#8b5cf6",
    TIMEOUT: "#f97316",
    TEMPBAN: "#ef4444",
    FORCEBAN: "#ef4444",
    SOFTBAN: "#f97316",
    KICK: "#f97316",
    BAN: "#ef4444",
    AUTO_BAN: "#ef4444",
    AUTO_KICK: "#f97316",
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
          ["active", "Activas"],
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
          <section
            className="glass-panel mod-section"
            aria-labelledby="message-role-title"
            style={{ padding: 24, borderRadius: 16, display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div className="section-title">
              <h3 id="message-role-title" style={{ margin: 0 }}>Rol requerido para hablar</h3>
            </div>
            <p style={{ margin: 0, color: "var(--text-muted)", maxWidth: "70ch" }}>
              Al enviar un mensaje sin este rol, el bot lo borra y publica un aviso en el mismo canal mencionando al autor. Con el rol puedes hablar libremente.
            </p>
            <div className="config-item inline-check" style={{ marginBottom: 0 }}>
              <label htmlFor="message-role-enabled" style={{ fontWeight: 700 }}>Exigir este rol para hablar</label>
              <label className="toggle-switch">
                <input
                  id="message-role-enabled"
                  type="checkbox"
                  checked={!!cfg.message_role_enabled}
                  onChange={(e) => set("message_role_enabled", e.target.checked ? 1 : 0)}
                />
                <span className="slider" />
              </label>
            </div>
            <div className="config-item" role="group" aria-labelledby="message-role-label" style={{ marginBottom: 0 }}>
              <label id="message-role-label">Rol requerido</label>
              <SearchableSelect
                value={cfg.message_role_id || ""}
                onChange={setId("message_role_id")}
                endpoint={`/api/guilds/${guildId}/roles?include_managed=true`}
                itemsKey="roles"
                placeholder="Selecciona el rol que permite hablar…"
                renderOption={renderRoleOption}
                renderSelected={renderRoleSelected}
                disabled={!cfg.message_role_enabled}
              />
            </div>
            <div className="config-item" style={{ marginBottom: 0 }}>
              <label htmlFor="message-role-notice">Texto del aviso</label>
              <textarea
                id="message-role-notice"
                rows={3}
                maxLength={1975}
                value={cfg.message_role_notice ?? "Necesitas el rol requerido para hablar en este servidor."}
                onChange={(e) => set("message_role_notice", e.target.value)}
                disabled={!cfg.message_role_enabled}
                aria-describedby="message-role-notice-help"
                aria-invalid={!!cfg.message_role_enabled && !cfg.message_role_notice?.trim()}
              />
              <small id="message-role-notice-help" style={{ color: "var(--text-muted)" }}>
                {cfg.message_role_notice?.length ?? 0}/1975 caracteres. La mención del autor se añade automáticamente; el texto no activa otras menciones.
              </small>
            </div>
            {!!cfg.message_role_enabled && (!cfg.message_role_id || !cfg.message_role_notice?.trim()) && (
              <p role="alert" style={{ margin: 0, color: "var(--danger)" }}>Selecciona un rol y escribe el aviso antes de guardar.</p>
            )}
            <p style={{ margin: 0, color: "var(--text-muted)", maxWidth: "70ch" }}>
              Afecta a todos los canales, incluidos administradores sin el rol. No actúa al escribir, en mensajes privados ni en mensajes de bots, webhooks o del sistema. Se envía un aviso por persona cada 10 segundos; los mensajes sin rol se siguen borrando. El bot necesita ver el canal, gestionar mensajes y enviar mensajes (también en hilos).
            </p>
          </section>

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
                gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))",
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
                gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))",
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
              {["all", "WARN", "MUTE", "TIMEOUT", "TEMPBAN", "KICK", "BAN", "PURGE"].map((f) => (
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
            {filteredCases.map((c, i) => {
              return (
              <div
                key={`${guildId}:${c.id || i}`}
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
                  {c.action_label || c.action_type}
                </span>
                <div style={{ flex: 1, minWidth: 140 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ fontSize: "0.78rem", color: "var(--muted)", fontWeight: 800 }}>
                      Caso #{c.case_number || c.id}
                    </div>
                    <IdentityBadge item={c} />
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                    <ModerationReason entry={c} />
                  </div>
                  {/^https?:\/\//i.test(c.evidence_url || "") && (
                    <a href={c.evidence_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.78rem" }}>
                      Evidencia
                    </a>
                  )}
                </div>
                <select
                  value={c.status || "active"}
                  onChange={(e) => updateCase(c, { status: e.target.value })}
                  style={{
                    background: "rgba(0,0,0,0.2)",
                    color: "var(--text)",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 10,
                    padding: "7px 10px"}}
                >
                  <option value="active">Activa</option>
                  <option value="expired">Caducada</option>
                  <option value="revoked">Revocada</option>
                  <option value="failed">Fallida</option>
                  <option value="applying" disabled>Aplicando · sin confirmar</option>
                </select>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => editCaseReason(c)}
                  style={{ fontSize: "0.78rem", padding: "7px 10px" }}
                >
                  Editar razón
                </button>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  {c.created_at
                    ? new Date(c.created_at).toLocaleDateString()
                    : "—"}
                </div>
                <CaseEvidence guildId={guildId} entry={c} onUpdated={(result) => {
                  setCases((previous) => previous.map((item) => item.id === c.id ? {
                    ...item,
                    evidence_count: result.items.filter((evidence) => evidence.status === "available").length,
                    evidence_status: result.items.some((evidence) => evidence.status === "failed") ? "partial" : "available",
                  } : item));
                }} />
              </div>
            );})}
          </div>
        </div>
      )}

      {tab === "active" && (
        <div className="moderation-container">
          <div className="cases-list">
            {activeModerations.cases.length === 0 && activeModerations.pending.length === 0 && (
              <div className="no-results">
                <p>No hay sanciones activas registradas.</p>
              </div>
            )}
            {activeModerations.cases.map((c, i) => {
              const color = COLORS[c.action_type] || "#6366f1";
              return (
                <div
                  key={`case-${c.id || i}`}
                  className="case-row"
                  style={{ padding: 16, borderRadius: 14, border: `1px solid ${color}33` }}
                >
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                    <span
                      style={{
                        padding: "4px 10px",
                        borderRadius: 999,
                        fontSize: "0.72rem",
                        fontWeight: 900,
                        background: `${color}22`,
                        color}}
                    >
                      {c.action_label || c.action_type}
                    </span>
                    <strong>#{c.case_number || c.id}</strong>
                    <IdentityBadge item={c} compact />
                    <span style={{ color: "var(--muted)" }}>
                      Expira: {c.expires_at ? new Date(c.expires_at).toLocaleString() : "permanente"}
                    </span>
                  </div>
                  <div style={{ marginTop: 8, color: "var(--muted)", fontSize: "0.86rem" }}>
                    <ModerationReason entry={c} />
                  </div>
                </div>
              );
            })}
            {activeModerations.pending.map((p, i) => {
              return (
              <div
                key={`pending-${p.id || i}`}
                className="case-row"
                style={{ padding: 16, borderRadius: 14, border: "1px solid rgba(245,158,11,0.25)" }}
              >
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                  <span
                    style={{
                      padding: "4px 10px",
                      borderRadius: 999,
                      fontSize: "0.72rem",
                      fontWeight: 900,
                      background: "rgba(245,158,11,0.14)",
                      color: "#f59e0b"}}
                  >
                    JOB
                  </span>
                  <strong>{p.action_label || p.action_type}</strong>
                  <IdentityBadge item={p} compact />
                  <span style={{ color: "var(--muted)" }}>
                    Ejecuta: {p.execute_at ? new Date(p.execute_at).toLocaleString() : "—"}
                  </span>
                </div>
              </div>
            );})}
          </div>
        </div>
      )}

      {tab === "appeals" && (
        <div className="moderation-container">
          <div className="tabs-container" style={{ marginBottom: 12 }}>
            {[
              ["PENDING", "Pendientes"],
              ["ACCEPTED", "Aceptadas"],
              ["DENIED", "Rechazadas"],
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
                DENIED: "#ef4444",
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
                      {a.action_label || a.action_type}
                    </span>
                    <IdentityBadge item={a} prefix="user" compact />
                    <div style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--muted)" }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : "—"}
                    </div>
                  </div>
                  <div style={{ fontSize: "0.86rem" }}>
                    <strong>Razón original:</strong> <ModerationReason entry={a} />
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
                        onClick={() => resolveAppeal(a.id, "DENIED", false)}
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
