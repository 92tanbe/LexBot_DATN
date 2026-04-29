# Chatbot RAG BLHS

Hybrid Retrieval-Augmented Generation cho **Bộ luật Hình sự Việt Nam (BLHS 2025 hợp nhất)**, đi qua đủ 4 giai đoạn:

1. **Embedding & Hybrid Retrieval** — BKAI bi-encoder (vi) + Neo4j vector index + fulltext + graph traversal
2. **Query Understanding** — `underthesea` + LLM hybrid NER, Cypher generator có whitelist, Query decomposition
3. **Generation & Structured Output** — Cross-encoder reranker (`bge-reranker-v2-m3`) + Pydantic `CaseAnalysis` + GPT-4o-mini
4. **Serving & Evaluation** — FastAPI `/rag/query` + SSE streaming, Streamlit demo, RAGAS-style retrieval recall

## Kiến trúc

```
React frontend ─┐
                ├─► backend (FastAPI) /chat/query ─► chatbot service /rag/query ─► Neo4j (graph + vector)
Streamlit demo ─┘                                                     │
                                                                      └─► OpenAI GPT-4o-mini
```

## Cấu trúc thư mục

```
chatbot/
├── app/                         # FastAPI service (port 8001)
│   ├── core/                   # config, neo4j driver, logging
│   ├── models/                 # Pydantic schema (request/response + legal output)
│   ├── routers/                # /health, /readyz, /rag/query[/stream]
│   ├── nlp/                    # NER, decomposer, cypher generator
│   ├── retrievers/             # embedding, vector, fulltext, graph, hybrid (RRF), reranker
│   ├── pipeline/               # orchestrator, prompts, context builder
│   ├── postprocessing/         # citation validator
│   └── main.py
├── ingestion/                   # CLI script chunk + embed → Neo4j
│   ├── chunk_embed.py
│   └── verify_index.py
├── streamlit_app/app.py         # demo UI
├── eval/
│   ├── test_cases.yaml          # 30 case benchmark
│   └── ragas_eval.py            # retrieval recall + RAGAS hook
├── tests/                       # pytest (NER, retriever, validator, pipeline)
├── dataset/                     # đã có sẵn (deepseek_merged.json, notebook import)
├── import_blhs_neo4j.ipynb      # notebook import dữ liệu (đã có)
├── .env                         # NEO4J_URI / OPENAI_API_KEY
└── requirements.txt
```

## Cài đặt

```powershell
# Tạo venv (nếu chưa) và cài deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r chatbot/requirements.txt
```

> **Lưu ý**: Lần đầu chạy, `sentence-transformers` sẽ tải về 2 model:
> - BKAI bi-encoder (~500 MB)
> - bge-reranker-v2-m3 (~600 MB)
>
> Có thể đặt biến `EMBEDDING_DEVICE=cuda` trong `chatbot/.env` nếu có GPU.

## Biến môi trường (`chatbot/.env`)

Đã có sẵn:

```env
NEO4J_URI=neo4j+s://...
NEO4J_USER=...
NEO4J_PASSWORD=...
OPENAI_API_KEY=sk-...
```

Tùy chọn thêm:

```env
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=bkai-foundation-models/vietnamese-bi-encoder
EMBEDDING_DEVICE=cpu               # cpu | cuda
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ENABLE_RERANKER=true
RERANKER_TOP_K=8
TOP_K_DIEU=10
TOP_K_KHOAN=20
TOP_K_FULLTEXT=10
CANDIDATE_TOP_K=30
RRF_K=60
CHATBOT_PORT=8001
LOG_LEVEL=INFO
```

## Quy trình chạy lần đầu

### Bước 1 — Import dữ liệu vào Neo4j (đã có notebook)

```powershell
# Chạy notebook tạo graph: chatbot/import_blhs_neo4j.ipynb
```

Notebook đã import sẵn schema:

```
(Phan)-[:CO_CHUONG]->(Chuong)-[:CO_DIEU]->(DieuLuat)-[:CO_QUY_TAC]->(QuyTac)
                            |                              |
                       [:THUOC_NHOM]              [:CO_DIEU_KIEN] / [:CO_HINH_PHAT]
                            |                              |
                       (NhomToi)                  (DieuKien) / (HinhPhat)
```

Số liệu: 2 Phần · 25 Chương · 411 Điều · 1326 Quy tắc · 3121 Điều kiện.

### Bước 2 — Chunk + Embed (multi-level: Điều + Khoản)

```powershell
# Từ thư mục gốc repo
python -m chatbot.ingestion.chunk_embed --level all --smoke
```

Lệnh này sẽ:

