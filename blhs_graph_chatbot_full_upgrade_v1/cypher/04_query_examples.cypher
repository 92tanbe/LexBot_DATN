// 1) Tìm điều luật theo số điều
MATCH (a:Article {article_code:'108'})
OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime)
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(cl:Clause)
OPTIONAL MATCH (cl)-[:HAS_PENALTY_FRAME]->(pf:PenaltyFrame)
RETURN a.article_code, a.title, c.name AS crime, cl.clause_no, cl.text, collect(pf.text) AS penalty_frames
ORDER BY cl.clause_no;

// 2) Tìm tội về gỗ/lâm sản và ngưỡng định lượng
MATCH (a:Article)-[:DEFINES_CRIME]->(c:Crime)
WHERE toLower(a.full_text) CONTAINS 'gỗ' OR toLower(a.title) CONTAINS 'rừng'
OPTIONAL MATCH (c)-[:HAS_QUANTITY_THRESHOLD]->(qt:QuantityThreshold)
RETURN a.article_code, a.title, collect(DISTINCT qt.text)[0..10] AS thresholds
LIMIT 20;

// 3) Tìm tình tiết giảm nhẹ/tăng nặng
MATCH (a:Article {article_code:'51'})-[:HAS_MITIGATING_FACTOR]->(m:MitigatingFactor)
RETURN m.point, m.text ORDER BY m.point;

MATCH (a:Article {article_code:'52'})-[:HAS_AGGRAVATING_FACTOR]->(g:AggravatingFactor)
RETURN g.point, g.text ORDER BY g.point;

// 4) Mapping tiếng lóng/đời thường
MATCH (x:SlangTerm)-[r]->(target)
RETURN x.text, type(r), labels(target), coalesce(target.name, target.description, target.text) AS normalized
ORDER BY x.text;

// 5) Fulltext search Article
CALL db.index.fulltext.queryNodes('article_fulltext', 'ma túy') YIELD node, score
RETURN node.article_code, node.title, score
ORDER BY score DESC LIMIT 20;
