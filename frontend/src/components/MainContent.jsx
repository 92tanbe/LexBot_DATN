import { useState, useRef, useEffect } from 'react';
import { useChatWorkspace } from '../context/ChatWorkspaceContext';
import { sendChatQuery, sendLegalChatMessage } from '../services/chatService';
import BotAnswerContent from './BotAnswerContent';
import ServerSelector from './ServerSelector';
import GraphV2AnalysisPanel from './GraphV2AnalysisPanel';
import { providerShortLabel } from '../utils/chatbotProvider';

const GOI_Y = [
  { icon: 'sparkle', label: 'Phân tích vi phạm giao thông' },
  { icon: 'sparkle', label: 'Tra cứu điều luật BLHS' },
  { icon: 'sparkle', label: 'Mức phạt nồng độ cồn' },
  { icon: 'sparkle', label: 'Hình phạt tội hình sự' },
];

function getModeChipLabel(answerMode, chatbotProvider) {
  if (chatbotProvider === 'graph_v2') {
    if (answerMode === 'thinking') return 'Agentic · Hỏi làm rõ';
    return 'Auto · Tra cứu/Phân tích';
  }
  if (answerMode === 'pdf') return 'VB hợp nhất · PDF';
  if (answerMode === 'thinking') return 'Neo4j · Phân tích';
  return 'Neo4j · Tra cứu nhanh';
}

function getBotBadgeLabel(msg) {
  if (msg.caseStatus === 'collecting_facts') return 'Đang bổ sung dữ kiện';
  if (msg.caseStatus === 'insufficient_information') return 'Thiếu dữ kiện';
  if (msg.caseStatus === 'ready_to_answer' || msg.caseStatus === 'answered') {
    return 'Pháp lý nhiều lượt';
  }
  if (msg.chatbotProvider === 'graph_v2') {
    if (msg.graphMode === 'agentic' || msg.responseMode === 'thinking') {
      return 'Graph v2 · Agentic RAG';
    }
    return 'Graph v2 · Agentic RAG';
  }
  if (msg.answerMode === 'pdf') return 'PDF VB';
  if (msg.responseMode === 'thinking') return 'Thinking';
  return 'Neo4j nhanh';
}

function getLegalStatusText(status) {
  const labels = {
    collecting_facts: 'Chưa đủ dữ kiện để kết luận. Vui lòng bổ sung các thông tin bên dưới.',
    ready_to_answer: 'Câu trả lời pháp lý chính dựa trên dữ kiện đã cung cấp.',
    answered: 'Câu trả lời pháp lý chính dựa trên dữ kiện đã cung cấp.',
    insufficient_information: 'Backend chưa đủ dữ kiện để kết luận; nội dung dưới đây chỉ là phân tích sơ bộ.',
  };
  return labels[status] || '';
}

function shouldRenderFinalAnswer(msg) {
  if (msg.caseStatus === 'collecting_facts') return false;
  return Boolean(String(msg.content || '').trim());
}

function formatRoleLabel(role) {
  const labels = {
    chu_muu: 'Chủ mưu',
    giup_suc: 'Giúp sức',
    thuc_hanh: 'Thực hành',
    xui_giuc: 'Xúi giục',
    dong_pham: 'Đồng phạm',
    khong_pham_toi: 'Chưa đủ căn cứ phạm tội',
    can_dieu_tra_them: 'Cần điều tra thêm',
  };
  return labels[role] || role || 'Chưa xác định';
}

function formatCrimeGroupLabel(classification) {
  const labels = {
    toi_chinh: 'Tội chính',
    toi_phu: 'Tội phụ',
    toi_co_the_xem_xet_them: 'Tội có thể xem xét thêm',
  };
  return labels[classification] || 'Khả năng pháp lý';
}

function buildCrimeReference(crime) {
  const clauseText = crime?.clause ? `, khoản ${crime.clause}` : '';
  return `Điều ${crime?.article}${clauseText}`;
}

function getPeopleFromMessage(msg) {
  if (Array.isArray(msg.people) && msg.people.length > 0) return msg.people;
  if (Array.isArray(msg.caseAnalysis?.people) && msg.caseAnalysis.people.length > 0) {
    return msg.caseAnalysis.people;
  }
  return [];
}

