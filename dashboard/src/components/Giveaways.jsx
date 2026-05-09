/**
 * components/Giveaways.jsx
 * ────────────────────────
 * Sorteos: crear, listar, cancelar, reroll.
 *
 * Endpoints:
 *   GET    /api/guilds/{g}/giveaways
 *   POST   /api/guilds/{g}/giveaways                    {channel_id, prize, duration_hours, winners_count, req_roles[], deny_roles[]}
 *   DELETE /api/guilds/{g}/giveaways/{msg_id}
 *   POST   /api/guilds/{g}/giveaways/{msg_id}/reroll
 *
 * Cada giveaway incluye `status` (active/ended/cancelled), `entries`, `req_roles`, `deny_roles`, `winners`.
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import SearchableSelect from "./ui/SearchableSelect";
import { Icon } from "../lib/icons";

const STATUS_COLOR = { active: "#34d399", ended: "#7a9bb5", cancelled: "#ef4444" };
const STATUS_LABEL = { active: "Activo", ended: "Finalizado", cancelled: "Cancelado" };

const EMPTY_FORM = {
  prize: "",
  winners_count: 1,
  duration_hours: 24,
  channel_id: null,
  req_roles: [],
  deny_roles: [],
};

export default function Giveaways({ selectedGuild, onToast }) {
  const guildId = selectedGuild;
  const [giveaways, setGiveaways] = useState([]);
  const [allRoles, setAllRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const toast = (kind, msg) => onToast?.({ type: kind, message: msg });

  const load = useCallback(async () => {
    if (!guildId) return;
    setLoading(true);
    try {
      const [gData, rData] = await Promise.all([
        apiGet(`/api/guilds/${guildId}/giveaways`).catch(() => ({ giveaways: [] })),
        apiGet(`/api/guilds/${guildId}/roles`).catch(() => ({ roles: [] })),
      ]);
      setGiveaways(gData?.giveaways || []);
      setAllRoles(rData?.roles || []);
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => { load(); }, [load]);

  const roleNameById = useMemo(() => {
    const m = new Map();
    for (const r of allRoles) m.set(String(r.id), r);
    return m;
  }, [allRoles]);

  const filtered = filter === "all"
    ? giveaways
    : giveaways.filter((g) => g.status === filter);

  const counts = useMemo(() => ({
    all: giveaways.length,
    active: giveaways.filter((g) => g.status === "active").length,
    ended: giveaways.filter((g) => g.status === "ended").length,
    cancelled: giveaways.filter((g) => g.status === "cancelled").length,
  }), [giveaways]);

  function timeRemainingFromUnix(endTimeSec) {
    const diff = endTimeSec * 1000 - Date.now();
    if (diff <= 0) return "Finalizado";
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    return h > 0 ? `${h}h ${m}m restantes` : `${m}m restantes`;
  }

  function formatUnix(endTimeSec) {
    return new Date(endTimeSec * 1000).toLocaleString("es");
  }

  const createGiveaway = async () => {
    if (!form.prize.trim()) return toast("error", "El premio es requerido");
    if (!form.channel_id) return toast("error", "Selecciona un canal");
    if (Number(form.duration_hours) <= 0) return toast("error", "Duración inválida");
    setCreating(true);
    try {
      await apiPost(`/api/guilds/${guildId}/giveaways`, {
        channel_id: Number(form.channel_id),
        prize: form.prize.trim(),
        duration_hours: Number(form.duration_hours),
        winners_count: Math.max(1, parseInt(form.winners_count, 10) || 1),
        req_roles: form.req_roles.map(Number),
        deny_roles: form.deny_roles.map(Number),
      });
      toast("success", "Sorteo creado");
      setForm(EMPTY_FORM);
      setShowCreate(false);
      await load();
    } catch (e) {
      toast("error", e?.message || "Error al crear sorteo");
    } finally {
      setCreating(false);
    }
  };

  const cancelGiveaway = async (msgId) => {
    if (!confirm("¿Cancelar este sorteo? No se elegirán ganadores.")) return;
    setBusyId(msgId);
    try {
      await apiDelete(`/api/guilds/${guildId}/giveaways/${msgId}`);
      toast("success", "Sorteo cancelado");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error cancelando");
    } finally {
      setBusyId(null);
    }
  };

  const rerollGiveaway = async (msgId) => {
    setBusyId(msgId);
    try {
      await apiPost(`/api/guilds/${guildId}/giveaways/${msgId}/reroll`, {});
      toast("success", "Reroll ejecutado");
      await load();
    } catch (e) {
      toast("error", e?.message || "Error en reroll");
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="loader">Cargando sorteos…</div>;

  return (
    <div className="ov-container animate-fade-in">
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 className="glow-text" style={{ margin: 0 }}>Sorteos</h2>
            <p className="subtitle" style={{ margin: "4px 0 0" }}>
              {counts.active} sorteo(s) activo(s)
            </p>
          </div>
          <button
            onClick={() => setShowCreate((s) => !s)}
            className="btn-primary"
          >
            <Icon name={showCreate ? "close" : "add"} /> {showCreate ? "Cancelar" : "Crear sorteo"}
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="glass-panel animate-fade-in" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title">
            <Icon name="add" />
            <h3>Nuevo sorteo</h3>
          </div>
          <div className="form-grid">
            <div className="form-field">
              <label>Premio</label>
              <input
                type="text"
                placeholder="Nitro Classic, Rol especial…"
                value={form.prize}
                onChange={(e) => setForm((p) => ({ ...p, prize: e.target.value }))}
              />
            </div>
            <div className="form-field">
              <label>Canal</label>
              <SearchableSelect
                value={form.channel_id}
                onChange={(v) => setForm((p) => ({ ...p, channel_id: v }))}
                endpoint={`/api/guilds/${guildId}/channels?type=text`}
                itemsKey="channels"
                placeholder="Seleccionar canal…"
                renderOption={(o) => <span>#{o.name}</span>}
                renderSelected={(o) => <span>#{o.name}</span>}
              />
            </div>
            <div className="form-field">
              <label>Ganadores</label>
              <input
                type="number" min="1" max="50"
                value={form.winners_count}
                onChange={(e) => setForm((p) => ({ ...p, winners_count: e.target.value }))}
              />
            </div>
            <div className="form-field">
              <label>Duración (horas)</label>
              <input
                type="number" min="0.1" max="720" step="0.5"
                value={form.duration_hours}
                onChange={(e) => setForm((p) => ({ ...p, duration_hours: e.target.value }))}
              />
            </div>
            <div className="form-field full-width">
              <label>Roles requeridos (al menos uno)</label>
              <SearchableSelect
                value={form.req_roles}
                onChange={(v) => setForm((p) => ({ ...p, req_roles: v }))}
                options={allRoles.map((r) => ({ id: r.id, name: r.name, color: r.color }))}
                multiple
                placeholder="Sin requisitos"
              />
            </div>
            <div className="form-field full-width">
              <label>Roles denegados</label>
              <SearchableSelect
                value={form.deny_roles}
                onChange={(v) => setForm((p) => ({ ...p, deny_roles: v }))}
                options={allRoles.map((r) => ({ id: r.id, name: r.name, color: r.color }))}
                multiple
                placeholder="Ninguno"
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
            <button className="btn-secondary" onClick={() => { setShowCreate(false); setForm(EMPTY_FORM); }}>
              Cancelar
            </button>
            <button className="btn-primary btn-save" onClick={createGiveaway} disabled={creating}>
              {creating ? "Creando…" : <><Icon name="save" /> Crear sorteo</>}
            </button>
          </div>
        </div>
      )}

      <div className="tab-bar" style={{ marginBottom: 20 }}>
        {[
          ["all", "Todos"],
          ["active", "Activos"],
          ["ended", "Finalizados"],
          ["cancelled", "Cancelados"],
        ].map(([f, l]) => (
          <button
            key={f}
            className={`tab-btn ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {l}
            <span style={{ marginLeft: 6, opacity: 0.7, fontSize: "0.78rem" }}>
              ({counts[f]})
            </span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="glass-panel" style={{ padding: 48, textAlign: "center" }}>
          <Icon name="giveaways" size="xl" />
          <h3 style={{ margin: "12px 0 8px" }}>Sin sorteos</h3>
          <p className="subtitle" style={{ margin: 0 }}>Crea uno con el botón de arriba.</p>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(320px,1fr))", gap: 16 }}>
          {filtered.map((g) => {
            const stColor = STATUS_COLOR[g.status] || "#7a9bb5";
            const isActive = g.status === "active";
            const isEnded = g.status === "ended";
            return (
              <div key={g.message_id} className="glass-panel" style={{ padding: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                  <div
                    style={{
                      width: 40, height: 40, borderRadius: 12,
                      background: `${stColor}22`, color: stColor,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "1.2rem",
                    }}
                  >
                    <Icon name="giveaways" />
                  </div>
                  <span
                    style={{
                      background: `${stColor}22`, color: stColor,
                      padding: "3px 10px", borderRadius: 999,
                      fontSize: "0.72rem", fontWeight: 700,
                    }}
                  >
                    {STATUS_LABEL[g.status] || g.status}
                  </span>
                </div>

                <h3 style={{ margin: "0 0 6px", fontSize: "1rem" }}>{g.prize || "Sin premio"}</h3>
                <p style={{ margin: "0 0 10px", fontSize: "0.78rem", color: "var(--muted)" }}>
                  {g.winners_count || 1} ganador(es) · {g.entries || 0} participante(s)
                </p>

                {g.end_time != null && (
                  <p style={{ margin: 0, fontSize: "0.76rem", color: "var(--muted)" }}>
                    {isActive ? timeRemainingFromUnix(g.end_time) : formatUnix(g.end_time)}
                  </p>
                )}

                {(g.req_roles?.length > 0 || g.deny_roles?.length > 0) && (
                  <div style={{ marginTop: 8, fontSize: "0.74rem", color: "var(--muted)" }}>
                    {g.req_roles?.length > 0 && (
                      <div>
                        Req: {g.req_roles.map((rid) => roleNameById.get(String(rid))?.name || rid).join(", ")}
                      </div>
                    )}
                    {g.deny_roles?.length > 0 && (
                      <div>
                        Deny: {g.deny_roles.map((rid) => roleNameById.get(String(rid))?.name || rid).join(", ")}
                      </div>
                    )}
                  </div>
                )}

                {isEnded && g.winners?.length > 0 && (
                  <div style={{ marginTop: 8, fontSize: "0.78rem" }}>
                    Ganadores: {g.winners.map((w) => `<@${w}>`).join(", ")}
                  </div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  {isActive && (
                    <button
                      className="btn-danger"
                      disabled={busyId === g.message_id}
                      onClick={() => cancelGiveaway(g.message_id)}
                    >
                      <Icon name="close" /> Cancelar
                    </button>
                  )}
                  {isEnded && (
                    <button
                      className="btn-secondary"
                      disabled={busyId === g.message_id}
                      onClick={() => rerollGiveaway(g.message_id)}
                    >
                      <Icon name="refresh" /> Reroll
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
