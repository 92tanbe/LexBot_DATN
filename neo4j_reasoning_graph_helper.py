from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from uuid import uuid4

import pandas as pd
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def run_cypher(query: str, params: dict | None = None):
    params = params or {}
    with driver.session() as session:
        result = session.run(query, params)
        summary = result.consume()
        counters = summary.counters
        return {
            "nodes_created": counters.nodes_created,
            "relationships_created": counters.relationships_created,
            "properties_set": counters.properties_set,
        }


def fetch_all(query: str, params: dict | None = None):
    params = params or {}
    with driver.session() as session:
        return [dict(record) for record in session.run(query, params)]


def normalize_text(text: str | None) -> str:
    if text is None or pd.isna(text):
        return ""
    text = str(text).lower().strip()
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_terms(text: str | None) -> list[str]:
    if not text:
        return []
    norm = normalize_text(text)
    if not norm:
        return []
    parts = re.split(r"[,;]|\bva\b|\bhoac\b|\bvoi\b", norm)
    return sorted({part.strip() for part in parts if part and part.strip()})


TERM_SYNONYMS = {
    "giet": ["giet nguoi", "tước đoạt tính mạng", "tuoc doat tinh mang", "lam chet nguoi"],
    "giet nguoi": ["giet", "tuoc doat tinh mang", "lam chet nguoi"],
    "nguoi": ["nguoi khac", "nan nhan", "bi hai"],
    "chet nguoi": ["lam chet nguoi", "gay chet nguoi", "tu vong", "chet"],
    "co y": ["co y", "co y truc tiep", "co y gian tiep"],
    "gay thuong tich": ["co y gay thuong tich", "gay ton hai suc khoe"],
}


def expand_terms(terms: list[str]) -> list[str]:
    expanded = set(terms)
    for term in terms:
        expanded.update(TERM_SYNONYMS.get(term, []))
    return sorted(expanded)


def build_case_payload(
    action_text: str = "",
    victim_text: str = "",
    consequence_text: str = "",
    actor_text: str = "",
    intent_text: str = "",
):
    action_terms = expand_terms(split_terms(action_text))
    victim_terms = expand_terms(split_terms(victim_text))
    consequence_terms = expand_terms(split_terms(consequence_text))
    actor_terms = expand_terms(split_terms(actor_text))
    intent_terms = expand_terms(split_terms(intent_text))
    return {
        "action_terms": action_terms,
        "victim_terms": victim_terms,
        "consequence_terms": consequence_terms,
        "actor_terms": actor_terms,
        "intent_terms": intent_terms,
        "raw": {
            "action": action_text,
            "victim": victim_text,
            "consequence": consequence_text,
            "actor": actor_text,
            "intent": intent_text,
        },
    }


SETUP_QUERIES = [
    "CREATE CONSTRAINT reasoning_case_id IF NOT EXISTS FOR (n:ReasoningCase) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT reasoning_term_id IF NOT EXISTS FOR (n:ReasoningTerm) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT reasoning_candidate_id IF NOT EXISTS FOR (n:ReasoningCandidate) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT reasoning_step_id IF NOT EXISTS FOR (n:ReasoningStep) REQUIRE n.id IS UNIQUE",
]


def setup_reasoning_graph():
    driver.verify_connectivity()
    for query in SETUP_QUERIES:
        run_cypher(query)


def materialize_normalized_properties():
    label_props = [
        ("ActionType", "name", "name_norm"),
        ("VictimType", "name", "name_norm"),
        ("ConsequenceType", "name", "name_norm"),
        ("ActorRole", "name", "name_norm"),
        ("IntentType", "name", "name_norm"),
        ("CrimeCategory", "name", "name_norm"),
        ("CrimeGroup", "name", "name_norm"),
        ("PenaltyMain", "name", "name_norm"),
        ("ExceptionClause", "text", "text_norm"),
        ("Dieu", "tieu_de", "tieu_de_norm"),
        ("Dieu", "noi_dung", "noi_dung_norm"),
        ("Dieu", "full_text", "full_text_norm"),
        ("Khoan", "noi_dung", "noi_dung_norm"),
        ("Khoan", "full_text", "full_text_norm"),
        ("Diem", "noi_dung", "noi_dung_norm"),
        ("Diem", "full_text", "full_text_norm"),
    ]

    total = 0
    for label, source_prop, target_prop in label_props:
        rows = fetch_all(
            f"MATCH (n:{label}) WHERE n.{source_prop} IS NOT NULL "
            f"RETURN elementId(n) AS eid, n.{source_prop} AS value"
        )
        for row in rows:
            run_cypher(
                f"MATCH (n) WHERE elementId(n) = $eid SET n.{target_prop} = $norm",
                {"eid": row["eid"], "norm": normalize_text(row["value"])},
            )
            total += 1
    return total


