/**
 * Thanh điều hướng bên trái + lịch sử chat theo tài khoản (JWT).
 */
import { useRef } from "react";
import { useAuth } from "../context/AuthContext";
import { useChatWorkspace } from "../context/ChatWorkspaceContext";
import { providerShortLabel } from "../utils/chatbotProvider";

const QUICK_LOOKUPS = [
  "Điều 260 BLHS",
  "Điều 5 Nghị định GT",
  "Phạt nồng độ cồn",
  "Tước bằng lái",
];

/** @param {string | undefined} iso */
function formatHistoryTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

/** @param {string} text @param {number} max */
function truncate(text, max) {
  const t = String(text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function Sidebar() {
  const { user } = useAuth();
  const historySectionRef = useRef(null);
  const {
    historyItems,
    historyLoading,
    historyOpening,
    historyError,
    selectedHistoryId,
    refreshHistoryList,
    loadHistoryEntry,
    startNewChat,
  } = useChatWorkspace();

  return (
    <aside className="sidebar">
      <nav className="sidebar-nav">
        <button
          type="button"
          className={`nav-item ${selectedHistoryId === null ? "nav-item-active" : ""}`}
          onClick={startNewChat}
        >
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </span>
          <span className="nav-text">Cuộc trò chuyện mới</span>
        </button>

        <button
          type="button"
          className="nav-item"
          onClick={() =>
            historySectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
          }
        >
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
          </span>
          <span className="nav-text">Lịch sử của tôi</span>
        </button>
      </nav>

      {/* Tra cứu nhanh */}
      <div className="sidebar-divider" />
      <h2 className="sidebar-section-title">🔍 Tra cứu nhanh</h2>
      <div style={{ padding: "0 12px", display: "flex", flexDirection: "column", gap: "5px" }}>
        {QUICK_LOOKUPS.map((q, i) => (
          <button key={i} type="button" className="nav-item" style={{ fontSize: "0.8rem", padding: "8px 12px" }}>
            <span style={{ color: "#6366f1" }}>🔎</span>
            <span className="nav-text">{q}</span>
          </button>
        ))}
      </div>

      {/* Lịch sử trò chuyện */}
      <div className="sidebar-divider" />
      <div className="sidebar-section" ref={historySectionRef}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingRight: "8px" }}>
          <h2 className="sidebar-section-title" style={{ flex: 1 }}>
            Cuộc trò chuyện
          </h2>
          {user && (
            <button
              type="button"
              className="sidebar-history-refresh"
              title="Tải lại danh sách"
              disabled={historyLoading}
              onClick={() => void refreshHistoryList()}
            >
              ⟳
            </button>
          )}
        </div>

        {!user && (
          <p className="sidebar-history-hint">Đăng nhập để xem lịch sử chat đã lưu trên tài khoản.</p>
        )}

        {user && historyError && (
          <p className="sidebar-history-error" role="alert">
            {historyError}
          </p>
        )}

        {user && historyLoading && historyItems.length === 0 && (
          <p className="sidebar-history-hint">Đang tải lịch sử…</p>
        )}

        <ul className="chat-list">
          {user &&
            historyItems.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`chat-list-item ${selectedHistoryId === item.id ? "chat-list-item--active" : ""}`}
                  disabled={historyOpening}
                  onClick={() => void loadHistoryEntry(item.id)}
                >
                  <span className="chat-list-item-title">{truncate(item.question, 52)}</span>
                  <span className="chat-list-item-meta">
                    {item.chatbot_provider && (
                      <span className="chat-list-item-provider">
                        {providerShortLabel(item.chatbot_provider)}
                      </span>
                    )}
                    {formatHistoryTime(item.created_at)}
                    {item.preview_answer ? ` · ${truncate(item.preview_answer, 36)}` : ""}
                  </span>
                </button>
              </li>
            ))}
        </ul>

        {user && !historyLoading && historyItems.length === 0 && !historyError && (
          <p className="sidebar-history-hint">Chưa có lượt chat nào được lưu.</p>
        )}
      </div>

      <div className="sidebar-footer">
        <button type="button" className="nav-item">
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </span>
          <span className="nav-text">Cài đặt và trợ giúp</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
