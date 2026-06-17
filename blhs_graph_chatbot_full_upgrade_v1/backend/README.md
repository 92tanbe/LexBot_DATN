# BLHS Graph Chatbot Backend

Backend FastAPI phân tích tình huống hình sự Việt Nam dựa trên Neo4j graph BLHS 2025 đã import sẵn. Neo4j là nguồn sự thật pháp lý; LLM chỉ dùng để trích xuất dữ kiện hoặc diễn giải context đã retrieve.

## Chạy

```powershell
cd backend
copy .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Chạy Backend Bằng Docker

Backend đọc cấu hình Neo4j Aura và OpenAI từ `backend/.env`.

```powershell
cd C:\Users\Admin\Downloads\2\blhs_graph_chatbot_full_upgrade_v1
docker compose up --build backend
```

Sau khi container chạy:

```text
API docs : http://127.0.0.1:8000/docs
UI demo  : http://127.0.0.1:8000/ui
Health   : http://127.0.0.1:8000/health
```

Nếu muốn chạy Neo4j local trong compose thay vì Neo4j Aura, bật profile riêng:

```powershell
docker compose --profile local-neo4j up --build
```

## Upload CSV Lên Neo4j Aura

Script `scripts/import_to_aura.py` đọc cấu hình Aura từ `backend/.env` và import dữ liệu trong `neo4j_import` bằng Neo4j driver. Mặc định script dùng `MERGE`, không xoá dữ liệu có sẵn.

```powershell
cd C:\Users\Admin\Downloads\2\blhs_graph_chatbot_full_upgrade_v1
python scripts\import_to_aura.py
```

Nếu muốn rebuild database Aura từ đầu, chỉ dùng khi chắc chắn target có thể xoá:

```powershell
python scripts\import_to_aura.py --reset
```

Nếu bạn mở `test_client.html` trực tiếp từ trình duyệt và gặp lỗi `OPTIONS ... 405`, backend này đã hỗ trợ CORS. Biến mặc định là:

```env
CORS_ALLOW_ORIGINS=*
```

Neo4j mặc định:

```text
bolt://localhost:7687
neo4j / password123456
database: neo4j
```

## Curl Test

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/articles/108
curl -X POST http://127.0.0.1:8000/search -H "Content-Type: application/json" -d "{\"query\":\"ma túy\",\"top_k\":10,\"search_type\":\"hybrid\",\"include_debug\":true}"
curl -X POST http://127.0.0.1:8000/normalize -H "Content-Type: application/json" -d "{\"text\":\"bay phòng, kẹo, khay\"}"
curl -X POST http://127.0.0.1:8000/analyze-scenario -H "Content-Type: application/json" -d "{\"scenario\":\"A 17 tuổi mua 2 viên thuốc lắc cho bạn dùng trong karaoke\",\"top_k\":8,\"include_debug\":true}"
```

## Multi-turn Legal Chat

Endpoint mới `/chat/legal` quản lý một phiên vụ việc bằng `case_id`. Nếu tình huống thiếu dữ kiện trọng yếu, bot trả về `status=collecting_facts`, danh sách `missing_facts` và `clarifying_questions` thay vì chốt tội danh/khoản. Khi người dùng gửi thêm thông tin với cùng `case_id`, hệ thống merge facts cũ/mới rồi mới chạy pipeline retrieval + reasoning nếu đủ dữ kiện.

```bash
curl -X POST http://127.0.0.1:8000/chat/legal -H "Content-Type: application/json" -d "{\"message\":\"A rủ B đi bay phòng, có ketamin và thuốc lắc.\",\"top_k\":8,\"include_debug\":true}"
```

Ví dụ phản hồi rút gọn khi thiếu dữ kiện:

```json
{
  "case_id": "uuid",
  "status": "collecting_facts",
  "missing_facts": [
    {"label": "Ma túy", "critical": true, "description": "Ma túy: thiếu khối lượng/hàm lượng hoặc số lượng để xác định khoản."}
  ],
  "clarifying_questions": ["Đã có kết luận giám định xác định loại chất ma túy chưa?"],
  "final_answer": "Chưa đủ dữ kiện để kết luận cuối cùng..."
}
```

Gửi lượt bổ sung:

```bash
curl -X POST http://127.0.0.1:8000/chat/legal -H "Content-Type: application/json" -d "{\"case_id\":\"<case_id từ lượt trước>\",\"message\":\"Có kết luận giám định, ketamine 1g, MDMA 0.5g, A đặt phòng và nhờ người mua, B cùng sử dụng.\"}"
```

### Structured clarification contract

`/chat/legal` hiện hỗ trợ câu hỏi làm rõ có cấu trúc để frontend dựng form radio, checkbox, số, ngày, text hoặc actor matrix. `clarifying_questions: list[str]` vẫn được giữ để tương thích client cũ; client mới nên đọc `clarification.questions`.

Lượt đầu:

```json
{
  "message": "Long nhờ Tân đặt phòng, thu giữ một gói nghi Ketamine và hai viên ma túy tổng hợp.",
  "top_k": 8,
  "include_debug": false
}
```

Phản hồi rút gọn:

