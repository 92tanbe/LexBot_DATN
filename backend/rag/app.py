from flask import *
from flask_cors import CORS, cross_origin
from playhouse.shortcuts import model_to_dict
from models import *
from directory import *
from cache import *
import chromadb
import json
import jwt
import  re
from waitress import serve
import requests
from dotenv import load_dotenv
import sys
import torch
from sentence_transformers import SentenceTransformer


load_dotenv()

LLM_BASE_URL = "http://127.0.0.1:1234/v1"
LLM_MODEL = "vistral-7b-chat"
EMBEDDING_MODEL = LLM_MODEL
EMBEDDING_PROVIDER = "sentence-transformer"
ST_MODEL_PATH = "keepitreal/vietnamese-sbert"
EMBEDDING_DEVICE = "auto"
LLM_TIMEOUT = 300
LLM_TEMPERATURE = 0.1
LLM_TOP_P = 0.85
RETRIEVAL_K = 8
MAX_CONTEXT_CHARS = 9000
MAX_DOC_CHARS = 900
CHROMA_COLLECTION_NAME = "langchain"
llm_session = requests.Session()
chroma_client = chromadb.PersistentClient(path=TOPIC_DB_PATH or "chroma_db_law")
vectordb = chroma_client.get_collection(CHROMA_COLLECTION_NAME)
sentence_embedding_model = None

app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

def normalize_result_string(page_content):
    result_string = page_content or ""
    result_string = result_string.replace("\n", " ")
    result_string = re.sub(r"\s+", r" ", result_string)
    return result_string.strip()

def get_query_embedding(text):
    global sentence_embedding_model
    if EMBEDDING_PROVIDER == "sentence-transformer":
        if sentence_embedding_model is None:
            device = EMBEDDING_DEVICE
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            sentence_embedding_model = SentenceTransformer(ST_MODEL_PATH, device=device)
        return sentence_embedding_model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0].tolist()

    payload = {
        "model": EMBEDDING_MODEL,
        "input": text
    }
    output = llm_session.post(
        f"{LLM_BASE_URL}/embeddings",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT,
    )
    output.raise_for_status()
    data = output.json()["data"][0]["embedding"]
    return data

def retrieve_docs(question, k=RETRIEVAL_K):
    if EMBEDDING_PROVIDER == "sentence-transformer":
        query_embedding = get_query_embedding(question)
        output = vectordb.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas"]
        )
    else:
        query_embedding = get_query_embedding(question)
        output = vectordb.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas"]
        )
    docs = []
    documents = output.get("documents", [[]])[0]
    metadatas = output.get("metadatas", [[]])[0]
    for index, page_content in enumerate(documents):
        metadata = metadatas[index] or {}
        result_string = normalize_result_string(page_content)[:MAX_DOC_CHARS]
        docs.append({
            "id": metadata.get("id", ""),
            "title": metadata.get("title", ""),
            "content": result_string,
            "demuc_id": metadata.get("demuc_id"),
            "chuong_id": metadata.get("chuong_id"),
        })
    return docs

def generate_response(question, context):
    prompt = f"""Bạn đang trả lời một tình huống pháp luật bằng tiếng Việt.
Dựa trên các căn cứ pháp luật được cung cấp bên dưới, hãy:
- Xác định phần căn cứ nào liên quan trực tiếp hoặc gián tiếp đến tình huống.
- Trả lời thực tế người hỏi nên làm gì tiếp theo.
- Nêu rõ nếu căn cứ chỉ hỗ trợ một phần và cần thêm giấy tờ/thông tin.
- Không bịa số điều hoặc nội dung không có trong căn cứ.
- Không đưa mã định danh nội bộ trong ngoặc vào câu trả lời, ví dụ id hoặc chuỗi số dài.

Các căn cứ pháp luật:
{context[:MAX_CONTEXT_CHARS]}

Câu hỏi/tình huống:
{question}"""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý pháp luật Việt Nam. Trả lời có cấu trúc, thực tế, chỉ dựa trên căn cứ được cung cấp và nói rõ mức độ chắc chắn của căn cứ."},
            {"role": "user", "content": prompt}
        ],
        "temperature": LLM_TEMPERATURE,
        "top_p": LLM_TOP_P
    }
    output = llm_session.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT,
    )
    output.raise_for_status()
    return output.json()["choices"][0]["message"]["content"].strip()

def build_context(citation):
    parts = []
    for index, item in enumerate(citation, start=1):
        title = item.get("title") or item.get("id") or f"Căn cứ {index}"
        heading = f"[{index}] {title}"
        parts.append(f"{heading}\n{item.get('content', '')}")
    return "\n\n".join(parts).strip()[:MAX_CONTEXT_CHARS]

def read_cached_answer(question):
    cached = redisClient.get(question)
    if not cached:
        return None
    return json.loads(cached.decode("utf-8"))

def write_cached_answer(question, result):
    redisClient.setex(question, redis_ttl_seconds, json.dumps(result, ensure_ascii=False))

def answer_question(question, should_generate=True, use_cache=True):
    if should_generate and use_cache:
        cached = read_cached_answer(question)
        if cached:
            cached["cache_hit"] = True
            return cached

    citation = retrieve_docs(question)
    context = build_context(citation)
    if not context:
        raise RuntimeError("No context retrieved from Chroma DB")
    response = generate_response(question, context) if should_generate else ""
    result = {
        "status": "success",
        "question": question,
        "citation": citation,
        "response": response,
    }
    if should_generate and use_cache:
        write_cached_answer(question, result)
    return result

