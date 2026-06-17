
"""Optional: build vector embeddings for Article/Clause/Condition.
Install: pip install sentence-transformers neo4j python-dotenv
Then: python scripts/build_embeddings.py
"""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

load_dotenv('backend/.env')
URI=os.getenv('NEO4J_URI','bolt://localhost:7687')
USER=os.getenv('NEO4J_USER','neo4j')
PASSWORD=os.getenv('NEO4J_PASSWORD','password123456')
DB=os.getenv('NEO4J_DATABASE','neo4j')
MODEL=os.getenv('EMBEDDING_MODEL','bkai-foundation-models/vietnamese-bi-encoder')
BATCH=int(os.getenv('EMBEDDING_BATCH','32'))
model=SentenceTransformer(MODEL)
driver=GraphDatabase.driver(URI, auth=(USER,PASSWORD))

def embed_label(label, text_expr):
    with driver.session(database=DB) as s:
        rows=s.run(f"MATCH (n:{label}) WHERE n.embedding IS NULL RETURN n.id AS id, {text_expr} AS text").data()
        print(label, len(rows))
        for i in range(0,len(rows),BATCH):
            batch=rows[i:i+BATCH]
            embs=model.encode([r['text'] or '' for r in batch], normalize_embeddings=True).tolist()
            payload=[{'id': r['id'], 'embedding': e} for r,e in zip(batch, embs)]
            s.run(f"UNWIND $rows AS row MATCH (n:{label} {{id: row.id}}) SET n.embedding = row.embedding", rows=payload)

embed_label('Article', "coalesce(n.title,'') + ' ' + coalesce(n.full_text,'')")
embed_label('Clause', "coalesce(n.text,'')")
embed_label('Condition', "coalesce(n.text,'')")
driver.close()
