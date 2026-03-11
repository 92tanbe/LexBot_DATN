/**
 * Tab "Graph Schema" — Sao chép từ demo.jsx
 * Hiển thị đồ thị Neo4j và Cypher queries mẫu
 */
const CYPHER_QUERIES = [
  {
    title: "Load BLHS từ CSV → Neo4j",
    badge: "Import",
    badgeColor: "#6366f1",
    code: `LOAD CSV WITH HEADERS FROM 'file:///blhs_2025.csv' AS row
MERGE (lv:LuatVanBan {ten: 'BLHS 2025', loai: 'Hình sự'})
MERGE (ch:Chuong {ma: row.Chương, ten: row.\`Tên chương\`})
MERGE (d:Dieu {so: toInteger(row.\`Số điều\`), ten: row.\`Tiêu đề điều\`})
MERGE (k:Khoan {so: toInteger(row.\`Số khoản\`), noi_dung: row.\`Nội dung khoản\`})
MERGE (lv)-[:CO_CHUONG]->(ch)
MERGE (ch)-[:CO_DIEU]->(d)
MERGE (d)-[:CO_KHOAN]->(k)`,
  },
  {
    title: "Tra cứu mức phạt theo hành vi",
    badge: "Query",
    badgeColor: "#10b981",
    code: `MATCH (hv:HanhVi {ten: 'Lái xe say rượu'})-[:BI_XU_PHAT_THEO]->(d:Dieu)
-[:QUY_DINH_HINH_PHAT]->(hp:HinhPhat)
RETURN hv.ten AS HanhVi,
       d.so AS DieuLuat, d.ten AS TenDieu,
       hp.loai AS LoaiPhat,
       hp.muc_toi_thieu AS TuMuc,
       hp.muc_toi_da AS DenMuc,
       hp.don_vi AS DonVi
ORDER BY hp.muc_toi_da DESC`,
  },
  {
    title: "Phân tích tình huống phức tạp",
    badge: "Analysis",
    badgeColor: "#f59e0b",
    code: `// Tìm tất cả điều luật liên quan đến tai nạn giao thông
MATCH path = (hv:HanhVi)-[:BI_XU_PHAT_THEO]->(d:Dieu)
             <-[:CO_DIEU]-(ch:Chuong)
             <-[:CO_CHUONG]-(lv:LuatVanBan)
WHERE hv.mo_ta CONTAINS 'giao thông' 
   OR hv.mo_ta CONTAINS 'tai nạn'
RETURN lv.ten, ch.ten, d.so, d.ten,
       collect(hv.ten) AS HanhViLienQuan
ORDER BY d.so`,
  },
  {
    title: "Import Nghị định giao thông",
    badge: "Import",
    badgeColor: "#6366f1",
    code: `LOAD CSV WITH HEADERS FROM 'file:///giaothong.csv' AS row
MERGE (lv:LuatVanBan {ten: 'Nghị định GT', loai: 'Hành chính'})
MERGE (hv:HanhVi {ten: row.\`Nội dung điểm\`})
  ON CREATE SET hv.muc_phat = row.\`Nội dung khoản\`
MERGE (d:Dieu {so: toInteger(row.\`Số điều\`), ten: row.\`Tiêu đề điều\`})
MERGE (hp:HinhPhat {loai: 'Phạt tiền', noi_dung: row.\`Nội dung khoản\`})
MERGE (hv)-[:BI_XU_PHAT_THEO]->(d)
MERGE (d)-[:QUY_DINH_HINH_PHAT]->(hp)`,
  },
];

const GRAPH_NODES = [
  [400, 210, "#6366f1", "⚖", "LuatVanBan", 62],
  [120, 110, "#0ea5e9", "📖", "Chuong",    46],
  [120, 310, "#10b981", "📄", "Dieu",      46],
  [680, 110, "#f59e0b", "🚨", "HanhVi",   46],
  [680, 310, "#ef4444", "🔒", "HinhPhat", 46],
  [250, 210, "#8b5cf6", "📝", "Khoan",    38],
  [550, 210, "#ec4899", "📌", "Diem",     38],
];

