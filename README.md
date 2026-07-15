# BLHS Graph Chatbot Full Upgrade v1

Bản này nâng cấp bộ `blhs_neo4j_from_pdf` trong file RAR lên schema graph đầy đủ hơn cho chatbot pháp lý. Nguồn dữ liệu đầu vào là `data/blhs_from_pdf_normalized.base.json`, tức dữ liệu đã parse từ PDF BLHS trong bộ RAR/starter kit. Không dùng `deepseek_merged.json` cũ.

## 📦 Link Dataset

- **Kaggle Dataset Chatbot**: [https://www.kaggle.com/datasets/thncnhttn/dataset-chatbot](https://www.kaggle.com/datasets/thncnhttn/dataset-chatbot)

## 🚀 Hướng dẫn cài đặt Source Code (Tổng quan)

Để hệ thống hoạt động đầy đủ, cần thực hiện cài đặt các thành phần theo thứ tự:

**1. Tải Dataset:**
- Tải dataset từ link Kaggle ở trên và giải nén vào thư mục tương ứng theo yêu cầu.

**2. Khởi tạo Neo4j (Database):**
- Chạy Neo4j và import dữ liệu (như hướng dẫn phần [Chạy Neo4j + import trên Windows](#chạy-neo4j--import-trên-windows) bên dưới).

**3. Cài đặt Chatbot RAG Service (`lexbot-main`):**
- Là AI service xử lý Embedding, NER, Cypher Generator và gọi LLM (chạy port 8001).
- Mở terminal, chuyển vào thư mục `lexbot-main`, cài đặt requirements và chạy server theo hướng dẫn chi tiết trong file `lexbot-main/README.md`.

**4. Cài đặt Backend API (`backend`):**
- Là server kết nối với frontend và forward requests sang chatbot service (chạy port 8000).
- Mở terminal, chuyển vào thư mục `backend`, cài đặt requirements và chạy server theo hướng dẫn chi tiết trong file `backend/README.md`.

---

## Schema chính

```text
(:Law) (:Part) (:Chapter) (:Section) (:Article) (:Clause) (:Point)
(:Crime) (:Rule) (:Condition) (:PenaltyFrame) (:Penalty)
(:LegalConcept) (:AggravatingFactor) (:MitigatingFactor) (:JudicialMeasure)
(:SubjectRequirement) (:ObjectRequirement) (:ActRequirement)
(:ConsequenceRequirement) (:QuantityThreshold) (:Exception) (:Reference)
(:SlangTerm) (:ActionAlias) (:LegalSignal) (:SubstanceAlias) (:Substance)
(:ScenarioFact) (:MatchedCondition)   # runtime, không có dữ liệu tĩnh
```

## Các tầng dữ liệu

```text
Tầng 1 - Legal Structure:
Law -> Part -> Chapter -> Section -> Article -> Clause -> Point

Tầng 2 - Legal Meaning:
Article -> Crime -> Act/Subject/Object/Consequence/QuantityThreshold

Tầng 3 - Penalty:
Clause/Point -> PenaltyFrame -> Penalty; Article 46-49 -> JudicialMeasure

Tầng 4 - General Rules:
LegalConcept, MitigatingFactor, AggravatingFactor, Exception

Tầng 5 - NLP Mapping:
SlangTerm/ActionAlias/SubstanceAlias -> LegalSignal/LegalConcept/Substance
```

## Counts sinh ra

```json
{
  "laws": 1,
  "parts": 3,
  "chapters": 26,
  "sections": 16,
  "articles": 427,
  "clauses": 1419,
  "points": 2872,
  "conditions": 4290,
  "penalty_frames": 1493,
  "references": 565,
  "crimes": 318,
  "rules": 4291,
  "penalties": 1493,
  "legal_concepts": 123,
  "aggravating_factors": 15,
  "mitigating_factors": 22,
  "subject_requirements": 443,
  "object_requirements": 318,
  "act_requirements": 318,
  "consequence_requirements": 580,
  "quantity_thresholds": 5688,
  "exceptions": 170,
  "slang_terms": 12,
  "action_aliases": 13,
  "substances": 4,
  "substance_aliases": 6,
  "legal_signals": 8
}
```

## Chạy Neo4j + import trên Windows

```powershell
cd blhs_graph_chatbot_full_upgrade_v1
docker compose up -d neo4j
powershell -ExecutionPolicy Bypass -File .\scripts\import_windows.ps1 -Reset
```

Hoặc:

```cmd
import_windows.bat -Reset
```

Mở Neo4j Browser:

```text
http://localhost:7474
user: neo4j
password: password123456
```

## Kiểm tra nhanh

```cypher
MATCH (n) RETURN labels(n) AS labels, count(n) AS total ORDER BY total DESC;
```

```cypher
MATCH (a:Article {article_code:'108'})-[:DEFINES_CRIME]->(c:Crime)
RETURN a.article_code, a.title, c.name;
```

```cypher
MATCH (a:Article {article_code:'51'})-[:HAS_MITIGATING_FACTOR]->(m:MitigatingFactor)
RETURN m.point, m.text ORDER BY m.point;
```

## Chạy backend chatbot mẫu

```powershell
cd backend
copy .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Deploy backend bằng Railway/Railpack

Repository đã có cấu hình ở root để Railpack nhận diện backend Python/FastAPI:

```text
requirements.txt  -> chứa dependency để Railpack cài từ root
.python-version   -> khóa Python 3.11 cho dependency ML/NLP ổn định hơn
railpack.json     -> dùng provider python và chạy bash start.sh
start.sh          -> cd backend rồi chạy uvicorn theo PORT của Railway
```

Khi deploy, cấu hình các biến môi trường tối thiểu:

```text
NEO4J_URI=<bolt-uri-cua-neo4j>
NEO4J_USER=neo4j
NEO4J_PASSWORD=<mat-khau>
NEO4J_DATABASE=neo4j
OPENAI_API_KEY=<neu-dung-LLM>
```

Test:

```bash
curl -X POST http://localhost:8000/analyze-scenario ^
  -H "Content-Type: application/json" ^
  -d "{"scenario":"A 15 tuổi giúp B che giấu tang vật sau khi B phạm tội","top_k":8}"
```

## Vector search tùy chọn

1. Cài thư viện trong môi trường Python:

```bash
pip install sentence-transformers neo4j python-dotenv
```

2. Sinh embedding:

```bash
python scripts/build_embeddings.py
```

3. Tạo vector index:

```bash
docker exec blhs-neo4j-full-upgrade cypher-shell -u neo4j -p password123456 -f /cypher/05_vector_indexes_optional.cypher
```

## Lưu ý quan trọng

Các node `Requirement`, `QuantityThreshold`, `Exception` được sinh bằng rule-based extractor từ text PDF. Đây là bản rất tốt để làm đồ án/chatbot RAG + graph, nhưng những điều có ngưỡng phức tạp như ma túy, lâm sản, môi trường, tham nhũng vẫn nên review thủ công trước khi dùng trong nghiệp vụ thật.
