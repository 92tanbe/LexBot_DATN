"""Chatbot RAG BLHS - FastAPI service.

Cung cap pipeline 4 giai doan:
- Stage 1: Embedding & Hybrid Retrieval (BKAI bi-encoder + Neo4j vector + fulltext + graph)
- Stage 2: Query Understanding (NER + Cypher gen + Query decomposition)
- Stage 3: Generation & Structured Output (rerank + Pydantic schema + LLM)
- Stage 4: Serving & Post-processing (FastAPI streaming + citation validator)
"""

__version__ = "0.1.0"