const GRAPH_EDGES = [
  [400, 210, 120, 110], [400, 210, 120, 310],
  [400, 210, 680, 110], [400, 210, 680, 310],
  [400, 210, 250, 210], [400, 210, 550, 210],
  [120, 110, 120, 310], [680, 110, 680, 310],
];

const REL_LABELS = [
  [260, 152, "CO_CHUONG"], [260, 272, "CO_DIEU"],
  [540, 152, "BI_XU_PHAT"], [540, 272, "QUY_DINH"],
  [322, 198, "CO_KHOAN"],  [478, 198, "CO_DIEM"],
];

function GraphSchema() {
  return (
    <div className="gs-page">
      <div className="tab-page-header">
        <h2 className="tab-page-title">🗄️ Neo4j Graph Database Schema</h2>
        <p className="tab-page-desc">
          Toàn bộ dữ liệu pháp luật được mô hình hóa thành đồ thị tri thức (Knowledge Graph)
          trong Neo4j, cho phép truy vấn quan hệ phức tạp giữa các điều luật.
        </p>
      </div>

      {/* ── Graph visualisation ── */}
      <div className="gs-graph-viz">
        <svg width="100%" height="420" viewBox="0 0 800 420">
          <defs>
            <filter id="node-glow">
              <feGaussianBlur stdDeviation="3" result="coloredBlur" />
              <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <marker id="gs-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="rgba(99,102,241,0.5)" />
            </marker>
            <linearGradient id="gs-edge-grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%"   stopColor="#6366f1" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.2" />
            </linearGradient>
          </defs>

          {/* Edges */}
          {GRAPH_EDGES.map(([x1, y1, x2, y2], i) => (
            <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke="url(#gs-edge-grad)" strokeWidth="1.5"
              strokeOpacity="0.55" strokeDasharray="6,3"
              markerEnd="url(#gs-arrow)" />
          ))}

          {/* Nodes */}
          {GRAPH_NODES.map(([x, y, color, icon, label, r], i) => (
            <g key={i} filter="url(#node-glow)">
              <circle cx={x} cy={y} r={r + 6} fill={color} fillOpacity="0.06" />
              <circle cx={x} cy={y} r={r}
                fill={color} fillOpacity="0.15"
                stroke={color} strokeWidth="1.8" />
              <text x={x} y={y - 6} textAnchor="middle" fontSize="20">{icon}</text>
              <text x={x} y={y + 15} textAnchor="middle" fontSize="11"
                fill={color} fontWeight="700"
                fontFamily="'Be Vietnam Pro', sans-serif">
                {label}
              </text>
            </g>
          ))}

          {/* Relationship labels */}
          {REL_LABELS.map(([x, y, label], i) => (
            <text key={i} x={x} y={y} textAnchor="middle" fontSize="9"
              fill="#64748b" fontStyle="italic"
              fontFamily="'Be Vietnam Pro', sans-serif">
              {label}
            </text>
          ))}
        </svg>
      </div>

      {/* ── Cypher queries ── */}
      <div className="gs-cypher-section">
        <h3 className="tab-section-title">📋 Cypher Queries mẫu</h3>
        <div className="gs-cypher-grid">
          {CYPHER_QUERIES.map((q, i) => (
            <div key={i} className="gs-cypher-card">
              <div className="gs-cypher-card__header">
                <span className="gs-cypher-card__title">{q.title}</span>
                <span
                  className="gs-cypher-card__badge"
                  style={{
                    color: q.badgeColor,
                    borderColor: q.badgeColor + "55",
                    background: q.badgeColor + "18",
                  }}
                >
                  {q.badge}
                </span>
              </div>
              <pre className="gs-code-block">{q.code}</pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default GraphSchema;
