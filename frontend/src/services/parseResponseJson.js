/**
 * Đọc body Response — tránh lỗi "Unexpected end of JSON input" khi body rỗng
 * hoặc server trả HTML/text (proxy lỗi, backend tắt, timeout).
 * @param {Response} res
 * @returns {Promise<Record<string, unknown>>}
 */
export async function parseResponseJson(res) {
  const text = await res.text();
  const trimmed = text.trim();
  if (!trimmed) {
    const hint =
      res.status === 502 || res.status === 503 || res.status === 504
        ? " Backend/chatbot có thể chưa chạy hoặc bị timeout."
        : "";
    throw new Error(
      `Phản hồi rỗng (HTTP ${res.status}).${hint} Kiểm tra LexBot API (cổng 8000), chatbot RAG (8001) và proxy Vite.`,
    );
  }
  try {
    return JSON.parse(text);
  } catch {
    const snippet = trimmed.length > 280 ? `${trimmed.slice(0, 280)}…` : trimmed;
    throw new Error(`Không parse được JSON (HTTP ${res.status}): ${snippet}`);
  }
}
