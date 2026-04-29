import csv
import shutil
import sys
from pathlib import Path

import chromadb
import torch
from sentence_transformers import SentenceTransformer


field_size_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(field_size_limit)
        break
    except OverflowError:
        field_size_limit //= 10


BASE_DIR = Path(__file__).resolve().parent
DOCS_PATH = (BASE_DIR / "corpus").resolve()
DOCS_FILE = "pddieu.csv"
DB_PERSIST_PATH = (BASE_DIR / "chroma_db_law").resolve()
ST_MODEL_PATH = "keepitreal/vietnamese-sbert"
EMBEDDING_DEVICE = "auto"
CHROMA_COLLECTION_NAME = "langchain"
CHROMA_BATCH_SIZE = 1024
ENCODE_BATCH_SIZE = 64
ARTICLE_CHUNK_MAX_CHARS = 2000
ARTICLE_CHUNK_OVERLAP_CHARS = 150


def row_text(row):
    title = (row.get("title") or "").strip()
    content = (row.get("content") or "").strip()
    if title and content:
        return f"{title}\n{content}"
    return title or content


def row_metadata(row, source_name, row_number):
    metadata = {
        "source": source_name,
        "row": row_number,
    }
    for key, value in row.items():
        if key == "content":
            continue
        value = str(value or "").strip()
        if value:
            metadata[key] = value
    return metadata


def split_long_text(text, max_chars):
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split_at = max(text.rfind(". ", start, end), text.rfind("; ", start, end), text.rfind(", ", start, end))
            if split_at > start:
                end = split_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def chunk_article(text, max_chars=ARTICLE_CHUNK_MAX_CHARS, overlap_chars=ARTICLE_CHUNK_OVERLAP_CHARS):
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [paragraph.strip() for paragraph in text.splitlines() if paragraph.strip()]
    chunks = []
    current = ""

    for paragraph in paragraphs:
        paragraph_parts = split_long_text(paragraph, max_chars)
        for part in paragraph_parts:
            candidate = f"{current}\n{part}".strip() if current else part
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks

    overlapped_chunks = [chunks[0]]
    for index in range(1, len(chunks)):
        overlap = chunks[index - 1][-overlap_chars:].strip()
        chunk = f"{overlap}\n{chunks[index]}".strip() if overlap else chunks[index]
        overlapped_chunks.append(chunk)
    return overlapped_chunks


def iter_article_chunks(doc_id, text, metadata):
    chunks = chunk_article(text)
    total_chunks = len(chunks)
    for chunk_index, chunk_text in enumerate(chunks, start=1):
        chunk_metadata = dict(metadata)
        chunk_metadata["article_id"] = metadata.get("id", doc_id)
        chunk_metadata["chunk_index"] = chunk_index
        chunk_metadata["chunk_total"] = total_chunks
        chunk_id = f"{doc_id}:chunk:{chunk_index}"
        yield chunk_id, chunk_text, chunk_metadata


def csv_paths():
    path = DOCS_PATH / DOCS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")
    return [path]


def iter_csv_documents():
    for csv_path in csv_paths():
        print(f"Loading corpus file: {csv_path}")
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row_number, row in enumerate(reader, start=1):
                text = row_text(row)
                if not text:
                    continue
                doc_id = f"{csv_path.stem}:{row.get('id') or row_number}"
                metadata = row_metadata(row, csv_path.name, row_number)
                yield from iter_article_chunks(doc_id, text, metadata)


def resolve_device():
    if EMBEDDING_DEVICE != "auto":
        return EMBEDDING_DEVICE
    return "cuda" if torch.cuda.is_available() else "cpu"


def flush_batch(collection, embedding_model, ids, documents, metadatas):
    if not ids:
        return 0
    embeddings = embedding_model.encode(
        documents,
        batch_size=ENCODE_BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


def main():
    print(f"Corpus path: {DOCS_PATH}")
    print(f"Corpus file: {DOCS_FILE}")
    print(f"Chroma DB path: {DB_PERSIST_PATH}")
    device = resolve_device()
    print(f"Embedding corpus with Vietnamese SBERT model: {ST_MODEL_PATH}")
    print(f"Embedding device: {device}")
    print(f"Chroma batch size: {CHROMA_BATCH_SIZE}")
    print(f"Encode batch size: {ENCODE_BATCH_SIZE}")
    print(f"Article chunk max chars: {ARTICLE_CHUNK_MAX_CHARS}")
    print(f"Article chunk overlap chars: {ARTICLE_CHUNK_OVERLAP_CHARS}")

    if DB_PERSIST_PATH.exists():
        print(f"Resetting Chroma DB at {DB_PERSIST_PATH}")
        shutil.rmtree(DB_PERSIST_PATH)

    DB_PERSIST_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_PERSIST_PATH))
    embedding_model = SentenceTransformer(ST_MODEL_PATH, device=device)
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    ids = []
    documents = []
    metadatas = []
    total = 0

    for doc_id, text, metadata in iter_csv_documents():
        ids.append(doc_id)
        documents.append(text)
        metadatas.append(metadata)

        if len(ids) >= CHROMA_BATCH_SIZE:
            total += flush_batch(collection, embedding_model, ids, documents, metadatas)
            print(f"Inserted {total} chunks")
            ids.clear()
            documents.clear()
            metadatas.clear()

    total += flush_batch(collection, embedding_model, ids, documents, metadatas)
    print(f"Done. Inserted {total} chunks into {DB_PERSIST_PATH} collection {CHROMA_COLLECTION_NAME}")


if __name__ == "__main__":
    main()
