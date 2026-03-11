# =============================================================================
# rag/rag_engine.py
# RAG Engine: kết hợp Neo4j Graph Search + Gemini LLM
# =============================================================================

import re
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import google.generativeai as genai
from config.settings import GEMINI
from graph.neo4j_service import Neo4jService


# Cấu hình Gemini
genai.configure(api_key=GEMINI.api_key)


# Prompt hướng dẫn LLM cách dùng kết quả từ Graph DB
SYSTEM_PROMPT = """Bạn là LexBot – AI chuyên gia pháp lý Việt Nam.

Bạn được cung cấp kết quả TRA CỨU từ Neo4j Graph Database chứa:
- Bộ Luật Hình Sự 2025 (BLHS_2025)
- Nghị định xử phạt vi phạm hành chính giao thông (ND_GIAOTHONG)

## Nhiệm vụ:
Dựa trên [GRAPH_CONTEXT] được cung cấp, phân tích tình huống và đưa ra mức xử phạt.

## Quy tắc phân loại:
- **Chỉ phạt HÀNH CHÍNH**: vi phạm nhẹ, chưa gây hậu quả nghiêm trọng
- **Chỉ xử lý HÌNH SỰ**: hành vi đủ yếu tố cấu thành tội phạm theo BLHS
- **CẢ HAI**: vừa vi phạm hành chính vừa cấu thành tội phạm (phổ biến nhất)

## Định dạng trả lời BẮT BUỘC:
```
## 🔍 Phân tích hành vi
[Xác định các hành vi vi phạm cụ thể trong tình huống]

## 📊 Điều luật áp dụng (từ Graph DB)
[Liệt kê các điều luật tìm được, kèm số điều và tên]

## ⚖️ Mức xử phạt

### 🚔 Xử phạt hành chính
- Điều ..., Nghị định ...: [mức phạt tiền]
- Hình phạt bổ sung: [tước GPLX, tịch thu...]

### 🏛️ Truy cứu hình sự  
- Tội danh: ...
- Điều ..., BLHS 2025: [khung hình phạt tù]
- Điều kiện áp dụng: [khi nào bị truy tố]

## 💡 Kết luận
[Tóm tắt ngắn gọn]
```

Nếu Graph DB không tìm được kết quả liên quan, hãy nói rõ và dùng kiến thức pháp luật chung.
Luôn nhắc người dùng tham khảo luật sư hoặc cơ quan có thẩm quyền để có kết quả chính xác nhất.
"""


def format_graph_context(graph_results: dict) -> str:
    """
    Chuyển kết quả từ Neo4j thành đoạn text để đưa vào prompt cho LLM.
    Đây là bước 'Augmentation' trong RAG pipeline.
    """
    lines = ["=== KẾT QUẢ TRA CỨU TỪ NEO4J GRAPH DATABASE ===\n"]

    # Phần hình sự
    if graph_results.get("hinh_su"):
        lines.append("【 ĐIỀU LUẬT HÌNH SỰ (BLHS 2025) 】")
        for r in graph_results["hinh_su"]:
            lines.append(f"\n▸ Điều {r['so_dieu']}: {r['ten_dieu']}")
            if r.get("noi_dung"):
                nd = r["noi_dung"][:300] + "..." if len(r.get("noi_dung","")) > 300 else r.get("noi_dung","")
                lines.append(f"  Nội dung: {nd}")
            lines.append(f"  Chương: {r.get('chuong', '')}")
    else:
        lines.append("【 HÌNH SỰ 】Không tìm thấy điều luật phù hợp")

    lines.append("")

    # Phần hành chính
    if graph_results.get("hanh_chinh"):
        lines.append("【 QUY ĐỊNH HÀNH CHÍNH (Nghị định Giao thông) 】")
        for r in graph_results["hanh_chinh"]:
            lines.append(f"\n▸ Điều {r['so_dieu']}: {r['ten_dieu']}")
            if r.get("noi_dung_khoan"):
                nd = r["noi_dung_khoan"][:300] + "..." if len(r.get("noi_dung_khoan","")) > 300 else r.get("noi_dung_khoan","")
                lines.append(f"  Khoản {r.get('khoan','')}: {nd}")
            if r.get("noi_dung_diem"):
                nd = r["noi_dung_diem"][:200] + "..." if len(r.get("noi_dung_diem","")) > 200 else r.get("noi_dung_diem","")
                lines.append(f"  Điểm {r.get('diem','')}: {nd}")
    else:
        lines.append("【 HÀNH CHÍNH 】Không tìm thấy quy định phù hợp")

    lines.append("\n=== HẾT KẾT QUẢ TRA CỨU ===")
    return "\n".join(lines)