RANK_CANDIDATES_QUERY = """
MATCH (n)
WHERE n:Dieu OR n:Khoan OR n:Diem
OPTIONAL MATCH (n)<-[:HAS_KHOAN]-(parent_dieu_from_khoan:Dieu)
OPTIONAL MATCH (n)<-[:HAS_DIEM]-(:Khoan)<-[:HAS_KHOAN]-(parent_dieu_from_diem:Dieu)
OPTIONAL MATCH (n)-[:HAS_ACTION]->(a:ActionType)
OPTIONAL MATCH (n)-[:HAS_VICTIM]->(v:VictimType)
OPTIONAL MATCH (n)-[:HAS_CONSEQUENCE]->(c:ConsequenceType)
OPTIONAL MATCH (n)-[:HAS_ACTOR]->(ar:ActorRole)
OPTIONAL MATCH (n)-[:HAS_INTENT]->(it:IntentType)
OPTIONAL MATCH (n)-[:HAS_CRIME_CATEGORY]->(cc:CrimeCategory)
OPTIONAL MATCH (n)-[:HAS_CRIME_GROUP]->(cg:CrimeGroup)
OPTIONAL MATCH (n)-[:HAS_PENALTY_MAIN]->(pm:PenaltyMain)
OPTIONAL MATCH (n)-[:EXCEPTION]->(exd1:Dieu)
OPTIONAL MATCH (n)-[:HAS_EXCEPTION]->(exc:ExceptionClause)
OPTIONAL MATCH (exc)-[:EXCEPTS_DIEU]->(exd2:Dieu)
WITH n,
     coalesce(n.so_dieu, parent_dieu_from_khoan.so_dieu, parent_dieu_from_diem.so_dieu) AS article_so_dieu,
     coalesce(n.tieu_de, parent_dieu_from_khoan.tieu_de, parent_dieu_from_diem.tieu_de, '') AS article_tieu_de,
     coalesce(n.tieu_de_norm, parent_dieu_from_khoan.tieu_de_norm, parent_dieu_from_diem.tieu_de_norm, '') AS article_tieu_de_norm,
     collect(DISTINCT {name: a.name, norm: coalesce(a.name_norm, '')}) AS action_nodes,
     collect(DISTINCT {name: v.name, norm: coalesce(v.name_norm, '')}) AS victim_nodes,
     collect(DISTINCT {name: c.name, norm: coalesce(c.name_norm, '')}) AS consequence_nodes,
     collect(DISTINCT {name: ar.name, norm: coalesce(ar.name_norm, '')}) AS actor_nodes,
     collect(DISTINCT {name: it.name, norm: coalesce(it.name_norm, '')}) AS intent_nodes,
     collect(DISTINCT cc.name) AS crime_categories,
     collect(DISTINCT cg.name) AS crime_groups,
     collect(DISTINCT pm.name) AS penalty_main,
     collect(DISTINCT exd1.so_dieu) AS direct_excluded,
     collect(DISTINCT exd2.so_dieu) AS clause_excluded,
     collect(DISTINCT exc.text) AS exception_texts,
     coalesce(n.full_text_norm, '') AS full_text_norm,
     coalesce(n.noi_dung_norm, '') AS noi_dung_norm
WITH n,
     article_so_dieu,
     article_tieu_de,
     article_tieu_de_norm,
     crime_categories,
     crime_groups,
     penalty_main,
     [x IN action_nodes WHERE x.norm <> '' AND any(term IN $action_terms WHERE x.norm CONTAINS term OR term CONTAINS x.norm) | x.name] AS matched_actions,
     [x IN victim_nodes WHERE x.norm <> '' AND any(term IN $victim_terms WHERE x.norm CONTAINS term OR term CONTAINS x.norm) | x.name] AS matched_victims,
     [x IN consequence_nodes WHERE x.norm <> '' AND any(term IN $consequence_terms WHERE x.norm CONTAINS term OR term CONTAINS x.norm) | x.name] AS matched_consequences,
     [x IN actor_nodes WHERE x.norm <> '' AND any(term IN $actor_terms WHERE x.norm CONTAINS term OR term CONTAINS x.norm) | x.name] AS matched_actors,
     [x IN intent_nodes WHERE x.norm <> '' AND any(term IN $intent_terms WHERE x.norm CONTAINS term OR term CONTAINS x.norm) | x.name] AS matched_intents,
     [term IN $action_terms WHERE article_tieu_de_norm CONTAINS term] AS title_action_hits,
     [term IN $action_terms WHERE full_text_norm CONTAINS term OR noi_dung_norm CONTAINS term OR article_tieu_de_norm CONTAINS term] AS text_action_hits,
     [term IN $victim_terms WHERE full_text_norm CONTAINS term OR noi_dung_norm CONTAINS term] AS text_victim_hits,
     [term IN $consequence_terms WHERE full_text_norm CONTAINS term OR noi_dung_norm CONTAINS term] AS text_consequence_hits,
     [term IN $actor_terms WHERE full_text_norm CONTAINS term OR noi_dung_norm CONTAINS term] AS text_actor_hits,
     [term IN $intent_terms WHERE full_text_norm CONTAINS term OR noi_dung_norm CONTAINS term] AS text_intent_hits,
     [term IN $action_terms WHERE NOT any(x IN action_nodes WHERE x.norm <> '' AND (x.norm CONTAINS term OR term CONTAINS x.norm))] AS missing_actions,
     [term IN $victim_terms WHERE NOT any(x IN victim_nodes WHERE x.norm <> '' AND (x.norm CONTAINS term OR term CONTAINS x.norm))] AS missing_victims,
     [term IN $consequence_terms WHERE NOT any(x IN consequence_nodes WHERE x.norm <> '' AND (x.norm CONTAINS term OR term CONTAINS x.norm))] AS missing_consequences,
     [term IN $actor_terms WHERE NOT any(x IN actor_nodes WHERE x.norm <> '' AND (x.norm CONTAINS term OR term CONTAINS x.norm))] AS missing_actors,
     [term IN $intent_terms WHERE NOT any(x IN intent_nodes WHERE x.norm <> '' AND (x.norm CONTAINS term OR term CONTAINS x.norm))] AS missing_intents,
     [x IN direct_excluded + clause_excluded WHERE x IS NOT NULL] AS excluded_articles,
     [x IN exception_texts WHERE x IS NOT NULL AND trim(x) <> ''] AS exception_texts
WITH n,
     article_so_dieu,
     article_tieu_de,
     article_tieu_de_norm,
     crime_categories,
     crime_groups,
     penalty_main,
     matched_actions,
     matched_victims,
     matched_consequences,
     matched_actors,
     matched_intents,
     title_action_hits,
     text_action_hits,
     text_victim_hits,
     text_consequence_hits,
     text_actor_hits,
     text_intent_hits,
     missing_actions,
     missing_victims,
     missing_consequences,
     missing_actors,
     missing_intents,
     excluded_articles,
     exception_texts,
     (
        size(matched_actions) * 5 +
        size(matched_victims) * 4 +
        size(matched_consequences) * 4 +
        size(matched_actors) * 3 +
        size(matched_intents) * 3 +
        size(title_action_hits) * 6 +
        size(text_action_hits) * 2 +
        size(text_victim_hits) +
        size(text_consequence_hits) +
        size(text_actor_hits) +
        size(text_intent_hits)
     ) AS support_score,
     (
        size(missing_actions) + size(missing_victims) +
        size(missing_consequences) + size(missing_actors) + size(missing_intents)
     ) AS missing_count
WITH n,
     article_so_dieu,
     article_tieu_de,
     article_tieu_de_norm,
     crime_categories,
     crime_groups,
     penalty_main,
     matched_actions,
     matched_victims,
     matched_consequences,
     matched_actors,
     matched_intents,
     title_action_hits,
     text_action_hits,
     text_victim_hits,
     text_consequence_hits,
     text_actor_hits,
     text_intent_hits,
     missing_actions,
     missing_victims,
     missing_consequences,
     missing_actors,
     missing_intents,
     excluded_articles,
     exception_texts,
     support_score,
     missing_count,
     size(matched_actions) + size(matched_victims) + size(matched_consequences) + size(matched_actors) + size(matched_intents) AS semantic_hit_count,
     size(text_action_hits) + size(text_victim_hits) + size(text_consequence_hits) + size(text_actor_hits) + size(text_intent_hits) AS text_hit_count
WHERE (semantic_hit_count > 0 OR text_hit_count > 0)
  AND (size($action_terms) = 0 OR size(matched_actions) + size(text_action_hits) > 0)
RETURN labels(n)[0] AS level,
       n.id AS node_id,
       article_so_dieu AS so_dieu,
       article_tieu_de AS tieu_de,
       crime_categories,
       crime_groups,
       penalty_main,
       matched_actions,
       matched_victims,
       matched_consequences,
       matched_actors,
       matched_intents,
       text_action_hits,
       text_victim_hits,
       text_consequence_hits,
       text_actor_hits,
       text_intent_hits,
       missing_actions,
       missing_victims,
       missing_consequences,
       missing_actors,
       missing_intents,
       excluded_articles,
       exception_texts,
       support_score,
       missing_count,
       size(excluded_articles) AS exception_count,
       (support_score - size(excluded_articles) * 0.25) AS final_score
ORDER BY final_score DESC, missing_count ASC, exception_count ASC, so_dieu ASC
LIMIT $limit
"""


