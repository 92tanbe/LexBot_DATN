// Chạy file này sau khi đã tạo property embedding bằng scripts/build_embeddings.py.
CREATE VECTOR INDEX article_embedding IF NOT EXISTS
FOR (n:Article) ON (n.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX clause_embedding IF NOT EXISTS
FOR (n:Clause) ON (n.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX condition_embedding IF NOT EXISTS
FOR (n:Condition) ON (n.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};
