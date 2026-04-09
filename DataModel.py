import os
import time
import warnings
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

warnings.filterwarnings("ignore")
load_dotenv()


class RAG:
    def __init__(self):
        self.vector_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.context = []
        self.index_name = "lawbot"

        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("Thiếu PINECONE_API_KEY trong file .env")

        self.pinecone = Pinecone(api_key=api_key)

        if not self.pinecone.has_index(self.index_name):
            self.pinecone.create_index(
                name=self.index_name,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                deletion_protection="disabled",
            )

        while not self.pinecone.describe_index(self.index_name).status["ready"]:
            time.sleep(1)

        host = self.pinecone.describe_index(self.index_name).host
        self.index = self.pinecone.Index(host=host)

    def read_html(self, path):
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()

        soup = BeautifulSoup(content, features="html.parser")
        for script in soup(["script", "style"]):
            script.extract()

        text = soup.get_text()
        lines = [line.strip() for line in text.splitlines()]
        chunks = (phrase.strip() for line in lines for phrase in line.split(" "))
        text = " ".join(chunk for chunk in chunks if chunk)

        return text, os.path.basename(path)

    def text_to_docs(self, text, filename):
        if isinstance(text, str):
            text = [text]

        page_docs = [Document(page_content=page) for page in text]
        for i, page_doc in enumerate(page_docs):
            page_doc.metadata["page"] = i + 1

        doc_chunks = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
            chunk_overlap=100,
        )

        for page_doc in page_docs:
            chunks = text_splitter.split_text(page_doc.page_content)

            for i, chunk in enumerate(chunks):
                chunk_doc = Document(
                    page_content=chunk,
                    metadata={
                        "page": page_doc.metadata["page"],
                        "chunk": i,
                        "filename": filename,
                        "source": f"{filename}-{page_doc.metadata['page']}-{i}",
                    },
                )
                doc_chunks.append(chunk_doc)

        return doc_chunks

    def docs_to_index(self, docs):
        vectors = []

        for doc in docs:
            embedding = self.vector_model.encode([doc.page_content])[0].tolist()
            metadata = {
                "page": doc.metadata["page"],
                "chunk": doc.metadata["chunk"],
                "filename": doc.metadata["filename"],
                "text": doc.page_content,
            }

            vectors.append(
                {
                    "id": doc.metadata["source"],
                    "values": embedding,
                    "metadata": metadata,
                }
            )

        if vectors:
            self.index.upsert(vectors=vectors)

    def create_vector_db(self, paths):
        documents = []
        for path in paths:
            text, filename = self.read_html(path)
            documents.extend(self.text_to_docs(text, filename))

        self.docs_to_index(documents)

    def retrieve_relevant_docs(self, query, top_k=5, threshold=0.5):
        query_embedding = self.vector_model.encode([query])[0].tolist()

        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )

        filtered_results = [
            match for match in results["matches"] if match["score"] >= threshold
        ]
        return filtered_results

    def generate_response(self, query):
        relevant_docs = self.retrieve_relevant_docs(query)

        context = " ".join(
            [
                match["metadata"]["text"]
                for match in relevant_docs
                if "metadata" in match and "text" in match["metadata"]
            ]
        )

        input_text = f"""
Bạn là một người am hiểu luật Việt Nam và có suy luận logic tốt.
Hãy trả lời ngắn gọn, súc tích, dễ hiểu và đúng trọng tâm.

Thông tin tham khảo:
{context}

Câu hỏi người dùng:
{query}
"""

        payload = {
            "model": "llama3.2",
            "prompt": input_text,
            "context": self.context,
            "stream": False,
        }

        response = requests.post(
            url="http://localhost:11434/api/generate",
            json=payload,
        ).json()

        self.context = response.get("context", [])
        answer = response.get("response", "Không nhận được phản hồi từ mô hình.")
        return answer