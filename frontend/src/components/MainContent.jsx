/**
 * Khu vực nội dung chính: lời chào, ô nhập, nút gợi ý
 * — Áp dụng design system từ demo.jsx (dark mode + glassmorphism) —
 */
const GOI_Y = [
  { icon: 'sparkle', label: 'Phân tích vi phạm giao thông' },
  { icon: 'sparkle', label: 'Tra cứu điều luật BLHS' },
  { icon: 'sparkle', label: 'Mức phạt nồng độ cồn' },
  { icon: 'sparkle', label: 'Hình phạt tội hình sự' },
];

function MainContent() {
  return (
    <main className="main-content">
      <div className="welcome-block">
        {/* Icon ⚖ giống demo.jsx */}
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
            {/* Glow halo */}
            <circle cx="36" cy="36" r="36" fill="url(#icon-glow)" />
            {/* Scale icon (cân pháp lý) */}
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

      <div className="input-area">
        <div className="input-box">
          {/* Plus / đính kèm */}
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
            aria-label="Nhập câu hỏi"
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

            {/* Send button */}
            <button type="button" className="input-send-btn" aria-label="Gửi">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24">
                <path d="M22 2L11 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>

        {/* Suggestion chips */}
        <div className="suggestion-chips">
          {GOI_Y.map((item, i) => (
            <button key={i} type="button" className="chip">
              {item.icon === 'sparkle' && (
                <svg className="chip-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L13.5 8.5L20 10L13.5 11.5L12 18L10.5 11.5L4 10L10.5 8.5L12 2Z" />
                </svg>
              )}
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}

export default MainContent;