```json
{
  "case_id": "uuid",
  "case_version": 1,
  "status": "collecting_facts",
  "missing_facts": [
    {
      "key": "exhibits.tablets.forensic_substance",
      "label": "Hoạt chất của viên nén",
      "critical": true,
      "description": "Tang vật và giám định: thiếu hoạt chất của viên nén theo kết luận giám định."
    }
  ],
  "clarification": {
    "type": "form",
    "question_set_id": "qs-uuid",
    "can_submit_partial": true,
    "questions": [
      {
        "id": "q_tablets_forensic_substance",
        "fact_path": "exhibits.tablets.forensic_substance",
        "group": "Tang vật và giám định",
        "text": "Kết luận giám định xác định hoạt chất trong hai viên nén là chất nào?",
        "input_type": "single_choice",
        "required": true,
        "critical": true,
        "options": [
          {"id": "mdma", "label": "MDMA"},
          {"id": "methamphetamine", "label": "Methamphetamine"},
          {"id": "ketamine", "label": "Ketamine"},
          {"id": "other", "label": "Chất khác", "requires_value": true, "value_type": "text"},
          {"id": "not_narcotic", "label": "Không phải chất ma túy"},
          {"id": "no_forensic_report", "label": "Chưa có kết luận giám định"},
          {"id": "unknown", "label": "Không biết"}
        ]
      }
    ]
  },
  "clarifying_questions": [
    "Kết luận giám định xác định hoạt chất trong hai viên nén là chất nào?"
  ],
  "final_answer": "Chưa đủ dữ kiện để kết luận cuối cùng."
}
```

Gửi option, không cần nhập message mới:

```json
{
  "case_id": "uuid",
  "case_version": 1,
  "message": "",
  "answers": [
    {
      "question_id": "q_tablets_forensic_substance",
      "selected_option_ids": ["mdma"],
      "value": null,
      "free_text": null
    }
  ]
}
```

Quy tắc tích hợp:

- `message` được rỗng khi `answers` không rỗng; cả hai cùng rỗng sẽ bị validation error.
- Client chỉ gửi `question_id`, `selected_option_ids`, `value`, `free_text`; không gửi `fact_path` hoặc fact patch.
- Server validate `question_id` và option theo question set đã phát hành cho đúng `case_id`.
- `case_version` phải khớp version hiện tại; version cũ trả HTTP 409.
- `question_set_id` là mã bộ câu hỏi server phát hành, dùng để debug/tracking; request hiện chỉ cần gửi `question_id`.
- `input_type` hỗ trợ: `single_choice`, `multi_choice`, `number`, `text`, `date`, `boolean`, `actor_matrix`.
- Session hiện là in-memory, phù hợp dev/demo. Khi deploy nhiều instance cần thay bằng Redis/PostgreSQL qua interface `session_store`.
- Backend nghiệp vụ nên lưu `case_id`, `case_version`, `question_set_id`, danh sách questions và gửi lại answers đúng option ID; frontend chỉ render form theo `clarification.questions`.

Tài liệu đầy đủ hơn: `docs/structured_clarification_api.md`.

## Test Cases Gợi Ý

```bash
curl -X POST http://127.0.0.1:8000/analyze-scenario -H "Content-Type: application/json" -d "{\"scenario\":\"A 15 tuổi giúp sức cho B che giấu tang vật sau khi phạm tội\",\"top_k\":8,\"include_debug\":true}"
curl -X POST http://127.0.0.1:8000/analyze-scenario -H "Content-Type: application/json" -d "{\"scenario\":\"A rủ B đi bay phòng, có ketamin và 2 viên thuốc lắc trong phòng karaoke\",\"top_k\":8,\"include_debug\":true}"
curl -X POST http://127.0.0.1:8000/analyze-scenario -H "Content-Type: application/json" -d "{\"scenario\":\"Người đủ 70 tuổi phạm tội và đã tự thú\",\"top_k\":8,\"include_debug\":true}"
curl -X POST http://127.0.0.1:8000/analyze-scenario -H "Content-Type: application/json" -d "{\"scenario\":\"A khai thác 2m3 gỗ nhóm IA\",\"top_k\":8,\"include_debug\":true}"
```

## Thuật Toán

- Fast response: chào hỏi, cảm ơn, ngoài phạm vi BLHS.
- Hybrid fact extraction: regex chạy mặc định, underthesea/LLM là optional.
- Query decomposition theo actor và vai trò.
- Query rewriting gồm original, action, actor, crime hint, article ref, substance, slang-normalized, quantity và HyDE rule-based.
- Retrieval: exact article, Neo4j fulltext/fallback CONTAINS, condition search, graph signal search, vector optional.
- RRF fusion: `sum(1 / (k + rank))`, mặc định `k=60`.
- Cross-encoder reranker optional.
- Legal matcher scoring minh bạch và reasoner phân loại crime/supporting/general rule.
- Validator chống hallucination theo điều luật, ngôn ngữ kết luận chắc chắn khi thiếu dữ kiện.
- Dialogue Manager cho `/chat/legal`: fact extraction, fact merge, missing fact detection, answer gate, session store in-memory.

## Giới Hạn

- Không import lại dữ liệu, không parse PDF, không dùng `deepseek_merged.json`.
- Vector search chỉ chạy nếu đã có embedding/index và `USE_VECTOR_SEARCH=true`.
- Reranker/underthesea/OpenAI đều optional; nếu thiếu model hoặc key, hệ thống fallback template.
- Session `/chat/legal` hiện lưu in-memory, phù hợp demo/dev và có thể thay bằng Redis/PostgreSQL sau.
- Kết quả là phân tích hỗ trợ, không thay thế kết luận điều tra/tòa án.
