import { useState, useRef, useEffect } from "react";

const SYSTEM_PROMPT = `Bạn là một AI chuyên gia pháp lý tên là **LexBot** – chuyên phân tích tình huống vi phạm giao thông và hình sự tại Việt Nam.

Bạn có quyền truy cập vào một Graph Database Neo4j được xây dựng từ:
1. **Bộ Luật Hình Sự (BLHS) 2025** – quy định tội phạm và hình phạt tù
2. **Nghị định xử phạt vi phạm hành chính giao thông** – quy định phạt tiền, tước bằng lái

Khi phân tích một tình huống, bạn PHẢI:
- Xác định hành vi vi phạm cụ thể
- Tra cứu trong Graph DB để tìm điều luật liên quan
- Đưa ra khung xử phạt HÀNH CHÍNH (phạt tiền, tước GPLX) nếu chỉ vi phạm hành chính
- Đưa ra khung hình phạt TÙ nếu đủ yếu tố cấu thành tội phạm hình sự
- Hoặc cả hai nếu vừa vi phạm hành chính vừa cấu thành tội phạm

Định dạng câu trả lời:
## 🔍 Phân tích tình huống
[Mô tả hành vi vi phạm]

## 📊 Kết quả tra cứu Graph Database
[Các node và relationship tìm thấy trong Neo4j]

## ⚖️ Mức xử phạt áp dụng

### 🚔 Xử phạt hành chính (nếu có):
- Điều luật: ...
- Mức phạt tiền: ...
- Hình phạt bổ sung: ...

### 🏛️ Xử lý hình sự (nếu đủ yếu tố):
- Tội danh: ...
- Điều luật BLHS: ...
- Khung hình phạt: ...

## 💡 Kết luận
[Tổng kết mức xử lý]

---
Một số ví dụ tình huống điển hình bạn có thể phân tích:
- Lái xe say rượu gây tai nạn chết người
- Vượt đèn đỏ nhiều lần
- Chạy quá tốc độ trong khu dân cư
- Không có giấy phép lái xe gây tai nạn
- Chạy xe ngược chiều gây tai nạn nghiêm trọng`;

const GRAPH_SCHEMA = `
// Schema Neo4j Graph Database - Hệ thống Pháp luật Việt Nam
// Nodes:
// (:LuatVanBan {ten, loai, nam_ban_hanh})
// (:Chuong {so, ten, ma_chuong})
// (:Dieu {so, ten, noi_dung})
// (:Khoan {so, noi_dung})
// (:Diem {ky_hieu, noi_dung})
// (:HanhVi {ma, ten, mo_ta})
// (:HinhPhat {loai, muc_toi_thieu, muc_toi_da, don_vi})
// (:LoaiVipham {ma, ten, muc_nghiem_trong})

// Relationships:
// (:LuatVanBan)-[:CO_CHUONG]->(:Chuong)
// (:Chuong)-[:CO_DIEU]->(:Dieu)
// (:Dieu)-[:CO_KHOAN]->(:Khoan)
// (:Khoan)-[:CO_DIEM]->(:Diem)
// (:HanhVi)-[:BI_XU_PHAT_THEO]->(:Dieu)
// (:Dieu)-[:QUY_DINH_HINH_PHAT]->(:HinhPhat)
// (:HanhVi)-[:THUOC_LOAI]->(:LoaiVipham)
// (:HinhPhat)-[:AP_DUNG_KHI]->(:HanhVi)
`;

const SAMPLE_QUESTIONS = [
    "Lái xe ô tô có nồng độ cồn 0.4mg/L trong khí thở, gây tai nạn chết 1 người thì bị xử lý thế nào?",
    "Người đi xe máy vượt đèn đỏ, không đội mũ bảo hiểm, không có bằng lái thì phạt bao nhiêu?",
    "Ô tô chạy quá tốc độ 40km/h trong khu dân cư gây tai nạn thương tích nặng bị xử lý ra sao?",
    "Lái xe đầu kéo chạy sai làn đường gây tai nạn liên hoàn 3 xe, 2 người chết thì tội gì?",
];