MERGE_CASE_QUERY = """
MERGE (c:ReasoningCase {id: $case_id})
SET c.case_name = $case_name,
    c.created_at = $created_at,
    c.prompt_action = $prompt_action,
    c.prompt_victim = $prompt_victim,
    c.prompt_consequence = $prompt_consequence,
    c.prompt_actor = $prompt_actor,
    c.prompt_intent = $prompt_intent,
    c.action_terms = $action_terms,
    c.victim_terms = $victim_terms,
    c.consequence_terms = $consequence_terms,
    c.actor_terms = $actor_terms,
    c.intent_terms = $intent_terms
RETURN c
"""

MERGE_TERM_QUERY = """
MATCH (c:ReasoningCase {id: $case_id})
MERGE (t:ReasoningTerm {id: $term_id})
SET t.case_id = $case_id,
    t.term_type = $term_type,
    t.value = $value,
    t.value_norm = $value_norm
MERGE (c)-[:HAS_TERM]->(t)
RETURN t
"""

MERGE_CANDIDATE_QUERY = """
MATCH (c:ReasoningCase {id: $case_id})
MATCH (law) WHERE law.id = $node_id
MERGE (cand:ReasoningCandidate {id: $candidate_id})
SET cand.case_id = $case_id,
    cand.rank = $rank,
    cand.status = $status,
    cand.level = $level,
    cand.node_id = $node_id,
    cand.so_dieu = $so_dieu,
    cand.tieu_de = $tieu_de,
    cand.support_score = $support_score,
    cand.final_score = $final_score,
    cand.missing_count = $missing_count,
    cand.exception_count = $exception_count,
    cand.crime_categories = $crime_categories,
    cand.crime_groups = $crime_groups,
    cand.penalty_main = $penalty_main,
    cand.created_at = $created_at
MERGE (c)-[:HAS_CANDIDATE]->(cand)
MERGE (cand)-[:CANDIDATE_FOR]->(law)
RETURN cand
"""

