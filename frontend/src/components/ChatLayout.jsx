/**
 * Layout chính: TopBar + Tab nav + (Sidebar + MainContent | GraphSchema | AboutPage)
 * — Có 3 tabs giống demo.jsx: Chat · Graph Schema · Kiến trúc —
 */
import { useState } from 'react';
import TopBar from './TopBar';
import Sidebar from './Sidebar';
import MainContent from './MainContent';
import GraphSchema from './GraphSchema';
import AboutPage from './AboutPage';
import './ChatLayout.css';

const TABS = [
  { id: 'chat',   label: '💬 Chat' },
  { id: 'schema', label: '🗄️ Graph Schema' },
  { id: 'about',  label: 'ℹ️ Kiến trúc' },
];

function ChatLayout() {
  const [activeTab, setActiveTab] = useState('chat');

  return (
    <div className="chat-layout">
      <TopBar />

      {/* ── Tab bar ── */}
      <nav className="cl-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`cl-tab ${activeTab === t.id ? 'cl-tab--active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* ── Tab content ── */}
      <div className="cl-tab-content">
        {activeTab === 'chat' && (
          <div className="chat-layout-body">
            <Sidebar />
            <MainContent />
          </div>
        )}

        {activeTab === 'schema' && (
          <div className="cl-page-wrapper">
            <GraphSchema />
          </div>
        )}

        {activeTab === 'about' && (
          <div className="cl-page-wrapper">
            <AboutPage />
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatLayout;
