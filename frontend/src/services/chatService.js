const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function sendChatQuery(question) {
  const token = localStorage.getItem("lexbot_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}/chat/query`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Có lỗi xảy ra khi truy vấn API");
  return data;
}