MERGE_STEP_QUERY = """
MATCH (cand:ReasoningCandidate {id: $candidate_id})
MERGE (step:ReasoningStep {id: $step_id})
SET step.case_id = $case_id,
    step.candidate_id = $candidate_id,
    step.step_type = $step_type,
    step.dimension = $dimension,
    step.verdict = $verdict,
    step.weight = $weight,
    step.input_terms = $input_terms,
    step.matched_terms = $matched_terms,
    step.text_hits = $text_hits,
    step.missing_terms = $missing_terms,
    step.detail = $detail
MERGE (cand)-[:HAS_STEP]->(step)
WITH step
UNWIND $term_ids AS term_id
MATCH (t:ReasoningTerm {id: term_id})
MERGE (step)-[:USES_TERM]->(t)
RETURN step
"""

LINK_EXCLUDED_ARTICLES_QUERY = """
MATCH (cand:ReasoningCandidate {id: $candidate_id})
UNWIND $excluded_articles AS so_dieu
MATCH (d:Dieu)
WHERE d.so_dieu = toFloat(so_dieu)
MERGE (cand)-[:EXCLUDES_ARTICLE]->(d)
RETURN count(d) AS linked
"""

TRACE_CASE_QUERY = """
MATCH (c:ReasoningCase {id: $case_id})-[:HAS_CANDIDATE]->(cand:ReasoningCandidate)-[:CANDIDATE_FOR]->(law)
OPTIONAL MATCH (cand)-[:HAS_STEP]->(step:ReasoningStep)
OPTIONAL MATCH (cand)-[:EXCLUDES_ARTICLE]->(exd:Dieu)
WITH c, cand, law,
     collect(DISTINCT {
         step_type: step.step_type,
         dimension: step.dimension,
         verdict: step.verdict,
         weight: step.weight,
         input_terms: step.input_terms,
         matched_terms: step.matched_terms,
         text_hits: step.text_hits,
         missing_terms: step.missing_terms,
         detail: step.detail
     }) AS steps,
     collect(DISTINCT exd.so_dieu) AS excluded_articles
RETURN c.id AS case_id,
       c.case_name AS case_name,
       cand.rank AS rank,
       cand.status AS status,
       cand.level AS level,
       cand.so_dieu AS so_dieu,
       cand.tieu_de AS tieu_de,
       cand.final_score AS final_score,
       cand.support_score AS support_score,
       cand.missing_count AS missing_count,
       cand.exception_count AS exception_count,
       cand.crime_categories AS crime_categories,
       cand.crime_groups AS crime_groups,
       cand.penalty_main AS penalty_main,
       excluded_articles,
       steps
ORDER BY rank ASC
"""

