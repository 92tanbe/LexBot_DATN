/**
 * Thanh điều hướng bên trái
 * — Áp dụng design system từ demo.jsx (dark mode + glassmorphism) —
 */


const QUICK_LOOKUPS = [
  "Điều 260 BLHS",
  "Điều 5 Nghị định GT",
  "Phạt nồng độ cồn",
  "Tước bằng lái",
];

function Sidebar() {
  return (
    <aside className="sidebar">
      <nav className="sidebar-nav">
        <button type="button" className="nav-item nav-item-active">
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </span>
          <span className="nav-text">Cuộc trò chuyện mới</span>
        </button>

        <button type="button" className="nav-item">
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
          </span>
          <span className="nav-text">Nội dung của tôi</span>
        </button>
      </nav>



      {/* Tra cứu nhanh */}
      <div className="sidebar-divider" />
      <h2 className="sidebar-section-title">🔍 Tra cứu nhanh</h2>
      <div style={{ padding: '0 12px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
        {QUICK_LOOKUPS.map((q, i) => (
          <button key={i} type="button" className="nav-item" style={{ fontSize: '0.8rem', padding: '8px 12px' }}>
            <span style={{ color: '#6366f1' }}>🔎</span>
            <span className="nav-text">{q}</span>
          </button>
        ))}
      </div>

      {/* Lịch sử trò chuyện */}
      <div className="sidebar-divider" />
      <div className="sidebar-section">
        <h2 className="sidebar-section-title">Cuộc trò chuyện</h2>
        <ul className="chat-list">
          {/* sẽ được render động */}
        </ul>
      </div>

      <div className="sidebar-footer">
        <button type="button" className="nav-item">
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </span>
          <span className="nav-text">Cài đặt và trợ giúp</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
