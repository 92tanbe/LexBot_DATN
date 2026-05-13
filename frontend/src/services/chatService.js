const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

/**
 * @param {string} queryMode `"fast"` | `"thinking"`
 * @param {{ chatMode?: "tra_cuu_pdf" | "phan_tich" }} [opts]
 */
export async function sendChatQuery(question, queryMode = "fast", opts = {}) {
  const token = localStorage.getItem("lexbot_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const mode = queryMode === "thinking" ? "thinking" : "fast";

  const body = { question, query_mode: mode };
  if (opts.chatMode) {
    body.chat_mode = opts.chatMode;
  }

  const res = await fetch(`${API_BASE}/chat/query`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Có lỗi xảy ra khi truy vấn API");
  return data;
}
