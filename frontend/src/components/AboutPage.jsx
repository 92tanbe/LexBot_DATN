/**
 * Tab "Kiến trúc hệ thống" — Sao chép từ demo.jsx
 * Hiển thị Architecture cards, Flow diagram, và Data stats
 */
const ARCH_CARDS = [
  {
    icon: "📁", title: "Data Sources", color: "#6366f1",
    items: ["BLHS 2025 (CSV)", "Nghị định giao thông (CSV)", "Văn bản pháp luật khác"],
  },
  {
    icon: "🔄", title: "ETL Pipeline", color: "#0ea5e9",
    items: ["Parse CSV → Graph", "Chunk text → Vector", "Index relationships", "Update realtime"],
  },
  {
    icon: "🗄️", title: "Neo4j Graph DB", color: "#10b981",
    items: ["Knowledge Graph", "Cypher queries", "Graph algorithms", "Full-text search"],
  },
  {
    icon: "🔍", title: "RAG Engine", color: "#f59e0b",
    items: ["Vector embeddings", "Semantic search", "Graph traversal", "Context assembly"],
  },
  {
    icon: "🤖", title: "LLM (Claude)", color: "#ef4444",
    items: ["Phân tích tình huống", "Tra cứu điều luật", "Tổng hợp phán quyết", "Giải thích pháp lý"],
  },
  {
    icon: "💬", title: "Chatbot UI", color: "#8b5cf6",
    items: ["React Interface", "Real-time chat", "Visualization", "Export báo cáo"],
  },
];

const FLOW_STEPS = [
  { step: "1", icon: "💬", text: "Người dùng mô tả tình huống vi phạm" },
  { step: "2", icon: "🧠", text: "NLP trích xuất: loại phương tiện, hành vi, hậu quả" },
  { step: "3", icon: "🔍", text: "Vector search tìm điều luật tương tự trong Neo4j" },
  { step: "4", icon: "🗄️", text: "Graph traversal: từ HanhVi → Dieu → HinhPhat" },
  { step: "5", icon: "⚖️", text: "LLM tổng hợp, xác định loại xử phạt (hành chính/hình sự/cả hai)" },
  { step: "6", icon: "📋", text: "Trả về kết quả phân tích chi tiết với điều luật cụ thể" },
];

const DATA_STATS = [
  { num: "3,633", label: "Điều khoản BLHS",    color: "#6366f1", icon: "📕" },
  { num: "1,052", label: "Quy định hành chính", color: "#0ea5e9", icon: "🚦" },
  { num: "~500",  label: "Nodes HanhVi",        color: "#10b981", icon: "🔗" },
  { num: "~2,000",label: "Relationships",        color: "#f59e0b", icon: "⚡" },
];

function AboutPage() {
  return (
    <div className="ab-page">
      <div className="tab-page-header">
        <h2 className="tab-page-title">🏗️ Kiến trúc hệ thống</h2>
        <p className="tab-page-desc">
          LexBot sử dụng kiến trúc RAG kết hợp Knowledge Graph để phân tích và tra cứu pháp luật chính xác.
        </p>
      </div>

      {/* ── Architecture cards ── */}
      <div className="ab-arch-grid">
        {ARCH_CARDS.map((card, i) => (
          <div
            key={i}
            className="ab-arch-card"
            style={{ "--card-color": card.color }}
          >
            <div className="ab-arch-card__icon">{card.icon}</div>
            <div className="ab-arch-card__title">{card.title}</div>
            <ul className="ab-arch-card__list">
              {card.items.map((item, j) => (
                <li key={j} className="ab-arch-card__item">
                  <span className="ab-arch-card__bullet">▸</span> {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* ── Flow diagram ── */}
      <div className="ab-flow-section">
        <h3 className="tab-section-title">🔄 Luồng xử lý tình huống</h3>
        <div className="ab-flow-steps">
          {FLOW_STEPS.map((s, i) => (
            <div key={i} className="ab-flow-step-wrap">
              <div className="ab-flow-step">
                <div className="ab-flow-step__num">{s.step}</div>
                <div className="ab-flow-step__icon">{s.icon}</div>
                <div className="ab-flow-step__text">{s.text}</div>
              </div>
              {i < FLOW_STEPS.length - 1 && (
                <div className="ab-flow-arrow">→</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Data stats ── */}
      <div className="ab-stats-section">
        <h3 className="tab-section-title">📊 Thống kê dữ liệu</h3>
        <div className="ab-stats-grid">
          {DATA_STATS.map((s, i) => (
            <div
              key={i}
              className="ab-stat-card"
              style={{ "--stat-color": s.color }}
            >
              <div className="ab-stat-card__icon">{s.icon}</div>
              <div className="ab-stat-card__num">{s.num}</div>
              <div className="ab-stat-card__label">{s.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default AboutPage;
