import { useEffect, useRef, useState } from "react";
import { fetchChatProviders } from "../services/chatService";
import { providerLabel } from "../utils/chatbotProvider";

const FALLBACK_PROVIDERS = [
  {
    id: "rag_v1",
    name: "LexBot RAG v1",
    description: "Neo4j Aura #1 — RAG + embedding + PDF",
    modes: ["pdf", "fast", "thinking"],
    enabled: true,
    neo4j_database: "neo4j",
    neo4j_uri_hint: "",
  },
  {
    id: "graph_v2",
    name: "BLHS Graph v2",
    description: "Neo4j Aura #2 — graph-first trên Railway",
    modes: ["fast", "thinking"],
    enabled: true,
    neo4j_database: "blhsgraph",
    neo4j_uri_hint: "",
  },
];

/**
 * Dropdown chọn microservice chatbot (RAG v1 vs Graph v2).
 * @param {{ value: "rag_v1"|"graph_v2", onChange: (id: string) => void, disabled?: boolean }} props
 */
function ServerSelector({ value, onChange, disabled = false }) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState(FALLBACK_PROVIDERS);
  const rootRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    fetchChatProviders()
      .then((data) => {
        if (cancelled) return;
        const list = Array.isArray(data.providers) ? data.providers : [];
        if (list.length > 0) setProviders(list);
      })
      .catch(() => {
        /* giữ fallback */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onDocClick = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const current =
    providers.find((p) => p.id === value) ||
    providers.find((p) => p.id === "rag_v1") ||
    providers[0];

  const handlePick = (id) => {
    if (disabled || id === value) {
      setOpen(false);
      return;
    }
    onChange(id);
    setOpen(false);
  };

  return (
    <div className="server-selector" ref={rootRef}>
      <button
        type="button"
        className={`server-selector-trigger ${open ? "server-selector-trigger--open" : ""}`}
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="server-selector-dot" aria-hidden="true" />
        <span className="server-selector-text">
          <span className="server-selector-label">Server chatbot</span>
          <span className="server-selector-value">
            {current?.name || providerLabel(value)}
          </span>
        </span>
        <svg
          className={`server-selector-chevron ${open ? "server-selector-chevron--up" : ""}`}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="server-selector-menu" role="listbox" aria-label="Chọn server chatbot">
          {providers.map((p) => (
            <button
              key={p.id}
              type="button"
              role="option"
              aria-selected={p.id === value}
              className={`server-selector-option ${
                p.id === value ? "server-selector-option--active" : ""
              }`}
              onClick={() => handlePick(p.id)}
              disabled={p.enabled === false}
            >
              <div className="server-selector-option-head">
                <span className="server-selector-option-name">{p.name}</span>
                {p.id === value && (
                  <span className="server-selector-option-badge">Đang dùng</span>
                )}
              </div>
              {p.description && (
                <span className="server-selector-option-desc">{p.description}</span>
              )}
              {(p.neo4j_database || p.neo4j_uri_hint) && (
                <span className="server-selector-option-neo4j">
                  Neo4j: {p.neo4j_database || "neo4j"}
                  {p.neo4j_uri_hint ? ` @ ${p.neo4j_uri_hint}` : ""}
                </span>
              )}
              {Array.isArray(p.modes) && p.modes.length > 0 && (
                <div className="server-selector-option-modes">
                  {p.modes.map((mode) => (
                    <span key={mode} className="server-selector-mode-chip">
                      {mode}
                    </span>
                  ))}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default ServerSelector;