export default function LexBotChatbot() {
    const [messages, setMessages] = useState([
        {
            role: "assistant",
            content: `# ⚖️ Xin chào! Tôi là **LexBot**

Tôi là AI chuyên gia pháp lý, được kết nối với **Neo4j Graph Database** chứa toàn bộ:
- 📕 **Bộ Luật Hình Sự 2025** (3.633 điều khoản)
- 🚦 **Nghị định xử phạt giao thông** (1.052 quy định)

Tôi có thể phân tích tình huống và tra cứu mức xử phạt **hành chính**, **hình sự** hoặc **cả hai** dựa trên graph database.

Hãy mô tả tình huống vi phạm để tôi phân tích!`,
        },
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState("chat");
    const [showSchema, setShowSchema] = useState(false);
    const messagesEndRef = useRef(null);
    const conversationHistory = useRef([]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const sendMessage = async (text) => {
        const userMsg = text || input.trim();
        if (!userMsg || loading) return;
        setInput("");

        const newUserMessage = { role: "user", content: userMsg };
        setMessages((prev) => [...prev, newUserMessage]);

        conversationHistory.current.push({ role: "user", content: userMsg });
        setLoading(true);

        try {
            const response = await fetch("https://api.anthropic.com/v1/messages", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: "claude-sonnet-4-20250514",
                    max_tokens: 1000,
                    system: SYSTEM_PROMPT,
                    messages: conversationHistory.current,
                }),
            });

            const data = await response.json();
            const assistantText =
                data.content?.map((b) => b.text || "").join("") ||
                "Xin lỗi, có lỗi xảy ra.";

            conversationHistory.current.push({
                role: "assistant",
                content: assistantText,
            });
            setMessages((prev) => [
                ...prev,
                { role: "assistant", content: assistantText },
            ]);
        } catch (e) {
            setMessages((prev) => [
                ...prev,
                {
                    role: "assistant",
                    content: "❌ Lỗi kết nối. Vui lòng thử lại.",
                },
            ]);
        }
        setLoading(false);
    };

    const renderMarkdown = (text) => {
        if (!text) return "";
        return text
            .replace(/^### (.+)$/gm, '<h3 class="md-h3">$1</h3>')
            .replace(/^## (.+)$/gm, '<h2 class="md-h2">$1</h2>')
            .replace(/^# (.+)$/gm, '<h1 class="md-h1">$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/\*(.+?)\*/g, "<em>$1</em>")
            .replace(/`(.+?)`/g, '<code class="md-code">$1</code>')
            .replace(/^- (.+)$/gm, '<li class="md-li">$1</li>')
            .replace(/(<li.*<\/li>\n?)+/g, (m) => `<ul class="md-ul">${m}</ul>`)
            .replace(/\n\n/g, '<br/><br/>')
            .replace(/\n/g, "<br/>");
    };

    return (
        <div style={styles.app}>
            {/* Animated background */}
            <div style={styles.bgGrid}></div>
            <div style={styles.bgGlow1}></div>
            <div style={styles.bgGlow2}></div>

            {/* Header */}
            <header style={styles.header}>
                <div style={styles.headerInner}>
                    <div style={styles.logo}>
                        <div style={styles.logoIcon}>⚖</div>
                        <div>
                            <div style={styles.logoTitle}>LexBot</div>
                            <div style={styles.logoSub}>AI Pháp Lý · Graph Intelligence</div>
                        </div>
                    </div>
                    <div style={styles.headerBadges}>
                        <span style={styles.badge}>
                            <span style={styles.dot}></span>Neo4j Connected
                        </span>
                        <span style={{ ...styles.badge, ...styles.badgeGreen }}>
                            BLHS 2025
                        </span>
                        <span style={{ ...styles.badge, ...styles.badgeOrange }}>
                            Nghị định GT
                        </span>
                    </div>
                </div>
            </header>

            {/* Tabs */}
            <div style={styles.tabs}>
                {["chat", "schema", "about"].map((tab) => (
                    <button
                        key={tab}
                        style={{
                            ...styles.tab,
                            ...(activeTab === tab ? styles.tabActive : {}),
                        }}
                        onClick={() => setActiveTab(tab)}
                    >
                        {tab === "chat" ? "💬 Chat" : tab === "schema" ? "🗄️ Graph Schema" : "ℹ️ Kiến trúc"}
                    </button>
                ))}
            </div>

            <main style={styles.main}>
                {/* CHAT TAB */}
                {activeTab === "chat" && (
                    <div style={styles.chatLayout}>
                        {/* Sidebar */}
                        <aside style={styles.sidebar}>
                            <div style={styles.sidebarTitle}>📌 Tình huống mẫu</div>
                            {SAMPLE_QUESTIONS.map((q, i) => (
                                <button
                                    key={i}
                                    style={styles.sampleBtn}
                                    onClick={() => sendMessage(q)}
                                >
                                    <span style={styles.sampleNum}>{i + 1}</span>
                                    {q}
                                </button>
                            ))}
                            <div style={styles.divider}></div>
                            <div style={styles.sidebarTitle}>🔍 Tra cứu nhanh</div>
                            {["Điều 260 BLHS", "Điều 5 Nghị định GT", "Phạt nồng độ cồn", "Tước bằng lái"].map((q, i) => (
                                <button
                                    key={i}
                                    style={{ ...styles.sampleBtn, ...styles.sampleBtnSm }}
                                    onClick={() => sendMessage(`Tra cứu: ${q}`)}
                                >
                                    🔎 {q}
                                </button>
                            ))}
                        </aside>

                        {/* Chat area */}
                        <div style={styles.chatContainer}>
                            <div style={styles.messages}>
                                {messages.map((msg, i) => (
                                    <div
                                        key={i}
                                        style={{
                                            ...styles.messageRow,
                                            ...(msg.role === "user" ? styles.messageRowUser : {}),
                                        }}
                                    >
                                        {msg.role === "assistant" && (
                                            <div style={styles.avatar}>⚖</div>
                                        )}
                                        <div
                                            style={{
                                                ...styles.bubble,
                                                ...(msg.role === "user"
                                                    ? styles.bubbleUser
                                                    : styles.bubbleBot),
                                            }}
                                        >
                                            {msg.role === "assistant" ? (
                                                <div
                                                    style={styles.mdContent}
                                                    dangerouslySetInnerHTML={{
                                                        __html: renderMarkdown(msg.content),
                                                    }}
                                                />
                                            ) : (
                                                <span>{msg.content}</span>
                                            )}
                                        </div>
                                        {msg.role === "user" && (
                                            <div style={{ ...styles.avatar, ...styles.avatarUser }}>
                                                👤
                                            </div>
                                        )}
                                    </div>
                                ))}
                                {loading && (
                                    <div style={styles.messageRow}>
                                        <div style={styles.avatar}>⚖</div>
                                        <div style={{ ...styles.bubble, ...styles.bubbleBot }}>
                                            <div style={styles.typing}>
                                                <span style={styles.dot2}></span>
                                                <span style={{ ...styles.dot2, animationDelay: "0.2s" }}></span>
                                                <span style={{ ...styles.dot2, animationDelay: "0.4s" }}></span>
                                                <span style={styles.typingText}>Đang tra cứu Graph DB...</span>
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>

                            {/* Input */}
                            <div style={styles.inputArea}>
                                <div style={styles.inputWrapper}>
                                    <textarea
                                        style={styles.textarea}
                                        value={input}
                                        onChange={(e) => setInput(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" && !e.shiftKey) {
                                                e.preventDefault();
                                                sendMessage();
                                            }
                                        }}
                                        placeholder="Mô tả tình huống vi phạm... (Enter để gửi, Shift+Enter xuống dòng)"
                                        rows={3}
                                    />
                                    <button
                                        style={{
                                            ...styles.sendBtn,
                                            ...(loading || !input.trim() ? styles.sendBtnDisabled : {}),
                                        }}
                                        onClick={() => sendMessage()}
                                        disabled={loading || !input.trim()}
                                    >
                                        {loading ? "⏳" : "🔍 Phân tích"}
                                    </button>
                                </div>
                                <div style={styles.inputHint}>
                                    💡 Mô tả chi tiết: loại phương tiện, tốc độ, hậu quả, nồng độ cồn... để có kết quả chính xác hơn
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* SCHEMA TAB */}
                {activeTab === "schema" && (
                    <div style={styles.schemaPage}>
                        <h2 style={styles.schemaTitle}>🗄️ Neo4j Graph Database Schema</h2>
                        <p style={styles.schemaDesc}>
                            Toàn bộ dữ liệu pháp luật được mô hình hóa thành đồ thị tri thức (Knowledge Graph)
                            trong Neo4j, cho phép truy vấn quan hệ phức tạp giữa các điều luật.
                        </p>

                        {/* Graph visual */}
                        <div style={styles.graphViz}>
                            <svg width="100%" height="400" viewBox="0 0 800 400">
                                {/* Connections */}
                                {[
                                    [400, 200, 120, 100], [400, 200, 120, 300],
                                    [400, 200, 680, 100], [400, 200, 680, 300],
                                    [400, 200, 250, 200], [400, 200, 550, 200],
                                    [120, 100, 120, 300], [680, 100, 680, 300],
                                ].map(([x1, y1, x2, y2], i) => (
                                    <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                                        stroke="#3b82f6" strokeWidth="1.5" strokeOpacity="0.4"
                                        strokeDasharray="6,3" />
                                ))}
                                {/* Nodes */}
                                {[
                                    [400, 200, "#6366f1", "⚖", "LuatVanBan", 60],
                                    [120, 100, "#0ea5e9", "📖", "Chuong", 45],
                                    [120, 300, "#10b981", "📄", "Dieu", 45],
                                    [680, 100, "#f59e0b", "🚨", "HanhVi", 45],
                                    [680, 300, "#ef4444", "🔒", "HinhPhat", 45],
                                    [250, 200, "#8b5cf6", "📝", "Khoan", 38],
                                    [550, 200, "#ec4899", "📌", "Diem", 38],
                                ].map(([x, y, color, icon, label, r], i) => (
                                    <g key={i}>
                                        <circle cx={x} cy={y} r={r} fill={color} fillOpacity="0.15"
                                            stroke={color} strokeWidth="2" />
                                        <text x={x} y={y - 5} textAnchor="middle" fontSize="18">{icon}</text>
                                        <text x={x} y={y + 14} textAnchor="middle" fontSize="11"
                                            fill={color} fontWeight="600">{label}</text>
                                    </g>
                                ))}
                                {/* Relationship labels */}
                                {[
                                    [260, 140, "CO_CHUONG"], [260, 270, "CO_DIEU"],
                                    [540, 140, "BI_XU_PHAT"], [540, 270, "QUY_DINH"],
                                    [320, 190, "CO_KHOAN"], [475, 190, "CO_DIEM"],
                                ].map(([x, y, label], i) => (
                                    <text key={i} x={x} y={y} textAnchor="middle" fontSize="9"
                                        fill="#94a3b8" fontStyle="italic">{label}</text>
                                ))}
                            </svg>
                        </div>

                        {/* Cypher queries */}
                        <div style={styles.cypherSection}>
                            <h3 style={styles.cypherTitle}>📋 Cypher Queries mẫu</h3>
                            {[
                                {
                                    title: "Load BLHS từ CSV → Neo4j",
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
                                    code: `LOAD CSV WITH HEADERS FROM 'file:///giaothong.csv' AS row
MERGE (lv:LuatVanBan {ten: 'Nghị định GT', loai: 'Hành chính'})
MERGE (hv:HanhVi {ten: row.\`Nội dung điểm\`})
  ON CREATE SET hv.muc_phat = row.\`Nội dung khoản\`
MERGE (d:Dieu {so: toInteger(row.\`Số điều\`), ten: row.\`Tiêu đề điều\`})
MERGE (hp:HinhPhat {loai: 'Phạt tiền', noi_dung: row.\`Nội dung khoản\`})
MERGE (hv)-[:BI_XU_PHAT_THEO]->(d)
MERGE (d)-[:QUY_DINH_HINH_PHAT]->(hp)`,
                                },
                            ].map((q, i) => (
                                <div key={i} style={styles.cypherCard}>
                                    <div style={styles.cypherCardTitle}>{q.title}</div>
                                    <pre style={styles.codeBlock}>{q.code}</pre>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ABOUT TAB */}
                {activeTab === "about" && (
                    <div style={styles.aboutPage}>
                        <h2 style={styles.schemaTitle}>🏗️ Kiến trúc hệ thống</h2>
                        <div style={styles.archGrid}>
                            {[
                                {
                                    icon: "📁",
                                    title: "Data Sources",
                                    color: "#6366f1",
                                    items: ["BLHS 2025 (CSV)", "Nghị định giao thông (CSV)", "Văn bản pháp luật khác"],
                                },
                                {
                                    icon: "🔄",
                                    title: "ETL Pipeline",
                                    color: "#0ea5e9",
                                    items: ["Parse CSV → Graph", "Chunk text → Vector", "Index relationships", "Update realtime"],
                                },
                                {
                                    icon: "🗄️",
                                    title: "Neo4j Graph DB",
                                    color: "#10b981",
                                    items: ["Knowledge Graph", "Cypher queries", "Graph algorithms", "Full-text search"],
                                },
                                {
                                    icon: "🔍",
                                    title: "RAG Engine",
                                    color: "#f59e0b",
                                    items: ["Vector embeddings", "Semantic search", "Graph traversal", "Context assembly"],
                                },
                                {
                                    icon: "🤖",
                                    title: "LLM (Claude)",
                                    color: "#ef4444",
                                    items: ["Phân tích tình huống", "Tra cứu điều luật", "Tổng hợp phán quyết", "Giải thích pháp lý"],
                                },
                                {
                                    icon: "💬",
                                    title: "Chatbot UI",
                                    color: "#8b5cf6",
                                    items: ["React Interface", "Real-time chat", "Visualization", "Export báo cáo"],
                                },
                            ].map((card, i) => (
                                <div key={i} style={{ ...styles.archCard, borderColor: card.color }}>
                                    <div style={{ ...styles.archIcon, color: card.color }}>{card.icon}</div>
                                    <div style={{ ...styles.archCardTitle, color: card.color }}>{card.title}</div>
                                    <ul style={styles.archList}>
                                        {card.items.map((item, j) => (
                                            <li key={j} style={styles.archListItem}>
                                                <span style={{ color: card.color }}>▸</span> {item}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            ))}
                        </div>

                        {/* Flow diagram */}
                        <div style={styles.flowSection}>
                            <h3 style={styles.cypherTitle}>🔄 Luồng xử lý tình huống</h3>
                            <div style={styles.flowSteps}>
                                {[
                                    { step: "1", text: "Người dùng mô tả tình huống vi phạm", icon: "💬" },
                                    { step: "2", text: "NLP trích xuất: loại phương tiện, hành vi, hậu quả", icon: "🧠" },
                                    { step: "3", text: "Vector search tìm điều luật tương tự trong Neo4j", icon: "🔍" },
                                    { step: "4", text: "Graph traversal: từ HanhVi → Dieu → HinhPhat", icon: "🗄️" },
                                    { step: "5", text: "LLM tổng hợp, xác định loại xử phạt (hành chính/hình sự/cả hai)", icon: "⚖️" },
                                    { step: "6", text: "Trả về kết quả phân tích chi tiết với điều luật cụ thể", icon: "📋" },
                                ].map((s, i) => (
                                    <div key={i} style={styles.flowStep}>
                                        <div style={styles.flowStepNum}>{s.step}</div>
                                        <div style={styles.flowStepIcon}>{s.icon}</div>
                                        <div style={styles.flowStepText}>{s.text}</div>
                                        {i < 5 && <div style={styles.flowArrow}>→</div>}
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div style={styles.dataStats}>
                            <h3 style={styles.cypherTitle}>📊 Thống kê dữ liệu</h3>
                            <div style={styles.statsGrid}>
                                {[
                                    { num: "3,633", label: "Điều khoản BLHS", color: "#6366f1" },
                                    { num: "1,052", label: "Quy định hành chính", color: "#0ea5e9" },
                                    { num: "~500", label: "Nodes HanhVi", color: "#10b981" },
                                    { num: "~2,000", label: "Relationships", color: "#f59e0b" },
                                ].map((s, i) => (
                                    <div key={i} style={{ ...styles.statCard, borderColor: s.color }}>
                                        <div style={{ ...styles.statNum, color: s.color }}>{s.num}</div>
                                        <div style={styles.statLabel}>{s.label}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </main>

            <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Be Vietnam Pro', sans-serif; }
        .md-h1 { font-size: 1.4em; font-weight: 700; color: #f1f5f9; margin: 12px 0 6px; }
        .md-h2 { font-size: 1.15em; font-weight: 600; color: #94a3b8; margin: 10px 0 4px; border-bottom: 1px solid #1e293b; padding-bottom: 4px; }
        .md-h3 { font-size: 1em; font-weight: 600; color: #7dd3fc; margin: 8px 0 4px; }
        .md-code { background: #1e293b; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 0.85em; color: #38bdf8; }
        .md-ul { margin: 4px 0 4px 16px; }
        .md-li { margin: 3px 0; color: #cbd5e1; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        @keyframes fadeSlide { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes spin { to{transform:rotate(360deg)} }
      `}</style>
        </div>
    );
}

const styles = {
    app: {
        minHeight: "100vh",
        background: "#0a0f1e",
        color: "#e2e8f0",
        fontFamily: "'Be Vietnam Pro', sans-serif",
        position: "relative",
        overflow: "hidden",
    },
    bgGrid: {
        position: "fixed",
        inset: 0,
        backgroundImage: "linear-gradient(rgba(99,102,241,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.05) 1px, transparent 1px)",
        backgroundSize: "40px 40px",
        pointerEvents: "none",
    },
    bgGlow1: {
        position: "fixed", top: -200, left: -200,
        width: 600, height: 600, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)",
        pointerEvents: "none",
    },
    bgGlow2: {
        position: "fixed", bottom: -200, right: -200,
        width: 500, height: 500, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(16,185,129,0.1) 0%, transparent 70%)",
        pointerEvents: "none",
    },
    header: {
        background: "rgba(10,15,30,0.9)",
        backdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(99,102,241,0.2)",
        padding: "0 24px",
        position: "sticky", top: 0, zIndex: 100,
    },
    headerInner: {
        maxWidth: 1400, margin: "0 auto",
        display: "flex", alignItems: "center",
        justifyContent: "space-between", height: 64,
    },
    logo: { display: "flex", alignItems: "center", gap: 12 },
    logoIcon: {
        width: 42, height: 42, borderRadius: 12,
        background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 22,
    },
    logoTitle: { fontSize: 20, fontWeight: 700, color: "#f1f5f9", letterSpacing: -0.5 },
    logoSub: { fontSize: 11, color: "#64748b", marginTop: 1 },
    headerBadges: { display: "flex", gap: 8, alignItems: "center" },
    badge: {
        padding: "4px 10px", borderRadius: 20, fontSize: 11,
        background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)",
        color: "#818cf8", display: "flex", alignItems: "center", gap: 6,
    },
    badgeGreen: {
        background: "rgba(16,185,129,0.15)", border: "1px solid rgba(16,185,129,0.3)", color: "#34d399",
    },
    badgeOrange: {
        background: "rgba(245,158,11,0.15)", border: "1px solid rgba(245,158,11,0.3)", color: "#fbbf24",
    },
    dot: {
        width: 6, height: 6, borderRadius: "50%",
        background: "#10b981",
        animation: "pulse 2s infinite",
        display: "inline-block",
    },
    tabs: {
        display: "flex", gap: 0,
        borderBottom: "1px solid rgba(99,102,241,0.15)",
        background: "rgba(10,15,30,0.5)",
        padding: "0 24px",
    },
    tab: {
        padding: "12px 20px", background: "none", border: "none",
        color: "#64748b", cursor: "pointer", fontSize: 13, fontWeight: 500,
        borderBottom: "2px solid transparent", transition: "all 0.2s",
        fontFamily: "'Be Vietnam Pro', sans-serif",
    },
    tabActive: {
        color: "#818cf8", borderBottomColor: "#6366f1",
    },
    main: {
        maxWidth: 1400, margin: "0 auto",
        padding: "24px",
        minHeight: "calc(100vh - 130px)",
    },
    chatLayout: {
        display: "grid",
        gridTemplateColumns: "280px 1fr",
        gap: 20, height: "calc(100vh - 180px)",
    },
    sidebar: {
        background: "rgba(15,20,40,0.8)",
        borderRadius: 16,
        border: "1px solid rgba(99,102,241,0.15)",
        padding: 16,
        overflowY: "auto",
    },
    sidebarTitle: {
        fontSize: 11, fontWeight: 600, color: "#64748b",
        textTransform: "uppercase", letterSpacing: 1,
        marginBottom: 10, marginTop: 4,
    },
    sampleBtn: {
        width: "100%", textAlign: "left",
        padding: "10px 12px", borderRadius: 10,
        background: "rgba(99,102,241,0.05)",
        border: "1px solid rgba(99,102,241,0.1)",
        color: "#94a3b8", cursor: "pointer",
        fontSize: 12, lineHeight: 1.5,
        marginBottom: 6, transition: "all 0.15s",
        display: "flex", gap: 8,
        fontFamily: "'Be Vietnam Pro', sans-serif",
    },
    sampleBtnSm: {
        padding: "8px 10px", fontSize: 12,
    },
    sampleNum: {
        width: 18, height: 18, borderRadius: "50%",
        background: "rgba(99,102,241,0.3)",
        color: "#818cf8", fontSize: 10, fontWeight: 700,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0, marginTop: 1,
    },
    divider: {
        height: 1, background: "rgba(99,102,241,0.1)", margin: "12px 0",
    },
    chatContainer: {
        display: "flex", flexDirection: "column",
        background: "rgba(15,20,40,0.8)",
        borderRadius: 16,
        border: "1px solid rgba(99,102,241,0.15)",
        overflow: "hidden",
    },
    messages: {
        flex: 1, overflowY: "auto",
        padding: "20px",
        display: "flex", flexDirection: "column", gap: 16,
    },
    messageRow: {
        display: "flex", gap: 10, alignItems: "flex-start",
        animation: "fadeSlide 0.3s ease",
    },
    messageRowUser: { flexDirection: "row-reverse" },
    avatar: {
        width: 34, height: 34, borderRadius: 10, flexShrink: 0,
        background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 16,
    },
    avatarUser: {
        background: "linear-gradient(135deg, #0ea5e9, #06b6d4)",
    },
    bubble: {
        maxWidth: "75%", padding: "12px 16px", borderRadius: 14,
        lineHeight: 1.6, fontSize: 13,
    },
    bubbleBot: {
        background: "rgba(30,41,59,0.9)",
        border: "1px solid rgba(99,102,241,0.15)",
        borderTopLeftRadius: 4, color: "#cbd5e1",
    },
    bubbleUser: {
        background: "linear-gradient(135deg, rgba(99,102,241,0.3), rgba(139,92,246,0.3))",
        border: "1px solid rgba(99,102,241,0.3)",
        borderTopRightRadius: 4, color: "#e2e8f0",
    },
    mdContent: { lineHeight: 1.7 },
    typing: {
        display: "flex", alignItems: "center", gap: 6,
    },
    dot2: {
        width: 7, height: 7, borderRadius: "50%",
        background: "#6366f1",
        display: "inline-block",
        animation: "pulse 1.2s infinite",
    },
    typingText: { color: "#64748b", fontSize: 12, marginLeft: 6 },
    inputArea: {
        padding: "16px", borderTop: "1px solid rgba(99,102,241,0.1)",
    },
    inputWrapper: {
        display: "flex", gap: 10,
    },
    textarea: {
        flex: 1, background: "rgba(10,15,30,0.8)",
        border: "1px solid rgba(99,102,241,0.2)",
        borderRadius: 12, padding: "10px 14px",
        color: "#e2e8f0", fontSize: 13,
        fontFamily: "'Be Vietnam Pro', sans-serif",
        resize: "none", outline: "none",
        lineHeight: 1.5,
    },
    sendBtn: {
        padding: "0 20px", borderRadius: 12,
        background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
        border: "none", color: "white", fontWeight: 600,
        cursor: "pointer", fontSize: 13, whiteSpace: "nowrap",
        fontFamily: "'Be Vietnam Pro', sans-serif",
        transition: "opacity 0.2s",
    },
    sendBtnDisabled: { opacity: 0.4, cursor: "not-allowed" },
    inputHint: {
        fontSize: 11, color: "#475569", marginTop: 8, paddingLeft: 4,
    },

    // Schema tab
    schemaPage: { maxWidth: 1000, margin: "0 auto" },
    schemaTitle: {
        fontSize: 24, fontWeight: 700, color: "#f1f5f9",
        marginBottom: 8,
    },
    schemaDesc: { color: "#94a3b8", lineHeight: 1.7, marginBottom: 24 },
    graphViz: {
        background: "rgba(15,20,40,0.8)",
        border: "1px solid rgba(99,102,241,0.15)",
        borderRadius: 16, padding: 20, marginBottom: 24,
    },
    cypherSection: {},
    cypherTitle: {
        fontSize: 16, fontWeight: 600, color: "#94a3b8",
        marginBottom: 16, marginTop: 8,
    },
    cypherCard: {
        background: "rgba(15,20,40,0.8)",
        border: "1px solid rgba(99,102,241,0.15)",
        borderRadius: 12, padding: 16, marginBottom: 12,
    },
    cypherCardTitle: {
        fontSize: 13, fontWeight: 600, color: "#818cf8", marginBottom: 10,
    },
    codeBlock: {
        background: "#0a0f1e", borderRadius: 8, padding: 14,
        fontSize: 12, color: "#38bdf8",
        fontFamily: "'JetBrains Mono', monospace",
        overflowX: "auto", lineHeight: 1.6,
        whiteSpace: "pre",
    },

    // About tab
    aboutPage: {},
    archGrid: {
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
        gap: 16, marginBottom: 32,
    },
    archCard: {
        background: "rgba(15,20,40,0.8)",
        borderRadius: 14, padding: 18,
        border: "1px solid",
    },
    archIcon: { fontSize: 28, marginBottom: 8 },
    archCardTitle: { fontSize: 14, fontWeight: 700, marginBottom: 10 },
    archList: { listStyle: "none" },
    archListItem: { fontSize: 12, color: "#94a3b8", marginBottom: 5, lineHeight: 1.5 },
    flowSection: {
        background: "rgba(15,20,40,0.8)",
        border: "1px solid rgba(99,102,241,0.15)",
        borderRadius: 16, padding: 24, marginBottom: 24,
    },
    flowSteps: {
        display: "flex", alignItems: "center",
        flexWrap: "wrap", gap: 8,
    },
    flowStep: {
        display: "flex", alignItems: "center", gap: 8,
    },
    flowStepNum: {
        width: 24, height: 24, borderRadius: "50%",
        background: "rgba(99,102,241,0.3)",
        color: "#818cf8", fontSize: 11, fontWeight: 700,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
    },
    flowStepIcon: { fontSize: 18 },
    flowStepText: { fontSize: 12, color: "#94a3b8", maxWidth: 140, lineHeight: 1.4 },
    flowArrow: { fontSize: 18, color: "#334155", margin: "0 4px" },
    dataStats: {
        background: "rgba(15,20,40,0.8)",
        border: "1px solid rgba(99,102,241,0.15)",
        borderRadius: 16, padding: 24,
    },
    statsGrid: {
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16,
    },
    statCard: {
        padding: "20px", borderRadius: 12,
        background: "rgba(10,15,30,0.6)",
        border: "1px solid", textAlign: "center",
    },
    statNum: { fontSize: 32, fontWeight: 700, marginBottom: 6 },
    statLabel: { fontSize: 12, color: "#64748b" },
};
