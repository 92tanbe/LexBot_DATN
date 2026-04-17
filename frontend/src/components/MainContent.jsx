import { useState, useRef, useEffect } from 'react';
import { sendChatQuery } from '../services/chatService';

const GOI_Y = [
  { icon: 'sparkle', label: 'Phân tích vi phạm giao thông' },
  { icon: 'sparkle', label: 'Tra cứu điều luật BLHS' },
  { icon: 'sparkle', label: 'Mức phạt nồng độ cồn' },
  { icon: 'sparkle', label: 'Hình phạt tội hình sự' },
];

function buildCitationLabel(row) {
  const clauseText = row?.clause ? `, khoản ${row.clause}` : '';
  return `BLHS 2015 Điều ${row?.article}${clauseText}`;
}

function buildLegalSummary(row) {
  const clauseText = row?.clause ? `khoản ${row.clause}` : 'điều luật liên quan';
  const logicText = row?.logic ? `${row.logic}.` : `quy định về ${row?.crime_name?.toLowerCase?.() || 'hành vi liên quan'}.`;
  return `Điều ${row?.article}, ${clauseText} ${logicText}`;
}

function getUniqueRows(rows = []) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = `${row.rule_id || ''}-${row.article || ''}-${row.clause || ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function MainContent() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
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

    // Add user message
    setMessages((prev) => [...prev, { role: 'user', content: question }]);
    setInputValue('');
    setIsLoading(true);

    try {
      const response = await sendChatQuery(question);
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          content: response.final_answer,
          explanation: response.explanation,
          hints: response.hints,
          rows: response.rows || [],
        },
      ]);
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
    <main className="main-content" style={{ display: 'flex', flexDirection: 'column' }}>
      
      {/* ── Chat History or Welcome Screen ── */}
      <div className="chat-history" style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {messages.length === 0 ? (
          <div className="welcome-block" style={{ margin: 'auto' }}>
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
            <p className="welcome-subtitle">Hãy mô tả tình huống vi phạm để tôi phân tích!</p>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <div key={idx} className={`message-bubble ${msg.role === 'user' ? 'message-user' : 'message-bot'}`}>
                {msg.role === 'user' ? (
                  <div className="message-content">{msg.content}</div>
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
                      <span className="message-bot-badge">Pro</span>
                    </div>

                    <div className="message-answer">
                      {String(msg.content || '')
                        .split('\n')
                        .filter(Boolean)
                        .map((paragraph, paragraphIdx) => (
                          <p key={paragraphIdx}>{paragraph}</p>
                        ))}
                    </div>

                    {msg.explanation && (
                      <div className="message-explanation">
                        <strong>Lưu ý:</strong> {msg.explanation}
                      </div>
                    )}

                    {getUniqueRows(msg.rows).length > 0 && (
                      <>
                        <div className="message-section">
                          <div className="message-section-title">Căn cứ pháp lý</div>
                          <ul className="legal-basis-list">
                            {getUniqueRows(msg.rows).map((row, rowIdx) => (
                              <li key={`${row.rule_id || rowIdx}`} className="legal-basis-item">
                                <span className="legal-basis-link">{buildCitationLabel(row)}</span>
                                <span className="legal-basis-text">{buildLegalSummary(row)}</span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="message-section">
                          <div className="message-section-title">Trích dẫn</div>
                          <div className="citation-chips">
                            {getUniqueRows(msg.rows).map((row, rowIdx) => (
                              <div key={`${row.rule_id || rowIdx}-citation`} className="citation-chip">
                                <span className="citation-chip-index">{rowIdx + 1}</span>
                                <span>{buildCitationLabel(row)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </>
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
      <div className="input-area" style={{ flexShrink: 0 }}>
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

        <div className="input-box">
          <button type="button" className="input-box-icon" aria-label="Đính kèm">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>

          <input
            type="text"
            className="input-field"
            placeholder="Mô tả tình huống vi phạm..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
          />

          <div className="input-box-actions">
            <button type="button" className="input-action-btn">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
              </svg>
              <span>Công cụ</span>
            </button>
            <button type="button" className="input-action-btn input-action-dropdown">
              <span>Nhanh</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
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
