# =============================================================================
# README.md – Hướng dẫn cài đặt & chạy LexBot
# =============================================================================

# LexBot – AI Tư Vấn Pháp Lý Giao Thông

Chatbot phân tích tình huống vi phạm giao thông, kết hợp:
- **Neo4j Graph Database** chứa BLHS 2025 + Nghị định GT  
- **Claude LLM** (Anthropic) để phân tích ngôn ngữ tự nhiên  
- **RAG Pipeline** để tra cứu điều luật chính xác

---

## 📁 Cấu trúc Project

```
lexbot/
│
├── config/
│   └── settings.py          ← Cấu hình Neo4j, Claude API
│
├── data/
│   ├── blhs_2025_from_text.csv   ← Bộ Luật Hình Sự 2025
│   └── giaothong.csv             ← Nghị định xử phạt giao thông
│
├── etl/
│   └── load_to_neo4j.py     ← Import CSV → Neo4j (chạy 1 lần)
│
├── graph/
│   └── neo4j_service.py     ← Tất cả Cypher queries
│
├── rag/
│   └── rag_engine.py        ← RAG Pipeline: Neo4j + Claude
│
├── chatbot/
│   └── cli_chat.py          ← Giao diện terminal chatbot
│
├── requirements.txt
└── README.md
```

---

## ⚙️ Cài đặt

### 1. Cài thư viện Python

```bash
pip install -r requirements.txt
```

### 2. Cài & chạy Neo4j

**Option A – Neo4j Desktop (local, dễ nhất):**
```
1. Tải: https://neo4j.com/download/
2. Tạo project mới → Add Database → Local DBMS
3. Đặt password → Start
4. URI mặc định: bolt://localhost:7687
```

**Option B – Neo4j AuraDB (cloud, miễn phí):**
```
1. Vào: https://console.neo4j.io/
2. Create Free Instance
3. Lấy URI dạng: neo4j+s://xxxx.databases.neo4j.io
```

### 3. Cấu hình biến môi trường

```bash
# Tạo file .env (hoặc set trực tiếp trong settings.py)
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="your_neo4j_password"
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 4. Copy file dữ liệu

```bash
cp blhs_2025_from_text.csv lexbot/data/
cp giaothong.csv           lexbot/data/
```

---

## 🚀 Chạy

### Bước 1: Import dữ liệu vào Neo4j (chỉ cần chạy 1 lần)

```bash
cd lexbot
python etl/load_to_neo4j.py
```

Output mong đợi:
```
✅ Kết nối Neo4j: bolt://localhost:7687
✅ Constraints & Indexes tạo xong
📕 Đang import BLHS 2025...
   ... 200 dòng
   ... 400 dòng
✅ BLHS: 3633 dòng import xong
🚦 Đang import Nghị định Giao thông...
✅ Nghị định GT: 1052 dòng import xong

📊 Thống kê Graph Database:
-----------------------------------
  Khoan                3200 nodes
  Dieu                  850 nodes
  Chuong                 60 nodes
  Diem                 1800 nodes
  VanBanPhapLuat          2 nodes
  Relationships        9500
-----------------------------------
```

### Bước 2: Chạy chatbot

```bash
python chatbot/cli_chat.py
```

---

## 💬 Ví dụ sử dụng

```
👤 Bạn: Lái xe say rượu 0.4mg/L gây tai nạn chết người thì bị xử lý thế nào?

⚖️  LexBot:

## 🔍 Phân tích hành vi
Tình huống này có 2 hành vi vi phạm:
1. Lái xe có nồng độ cồn vượt mức (0.4mg/L > 0.25mg/L)
2. Gây tai nạn dẫn đến chết người

## 📊 Điều luật áp dụng (từ Graph DB)
- Điều 260 BLHS 2025: Tội vi phạm quy định về tham gia GT đường bộ
- Điều 5 Nghị định GT: Xử phạt vi phạm nồng độ cồn

## ⚖️ Mức xử phạt

### 🚔 Xử phạt hành chính
- Điều 5, khoản 10: Phạt tiền 30-40 triệu đồng
- Tước GPLX 22-24 tháng

### 🏛️ Truy cứu hình sự
- Tội danh: Vi phạm quy định về tham gia GTĐB gây hậu quả nghiêm trọng
- Điều 260, khoản 2 BLHS 2025: Phạt tù 3-10 năm
- (Gây chết 1 người + say rượu = tình tiết tăng nặng)

## 💡 Kết luận
Bị xử lý CẢ HAI: phạt hành chính 30-40tr + tước bằng 22-24 tháng
VÀ truy tố hình sự với khung 3-10 năm tù.
```

---

## 🔧 Mở rộng

| Tính năng | Cách thêm |
|-----------|-----------|
| Web UI | Thêm `fastapi` + `streamlit` |
| Nhiều luật hơn | Thêm CSV mới → chạy lại ETL |
| Tìm kiếm vector | Tích hợp `sentence-transformers` |
| Export PDF | Thêm `reportlab` |