- Tạo 2 vector index `dieu_embedding` (411 chunks) và `rule_embedding` (~1326 chunks)
- Ghi `embedding`, `chunk_text`, `chunk_token_count` lên chính node `DieuLuat`/`QuyTac`
- Smoke test: query `"cuop tai san co vu khi"` để xác nhận index OK

Tuỳ chọn:

```powershell
python -m chatbot.ingestion.chunk_embed --level dieu --limit 20  # debug nhanh 20 điều
python -m chatbot.ingestion.chunk_embed --level khoan            # chỉ Khoản
python -m chatbot.ingestion.verify_index --query "giet 2 nguoi"  # smoke riêng
```

### Bước 3 — Chạy FastAPI service (port 8001)

```powershell
# Từ thư mục gốc repo
uvicorn chatbot.app.main:app --host 0.0.0.0 --port 8001 --reload
```

Endpoints:

- `GET  /health` — liveness
- `GET  /readyz` — readiness (Neo4j, embedding, reranker, OpenAI)
- `POST /rag/query` — JSON `{question, top_k, include_debug}` → `ChatResponse`
- `POST /rag/query/stream` — SSE, mỗi sự kiện là 1 stage

Test nhanh bằng `curl`:

```powershell
curl -X POST http://127.0.0.1:8001/rag/query `
  -H "Content-Type: application/json" `
  -d '{"question":"Toi cuop 100 trieu thi bi xu the nao?","top_k":8,"include_debug":true}'
```

### Bước 4 — Streamlit demo

```powershell
streamlit run chatbot/streamlit_app/app.py
```

Mở `http://localhost:8501`. Trong sidebar:

- `mode = local`: import pipeline trực tiếp (debug nhanh, không cần FastAPI chạy)
- `mode = http`: gọi service FastAPI ở `http://127.0.0.1:8001`
- Toggle "Stream từng giai đoạn" để xem SSE events

### Bước 5 — Tích hợp với React + backend hiện có

Backend `backend/app/routers/chat.py` đã forward đến `http://127.0.0.1:8001/rag/query` (biến `CHATBOT_SERVICE_URL`).
Không cần sửa thêm — chạy backend cũ + chatbot service mới là frontend React đã hoạt động:

```powershell
# Terminal 1 — Chatbot RAG service
uvicorn chatbot.app.main:app --port 8001

# Terminal 2 — Backend chính
cd backend; uvicorn app.main:app --port 8000

# Terminal 3 — Frontend React
cd frontend; npm run dev
```

## Đánh giá pipeline

```powershell
python -m chatbot.eval.ragas_eval --report-out chatbot/eval/report.json
```

Báo cáo bao gồm:

- `recall_any@10` — top-k có ≥1 expected article
- `recall_full@10` — top-k chứa toàn bộ expected articles
- `citation_recall` — citation cuối cùng trùng expected articles
- `low_confidence_rate` — tỉ lệ case bị validator hạ confidence

## Pytest

```powershell
# Unit test (không cần Neo4j/OpenAI)
pytest chatbot/tests -m "not integration" -q

# Full test (cần Neo4j chạy + OPENAI_API_KEY)
pytest chatbot/tests -q
```

## Schema response chính

`ChatResponse` (xem `app/models/schemas.py`):

```jsonc
{
  "question": "...",
  "final_answer": "Markdown đã render",
  "structured": {                   // CaseAnalysis Pydantic
    "summary": "...",
    "actors": [
      {
        "name": "A",
        "vai_tro": "chinh pham",
        "toi_danh": [
          {
            "dieu": 168, "khoan": 2,
            "ten_toi": "Tội cướp tài sản",
            "vai_tro": "chinh pham",
            "tinh_tiet_tang_nang": ["Có vũ khí"],
            "hinh_phat": {"loai": "tu", "min": 7, "max": 15, "don_vi": "nam"},
            "citations": [{"article": 168, "clause": 2, "rule_id": "168_r2"}]
          }
        ]
      }
    ],
    "confidence": "high",
    "warnings": []
  },
  "citations": [...],
  "confidence": "high",
  "debug": { ... }                  // nếu include_debug=true
}
```

## Guardrail chống hallucination

`app/postprocessing/validator.py` đảm bảo:

- Mọi `Điều` trong output phải tồn tại trong `retrieved_chunks` hoặc trong Neo4j
- Mọi `rule_id` phải có thật, citation sai sẽ bị loại
- Khi có `Điều` không khớp → confidence tự động hạ xuống `low` + thêm `warnings`

## Deploy lên FastAPI Cloud

### Lưu ý về tài nguyên (đọc trước khi deploy)

Pipeline mặc định load 2 model nặng:

