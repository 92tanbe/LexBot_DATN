from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
IMPORT_DIR = ROOT / "neo4j_import"
ENV_PATH = ROOT / "backend" / ".env"
BATCH_SIZE = 500


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def to_int(value: str | None) -> int | None:
    value = clean(value)
    return int(value) if value is not None else None


def to_float(value: str | None) -> float | None:
    value = clean(value)
    return float(value) if value is not None else None


def to_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def as_row(raw: dict[str, str], converters: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in raw.items():
        converter = converters.get(key, clean)
        row[key] = converter(value)
    return row


def read_csv(name: str, converters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    path = IMPORT_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [as_row(row, converters or {}) for row in csv.DictReader(f)]


@dataclass(frozen=True)
class NodeSpec:
    file: str
    label: str
    key: str
    converters: dict[str, Any]


NODE_SPECS = [
    NodeSpec("laws.csv", "Law", "id", {}),
    NodeSpec("parts.csv", "Part", "id", {}),
    NodeSpec("chapters.csv", "Chapter", "id", {}),
    NodeSpec("sections.csv", "Section", "id", {}),
    NodeSpec("articles.csv", "Article", "id", {"article_number": to_int, "page_start": to_int, "page_end": to_int}),
    NodeSpec("clauses.csv", "Clause", "id", {"clause_no": to_int}),
    NodeSpec("points.csv", "Point", "id", {"clause_no": to_int}),
    NodeSpec("conditions.csv", "Condition", "id", {"required": to_bool}),
    NodeSpec(
        "penalty_frames.csv",
        "PenaltyFrame",
        "id",
        {
            "min_imprisonment_months": to_int,
            "max_imprisonment_months": to_int,
            "fine_min_vnd": to_int,
            "fine_max_vnd": to_int,
            "has_life_imprisonment": to_bool,
            "has_death_penalty": to_bool,
        },
    ),
    NodeSpec("crimes.csv", "Crime", "id", {}),
    NodeSpec("rules.csv", "Rule", "id", {"clause_no": to_int, "priority": to_int}),
    NodeSpec(
        "penalties.csv",
        "Penalty",
        "id",
        {
            "min_imprisonment_months": to_int,
            "max_imprisonment_months": to_int,
            "fine_min_vnd": to_int,
            "fine_max_vnd": to_int,
            "has_life_imprisonment": to_bool,
            "has_death_penalty": to_bool,
        },
    ),
    NodeSpec("legal_concepts.csv", "LegalConcept", "id", {}),
    NodeSpec("mitigating_factors.csv", "MitigatingFactor", "id", {}),
    NodeSpec("aggravating_factors.csv", "AggravatingFactor", "id", {}),
    NodeSpec("subject_requirements.csv", "SubjectRequirement", "id", {}),
    NodeSpec("object_requirements.csv", "ObjectRequirement", "id", {}),
    NodeSpec("act_requirements.csv", "ActRequirement", "id", {}),
    NodeSpec("consequence_requirements.csv", "ConsequenceRequirement", "id", {}),
    NodeSpec("quantity_thresholds.csv", "QuantityThreshold", "id", {"min_value": to_float, "max_value": to_float}),
    NodeSpec("exceptions.csv", "Exception", "id", {}),
    NodeSpec("judicial_measures.csv", "JudicialMeasure", "id", {}),
    NodeSpec("references.csv", "Reference", "id", {}),
    NodeSpec("legal_signals.csv", "LegalSignal", "id", {}),
    NodeSpec("substances.csv", "Substance", "id", {}),
    NodeSpec("substance_aliases.csv", "SubstanceAlias", "id", {}),
    NodeSpec("slang_terms.csv", "SlangTerm", "id", {}),
    NodeSpec("action_aliases.csv", "ActionAlias", "id", {}),
]


CONSTRAINTS_AND_INDEXES = [
    "CREATE CONSTRAINT law_id IF NOT EXISTS FOR (n:Law) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT part_id IF NOT EXISTS FOR (n:Part) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT article_code IF NOT EXISTS FOR (n:Article) REQUIRE n.article_code IS UNIQUE",
    "CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (n:Clause) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT crime_id IF NOT EXISTS FOR (n:Crime) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (n:Rule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT condition_id IF NOT EXISTS FOR (n:Condition) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT penalty_frame_id IF NOT EXISTS FOR (n:PenaltyFrame) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT penalty_id IF NOT EXISTS FOR (n:Penalty) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT legal_concept_id IF NOT EXISTS FOR (n:LegalConcept) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT aggravating_id IF NOT EXISTS FOR (n:AggravatingFactor) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT mitigating_id IF NOT EXISTS FOR (n:MitigatingFactor) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT subject_req_id IF NOT EXISTS FOR (n:SubjectRequirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT object_req_id IF NOT EXISTS FOR (n:ObjectRequirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT act_req_id IF NOT EXISTS FOR (n:ActRequirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT consequence_req_id IF NOT EXISTS FOR (n:ConsequenceRequirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT quantity_threshold_id IF NOT EXISTS FOR (n:QuantityThreshold) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT exception_id IF NOT EXISTS FOR (n:Exception) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT reference_id IF NOT EXISTS FOR (n:Reference) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT judicial_measure_id IF NOT EXISTS FOR (n:JudicialMeasure) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT slang_id IF NOT EXISTS FOR (n:SlangTerm) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT legal_signal_id IF NOT EXISTS FOR (n:LegalSignal) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT action_alias_id IF NOT EXISTS FOR (n:ActionAlias) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT substance_id IF NOT EXISTS FOR (n:Substance) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT substance_alias_id IF NOT EXISTS FOR (n:SubstanceAlias) REQUIRE n.id IS UNIQUE",
    "CREATE FULLTEXT INDEX article_fulltext IF NOT EXISTS FOR (n:Article) ON EACH [n.title, n.full_text, n.normalized_text]",
    "CREATE FULLTEXT INDEX clause_fulltext IF NOT EXISTS FOR (n:Clause) ON EACH [n.text, n.normalized_text]",
    "CREATE FULLTEXT INDEX condition_fulltext IF NOT EXISTS FOR (n:Condition) ON EACH [n.text, n.normalized_text]",
    "CREATE FULLTEXT INDEX crime_fulltext IF NOT EXISTS FOR (n:Crime) ON EACH [n.name, n.normalized_name]",
    "CREATE FULLTEXT INDEX concept_fulltext IF NOT EXISTS FOR (n:LegalConcept) ON EACH [n.name, n.description, n.normalized_name]",
]


def batched(rows: list[dict[str, Any]], size: int = BATCH_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def run_batches(session, cypher: str, rows: list[dict[str, Any]]) -> int:
    count = 0
    for batch in batched(rows):
        session.run(cypher, rows=batch).consume()
        count += len(batch)
    return count


def merge_nodes(session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in NODE_SPECS:
        rows = read_csv(spec.file, spec.converters)
        if not rows:
            counts[spec.label] = 0
            continue
        cypher = f"""
        UNWIND $rows AS row
        MERGE (n:{spec.label} {{{spec.key}: row.{spec.key}}})
        SET n += row
        """
        counts[spec.label] = run_batches(session, cypher, rows)
        print(f"Imported {counts[spec.label]:>5} {spec.label}")
    return counts


def relationship(session, rows: list[dict[str, Any]], cypher: str, label: str) -> int:
    if not rows:
        return 0
    count = run_batches(session, cypher, rows)
    print(f"Linked   {count:>5} {label}")
    return count


def merge_relationships(session) -> None:
    relationship(
        session,
        read_csv("parts.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Law {id: row.law_id}), (b:Part {id: row.id})
        MERGE (a)-[:HAS_PART]->(b)
        """,
        "Law-HAS_PART-Part",
    )
    relationship(
        session,
        read_csv("chapters.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Part {id: row.part_node_id}), (b:Chapter {id: row.id})
        MERGE (a)-[:HAS_CHAPTER]->(b)
        """,
        "Part-HAS_CHAPTER-Chapter",
    )
    relationship(
        session,
        read_csv("sections.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Chapter {id: row.chapter_node_id}), (b:Section {id: row.id})
        MERGE (a)-[:HAS_SECTION]->(b)
        """,
        "Chapter-HAS_SECTION-Section",
    )
    relationship(
        session,
        read_csv("articles.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:Article {id: row.id})
        OPTIONAL MATCH (ch:Chapter {id: row.chapter_node_id})
        FOREACH (_ IN CASE WHEN ch IS NULL THEN [] ELSE [1] END | MERGE (ch)-[:HAS_ARTICLE]->(b))
        WITH row, b
        OPTIONAL MATCH (s:Section {id: row.section_node_id})
        FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | MERGE (s)-[:HAS_ARTICLE]->(b))
        """,
        "Structure-HAS_ARTICLE-Article",
    )
    relationship(
        session,
        read_csv("clauses.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:Clause {id: row.id})
        MERGE (a)-[:HAS_CLAUSE]->(b)
        """,
        "Article-HAS_CLAUSE-Clause",
    )
    relationship(
        session,
        read_csv("points.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Clause {id: row.clause_id}), (b:Point {id: row.id})
        MERGE (a)-[:HAS_POINT]->(b)
        """,
        "Clause-HAS_POINT-Point",
    )
    relationship(
        session,
        read_csv("conditions.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:Condition {id: row.id})
        OPTIONAL MATCH (c:Clause {id: row.owner_id})
        WHERE row.owner_kind = 'Clause'
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_CONDITION]->(b))
        WITH row, b
        OPTIONAL MATCH (p:Point {id: row.owner_id})
        WHERE row.owner_kind = 'Point'
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:HAS_CONDITION]->(b))
        """,
        "Owner-HAS_CONDITION-Condition",
    )
    relationship(
        session,
        read_csv("penalty_frames.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:PenaltyFrame {id: row.id})
        OPTIONAL MATCH (c:Clause {id: row.owner_id})
        WHERE row.owner_kind = 'Clause'
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_PENALTY_FRAME]->(b))
        WITH row, b
        OPTIONAL MATCH (p:Point {id: row.owner_id})
        WHERE row.owner_kind = 'Point'
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:HAS_PENALTY_FRAME]->(b))
        """,
        "Owner-HAS_PENALTY_FRAME-PenaltyFrame",
    )
    relationship(
        session,
        read_csv("crimes.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:Crime {id: row.id})
        MERGE (a)-[:DEFINES_CRIME]->(b)
        """,
        "Article-DEFINES_CRIME-Crime",
    )
    relationship(
        session,
        read_csv("rules.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:Rule {id: row.id})
        MERGE (a)-[:HAS_RULE]->(b)
        WITH row, b
        OPTIONAL MATCH (c:Clause {id: row.owner_id})
        WHERE row.owner_kind = 'Clause'
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:REPRESENTS_RULE]->(b))
        WITH row, b
        OPTIONAL MATCH (p:Point {id: row.owner_id})
        WHERE row.owner_kind = 'Point'
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:REPRESENTS_RULE]->(b))
        """,
        "Article-HAS_RULE-Rule",
    )
    session.run(
        """
        MATCH (r:Rule), (c:Condition)
        WHERE r.owner_id IS NOT NULL
          AND c.id STARTS WITH 'condition_'
          AND c.id CONTAINS replace(r.owner_id, 'article_', 'article_')
          AND c.article_code = r.article_code
        MERGE (r)-[:HAS_CONDITION]->(c)
        """
    ).consume()
    relationship(
        session,
        read_csv("penalties.csv"),
        """
        UNWIND $rows AS row
        MATCH (pf:PenaltyFrame {id: row.penalty_frame_id}), (b:Penalty {id: row.id})
        FOREACH (_ IN CASE WHEN row.role = 'main' THEN [1] ELSE [] END | MERGE (pf)-[:HAS_MAIN_PENALTY]->(b))
        FOREACH (_ IN CASE WHEN row.role = 'additional' THEN [1] ELSE [] END | MERGE (pf)-[:HAS_ADDITIONAL_PENALTY]->(b))
        """,
        "PenaltyFrame-HAS_PENALTY-Penalty",
    )
    for file_name, child_label, rel_type in [
        ("subject_requirements.csv", "SubjectRequirement", "HAS_SUBJECT_REQUIREMENT"),
        ("object_requirements.csv", "ObjectRequirement", "HAS_OBJECT_REQUIREMENT"),
        ("act_requirements.csv", "ActRequirement", "HAS_ACT_REQUIREMENT"),
        ("consequence_requirements.csv", "ConsequenceRequirement", "HAS_CONSEQUENCE_REQUIREMENT"),
        ("quantity_thresholds.csv", "QuantityThreshold", "HAS_QUANTITY_THRESHOLD"),
    ]:
        relationship(
            session,
            read_csv(file_name),
            f"""
            UNWIND $rows AS row
            MATCH (a:Crime {{id: row.crime_id}}), (b:{child_label} {{id: row.id}})
            MERGE (a)-[:{rel_type}]->(b)
            """,
            f"Crime-{rel_type}-{child_label}",
        )
    relationship(
        session,
        read_csv("quantity_thresholds.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:QuantityThreshold {id: row.id})
        OPTIONAL MATCH (a:Condition {id: row.owner_id})
        WHERE row.owner_kind = 'Condition'
        FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (a)-[:HAS_QUANTITY_THRESHOLD]->(b))
        """,
        "Condition-HAS_QUANTITY_THRESHOLD-QuantityThreshold",
    )
    relationship(
        session,
        read_csv("exceptions.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:Exception {id: row.id})
        MERGE (a)-[:HAS_EXCEPTION]->(b)
        """,
        "Article-HAS_EXCEPTION-Exception",
    )
    relationship(
        session,
        read_csv("judicial_measures.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:JudicialMeasure {id: row.id})
        MERGE (a)-[:HAS_JUDICIAL_MEASURE]->(b)
        """,
        "Article-HAS_JUDICIAL_MEASURE-JudicialMeasure",
    )
    relationship(
        session,
        read_csv("mitigating_factors.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:MitigatingFactor {id: row.id})
        MERGE (a)-[:HAS_MITIGATING_FACTOR]->(b)
        """,
        "Article-HAS_MITIGATING_FACTOR-MitigatingFactor",
    )
    relationship(
        session,
        read_csv("aggravating_factors.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id}), (b:AggravatingFactor {id: row.id})
        MERGE (a)-[:HAS_AGGRAVATING_FACTOR]->(b)
        """,
        "Article-HAS_AGGRAVATING_FACTOR-AggravatingFactor",
    )
    relationship(
        session,
        read_csv("legal_concepts.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:LegalConcept {id: row.id})
        OPTIONAL MATCH (a:Article {id: row.article_id})
        FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (a)-[:HAS_LEGAL_CONCEPT]->(b))
        """,
        "Article-HAS_LEGAL_CONCEPT-LegalConcept",
    )
    relationship(
        session,
        read_csv("references.csv"),
        """
        UNWIND $rows AS row
        MATCH (b:Reference {id: row.id})
        OPTIONAL MATCH (fromA:Article {id: row.from_article_id})
        FOREACH (_ IN CASE WHEN fromA IS NULL THEN [] ELSE [1] END | MERGE (fromA)-[:HAS_REFERENCE]->(b))
        WITH row, b
        OPTIONAL MATCH (toA:Article {article_code: row.to_article_code})
        FOREACH (_ IN CASE WHEN toA IS NULL THEN [] ELSE [1] END | MERGE (b)-[:TARGETS]->(toA))
        WITH row
        OPTIONAL MATCH (fromA:Article {id: row.from_article_id})
        OPTIONAL MATCH (toA:Article {article_code: row.to_article_code})
        FOREACH (_ IN CASE WHEN fromA IS NULL OR toA IS NULL THEN [] ELSE [1] END | MERGE (fromA)-[:REFERENCES]->(toA))
        """,
        "Reference links",
    )
    relationship(
        session,
        read_csv("signal_article_links.csv"),
        """
        UNWIND $rows AS row
        MATCH (s:LegalSignal {id: row.signal_id})
        OPTIONAL MATCH (a:Article {article_code: row.article_code})
        FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (s)-[:RELATED_TO]->(a))
        """,
        "LegalSignal-RELATED_TO-Article",
    )
    relationship(
        session,
        read_csv("substance_aliases.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:SubstanceAlias {id: row.id}), (b:Substance {id: row.substance_id})
        MERGE (a)-[:NORMALIZES_TO]->(b)
        """,
        "SubstanceAlias-NORMALIZES_TO-Substance",
    )
    relationship(
        session,
        read_csv("slang_terms.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:SlangTerm {id: row.id})
        OPTIONAL MATCH (sig:LegalSignal {id: row.signal_id})
        FOREACH (_ IN CASE WHEN sig IS NULL THEN [] ELSE [1] END | MERGE (a)-[:MAY_INDICATE]->(sig))
        WITH row, a
        OPTIONAL MATCH (lc:LegalConcept {id: row.concept_id})
        FOREACH (_ IN CASE WHEN lc IS NULL THEN [] ELSE [1] END | MERGE (a)-[:NORMALIZES_TO]->(lc))
        WITH row, a
        OPTIONAL MATCH (sub:Substance {id: row.substance_id})
        FOREACH (_ IN CASE WHEN sub IS NULL THEN [] ELSE [1] END | MERGE (a)-[:NORMALIZES_TO]->(sub))
        """,
        "SlangTerm mappings",
    )
    relationship(
        session,
        read_csv("action_aliases.csv"),
        """
        UNWIND $rows AS row
        MATCH (a:ActionAlias {id: row.id}), (b:LegalSignal {id: row.signal_id})
        MERGE (a)-[:MAY_INDICATE]->(b)
        """,
        "ActionAlias-MAY_INDICATE-LegalSignal",
    )


def verify_counts(session) -> dict[str, int]:
    labels = ["Article", "Crime", "Clause", "Point", "Condition", "Rule", "PenaltyFrame", "Penalty"]
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = session.run(f"MATCH (n:{label}) RETURN count(n) AS count").single()["count"]
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local neo4j_import CSV files into Neo4j Aura using backend/.env.")
    parser.add_argument("--reset", action="store_true", help="Delete all Aura nodes before importing. Use only for an empty/rebuild database.")
    parser.add_argument("--skip-indexes", action="store_true", help="Skip constraints and fulltext indexes.")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    uri = os.getenv("NEO4J_URI", "")
    user = os.getenv("NEO4J_USER", "")
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    if not uri or not user or not password:
        print("Missing NEO4J_URI, NEO4J_USER, or NEO4J_PASSWORD in backend/.env", file=sys.stderr)
        return 2
    if "localhost" in uri or "127.0.0.1" in uri:
        print(f"Refusing to import because NEO4J_URI is local: {uri}", file=sys.stderr)
        return 2

    print(f"Connecting to {uri} database={database} user={user}")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            session.run("RETURN 1").consume()
            if args.reset:
                print("Resetting target database...")
                session.run("MATCH (n) DETACH DELETE n").consume()
            if not args.skip_indexes:
                print("Ensuring constraints and indexes...")
                for statement in CONSTRAINTS_AND_INDEXES:
                    session.run(statement).consume()
            print("Importing nodes...")
            merge_nodes(session)
            print("Importing relationships...")
            merge_relationships(session)
            counts = verify_counts(session)
            print("Verified counts:")
            for label, count in counts.items():
                print(f"  {label}: {count}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
