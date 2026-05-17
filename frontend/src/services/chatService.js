import { API_BASE } from "./apiBase.js";
import { parseResponseJson } from "./parseResponseJson.js";

/** @param {unknown} detail */
function formatApiError(detail) {
  if (detail == null) return "Có lỗi xảy ra khi gọi API";
  if (typeof detail === "string") return detail;
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

/**
 * Gửi câu hỏi RAG qua LexBot API.
 * Kiểu phản hồi: xem typedef RagChatResponse trong `src/schemas/chatSchemas.js`.
 * @param {string} question
 * @param {"fast"|"thinking"} [queryMode]
 * @param {{ chatMode?: "tra_cuu_pdf" | "phan_tich", conversationId?: string|null }} [opts]
 * @returns {Promise<object>} payload JSON từ RAG (final_answer, structured, …)
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
  if (opts.conversationId) {
    body.conversation_id = opts.conversationId;
  }

  const res = await fetch(`${API_BASE}/chat/query`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throw new Error(formatApiError(data.detail));
  return data;
}

/**
 * Danh sách lịch sử chat (cần Bearer token).
 * @param {{ skip?: number, limit?: number, conversationId?: string|null }} [params]
 * @returns {Promise<{ items: object[], total: number, skip: number, limit: number }>}
 */
export async function fetchChatHistory(params = {}) {
  const token = localStorage.getItem("lexbot_token");
  if (!token) {
    throw new Error("Cần đăng nhập để xem lịch sử chat.");
  }
  const skip = Number(params.skip) || 0;
  const limit = Number(params.limit) || 20;
  const q = new URLSearchParams({ skip: String(skip), limit: String(limit) });
  if (params.conversationId) {
    q.set("conversation_id", params.conversationId);
  }
  const res = await fetch(`${API_BASE}/chat/history?${q.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throw new Error(formatApiError(data.detail));
  return data;
}

/**
 * Chi tiết một lượt chat đã lưu.
 * @param {string} chatId Mongo ObjectId dạng string
 * @returns {Promise<{ id: string, user_id: string, question: string, response: object, created_at: string, query_mode: string, chat_mode?: string|null, conversation_id?: string|null }>}
 */
export async function fetchChatHistoryById(chatId) {
  const token = localStorage.getItem("lexbot_token");
  if (!token) {
    throw new Error("Cần đăng nhập để xem lịch sử chat.");
  }
  const res = await fetch(`${API_BASE}/chat/history/${encodeURIComponent(chatId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throw new Error(formatApiError(data.detail));
  return data;
}
