import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useAuth } from "./AuthContext";
import { fetchChatHistory, fetchChatHistoryById } from "../services/chatService";
import {
  loadStoredChatbotProvider,
  saveChatbotProvider,
} from "../utils/chatbotProvider";

const ChatWorkspaceContext = createContext(null);

/** @param {Record<string, unknown>} detail phản hồi GET /chat/history/:id */
function historyDetailToMessages(detail) {
  const r =
    detail.response && typeof detail.response === "object"
      ? detail.response
      : {};
  const chatMode = detail.chat_mode;
  const queryMode =
    detail.query_mode === "thinking" ? "thinking" : "fast";
  const chatbotProvider =
    detail.chatbot_provider === "graph_v2" ? "graph_v2" : "rag_v1";

  let answerMode = "fast";
  if (chatMode === "tra_cuu_pdf") answerMode = "pdf";
  else if (chatMode === "phan_tich") answerMode = "thinking";
  else if (queryMode === "thinking") answerMode = "thinking";
  else answerMode = "fast";

  const modeUsed = queryMode === "thinking" ? "thinking" : "fast";
  const structured =
    r.structured && typeof r.structured === "object" ? r.structured : null;

  return [
    {
      role: "user",
      content: String(detail.question || ""),
      answerMode,
      chatbotProvider,
    },
    {
      role: "bot",
      content: String(r.final_answer || ""),
      caseId: r.case_id || null,
      caseStatus: r.status || null,
      confidence: typeof r.confidence === "number" ? r.confidence : null,
      explanation: r.explanation,
      hints: r.hints,
      rows: Array.isArray(r.rows) ? r.rows : [],
      people: Array.isArray(r.people) ? r.people : [],
      caseAnalysis: r.case_analysis ?? structured,
      exhibits: Array.isArray(r.facts?.exhibits) ? r.facts.exhibits : [],
      clarifyingQuestions: Array.isArray(r.clarifying_questions) ? r.clarifying_questions : [],
      legalReasoning: Array.isArray(r.legal_reasoning) ? r.legal_reasoning : [],
      missingFacts: Array.isArray(r.missing_facts) ? r.missing_facts : [],
      candidateArticles: Array.isArray(r.candidate_articles) ? r.candidate_articles : [],
      citations: Array.isArray(r.citations) ? r.citations : [],
      warnings: Array.isArray(r.warnings) ? r.warnings : [],
      responseMode: chatMode === "phan_tich" ? "thinking" : modeUsed,
      answerMode,
      chatbotProvider: r.chatbot_provider || chatbotProvider,
      graphMode: r.graph_mode || null,
    },
  ];
}

export function ChatWorkspaceProvider({ children }) {
  const { user, token } = useAuth();
  const [messages, setMessages] = useState([]);
  const [answerMode, setAnswerMode] = useState("fast");
  const [chatbotProvider, setChatbotProviderState] = useState(loadStoredChatbotProvider);
  const [isLoading, setIsLoading] = useState(false);
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyOpening, setHistoryOpening] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState(null);
  const [caseId, setCaseId] = useState(null);

  const refreshHistoryList = useCallback(async () => {
    if (!token || !user) {
      setHistoryItems([]);
      return;
    }
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await fetchChatHistory({ skip: 0, limit: 50 });
      setHistoryItems(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : "Không tải được lịch sử");
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [token, user]);

  const setChatbotProvider = useCallback((provider) => {
    const next = provider === "graph_v2" ? "graph_v2" : "rag_v1";
    if (next === chatbotProvider) return;
    saveChatbotProvider(next);
    setChatbotProviderState(next);
    if (next === "graph_v2" && answerMode === "pdf") {
      setAnswerMode("fast");
    }
    setMessages([]);
    setSelectedHistoryId(null);
    setCaseId(null);
  }, [answerMode, chatbotProvider]);

  useEffect(() => {
    refreshHistoryList();
  }, [refreshHistoryList]);

  useEffect(() => {
    if (chatbotProvider === "graph_v2" && answerMode === "pdf") {
      setAnswerMode("fast");
    }
  }, [chatbotProvider, answerMode]);

  useEffect(() => {
    if (!user || !token) {
      setMessages([]);
      setHistoryItems([]);
      setSelectedHistoryId(null);
      setHistoryError(null);
      setCaseId(null);
    }
  }, [user, token]);

  const startNewChat = useCallback(() => {
    setMessages([]);
    setSelectedHistoryId(null);
    setCaseId(null);
  }, []);

  const loadHistoryEntry = useCallback(
    async (id) => {
      if (!token) return;
      setHistoryOpening(true);
      setHistoryError(null);
      try {
        const detail = await fetchChatHistoryById(id);
        setSelectedHistoryId(id);
        const msgs = historyDetailToMessages(detail);
        setMessages(msgs);
        setCaseId(msgs[1]?.caseId || null);
        const first = msgs[0];
        if (first && first.answerMode) {
          setAnswerMode(first.answerMode);
        }
        if (first && first.chatbotProvider) {
          setChatbotProviderState(
            first.chatbotProvider === "graph_v2" ? "graph_v2" : "rag_v1"
          );
          saveChatbotProvider(
            first.chatbotProvider === "graph_v2" ? "graph_v2" : "rag_v1"
          );
        }
      } catch (e) {
        setHistoryError(e instanceof Error ? e.message : "Không mở được lịch sử");
      } finally {
        setHistoryOpening(false);
      }
    },
    [token]
  );

  const value = useMemo(
    () => ({
      messages,
      setMessages,
      answerMode,
      setAnswerMode,
      chatbotProvider,
      setChatbotProvider,
      isLoading,
      setIsLoading,
      historyItems,
      historyLoading,
      historyOpening,
      historyError,
      selectedHistoryId,
      setSelectedHistoryId,
      refreshHistoryList,
      loadHistoryEntry,
      startNewChat,
      caseId,
      setCaseId,
    }),
    [
      messages,
      answerMode,
      chatbotProvider,
      isLoading,
      historyItems,
      historyLoading,
      historyOpening,
      historyError,
      selectedHistoryId,
      refreshHistoryList,
      loadHistoryEntry,
      startNewChat,
      setChatbotProvider,
      caseId,
    ]
  );

  return (
    <ChatWorkspaceContext.Provider value={value}>
      {children}
    </ChatWorkspaceContext.Provider>
  );
}

export function useChatWorkspace() {
  const ctx = useContext(ChatWorkspaceContext);
  if (!ctx) {
    throw new Error("useChatWorkspace phải nằm trong ChatWorkspaceProvider");
  }
  return ctx;
}