def extract_keywords(user_input: str) -> list[str]:
    """
    Trích xuất từ khóa pháp lý từ câu hỏi người dùng.
    """
    legal_keywords = [
        "say rượu", "nồng độ cồn", "tai nạn", "chết người", "thương tích",
        "vượt đèn đỏ", "quá tốc độ", "không bằng lái", "ngược chiều",
        "bỏ trốn", "gây thương tích", "giết người", "gây chết",
        "xe máy", "ô tô", "xe tải", "khu dân cư",
    ]

    found = []
    lower = user_input.lower()
    for kw in legal_keywords:
        if kw in lower:
            found.append(kw)

    words = re.findall(r'\b\w{4,}\b', lower)
    found.extend(words[:5])

    return list(set(found)) if found else user_input.split()[:6]


class RAGEngine:
    """
    RAG Pipeline chính:
    User Input → Extract Keywords → Neo4j Search → Format Context → Gemini LLM → Response
    """

    def __init__(self):
        self.neo4j = Neo4jService()
        # Tạo Gemini model với system prompt
        self._model = genai.GenerativeModel(
            model_name=GEMINI.model,
            system_instruction=SYSTEM_PROMPT,
            generation_config={"max_output_tokens": GEMINI.max_tokens},
        )
        # Chat session giữ lịch sử multi-turn tự động
        self._chat = self._model.start_chat(history=[])
        print("✅ RAG Engine khởi động (Gemini)")

    def close(self):
        self.neo4j.close()

    def query(self, user_input: str, verbose: bool = False) -> str:
        """
        Xử lý 1 câu hỏi từ người dùng.

        Luồng:
        1. Extract keywords từ input
        2. Query Neo4j Graph DB
        3. Format context từ graph results
        4. Gọi Gemini với context + conversation history (qua ChatSession)
        5. Trả về câu trả lời
        """

        # ── Bước 1: Extract keywords ──────────────────────────────
        keywords = extract_keywords(user_input)
        if verbose:
            print(f"\n🔑 Keywords: {keywords}")

        # ── Bước 2: Query Neo4j ───────────────────────────────────
        graph_results = self.neo4j.analyze_situation(keywords)
        if verbose:
            print(f"📊 Graph hits: {len(graph_results['hinh_su'])} HS, "
                  f"{len(graph_results['hanh_chinh'])} HC")

        # ── Bước 3: Format context cho LLM ───────────────────────
        graph_context = format_graph_context(graph_results)

        # ── Bước 4: Gọi Gemini LLM ───────────────────────────────
        augmented_user_msg = f"""[GRAPH_CONTEXT]
{graph_context}

[CÂU HỎI CỦA NGƯỜI DÙNG]
{user_input}
"""
        # ChatSession tự động lưu lịch sử multi-turn
        response = self._chat.send_message(augmented_user_msg)

        # ── Bước 5: Trả về ───────────────────────────────────────
        return response.text

    def reset_conversation(self):
        """Xóa lịch sử chat, bắt đầu cuộc hội thoại mới"""
        self._chat = self._model.start_chat(history=[])
        print("🔄 Đã reset lịch sử hội thoại")


# ==============================================================================
# Quick test
# ==============================================================================
if __name__ == "__main__":
    engine = RAGEngine()
    try:
        test_q = "Lái xe ô tô có nồng độ cồn 0.4mg/L, gây tai nạn chết 1 người thì bị xử lý thế nào?"
        print(f"\n❓ Câu hỏi: {test_q}\n")
        answer = engine.query(test_q, verbose=True)
        print("\n" + "="*60)
        print(answer)
    finally:
        engine.close()


