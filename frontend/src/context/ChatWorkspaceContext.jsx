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
    },
    {
      role: "bot",
      content: String(r.final_answer || ""),
      explanation: r.explanation,
      hints: r.hints,
      rows: Array.isArray(r.rows) ? r.rows : [],
      people: Array.isArray(r.people) ? r.people : [],
      caseAnalysis: r.case_analysis ?? structured,
      responseMode: chatMode === "phan_tich" ? "thinking" : modeUsed,
      answerMode,
    },
  ];
}

export function ChatWorkspaceProvider({ children }) {
  const { user, token } = useAuth();
  const [messages, setMessages] = useState([]);
  const [answerMode, setAnswerMode] = useState("pdf");
  const [isLoading, setIsLoading] = useState(false);
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyOpening, setHistoryOpening] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState(null);

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

  useEffect(() => {
    refreshHistoryList();
  }, [refreshHistoryList]);

  useEffect(() => {
    if (!user || !token) {
      setMessages([]);
      setHistoryItems([]);
      setSelectedHistoryId(null);
      setHistoryError(null);
    }
  }, [user, token]);

  const startNewChat = useCallback(() => {
    setMessages([]);
    setSelectedHistoryId(null);
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
        const first = msgs[0];
        if (first && first.answerMode) {
          setAnswerMode(first.answerMode);
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
    }),
    [
      messages,
      answerMode,
      isLoading,
      historyItems,
      historyLoading,
      historyOpening,
      historyError,
      selectedHistoryId,
      refreshHistoryList,
      loadHistoryEntry,
      startNewChat,
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
