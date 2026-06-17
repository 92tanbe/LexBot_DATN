MATCH (n) RETURN labels(n) AS labels, count(n) AS total ORDER BY total DESC;

MATCH (a:Article) RETURN count(a) AS total_articles;
MATCH (c:Crime) RETURN count(c) AS total_crimes;
MATCH (pf:PenaltyFrame)-[:HAS_MAIN_PENALTY|HAS_ADDITIONAL_PENALTY]->(p:Penalty) RETURN count(p) AS total_penalties;
MATCH (a:Article {article_code:'108'}) OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime) RETURN a.article_code, a.title, c.name;
MATCH (a:Article {article_code:'51'})-[:HAS_MITIGATING_FACTOR]->(m:MitigatingFactor) RETURN m.point, m.text LIMIT 10;
MATCH (a:Article {article_code:'52'})-[:HAS_AGGRAVATING_FACTOR]->(g:AggravatingFactor) RETURN g.point, g.text LIMIT 10;