EXCLUSION_TRACE_QUERY = """
MATCH (c:ReasoningCase {id: $case_id})-[:HAS_CANDIDATE]->(cand:ReasoningCandidate)-[:EXCLUDES_ARTICLE]->(exd:Dieu)
WHERE cand.rank <= $top_k
RETURN cand.rank AS rank,
       cand.so_dieu AS source_so_dieu,
       cand.tieu_de AS source_tieu_de,
       collect(DISTINCT exd.so_dieu) AS excluded_articles
ORDER BY rank ASC
"""

TRACE_CASE_QUERY_NO_EXCLUSION = """
MATCH (c:ReasoningCase {id: $case_id})-[:HAS_CANDIDATE]->(cand:ReasoningCandidate)-[:CANDIDATE_FOR]->(law)
OPTIONAL MATCH (cand)-[:HAS_STEP]->(step:ReasoningStep)
WITH c, cand, law,
     collect(DISTINCT {
         step_type: step.step_type,
         dimension: step.dimension,
         verdict: step.verdict,
         weight: step.weight,
         input_terms: step.input_terms,
         matched_terms: step.matched_terms,
         text_hits: step.text_hits,
         missing_terms: step.missing_terms,
         detail: step.detail
     }) AS steps
RETURN c.id AS case_id,
       c.case_name AS case_name,
       cand.rank AS rank,
       cand.status AS status,
       cand.level AS level,
       cand.so_dieu AS so_dieu,
       cand.tieu_de AS tieu_de,
       cand.final_score AS final_score,
       cand.support_score AS support_score,
       cand.missing_count AS missing_count,
       cand.exception_count AS exception_count,
       cand.crime_categories AS crime_categories,
       cand.crime_groups AS crime_groups,
       cand.penalty_main AS penalty_main,
       [] AS excluded_articles,
       steps
ORDER BY rank ASC
"""