function MainContent() {
  const {
    messages,
    setMessages,
    answerMode,
    setAnswerMode,
    chatbotProvider,
    setChatbotProvider,
    isLoading,
    setIsLoading,
    refreshHistoryList,
    setSelectedHistoryId,
    startNewChat,
    caseId,
    setCaseId,
  } = useChatWorkspace();
  const isGraphV2 = chatbotProvider === 'graph_v2';
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSend = async (text) => {
    const question = text || inputValue;
    if (!question.trim()) return;

    const modeUsed = answerMode === 'thinking' ? 'thinking' : 'fast';
    const chatModeOpt = {};
    if (!isGraphV2 && answerMode === 'pdf') {
      chatModeOpt.chatMode = 'tra_cuu_pdf';
    } else if (isGraphV2 && answerMode === 'thinking') {
      chatModeOpt.chatMode = 'phan_tich';
    }

    setSelectedHistoryId(null);

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question, answerMode, chatbotProvider },
    ]);
    setInputValue('');
    setIsLoading(true);

    try {
      const response = isGraphV2
        ? await sendLegalChatMessage(question, {
            caseId,
            topK: 8,
            includeDebug: answerMode === 'thinking',
            answerStyle: 'auto',
            mode: answerMode === 'thinking' ? 'agentic' : 'auto',
          })
        : await sendChatQuery(question, modeUsed, {
            ...chatModeOpt,
            chatbotProvider,
          });
      if (isGraphV2 && response.case_id) {
        setCaseId(response.case_id);
      }
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          content: response.final_answer,
          caseId: response.case_id || null,
          caseStatus: response.status || null,
          confidence: typeof response.confidence === 'number' ? response.confidence : null,
          explanation: response.explanation,
          hints: response.hints,
          rows: response.rows || [],
          people: response.people || [],
          caseAnalysis: response.case_analysis || null,
          exhibits: Array.isArray(response.facts?.exhibits) ? response.facts.exhibits : [],
          clarifyingQuestions: response.clarifying_questions || [],
          legalReasoning: response.legal_reasoning || [],
          missingFacts: response.missing_facts || [],
          candidateArticles: response.candidate_articles || [],
          citations: response.citations || [],
          warnings: response.warnings || [],
          responseMode: modeUsed,
          answerMode,
          chatbotProvider: isGraphV2 ? 'graph_v2' : response.chatbot_provider || chatbotProvider,
          graphMode: isGraphV2 ? response.graph_mode || 'agentic' : response.graph_mode || null,
        },
      ]);
      void refreshHistoryList();
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'bot', content: `Lỗi: ${error.message}`, isError: true },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <main className="main-content">
      
      {/* ── Chat History or Welcome Screen ── */}
      <div className="chat-history">
        {messages.length === 0 ? (
          <div className="welcome-block">
            <div className="welcome-icon" aria-hidden="true">
              <svg width="72" height="72" viewBox="0 0 72 72" fill="none">
                <defs>
                  <radialGradient id="icon-glow" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="rgba(99,102,241,0.4)" />
                    <stop offset="100%" stopColor="transparent" />
                  </radialGradient>
                  <linearGradient id="scale-grad" x1="0" y1="0" x2="72" y2="72" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#6366f1" />
                    <stop offset="0.5" stopColor="#8b5cf6" />
                    <stop offset="1" stopColor="#0ea5e9" />
                  </linearGradient>
                </defs>
                <circle cx="36" cy="36" r="36" fill="url(#icon-glow)" />
                <rect x="34" y="12" width="4" height="48" rx="2" fill="url(#scale-grad)" />
                <rect x="16" y="14" width="40" height="3" rx="1.5" fill="url(#scale-grad)" />
                <ellipse cx="24" cy="36" rx="10" ry="4" stroke="url(#scale-grad)" strokeWidth="2.5" fill="none" />
                <ellipse cx="48" cy="36" rx="10" ry="4" stroke="url(#scale-grad)" strokeWidth="2.5" fill="none" />
                <line x1="36" y1="14" x2="24" y2="32" stroke="url(#scale-grad)" strokeWidth="2" />
                <line x1="36" y1="14" x2="48" y2="32" stroke="url(#scale-grad)" strokeWidth="2" />
              </svg>
            </div>
            <h2 className="welcome-title">Xin chào! Tôi là LexBot</h2>
            <p className="welcome-subtitle">
              Chọn server chatbot và mô tả tình huống vi phạm để phân tích.
            </p>
            <p className="welcome-server-hint">
              Đang dùng: <strong>{providerShortLabel(chatbotProvider)}</strong>
            </p>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <div key={idx} className={`message-bubble ${msg.role === 'user' ? 'message-user' : 'message-bot'}`}>
                {msg.role === 'user' ? (
                  <div className="message-content message-user-wrap">
                    {msg.answerMode && (
                      <div
                        className={`user-mode-chip ${
                          msg.answerMode === 'thinking' ? 'user-mode-chip--thinking' : ''
                        }`}
                      >
                        {getModeChipLabel(msg.answerMode, msg.chatbotProvider || chatbotProvider)}
                      </div>
                    )}
                    <div>{msg.content}</div>
                  </div>
                ) : (
                  <div className="message-content">
                    <div className="message-bot-header">
                      <div className="message-bot-brand">
                        <div className="message-bot-avatar">AI</div>
                        <div>
                          <div className="message-bot-name">AI Luật</div>
                          <div className="message-bot-subtitle">Phân tích dựa trên dữ liệu pháp lý truy xuất được</div>
                        </div>
                      </div>
                      <span
                        className={`message-bot-badge ${
                          msg.answerMode === 'pdf'
                            ? 'message-bot-badge--pdf'
                            : msg.responseMode === 'thinking'
                              ? 'message-bot-badge--thinking'
                              : msg.chatbotProvider === 'graph_v2'
                                ? 'message-bot-badge--graph'
                                : ''
                        }`}
                      >
                        {getBotBadgeLabel(msg)}
                      </span>
                    </div>

                    <div className="message-answer">
                      {getLegalStatusText(msg.caseStatus) && (
                        <div className={`legal-status-note legal-status-note--${msg.caseStatus}`}>
                          {getLegalStatusText(msg.caseStatus)}
                          {msg.caseId ? <span> Mã vụ việc: {msg.caseId}</span> : null}
                        </div>
                      )}
                      {shouldRenderFinalAnswer(msg) && (
                        <BotAnswerContent text={msg.content} />
                      )}
                    </div>

                    {getPeopleFromMessage(msg).length > 0 && (
                      <div className="message-section">
                        <div className="message-section-title">Phân tích theo từng đối tượng</div>
                        {msg.caseAnalysis?.case_summary && (
                          <div className="case-summary-box">
                            <BotAnswerContent text={msg.caseAnalysis.case_summary} />
                          </div>
                        )}
                        <div className="person-analysis-grid">
                          {getPeopleFromMessage(msg).map((person, personIdx) => (
                            <article key={`${person.name || 'person'}-${personIdx}`} className="person-analysis-card">
                              <div className="person-analysis-header">
                                <div>
                                  <div className="person-analysis-name">{person.name || 'Chưa rõ tên'}</div>
                                  <div className="person-analysis-role">{formatRoleLabel(person.role)}</div>
                                </div>
                                <div className="person-analysis-confidence">
                                  Độ tin cậy {Math.round((person.confidence || 0) * 100)}%
                                </div>
                              </div>

{/* 
                              <div className="person-analysis-meta">
                                <span className="person-analysis-chip">Cầm ma túy: {formatTriState(person.direct_drug_contact)}</span>
                                <span className="person-analysis-chip">Hưởng lợi: {formatTriState(person.benefited)}</span>
                                <span className="person-analysis-chip">Biết mục đích: {formatTriState(person.knew_criminal_purpose)}</span>
                              </div>
                              */}

                              <div className="person-analysis-block">
                                <div className="person-analysis-label">Hành vi</div>
                                {Array.isArray(person.actions) && person.actions.length > 0 ? (
                                  <ul className="person-analysis-list">
                                    {person.actions.map((action, actionIdx) => (
                                      <li key={`${person.name || 'person'}-action-${actionIdx}`}>{action}</li>
                                    ))}
                                  </ul>
                                ) : (
                                  <div className="person-analysis-empty">Chưa có dữ kiện hành vi cụ thể.</div>
                                )}
                              </div>

                              <div className="person-analysis-block">
                                <div className="person-analysis-label">Tội danh có thể áp dụng</div>
                                {Array.isArray(person.possible_crimes) && person.possible_crimes.length > 0 ? (
                                  <div className="crime-analysis-list">
                                    {person.possible_crimes.map((crime, crimeIdx) => (
                                      <div key={`${person.name || 'person'}-crime-${crimeIdx}`} className="crime-analysis-item">
                                        <div className="crime-analysis-top">
                                          <span className="crime-analysis-tag">{formatCrimeGroupLabel(crime.classification)}</span>
                                          <span className="crime-analysis-reference">{buildCrimeReference(crime)}</span>
                                        </div>
                                        <div className="crime-analysis-name">{crime.crime_name}</div>
                                        {crime.basis && <div className="crime-analysis-basis">{crime.basis}</div>}
                                        {crime.penalty_range && <div className="crime-analysis-penalty">{crime.penalty_range}</div>}
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <div className="person-analysis-empty">Cần điều tra thêm.</div>
                                )}
                              </div>

                              {person.penalty_range && (
                                <div className="person-analysis-block">
                                  <div className="person-analysis-label">Khung hình phạt sơ bộ</div>
                                  <div className="person-analysis-penalty-summary">{person.penalty_range}</div>
                                </div>
                              )}

                              {Array.isArray(person.legal_articles) && person.legal_articles.length > 0 && (
                                <div className="person-analysis-block">
                                  <div className="person-analysis-label">Điều luật liên quan</div>
                                  <div className="person-analysis-meta">
                                    {person.legal_articles.map((article, articleIdx) => (
                                      <span key={`${person.name || 'person'}-article-${articleIdx}`} className="person-analysis-chip">
                                        {article}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {person.investigation_note && (
                                <div className="person-analysis-note">{person.investigation_note}</div>
                              )}
                            </article>
                          ))}
                        </div>

                        {Array.isArray(msg.caseAnalysis?.unresolved_facts) && msg.caseAnalysis.unresolved_facts.length > 0 && (
                          <div className="case-warning-box">
                            <strong>Cần điều tra thêm:</strong> {msg.caseAnalysis.unresolved_facts.join('; ')}
                          </div>
                        )}
                      </div>
                    )}

                    {msg.chatbotProvider === 'graph_v2' && (
                      <GraphV2AnalysisPanel message={msg} />
                    )}

                    {msg.explanation && (
                      <div className="message-explanation">
                        <strong>Lưu ý:</strong>{' '}
                        <BotAnswerContent variant="inline" text={msg.explanation} />
                      </div>
                    )}

                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="message-bubble message-bot typing-indicator">
                <span></span><span></span><span></span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* ── Input Area ── */}
      <div className="input-area">
        {(messages.length > 0 || caseId) && (
          <div className="chat-action-row">
            <button
              type="button"
              className="new-case-btn"
              onClick={startNewChat}
              disabled={isLoading}
            >
              Vụ việc mới
            </button>
            {caseId && (
              <span className="case-id-chip">case_id: {caseId}</span>
            )}
          </div>
        )}

        {messages.length === 0 && (
          <div className="suggestion-chips">
            {GOI_Y.map((item, i) => (
              <button key={i} type="button" className="chip" onClick={() => handleSend(item.label)}>
                {item.icon === 'sparkle' && (
                  <svg className="chip-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 2L13.5 8.5L20 10L13.5 11.5L12 18L10.5 11.5L4 10L10.5 8.5L12 2Z" />
                  </svg>
                )}
                {item.label}
              </button>
            ))}
          </div>
        )}

        <ServerSelector
          value={chatbotProvider}
          onChange={setChatbotProvider}
          disabled={isLoading}
        />

        <div className="query-mode-row" role="group" aria-label="Chế độ trả lời">
          {!isGraphV2 && (
            <button
              type="button"
              className={`query-mode-btn query-mode-btn--fast ${answerMode === 'pdf' ? 'query-mode-btn--active' : ''}`}
              onClick={() => setAnswerMode('pdf')}
              disabled={isLoading}
            >
              <span className="query-mode-btn-title">VB PDF</span>
              <span className="query-mode-btn-sub">Trích văn hợp nhất</span>
            </button>
          )}
          <button
            type="button"
            className={`query-mode-btn query-mode-btn--fast ${answerMode === 'fast' ? 'query-mode-btn--active' : ''}`}
            onClick={() => setAnswerMode('fast')}
            disabled={isLoading}
          >
            <span className="query-mode-btn-title">
              {isGraphV2 ? 'Auto' : 'Tra cứu nhanh'}
            </span>
            <span className="query-mode-btn-sub">
              {isGraphV2 ? 'Tra cứu/Phân tích' : 'Neo4j · embedding'}
            </span>
          </button>
          <button
            type="button"
            className={`query-mode-btn query-mode-btn--thinking ${answerMode === 'thinking' ? 'query-mode-btn--active' : ''}`}
            onClick={() => setAnswerMode('thinking')}
            disabled={isLoading}
          >
            <span className="query-mode-btn-title">Phân tích</span>
            <span className="query-mode-btn-sub">
              {isGraphV2 ? 'Agentic · Hỏi làm rõ' : 'Neo4j + LLM đầy đủ'}
            </span>
          </button>
        </div>

        <div className="input-box">
          <button type="button" className="input-box-icon" aria-label="Đính kèm">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>

          <textarea
            className="input-field"
            placeholder="Mô tả tình huống vi phạm..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={1}
          />

          <div className="input-box-actions">
            <button type="button" className="input-send-btn" onClick={() => handleSend()} disabled={isLoading || !inputValue.trim()}>
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24">
                <path d="M22 2L11 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

export default MainContent;
