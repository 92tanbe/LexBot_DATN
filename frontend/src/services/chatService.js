const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

/** @param {string} queryMode `"fast"` | `"thinking"` */
export async function sendChatQuery(question, queryMode = "fast") {
  const token = localStorage.getItem("lexbot_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const mode = queryMode === "thinking" ? "thinking" : "fast";

  const res = await fetch(`${API_BASE}/chat/query`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question, query_mode: mode }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Có lỗi xảy ra khi truy vấn API");
  return data;
}
