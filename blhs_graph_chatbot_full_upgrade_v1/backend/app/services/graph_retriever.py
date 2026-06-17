from __future__ import annotations

from app.core.neo4j import neo4j_db

GRAPH_CONTEXT_CYPHER = """
MATCH (a:Article {article_code:$article_code})
OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(crime:Crime)
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(cl:Clause)
OPTIONAL MATCH (cl)-[:HAS_POINT]->(pt:Point)
OPTIONAL MATCH (cl)-[:HAS_CONDITION]->(cond1:Condition)
OPTIONAL MATCH (pt)-[:HAS_CONDITION]->(cond2:Condition)
OPTIONAL MATCH (cl)-[:HAS_PENALTY_FRAME]->(pf1:PenaltyFrame)
OPTIONAL MATCH (pt)-[:HAS_PENALTY_FRAME]->(pf2:PenaltyFrame)
OPTIONAL MATCH (pf1)-[r1]->(p1:Penalty)
WHERE r1 IS NULL OR type(r1) IN ["HAS_MAIN_PENALTY", "HAS_ADDITIONAL_PENALTY", "HAS_PENALTY"]
OPTIONAL MATCH (pf2)-[r2]->(p2:Penalty)
WHERE r2 IS NULL OR type(r2) IN ["HAS_MAIN_PENALTY", "HAS_ADDITIONAL_PENALTY", "HAS_PENALTY"]
OPTIONAL MATCH (crime)-[:HAS_ACT_REQUIREMENT]->(ar:ActRequirement)
OPTIONAL MATCH (crime)-[:HAS_SUBJECT_REQUIREMENT]->(sr:SubjectRequirement)
OPTIONAL MATCH (crime)-[:HAS_OBJECT_REQUIREMENT]->(orq:ObjectRequirement)
OPTIONAL MATCH (crime)-[:HAS_CONSEQUENCE_REQUIREMENT]->(cr:ConsequenceRequirement)
OPTIONAL MATCH (crime)-[:HAS_QUANTITY_THRESHOLD]->(qt:QuantityThreshold)
OPTIONAL MATCH (a)-[:HAS_EXCEPTION]->(ex:Exception)
OPTIONAL MATCH (a)-[:HAS_MITIGATING_FACTOR]->(mf:MitigatingFactor)
OPTIONAL MATCH (a)-[:HAS_AGGRAVATING_FACTOR]->(af:AggravatingFactor)
OPTIONAL MATCH (a)-[:REFERENCES]->(ref:Article)
RETURN a AS article, crime,
       collect(DISTINCT cl) AS clauses,
       collect(DISTINCT pt) AS points,
       collect(DISTINCT cond1) + collect(DISTINCT cond2) AS conditions,
       collect(DISTINCT pf1) + collect(DISTINCT pf2) AS penalty_frames,
       collect(DISTINCT p1) + collect(DISTINCT p2) AS penalties,
       collect(DISTINCT ar) AS act_requirements,
       collect(DISTINCT sr) AS subject_requirements,
       collect(DISTINCT orq) AS object_requirements,
       collect(DISTINCT cr) AS consequence_requirements,
       collect(DISTINCT qt) AS quantity_thresholds,
       collect(DISTINCT ex) AS exceptions,
       collect(DISTINCT mf) AS mitigating_factors,
       collect(DISTINCT af) AS aggravating_factors,
       collect(DISTINCT ref) AS references
"""


def fetch_context_by_article(article_code: str) -> dict | None:
    rows = neo4j_db.query(GRAPH_CONTEXT_CYPHER, {"article_code": str(article_code)})
    return rows[0] if rows else None


def fetch_contexts(article_codes: list[str]) -> list[dict]:
    out: list[dict] = []
    for code in article_codes:
        ctx = fetch_context_by_article(code)
        if ctx:
            out.append(ctx)
    return out


def search_exact_articles(article_refs: list[str], limit: int = 10) -> list[dict]:
    if not article_refs:
        return []
    return neo4j_db.try_query(
        """
        MATCH (a:Article)
        WHERE a.article_code IN $codes
        OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               2.0 AS score, "exact_article" AS source, ["Điều " + a.article_code] AS matched_terms
        LIMIT $limit
        """,
        {"codes": [str(x) for x in article_refs], "limit": limit},
    )


def search_related_from_signals(normalized: list[dict], limit: int = 10) -> list[dict]:
    article_codes = [str(r["article_code"]) for r in normalized if r.get("article_code")]
    if not article_codes:
        return []
    return neo4j_db.try_query(
        """
        MATCH (a:Article)
        WHERE a.article_code IN $codes
        OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               1.3 AS score, "normalized_signal_graph" AS source, [a.title] AS matched_terms
        LIMIT $limit
        """,
        {"codes": article_codes, "limit": limit},
    )


def search_articles_by_title_terms(terms: list[str], limit: int = 10) -> list[dict]:
    if not terms:
        return []
    return neo4j_db.try_query(
        """
        MATCH (a:Article)
        WHERE any(term IN $terms WHERE toLower(a.title) CONTAINS toLower(term))
        OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               1.6 AS score, "legal_action_title" AS source, $terms AS matched_terms
        ORDER BY a.article_number
        LIMIT $limit
        """,
        {"terms": terms, "limit": limit},
    )


def find_articles_by_keyword(keyword: str, limit: int = 10) -> list[dict]:
    return neo4j_db.try_query(
        """
        MATCH (a:Article)
        WHERE toLower(a.title) CONTAINS toLower($keyword)
           OR toLower(coalesce(a.full_text, "")) CONTAINS toLower($keyword)
        OPTIONAL MATCH (a)-[:DEFINES_CRIME]->(c:Crime)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               1.0 AS score, "keyword_graph" AS source, [$keyword] AS matched_terms
        ORDER BY a.article_number
        LIMIT $limit
        """,
        {"keyword": keyword, "limit": limit},
    )


def find_crime_by_act(act: str, limit: int = 10) -> list[dict]:
    return neo4j_db.try_query(
        """
        MATCH (a:Article)-[:DEFINES_CRIME]->(c:Crime)
        WHERE toLower(c.name) CONTAINS toLower($act)
           OR toLower(a.title) CONTAINS toLower($act)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               1.4 AS score, "act_graph" AS source, [$act] AS matched_terms
        ORDER BY a.article_number
        LIMIT $limit
        """,
        {"act": act, "limit": limit},
    )


def find_drug_articles(limit: int = 20) -> list[dict]:
    return find_articles_by_keyword("ma túy", limit)


def find_article_with_penalty_frames(article_number: str) -> dict | None:
    return fetch_context_by_article(str(article_number))


def find_conditions_and_penalty_frames(article_number: str) -> dict | None:
    return fetch_context_by_article(str(article_number))


def find_quantity_thresholds(substance: str, limit: int = 20) -> list[dict]:
    return neo4j_db.try_query(
        """
        MATCH (qt:QuantityThreshold)
        WHERE toLower(coalesce(qt.substance, qt.substance_name, qt.text, qt.description, "")) CONTAINS toLower($substance)
        RETURN qt AS quantity_threshold
        LIMIT $limit
        """,
        {"substance": substance, "limit": limit},
    )


def fetch_by_article(article_number: str | int) -> list[dict]:
    ctx = fetch_context_by_article(str(article_number))
    return [ctx] if ctx else []