def print_terminal_result(result):
    print("\n=== Retrieved documents ===")
    for index, citation in enumerate(result["citation"], start=1):
        title = citation.get("title") or citation.get("id") or f"Document {index}"
        print(f"\n[{index}] {title}")
        print(citation.get("content", ""))

    if result.get("response"):
        print("\n=== Answer ===")
        if result.get("cache_hit"):
            print("(from Redis cache)")
        print(result["response"])
    print()

def run_terminal_test():
    print("QNA terminal test mode")
    print("Type a question and press Enter.")
    print("Commands: :q to quit, :retrieve to toggle retrieval-only mode.")
    retrieval_only = False

    while True:
        try:
            question = input("\nQuestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue
        if question.lower() in {":q", ":quit", "exit", "quit"}:
            break
        if question.lower() in {":retrieve", ":retrieval"}:
            retrieval_only = not retrieval_only
            mode = "retrieval only" if retrieval_only else "retrieval + generation"
            print(f"Mode: {mode}")
            continue

        try:
            result = answer_question(question, should_generate=not retrieval_only)
            print_terminal_result(result)
        except Exception as error:
            print(f"Error: {error}")

def save_references(question_id, citation):
    for item in citation:
        Reference.create(**{
            'question_id': question_id,
            'mapc': item.get('id', ''),
            'noidung': item.get('content', ''),
            'ten': item.get('title', ''),
        })

@app.route('/api/v1/question', methods=['GET'])
def get_question(email=None):
    token = request.headers.get('Authorization')

    if token.startswith('Bearer '):
        token = token[7:]
        
    decoded = jwt.decode(token, ACCESS_TOKEN_KEY, algorithms=['HS256'])
    email = decoded['email']
    if email:
        query = QuestionModel.select().where(email == QuestionModel.email).dicts()
        res = []
        for row in query:
            answer = []
            query1 = Reference.select().where(row['id'] == Reference.question_id).dicts()
            for r in query1: 
                answer.append({
                    "id": r['mapc'],
                    "title": r['ten'],
                    "content": r['noidung'],
                    "demuc_id": None,
                    "chuong_id": None,
                })
            res.append({
                "id": row['id'],
                "email": row['email'],
                "question": row['question'],
                "updatedAt": row['updatedAt'].strftime("%m/%d/%Y"),
                "response": row['response'],
                "answer": answer
            })
        return res, 201
    
@app.route('/api/v1/question', methods=['POST'])
def add_question():
    token = request.headers.get('Authorization')

    if token.startswith('Bearer '):
        token = token[7:]
    data = request.get_json()
    decoded = jwt.decode(token, ACCESS_TOKEN_KEY, algorithms=['HS256'])

    email = decoded['email']

    try:
        question = data["question"]
    except:
        return {
            "status": "error",
            "response": "No question in payload",
        }, 400
    
    if not question:
        return {
            "status": "error",
            "response": "Question can not be empty",
        }, 400

    try:
        result = answer_question(question)
    except Exception:
        return {
            "status": "error",
            "response": "Error while retrieving context from DB or generating answer",
        }, 500

    citation = result["citation"]
    response = result["response"]
    query = QuestionModel.create(**{"email": email, "question": question ,"response": response})
    save_references(query.id, citation)
    return result, 200

@app.route('/api/v1/question-with-context', methods=['POST'])
def add_question_with_context():
    try: 
        token = request.headers.get('Authorization')

        if token.startswith('Bearer '):
            token = token[7:]
        data = request.get_json()
        decoded = jwt.decode(token, ACCESS_TOKEN_KEY, algorithms=['HS256'])

        email = decoded['email']
    except: 
         return {
            "status": "error",
            "response": "Need authencation",
        }, 400
         
    try:
        question = data["question"]
        context = data["context"]
    except:
        return {
            "status": "error",
            "response": "Question or Context not found in the payload",
        }, 400
    
    if not question:
        return {
            "status": "error",
            "response": "Question can not be empty",
        }, 400
    if not context:
        return {
            "status": "error",
            "response": "Context can not be empty",
        }, 400
    cached = read_cached_answer(question)
    if cached:
        cached["cache_hit"] = True
        return cached, 200
    
    try:
        citation = retrieve_docs(question)
    except Exception:
        return {
            "status": "error",
            "response": "Error while retrieving context from DB",
        }, 500

    try:
        response = generate_response(question, context)
    except Exception:
        return {
            "status": "error",
            "response": "Error while generating answer",
        }, 500

    query = QuestionModel.create(**{"email": email, "question": question ,"response": response})
    save_references(query.id, citation)
    res = {
        "status": "success",
        "question": question,
        "citation": citation,
        "response": response,
    }
    write_cached_answer(question, res)
    return res, 200


@app.route('/api/v1/question/<int:question_id>', methods=['PUT'])
def update_question(question_id):
    data = request.get_json()
    QuestionModel.update(**data).where(QuestionModel.id == question_id).execute()
    return '', 204

@app.route('/api/v1/question/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    QuestionModel.delete().where(QuestionModel.id == question_id).execute()
    return '', 204

if __name__ == "__main__":
    if "--terminal" in sys.argv or "--test" in sys.argv:
        run_terminal_test()
    else:
        print('QNA server is running. ')
        serve(app, host='0.0.0.0', port=5001, threads=1)
