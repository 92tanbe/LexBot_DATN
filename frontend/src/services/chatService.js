const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function sendChatQuery(question) {
  const res = await fetch(`${API_BASE}/chat/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Có lỗi xảy ra khi truy vấn API");
  return data;
}
