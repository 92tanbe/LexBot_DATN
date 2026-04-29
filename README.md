# Vistral-Saul-VN

Vistral-Saul-VN là project hỏi đáp pháp luật tiếng Việt dựa trên RAG. Dữ liệu pháp luật được lưu trong corpus CSV, vectorize vào ChromaDB, sau đó API RAG retrieve căn cứ liên quan và gọi LLM để sinh câu trả lời.

## Cấu trúc chính

```text
backend/rag/                 RAG service, ChromaDB, Q&A API
backend/rag/corpus/          Corpus CSV, mặc định là pddieu.csv
backend/docker-compose.yml   Docker services cho backend/infrastructure
law-crawler/                 Tool crawl/export dữ liệu pháp luật ra corpus
docs/                        Tài liệu project
```

`law-service` không còn được chạy trong `backend/docker-compose.yml`. RAG không phụ thuộc trực tiếp vào `law-service`.

## Yêu cầu

- Python 3.11 trở lên
- Docker Desktop, nếu muốn chạy MySQL/Redis bằng Docker
- Một OpenAI-compatible local LLM server nếu muốn generate answer, mặc định:

```text
http://127.0.0.1:1234/v1
model: vistral-7b-chat
```

Có thể dùng LM Studio hoặc server tương thích OpenAI API khác.

## Chuẩn bị RAG

Đi vào thư mục RAG:

```powershell
cd backend\rag
```

Tạo virtual environment và cài dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Tạo file `.env` nếu chưa có:

```env
MYSQL_ROOT_PASSWORD=<mysql-root-password>
ACCESS_TOKEN_KEY=<jwt-access-token-secret>
```

Corpus mặc định cần nằm ở:

```text
backend/rag/corpus/pddieu.csv
```

## Vectorize Corpus

Chạy lệnh sau để tạo lại ChromaDB từ corpus:

```powershell
cd backend\rag
python vectorize_corpus.py
```

Script sẽ:

- đọc `corpus/pddieu.csv`
- chunk từng điều luật
- embed từng chunk bằng `keepitreal/vietnamese-sbert`
- ghi vào `chroma_db_law`

Sau khi chạy xong, thư mục vector DB nằm ở:

```text
backend/rag/chroma_db_law
```

## Chạy RAG Ở Terminal

Terminal mode là cách nhanh nhất để test retrieve/generate:

```powershell
cd backend\rag
python app.py --terminal
```

Trong terminal:

```text
Question> người lao động được nghỉ thai sản bao lâu?
```

Gõ `:retrieve` để bật/tắt chế độ chỉ retrieve, không gọi LLM.

## Chạy RAG API Local

Khởi động service:

```powershell
cd backend\rag
python app.py
```

API chạy tại:

```text
http://localhost:5001
```

Endpoint chính:

```text
POST /api/v1/question
POST /api/v1/question-with-context
```

Các endpoint này đang kiểm tra JWT qua header:

```text
Authorization: Bearer <token>
```

Token cần được ký bằng `ACCESS_TOKEN_KEY`.

## Chạy Infrastructure Bằng Docker

Nếu chỉ cần hạ tầng cho RAG local, chạy MySQL Q&A và Redis:

```powershell
cd backend
docker compose up -d qna-mysql redis
```

Các cổng mặc định:

```text
qna-mysql: localhost:3307
redis:     localhost:6379
```

Nếu muốn mở thêm MySQL luật và phpMyAdmin:

```powershell
docker compose up -d law-mysql phpmyadmin
```

phpMyAdmin:

```text
http://localhost:8081
```

Lưu ý: `backend/docker-compose.yml` vẫn có một số service phụ như `auth-service`, `recommendation-service`, `kong`. Chỉ chạy toàn bộ compose khi các thư mục/service tương ứng đã có đủ trong repo.

## Tạo Corpus Từ Crawler

Nếu đã có sẵn `backend/rag/corpus/pddieu.csv`, có thể bỏ qua bước này.

Cài dependency cho crawler:

```powershell
cd law-crawler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Cấu hình `.env`:

```env
MYSQL_PASSWORD=<mysql-password>
```

Chạy crawler/export:

```powershell
python main.py
```

Script sẽ ghi corpus ra:

```text
backend/rag/corpus/pddieu.csv
```

## Lệnh Thường Dùng

```powershell
# Start infra tối thiểu
cd backend
docker compose up -d qna-mysql redis

# Vectorize lại corpus
cd ..\backend\rag
python vectorize_corpus.py

# Test RAG trong terminal
python app.py --terminal

# Chạy API
python app.py
```

## Troubleshooting

Nếu `vectorize_corpus.py` báo không thấy corpus, kiểm tra:

```text
backend/rag/corpus/pddieu.csv
```

Nếu API báo không tìm thấy collection Chroma, chạy lại:

```powershell
python vectorize_corpus.py
```

Nếu generate answer lỗi connection, kiểm tra local LLM server tại:

```text
http://127.0.0.1:1234/v1
```

Nếu chỉ muốn kiểm tra retrieval mà không cần LLM, chạy:

```powershell
python app.py --terminal
```

rồi gõ:

```text
:retrieve
```
