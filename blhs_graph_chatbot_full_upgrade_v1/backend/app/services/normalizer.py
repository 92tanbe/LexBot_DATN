from __future__ import annotations

from app.core.neo4j import neo4j_db


def normalize_text_with_graph(text: str) -> list[dict]:
    rows: list[dict] = []
    rows.extend(neo4j_db.try_query(
        """
        MATCH (s:SlangTerm)
        WHERE toLower($text) CONTAINS toLower(s.text)
        OPTIONAL MATCH (s)-[:NORMALIZES_TO]->(target)
        RETURN s.text AS text, labels(target) AS target_labels,
               coalesce(target.name, target.description, target.text, target.id) AS target_name,
               "slang_term" AS type
        """,
        {"text": text},
    ))
    rows.extend(neo4j_db.try_query(
        """
        MATCH (a:ActionAlias)
        WHERE toLower($text) CONTAINS toLower(a.text)
        OPTIONAL MATCH (a)-[:MAY_INDICATE]->(signal:LegalSignal)
        RETURN a.text AS text, signal.name AS signal_name, signal.id AS signal_id, "action_alias" AS type
        """,
        {"text": text},
    ))
    rows.extend(neo4j_db.try_query(
        """
        MATCH (sa:SubstanceAlias)
        WHERE toLower($text) CONTAINS toLower(sa.text)
        OPTIONAL MATCH (sa)-[:NORMALIZES_TO]->(sub:Substance)
        RETURN sa.text AS text, sub.name AS substance_name, sub.id AS substance_id, "substance_alias" AS type
        """,
        {"text": text},
    ))
    rows.extend(neo4j_db.try_query(
        """
        MATCH (sig:LegalSignal)-[:RELATED_TO]->(a:Article)
        WHERE toLower($text) CONTAINS toLower(sig.name)
        RETURN sig.name AS signal_name, a.article_code AS article_code, a.title AS title, "legal_signal" AS type
        LIMIT 20
        """,
        {"text": text},
    ))
    return rows


def normalize_endpoint_payload(text: str) -> dict:
    rows = normalize_text_with_graph(text)
    return {
        "slang_terms": [r for r in rows if r.get("type") == "slang_term"],
        "action_aliases": [r for r in rows if r.get("type") == "action_alias"],
        "substance_aliases": [r for r in rows if r.get("type") == "substance_alias"],
        "legal_signals": [r for r in rows if r.get("type") == "legal_signal"],
    }
