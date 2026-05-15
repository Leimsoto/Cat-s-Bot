/**
 * EmojiPicker.jsx
 * ───────────────
 * Selector de emoji con tabs: servidor, bot (Cat's Bot) y genéricos Unicode.
 *
 * Uso típico:
 *
 *   const [emoji, setEmoji] = useState("✅");
 *   <EmojiPicker guildId={guildId} value={emoji} onChange={setEmoji} />
 *
 * Renderiza un botón que abre un popover. El valor devuelto puede ser:
 *   • Un carácter Unicode (ej. "✅").
 *   • Un tag de emoji custom (ej. "<:hi:123456789>"), que Discord renderiza
 *     automáticamente cuando se envía en un mensaje. El backend solo necesita
 *     persistir la cadena tal cual.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { apiGet } from "../lib/api";

const UNICODE_EMOJIS = [
  "😀","😃","😄","😁","😆","😅","🤣","😂","🙂","🙃","😉","😊","😇","🥰","😍","🤩",
  "😘","😗","😚","😙","🥲","😋","😛","😜","🤪","😝","🤑","🤗","🤭","🤫","🤔","🤐",
  "🤨","😐","😑","😶","😏","😒","🙄","😬","🤥","😌","😔","😪","🤤","😴","😷","🤒",
  "🤕","🤢","🤮","🤧","🥵","🥶","🥴","😵","🤯","🤠","🥳","😎","🤓","🧐","😕","😟",
  "🙁","☹️","😮","😯","😲","😳","🥺","😦","😧","😨","😰","😥","😢","😭","😱","😖",
  "😣","😞","😓","😩","😫","🥱","😤","😡","😠","🤬","😈","👿","💀","☠️","💩","🤡",
  "👹","👺","👻","👽","👾","🤖","😺","😸","😹","😻","😼","😽","🙀","😿","😾",
  "👍","👎","👌","🤌","🤏","✌️","🤞","🤟","🤘","🤙","👈","👉","👆","🖕","👇","☝️",
  "👋","🤚","🖐️","✋","🖖","👏","🙌","👐","🤲","🤝","🙏","✍️","💪","🦾","🦿","🦵",
  "❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","💔","❣️","💕","💞","💓","💗","💖",
  "💘","💝","💟","☮️","✝️","☪️","🕉️","☸️","✡️","🔯","🕎","☯️","☦️","🛐","⛎","♈",
  "✅","❌","⭕","🚫","⛔","📛","🔞","♨️","🚷","🚯","🚳","🚱","🔞","📵","🚭","❗",
  "❓","❕","❔","‼️","⁉️","💯","🔥","✨","🌟","⭐","💫","💥","💢","💦","💨","🕳️",
  "🎉","🎊","🎈","🎁","🎀","🎗️","🎟️","🎫","🎖️","🏆","🏅","🥇","🥈","🥉","⚽","🏀",
  "🏈","⚾","🥎","🎾","🏐","🏉","🥏","🎱","🪀","🏓","🏸","🏒","🏑","🥍","🏏","🥅",
];

export default function EmojiPicker({ guildId, value, onChange, label, disabled }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("server");
  const [serverEmojis, setServerEmojis] = useState([]);
  const [botEmojis, setBotEmojis] = useState([]);
  const [search, setSearch] = useState("");
  const [loaded, setLoaded] = useState(false);
  const popRef = useRef(null);
  const triggerRef = useRef(null);

  const load = useCallback(async () => {
    if (!guildId || loaded) return;
    try {
      const data = await apiGet(`/api/guilds/${guildId}/emojis`);
      setServerEmojis(Array.isArray(data?.guild) ? data.guild : []);
      setBotEmojis(Array.isArray(data?.bot) ? data.bot : []);
    } catch {
      setServerEmojis([]);
      setBotEmojis([]);
    } finally {
      setLoaded(true);
    }
  }, [guildId, loaded]);

  useEffect(() => {
    if (!open) return;
    load();
    const handler = (e) => {
      if (
        popRef.current &&
        !popRef.current.contains(e.target) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target)
      ) {
        setOpen(false);
      }
    };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", esc);
    };
  }, [open, load]);

  const pick = (val) => {
    onChange(val);
    setOpen(false);
  };

  const filtered = (list) => {
    if (!search) return list;
    const q = search.toLowerCase();
    return list.filter((e) => e.name?.toLowerCase().includes(q));
  };

  const displayValue = value || "🙂";

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      {label && (
        <label style={{ display: "block", fontSize: "0.8rem", color: "var(--muted)", marginBottom: 4 }}>
          {label}
        </label>
      )}
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        style={{
          padding: "8px 12px",
          borderRadius: 10,
          background: "rgba(255,255,255,0.04)",
          border: "1px solid rgba(139,92,246,0.25)",
          color: "var(--text)",
          fontSize: "1.1rem",
          cursor: disabled ? "not-allowed" : "pointer",
          minWidth: 50,
          opacity: disabled ? 0.5 : 1,
        }}
      >
        {displayValue}
      </button>

      {open && (
        <div
          ref={popRef}
          style={{
            position: "absolute",
            zIndex: 50,
            top: "100%",
            left: 0,
            marginTop: 6,
            width: 320,
            maxHeight: 360,
            background: "var(--bg-glass, #1e1f22)",
            border: "1px solid rgba(139,92,246,0.3)",
            borderRadius: 14,
            boxShadow: "0 12px 36px rgba(0,0,0,0.5)",
            padding: 10,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", gap: 6 }}>
            {[
              ["server", `Servidor (${serverEmojis.length})`],
              ["bot", `Bot (${botEmojis.length})`],
              ["unicode", "Genéricos"],
            ].map(([id, lbl]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`tab-btn ${tab === id ? "active" : ""}`}
                style={{ fontSize: "0.72rem", padding: "5px 10px", flex: 1 }}
              >
                {lbl}
              </button>
            ))}
          </div>
          <input
            type="text"
            placeholder="Buscar…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ padding: "6px 10px", fontSize: "0.82rem" }}
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(8, 1fr)",
              gap: 4,
              overflowY: "auto",
              flex: 1,
              minHeight: 200,
            }}
          >
            {tab === "server" &&
              (loaded ? (
                filtered(serverEmojis).length === 0 ? (
                  <span style={{ gridColumn: "1 / -1", textAlign: "center", color: "var(--muted)", fontSize: "0.78rem", padding: 12 }}>
                    Sin emojis personalizados.
                  </span>
                ) : (
                  filtered(serverEmojis).map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => pick(e.tag)}
                      title={`:${e.name}:`}
                      style={{ padding: 4, background: "transparent", border: "none", cursor: "pointer", borderRadius: 6 }}
                    >
                      <img src={e.url} alt={e.name} style={{ width: 28, height: 28 }} />
                    </button>
                  ))
                )
              ) : (
                <span style={{ gridColumn: "1 / -1", textAlign: "center", color: "var(--muted)", fontSize: "0.78rem", padding: 12 }}>
                  Cargando…
                </span>
              ))}

            {tab === "bot" &&
              (loaded ? (
                filtered(botEmojis).length === 0 ? (
                  <span style={{ gridColumn: "1 / -1", textAlign: "center", color: "var(--muted)", fontSize: "0.78rem", padding: 12 }}>
                    Sin emojis del bot.
                  </span>
                ) : (
                  filtered(botEmojis).map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => pick(e.tag)}
                      title={`:${e.name}:`}
                      style={{ padding: 4, background: "transparent", border: "none", cursor: "pointer", borderRadius: 6 }}
                    >
                      <img src={e.url} alt={e.name} style={{ width: 28, height: 28 }} />
                    </button>
                  ))
                )
              ) : (
                <span style={{ gridColumn: "1 / -1", textAlign: "center", color: "var(--muted)", fontSize: "0.78rem", padding: 12 }}>
                  Cargando…
                </span>
              ))}

            {tab === "unicode" &&
              UNICODE_EMOJIS.filter((u) => !search || u.includes(search)).map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => pick(u)}
                  style={{ padding: 4, background: "transparent", border: "none", cursor: "pointer", fontSize: "1.4rem", borderRadius: 6 }}
                >
                  {u}
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
