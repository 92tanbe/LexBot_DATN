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
 * @typedef {"rag_v1"|"graph_v2"} ChatbotProvider
 */

/**
 * @typedef {"collecting_facts"|"ready_to_answer"|"answered"|"insufficient_information"} CaseStatus
 */

/**
 * @typedef {{
 *   key: string,
 *   label: string,
 *   description: string,
 *   critical?: boolean,
 *   domain?: string|null,
 *   question?: string|null,
 * }} MissingFactItem
 */

/**
 * Body POST /chat/legal.
 * @typedef {{
 *   message: string,
 *   case_id?: string|null,
 *   top_k?: number,
 *   include_debug?: boolean,
 *   answer_style?: "auto"|"balanced"|"conversational"|"brief"|"educational"|"structured",
 * }} LegalChatRequest
 */

/**
 * Response POST /chat/legal.
 * @typedef {{
 *   case_id: string,
 *   status: CaseStatus,
 *   facts: Record<string, unknown>,
 *   missing_facts: MissingFactItem[],
 *   clarifying_questions: string[],
 *   candidate_articles: unknown[],
 *   legal_reasoning: unknown[],
 *   final_answer: string,
 *   confidence: number,
 *   citations: unknown[],
 *   warnings: string[],
 *   debug?: Record<string, unknown>|null,
 * }} LegalChatResponse
 */

/**
 * Body POST /chat/query (LexBot API → forward RAG).
 * @typedef {{
 *   question: string,
 *   top_k?: number,
 *   query_mode?: QueryMode,
 *   chat_mode?: ChatMode,
 *   conversation_id?: string|null,
 *   chatbot_provider?: ChatbotProvider,
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
 *   facts?: {
 *     exhibits?: Array<{
 *       status: "seized"|"consumed"|"not_seized"|"mentioned"|string,
 *       description: string,
 *       quantity?: {
 *         value?: number,
 *         unit?: string,
 *         raw_text: string,
 *         object?: string,
 *       },
 *       source_text?: string,
 *     }>,
 *   },
 *   case_analysis?: Record<string, unknown>|null,
 * }} RagChatResponse
 */

export {};
