const STORAGE_KEY = "lexbot_chatbot_provider";

/** @returns {"rag_v1"|"graph_v2"} */
export function loadStoredChatbotProvider() {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw === "graph_v2" ? "graph_v2" : "rag_v1";
}

/** @param {"rag_v1"|"graph_v2"} provider */
export function saveChatbotProvider(provider) {
  localStorage.setItem(STORAGE_KEY, provider === "graph_v2" ? "graph_v2" : "rag_v1");
}

/** @param {string} id */
export function providerLabel(id) {
  if (id === "graph_v2") return "BLHS Graph v2";
  return "LexBot RAG v1";
}

/** @param {string} id */
export function providerShortLabel(id) {
  if (id === "graph_v2") return "Graph v2";
  return "RAG v1";
}