DIMENSION_WEIGHTS = {
    "action": 5,
    "victim": 4,
    "consequence": 4,
    "actor": 3,
    "intent": 3,
    "exclusion": 1,
}


def get_graph_stats():
    rows = fetch_all("MATCH (d:Dieu) RETURN count(d) AS dieu_count")
    return rows[0] if rows else {"dieu_count": 0}


def relationship_type_exists(rel_type: str) -> bool:
    rows = fetch_all(
        "CALL db.relationshipTypes() YIELD relationshipType WHERE relationshipType = $rel_type RETURN count(*) AS n",
        {"rel_type": rel_type},
    )
    return bool(rows and rows[0]["n"] > 0)


def upsert_case_terms(case_id: str, payload: dict):
    for term_type in ["action", "victim", "consequence", "actor", "intent"]:
        for value in payload[f"{term_type}_terms"]:
            run_cypher(
                MERGE_TERM_QUERY,
                {
                    "case_id": case_id,
                    "term_id": f"{case_id}|{term_type}|{value}",
                    "term_type": term_type,
                    "value": value,
                    "value_norm": value,
                },
            )


def make_step_detail(
    dimension: str,
    matched_terms: list[str],
    text_hits: list[str],
    missing_terms: list[str],
) -> str:
    matched_text = ", ".join(matched_terms) if matched_terms else "khong co"
    text_text = ", ".join(text_hits) if text_hits else "khong co"
    missing_text = ", ".join(missing_terms) if missing_terms else "khong co"
    return f"{dimension}: semantic={matched_text}; text={text_text}; missing={missing_text}"


def merge_candidate_steps(case_id: str, candidate_id: str, payload: dict, row: dict):
    dimensions = ["action", "victim", "consequence", "actor", "intent"]
    for dimension in dimensions:
        input_terms = payload[f"{dimension}_terms"]
        matched_terms = row[f"matched_{dimension}s"]
        text_hits = row[f"text_{dimension}_hits"]
        missing_terms = row[f"missing_{dimension}s"]
        if not input_terms:
            continue
        if not matched_terms and text_hits:
            verdict = "TEXT_ONLY"
        elif not matched_terms and not text_hits:
            verdict = "MISS"
        elif missing_terms:
            verdict = "PARTIAL"
        else:
            verdict = "MATCH"
        run_cypher(
            MERGE_STEP_QUERY,
            {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "step_id": f"{candidate_id}|{dimension}",
                "step_type": "SUPPORT",
                "dimension": dimension,
                "verdict": verdict,
                "weight": DIMENSION_WEIGHTS[dimension],
                "input_terms": input_terms,
                "matched_terms": matched_terms,
                "text_hits": text_hits,
                "missing_terms": missing_terms,
                "detail": make_step_detail(dimension, matched_terms, text_hits, missing_terms),
                "term_ids": [f"{case_id}|{dimension}|{term}" for term in input_terms],
            },
        )

    excluded_articles = [str(item) for item in row["excluded_articles"] if item is not None]
    exclusion_detail = "khong co"
    if excluded_articles:
        exclusion_detail = ", ".join(excluded_articles)
    run_cypher(
        MERGE_STEP_QUERY,
        {
            "case_id": case_id,
            "candidate_id": candidate_id,
            "step_id": f"{candidate_id}|exclusion",
            "step_type": "EXCLUSION_SCAN",
            "dimension": "exclusion",
            "verdict": "HAS_EXCEPTION" if excluded_articles else "NO_EXCEPTION",
            "weight": DIMENSION_WEIGHTS["exclusion"],
            "input_terms": [],
            "matched_terms": excluded_articles,
            "text_hits": row["exception_texts"],
            "missing_terms": [],
            "detail": f"Loai tru dieu: {exclusion_detail}",
            "term_ids": [],
        },
    )
    if excluded_articles:
        run_cypher(
            LINK_EXCLUDED_ARTICLES_QUERY,
            {"candidate_id": candidate_id, "excluded_articles": excluded_articles},
        )


