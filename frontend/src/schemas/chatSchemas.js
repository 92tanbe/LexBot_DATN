/**
 * Kiểu dữ liệu (JSDoc) đồng bộ với backend/app/models/chat.py và phản hồi RAG.
 * Dùng để autofill IDE và kiểm tra hợp đồng API khi làm UI lịch sử chat.
 */

/**
 * @typedef {"fast"|"thinking"} QueryMode
 */

/**
 * @typedef {"tra_cuu_pdf"|"phan_tich"|null|undefined} ChatMode
 */

/**
 * Body POST /chat/query (LexBot API → forward RAG).
 * @typedef {{
 *   question: string,
 *   top_k?: number,
 *   query_mode?: QueryMode,
 *   chat_mode?: ChatMode,
 *   conversation_id?: string|null,
 * }} ChatQueryRequestBody
 */

/**
 * Một dòng trong GET /chat/history.
 * @typedef {{
 *   id: string,
 *   user_id: string,
 *   question: string,
 *   preview_answer: string,
 *   query_mode: QueryMode,
 *   chat_mode: ChatMode,
 *   conversation_id?: string|null,
 *   created_at: string,
 * }} ChatHistoryItem
 */

/**
 * GET /chat/history/:id — đủ để render lại bubble bot (final_answer, structured, …).
 * @typedef {{
 *   id: string,
 *   user_id: string,
 *   question: string,
 *   query_mode: QueryMode,
 *   chat_mode: ChatMode,
 *   conversation_id?: string|null,
 *   created_at: string,
 *   response: RagChatResponse,
 * }} ChatHistoryDetail
 */

/**
 * GET /chat/history.
 * @typedef {{
 *   items: ChatHistoryItem[],
 *   total: number,
 *   skip: number,
 *   limit: number,
 * }} ChatHistoryListResponse
 */

/**
 * Phản hồi JSON từ chatbot RAG (và lưu trong MongoDB field `response`).
 * Một số trường chỉ có ở chế độ PDF hoặc pipeline mở rộng — optional.
 * @typedef {{
 *   question?: string,
 *   final_answer: string,
 *   structured?: Record<string, unknown>,
 *   citations?: unknown[],
 *   confidence?: "high"|"medium"|"low",
 *   debug?: Record<string, unknown>|null,
 *   explanation?: string,
 *   hints?: unknown,
 *   rows?: unknown[],
 *   people?: unknown[],
 *   case_analysis?: Record<string, unknown>|null,
 * }} RagChatResponse
 */

export {};