| Model | Dung lượng | Vai trò |
|---|---|---|
| `bkai-foundation-models/vietnamese-bi-encoder` | ~500 MB | Embedding query + chunk |
| `BAAI/bge-reranker-v2-m3` | ~2.27 GB | Cross-encoder rerank |

**Tổng RAM cần chạy: ~4-5 GB**, cold start ~30-60s lần đầu để tải model. Hãy đảm bảo tier FastAPI Cloud của bạn đủ:

- Free tier có thể OOM hoặc timeout
- Khuyến nghị tier có ít nhất **4 GB RAM**
- Nếu không, tắt reranker (`ENABLE_RERANKER=false`) để giảm xuống ~1 GB

### 1. Cài CLI và link project

```powershell
pip install fastapicloud
cd C:\Users\Admin\Desktop\DATN\chatbot
fastapicloud login
fastapicloud link        # tạo app mới hoặc link app có sẵn
```

Sau lệnh `link` sẽ có thư mục `chatbot/.fastapicloud/cloud.json` chứa `app_id` (đã có `.gitignore` chặn commit).

### 2. Set environment variables

Trong dashboard FastAPI Cloud → app vừa link → **Environment Variables**, paste tối thiểu:

```env
NEO4J_URI=neo4j+s://...
NEO4J_USER=...
NEO4J_PASSWORD=...
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
HF_TOKEN=hf_...                 # giảm rate limit khi tải BKAI/bge
ENABLE_RERANKER=false           # khuyến nghị tắt nếu RAM hạn chế
LOG_LEVEL=INFO
CHATBOT_CORS_ORIGINS=https://lex-bot-datn.vercel.app,http://localhost:5173
```

> Tham khảo đầy đủ tại [chatbot/.env.example](.env.example).

### 3. Deploy

```powershell
fastapicloud deploy
```

CLI sẽ tự detect [chatbot/main.py](main.py) làm entry point (đã re-export `app` từ `app.main`).

Theo dõi log build:

```powershell
fastapicloud logs --follow
```

Build thường mất 3-5 phút (cài torch, sentence-transformers, underthesea). Lần đầu start, BKAI và bge-reranker sẽ được tải xuống (~3 GB) → cold start lâu.

### 4. Verify deployment

Sau khi deploy xong, lấy URL từ dashboard (ví dụ `https://chatbot-rag-xyz.fastapicloud.dev`):

```powershell
curl https://chatbot-rag-xyz.fastapicloud.dev/readyz
# Kỳ vọng: {"neo4j":"ok","embedding_model":"...","openai_configured":true}

curl -X POST https://chatbot-rag-xyz.fastapicloud.dev/rag/query `
  -H "Content-Type: application/json" `
  -d '{"question":"Toi cuop 100 trieu thi bi xu the nao?","top_k":5}'
```

### 5. Cập nhật backend để forward sang URL mới

Trong dashboard FastAPI Cloud của **backend app** (đã có sẵn), set:

```env
CHATBOT_SERVICE_URL=https://chatbot-rag-xyz.fastapicloud.dev/rag/query
CHATBOT_TIMEOUT_SECONDS=120     # cold start có thể lâu
```

Frontend React `https://lex-bot-datn.vercel.app` không cần sửa code — vẫn gọi `backend/chat/query` như cũ.

### Các vấn đề thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Build fail "out of memory" khi pip install torch | Tier thấp | Nâng tier hoặc dùng `--index-url https://download.pytorch.org/whl/cpu` |
| App start xong rồi crash với SIGKILL | OOM khi load bge-reranker | Set `ENABLE_RERANKER=false` |
| Request đầu tiên timeout | Cold start tải model | Tăng `CHATBOT_TIMEOUT_SECONDS` ở backend lên 120s |
| `Rate limited by HF Hub` | Thiếu HF_TOKEN | Set HF_TOKEN trong env vars |
| `vector index not found` | Chưa chạy ingest | Chạy `python -m ingestion.chunk_embed --level all` từ máy local trước (Neo4j Aura share giữa local và cloud) |

## Troubleshooting

| Vấn đề | Cách xử lý |
| --- | --- |
| `Vector index không tồn tại` khi search | Chạy lại `python -m chatbot.ingestion.chunk_embed --level all` |
| `EMBEDDING_DIM` mismatch | Xoá vector index cũ rồi ingest lại với model mới |
| `OPENAI_API_KEY` rỗng | Pipeline tự fallback sang mode "low confidence" |
| Reranker chậm trên CPU | Đặt `ENABLE_RERANKER=false` để bỏ rerank, chỉ dùng RRF |
| `underthesea` import lỗi | Thử `pip install --upgrade underthesea`, không bắt buộc cho pipeline |
