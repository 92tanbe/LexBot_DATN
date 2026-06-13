import { API_BASE } from "./apiBase.js";
import { parseResponseJson } from "./parseResponseJson.js";
import { sanitizeLegalChatAnswers } from "../utils/clarificationAnswers.js";

/** @param {unknown} detail */
function formatApiError(detail) {
  if (detail == null) return "Có lỗi xảy ra khi gọi API";
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    return detail.message;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function throwApiError(res, detail) {
  const err = new Error(formatApiError(detail));
  err.status = res.status;
  err.detail = detail;
  throw err;
}

/**
 * Danh sách server chatbot khả dụng.
 * @returns {Promise<{ providers: object[], default_provider: string }>}
 */
export async function fetchChatProviders() {
  const res = await fetch(`${API_BASE}/chat/providers`);
  const data = await parseResponseJson(res);
  if (!res.ok) throwApiError(res, data.detail);
  return data;
}

/**
 * Gửi câu hỏi qua LexBot API (proxy tới microservice chatbot được chọn).
 * @param {string} question
 * @param {"fast"|"thinking"} [queryMode]
 * @param {{ chatMode?: "tra_cuu_pdf" | "phan_tich", conversationId?: string|null, chatbotProvider?: "rag_v1"|"graph_v2" }} [opts]
 * @returns {Promise<object>}
 */
export async function sendChatQuery(question, queryMode = "fast", opts = {}) {
  const token = localStorage.getItem("lexbot_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const mode = queryMode === "thinking" ? "thinking" : "fast";
  const provider = opts.chatbotProvider === "graph_v2" ? "graph_v2" : "rag_v1";

  const body = {
    question,
    query_mode: mode,
    chatbot_provider: provider,
  };
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
  if (!res.ok) throwApiError(res, data.detail);
  return data;
}

/**
 * Gửi tin nhắn tới BLHS Graph legal chatbot nhiều lượt.
 * @param {string} message
 * @param {{ caseId?: string|null, caseVersion?: number|null, answers?: object[], topK?: number, includeDebug?: boolean, answerStyle?: "auto"|"balanced"|"conversational"|"brief"|"educational"|"structured", mode?: "auto"|"fast"|"thinking"|"agentic" }} [opts]
 * @returns {Promise<import("../schemas/chatSchemas.js").LegalChatResponse>}
 */
export async function sendLegalChatMessage(message, opts = {}) {
  const token = localStorage.getItem("lexbot_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const body = {
    message,
    case_id: opts.caseId || null,
    case_version: Number.isInteger(opts.caseVersion) ? opts.caseVersion : null,
    answers: sanitizeLegalChatAnswers(opts.answers),
    top_k: Number.isFinite(opts.topK) ? opts.topK : 8,
    include_debug: opts.includeDebug === true,
    answer_style: opts.answerStyle || "auto",
    mode: opts.mode || "auto",
  };

  const res = await fetch(`${API_BASE}/chat/legal`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throwApiError(res, data.detail);
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
  if (!res.ok) throwApiError(res, data.detail);
  return data;
}

/**
 * Chi tiết một lượt chat đã lưu.
 * @param {string} chatId Mongo ObjectId dạng string
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
  if (!res.ok) throwApiError(res, data.detail);
  return data;
}
