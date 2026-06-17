from __future__ import annotations

import re

ALLOWED_LABELS = {
    "Law", "Part", "Chapter", "Section", "Article", "Clause", "Point", "Crime", "Rule", "Condition",
    "PenaltyFrame", "Penalty", "LegalConcept", "AggravatingFactor", "MitigatingFactor",
    "SubjectRequirement", "ObjectRequirement", "ActRequirement", "ConsequenceRequirement",
    "QuantityThreshold", "Exception", "Reference", "SlangTerm", "ActionAlias", "LegalSignal",
    "Substance", "SubstanceAlias", "JudicialMeasure",
}
ALLOWED_RELATIONSHIPS = {
    "HAS_PART", "HAS_CHAPTER", "HAS_ARTICLE", "HAS_SECTION", "HAS_CLAUSE", "HAS_POINT",
    "DEFINES_CRIME", "HAS_RULE", "HAS_CONDITION", "HAS_ACT_REQUIREMENT",
    "HAS_SUBJECT_REQUIREMENT", "HAS_OBJECT_REQUIREMENT", "HAS_CONSEQUENCE_REQUIREMENT",
    "HAS_QUANTITY_THRESHOLD", "HAS_PENALTY_FRAME", "HAS_MAIN_PENALTY",
    "HAS_ADDITIONAL_PENALTY", "HAS_PENALTY", "HAS_JUDICIAL_MEASURE", "HAS_EXCEPTION",
    "HAS_MITIGATING_FACTOR", "HAS_AGGRAVATING_FACTOR", "REFERENCES", "NORMALIZES_TO",
    "MAY_INDICATE", "RELATED_TO",
}
FORBIDDEN = re.compile(r"\b(DELETE|DETACH|REMOVE|SET|MERGE|CREATE|DROP|LOAD\s+CSV|CALL\s+apoc)\b", re.I)


def validate_readonly_cypher(cypher: str) -> None:
    if FORBIDDEN.search(cypher):
        raise ValueError("Cypher runtime query must be read-only.")
    for label in re.findall(r":([A-Za-z][A-Za-z0-9_]*)", cypher):
        if label.isupper():
            if label not in ALLOWED_RELATIONSHIPS:
                raise ValueError(f"Relationship not allowed: {label}")
        elif label not in ALLOWED_LABELS:
            raise ValueError(f"Label not allowed: {label}")