def dedupe_candidate_rows(rows: list[dict], top_k: int) -> list[dict]:
    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for row in rows:
        key = str(row["so_dieu"]) if row.get("so_dieu") is not None else row["node_id"]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
        if len(deduped) >= top_k:
            break
    return deduped


def build_reasoning_graph(
    case_name: str,
    action_text: str = "",
    victim_text: str = "",
    consequence_text: str = "",
    actor_text: str = "",
    intent_text: str = "",
    top_k: int = 10,
):
    payload = build_case_payload(
        action_text=action_text,
        victim_text=victim_text,
        consequence_text=consequence_text,
        actor_text=actor_text,
        intent_text=intent_text,
    )
    rows = fetch_all(
        RANK_CANDIDATES_QUERY,
        {
            "action_terms": payload["action_terms"],
            "victim_terms": payload["victim_terms"],
            "consequence_terms": payload["consequence_terms"],
            "actor_terms": payload["actor_terms"],
            "intent_terms": payload["intent_terms"],
            "limit": top_k,
        },
    )
    rows = dedupe_candidate_rows(rows, top_k)
    if payload["action_terms"]:
        rows = [row for row in rows if row["matched_actions"] or row["text_action_hits"]]

    case_id = f"case-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    created_at = datetime.now().isoformat(timespec="seconds")
    run_cypher(
        MERGE_CASE_QUERY,
        {
            "case_id": case_id,
            "case_name": case_name,
            "created_at": created_at,
            "prompt_action": payload["raw"]["action"],
            "prompt_victim": payload["raw"]["victim"],
            "prompt_consequence": payload["raw"]["consequence"],
            "prompt_actor": payload["raw"]["actor"],
            "prompt_intent": payload["raw"]["intent"],
            "action_terms": payload["action_terms"],
            "victim_terms": payload["victim_terms"],
            "consequence_terms": payload["consequence_terms"],
            "actor_terms": payload["actor_terms"],
            "intent_terms": payload["intent_terms"],
        },
    )
    upsert_case_terms(case_id, payload)

    for rank, row in enumerate(rows, start=1):
        candidate_id = f"{case_id}|{row['node_id']}"
        run_cypher(
            MERGE_CANDIDATE_QUERY,
            {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "rank": rank,
                "status": "RECOMMENDED" if rank == 1 else "CANDIDATE",
                "level": row["level"],
                "node_id": row["node_id"],
                "so_dieu": row["so_dieu"],
                "tieu_de": row["tieu_de"],
                "support_score": row["support_score"],
                "final_score": row["final_score"],
                "missing_count": row["missing_count"],
                "exception_count": row["exception_count"],
                "crime_categories": row["crime_categories"],
                "crime_groups": row["crime_groups"],
                "penalty_main": row["penalty_main"],
                "created_at": created_at,
            },
        )
        merge_candidate_steps(case_id, candidate_id, payload, row)

    return case_id, rows


def trace_case(case_id: str) -> pd.DataFrame:
    candidate_count = fetch_all(
        "MATCH (:ReasoningCase {id: $case_id})-[:HAS_CANDIDATE]->(cand:ReasoningCandidate) RETURN count(cand) AS n",
        {"case_id": case_id},
    )[0]["n"]
    if candidate_count == 0:
        return pd.DataFrame()
    query = TRACE_CASE_QUERY if relationship_type_exists("EXCLUDES_ARTICLE") else TRACE_CASE_QUERY_NO_EXCLUSION
    return pd.DataFrame(fetch_all(query, {"case_id": case_id}))


def trace_exclusions(case_id: str, top_k: int = 5) -> pd.DataFrame:
    if not relationship_type_exists("EXCLUDES_ARTICLE"):
        return pd.DataFrame()
    exclusion_count = fetch_all(
        "MATCH (:ReasoningCase {id: $case_id})-[:HAS_CANDIDATE]->(:ReasoningCandidate)-[:EXCLUDES_ARTICLE]->(:Dieu) RETURN count(*) AS n",
        {"case_id": case_id},
    )[0]["n"]
    if exclusion_count == 0:
        return pd.DataFrame()
    return pd.DataFrame(fetch_all(EXCLUSION_TRACE_QUERY, {"case_id": case_id, "top_k": top_k}))
