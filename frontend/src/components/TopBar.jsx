/**
 * Thanh trên cùng: logo LexBot, badges trạng thái, avatar + logout
 * — Áp dụng design system từ demo.jsx (dark mode + glassmorphism) —
 */
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function TopBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  // lấy chữ cái đầu của username
  const initial = user?.username ? user.username[0].toUpperCase() : 'U';

  return (
    <header className="top-bar">
      <div className="top-bar-left">
        <button type="button" className="icon-btn" aria-label="Menu">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>

        {/* Logo */}
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

        {/* User info + logout */}
        {user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{ fontSize: '0.82rem', color: '#94a3b8' }}>{user.username}</span>
            <button
              id="logout-btn"
              onClick={handleLogout}
              title="Đăng xuất"
              style={{
                background: 'rgba(239,68,68,0.12)',
                border: '1px solid rgba(239,68,68,0.25)',
                borderRadius: '8px',
                color: '#f87171',
                fontSize: '0.78rem',
                fontWeight: '600',
                padding: '0.35rem 0.75rem',
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
              onMouseEnter={e => e.target.style.background = 'rgba(239,68,68,0.22)'}
              onMouseLeave={e => e.target.style.background = 'rgba(239,68,68,0.12)'}
            >
              Đăng xuất
            </button>
          </div>
        )}

        {/* Avatar */}
        <div className="avatar" aria-hidden="true">
          <span>{initial}</span>
        </div>
      </div>
    </header>
  );
}

export default TopBar;
