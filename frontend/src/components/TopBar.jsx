/**
 * Thanh trên cùng: logo LexBot, badges trạng thái, avatar người dùng
 * — Áp dụng design system từ demo.jsx (dark mode + glassmorphism) —
 */
function TopBar() {
  return (
    <header className="top-bar">
      <div className="top-bar-left">
        <button type="button" className="icon-btn" aria-label="Menu">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>

        {/* Logo giống demo.jsx */}
        <div className="top-bar-logo-icon">⚖</div>
        <div>
          <h1 className="top-bar-logo">LexBot</h1>
          <div className="top-bar-logo-sub">AI Pháp Lý · Graph Intelligence</div>
        </div>
      </div>

      <div className="top-bar-right">
        {/* Badges trạng thái */}
        <div className="tb-badges">
          <span className="tb-badge tb-badge--indigo">
            <span className="tb-pulse-dot" />
            Neo4j Connected
          </span>
          <span className="tb-badge tb-badge--green">BLHS 2025</span>
          <span className="tb-badge tb-badge--amber">Nghị định GT</span>
        </div>

        {/* Avatar */}
        <div className="avatar" aria-hidden="true">
          <span>T</span>
        </div>
      </div>
    </header>
  );
}

export default TopBar;
