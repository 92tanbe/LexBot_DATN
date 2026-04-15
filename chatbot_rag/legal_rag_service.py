from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from neo4j import GraphDatabase
from pydantic import BaseModel, Field


GENERIC_TERMS = {
    "toi pham",
    "toi danh",
    "hinh phat",
    "luat hinh su",
    "bo luat hinh su",
    "trach nhiem hinh su",
    "truy cuu trach nhiem",
    "tham nhung",
}


class SearchHints(BaseModel):
    crime_hint: str = Field(default="")
    condition_hint: str = Field(default="")
    search_terms: list[str] = Field(default_factory=list)


def normalize_text(text: str | None) -> str:
    text = (text or "").lower().strip()
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def score_text(term: str, text: str, exact_bonus: int, partial_bonus: int) -> int:
    if not term or not text:
        return 0
    if term == text:
        return exact_bonus
    if term in text or text in term:
        return partial_bonus
    return 0


def safe_number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_money_value(prompt: str) -> float | None:
    text = normalize_text(prompt)
    compact = text.replace(" ", "")
    match = re.search(r"(\d[\d\.]*)ty", compact)
    if match:
        return float(match.group(1).replace(".", "")) * 1_000_000_000
    match = re.search(r"(\d[\d\.]*)trieu", compact)
    if match:
        return float(match.group(1).replace(".", "")) * 1_000_000
    match = re.search(r"(\d[\d\.]*)nghin", compact)
    if match:
        return float(match.group(1).replace(".", "")) * 1_000
    numbers = re.findall(r"\d[\d\.]*", prompt)
    if numbers:
        return float(numbers[-1].replace(".", ""))
    return None


def parse_money_ranges(text: str | None) -> tuple[float | None, float | None]:
    normalized = normalize_text(text)
    matches = re.findall(r"(\d[\d\.]*)", text or "")
    values = [float(x.replace(".", "")) for x in matches]
    multiplier = 1
    if "ty" in normalized:
        multiplier = 1_000_000_000
    elif "trieu" in normalized:
        multiplier = 1_000_000
    elif "nghin" in normalized:
        multiplier = 1_000
    values = [v * multiplier for v in values]
    lower = None
    upper = None
    if len(values) >= 2:
        lower, upper = values[0], values[1]
    elif len(values) == 1:
        if "tu" in normalized and ("duoi" in normalized or "den" in normalized or "tro len" in normalized):
            lower = values[0]
        elif "duoi" in normalized:
            upper = values[0]
        else:
            lower = values[0]
    return lower, upper


def extract_prompt_terms(prompt: str) -> list[str]:
    text = normalize_text(prompt)
    phrases = []
    for token in [
        "tai san nha nuoc",
        "that thoat",
        "lang phi",
        "vu khi quan dung",
        "dong vat",
        "quy hiem",
        "giet nguoi",
        "ma tuy",
        "hoi lo",
        "phan boi to quoc",
        "an ninh quoc gia",
        "hiep dam",
    ]:
        if token in text:
            phrases.append(token)
    return phrases


def infer_amount_bonus(row: dict[str, Any], amount_value: float | None, crime_rules: dict[str, list[dict[str, Any]]]) -> int:
    if amount_value is None:
        return 0
    current_clause = safe_number(row.get("clause"), 0)
    rules = crime_rules.get(row["crime_id"], [])
    ranged_rules = []
    for candidate in rules:
        for cond in candidate.get("conditions") or []:
            low, high = parse_money_ranges(cond)
            if low is not None or high is not None:
                ranged_rules.append(
                    {
                        "clause": safe_number(candidate.get("clause"), 0),
                        "low": low,
                        "high": high,
                    }
                )
    for ranged_rule in ranged_rules:
        low = ranged_rule["low"]
        high = ranged_rule["high"]
        in_range = (low is None or amount_value >= low) and (high is None or amount_value < high)
        if in_range and current_clause == ranged_rule["clause"]:
            return 120
    uppers = [item["high"] for item in ranged_rules if item["high"] is not None]
    if uppers and amount_value >= max(uppers):
        higher_clauses = [
            safe_number(rule.get("clause"), 0)
            for rule in rules
            if safe_number(rule.get("clause"), 0) > max(item["clause"] for item in ranged_rules)
        ]
        if higher_clauses:
            target_clause = max(higher_clauses)
            return 110 if current_clause == target_clause else -50
    lowers = [item["low"] for item in ranged_rules if item["low"] is not None]
    if lowers and amount_value < min(lowers):
        lower_clauses = [
            safe_number(rule.get("clause"), 0)
            for rule in rules
            if safe_number(rule.get("clause"), 0) < min(item["clause"] for item in ranged_rules)
        ]
        if lower_clauses:
            target_clause = min(lower_clauses)
            return 90 if current_clause == target_clause else -30
    if ranged_rules and current_clause not in [item["clause"] for item in ranged_rules]:
        return -20
    return 0


class LegalRAGService:
    def __init__(
        self,
        *,
        json_path: str | Path,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        openai_api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.json_path = Path(json_path)
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.driver.verify_connectivity()
        self.raw_data = json.loads(self.json_path.read_text(encoding="utf-8"))
        self.llm = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=openai_api_key or os.getenv("OPENAI_API_KEY"),
        )
        self.extract_chain = self._build_extract_chain()
        self.answer_chain = self._build_answer_chain()

    def close(self) -> None:
        self.driver.close()

    def _build_extract_chain(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "Chi tra ve JSON hop le."),
                (
                    "user",
                    (
                        "Ban la tro ly phap ly. Hay tra ve JSON hop le voi 3 truong sau:\n"
                        "- crime_hint: ten toi danh gan nhat theo ngon ngu phap ly\n"
                        "- condition_hint: tinh tiet quan trong nhat de tra cuu, uu tien viet ngan gon theo cach dien dat cua dieu luat\n"
                        "- search_terms: mang 3 den 8 cum tu khoa ngan phuc vu tim kiem\n"
                        "Chi tra ve JSON, khong giai thich.\n\n"
                        "Cau cua nguoi dung: {question}"
                    ),
                ),
            ]
        )
        return prompt | self.llm.with_structured_output(SearchHints)

    def _build_answer_chain(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "Ban la tro ly RAG phap ly. "
                        "Chi duoc tra loi dua tren context duoc cung cap. "
                        "Neu context chua du chac chan, phai noi ro do la ket qua tham khao."
                    ),
                ),
                (
                    "user",
                    (
                        "Cau hoi:\n{question}\n\n"
                        "Top ket qua retrieve:\n{context}\n\n"
                        "Hay viet cau tra loi ngan gon, de doc, neu co thi neu ro Dieu, khoan, diem va hinh phat."
                    ),
                ),
            ]
        )
        return prompt | self.llm

    def extract_hints(self, question: str) -> SearchHints:
        return self.extract_chain.invoke({"question": question})

    def _fetch_rows(self) -> list[dict[str, Any]]:
        query = """
        MATCH (cr:Crime)-[:HAS_RULE]->(r:Rule)-[:HAS_PENALTY]->(p:Penalty)
        OPTIONAL MATCH (r)-[:HAS_CONDITION]->(c:Condition)
        WITH cr, r, p, collect(DISTINCT c.text) AS conditions
        RETURN cr.id AS crime_id,
               cr.name AS crime_name,
               cr.article AS article,
               r.id AS rule_id,
               r.clause AS clause,
               r.logic AS logic,
               r.priority AS priority,
               conditions,
               p.min AS penalty_min,
               p.max AS penalty_max,
               p.extra AS penalty_extra,
               p.note AS penalty_note
        """
        with self.driver.session() as session:
            return [dict(record) for record in session.run(query)]

    def _find_rule_details(self, target_rule_id: str) -> dict[str, Any] | None:
        parts = self.raw_data.get("parts", [self.raw_data])
        for part in parts:
            for chapter in part.get("chapters", []):
                for article in chapter.get("articles", []):
                    crime = article.get("crime", {})
                    for rule in article.get("rules", []):
                        if rule.get("rule_id") == target_rule_id:
                            point_conditions = []
                            for cond in rule.get("conditions", []):
                                point_value = cond.get("point") or cond.get("code")
                                if point_value:
                                    point_conditions.append(
                                        {
                                            "point": str(point_value),
                                            "text": cond.get("text", ""),
                                        }
                                    )
                            return {
                                "crime_name": crime.get("name"),
                                "article": crime.get("article"),
                                "clause": rule.get("clause"),
                                "point_conditions": point_conditions,
                                "conditions": [cond.get("text") for cond in rule.get("conditions", []) if cond.get("text")],
                            }
        return None

    def _choose_best_point(
        self,
        rule_details: dict[str, Any] | None,
        user_prompt: str,
        condition_hint_norm: str,
        search_terms: list[str],
    ) -> dict[str, Any] | None:
        if not rule_details:
            return None
        candidates = rule_details.get("point_conditions", [])
        if not candidates:
            return None
        prompt_norm = normalize_text(user_prompt)
        best = None
        best_score = -1
        for candidate in candidates:
            cond_norm = normalize_text(candidate.get("text", ""))
            score = 0
            score += score_text(condition_hint_norm, cond_norm, 80, 40)
            score += score_text(prompt_norm, cond_norm, 60, 30)
            for term in search_terms:
                score += score_text(term, cond_norm, 20, 10)
            if score > best_score:
                best_score = score
                best = candidate
        return best if best_score > 0 else None

    def _format_penalty_text(self, row: dict[str, Any]) -> str:
        if row.get("penalty_note"):
            return row["penalty_note"]
        if row.get("penalty_min") is not None and row.get("penalty_max") is not None:
            penalty_text = f"phat tu tu {row['penalty_min']} den {row['penalty_max']} nam"
        elif row.get("penalty_min") is not None:
            penalty_text = f"muc phat tu {row['penalty_min']}"
        else:
            penalty_text = "chiu hinh phat theo quy dinh"
        if row.get("penalty_extra"):
            penalty_text += f", {row['penalty_extra']}"
        return penalty_text

    def retrieve(self, question: str, hints: SearchHints | None = None, top_k: int = 5) -> dict[str, Any]:
        hints = hints or self.extract_hints(question)
        search_terms = list(hints.search_terms or [])
        search_terms.extend([hints.crime_hint, hints.condition_hint])
        search_terms = [normalize_text(item) for item in search_terms if item and normalize_text(item)]
        search_terms = [item for item in dict.fromkeys(search_terms) if item not in GENERIC_TERMS and len(item) >= 4]
        crime_hint_norm = normalize_text(hints.crime_hint)
        condition_hint_norm = normalize_text(hints.condition_hint)
        amount_value = parse_money_value(question)
        prompt_terms = extract_prompt_terms(question)

        rows = self._fetch_rows()
        crime_rules: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            crime_rules[row["crime_id"]].append(row)

        crime_candidates = []
        for crime_id, rule_rows in crime_rules.items():
            crime_name_norm = normalize_text(rule_rows[0]["crime_name"])
            all_conditions = []
            for rule_row in rule_rows:
                all_conditions.extend([normalize_text(x) for x in (rule_row.get("conditions") or []) if x])
            crime_score = 0
            for term in prompt_terms:
                crime_score += score_text(term, crime_name_norm, 50, 25)
                crime_score += max([score_text(term, cond, 20, 10) for cond in all_conditions] or [0])
            for term in search_terms:
                crime_score += score_text(term, crime_name_norm, 18, 9)
                crime_score += max([score_text(term, cond, 8, 4) for cond in all_conditions] or [0])
            if crime_hint_norm and score_text(crime_hint_norm, crime_name_norm, 0, 0) > 0:
                crime_score += 5
            if crime_score > 0:
                crime_candidates.append((crime_id, crime_score))

        crime_candidates.sort(key=lambda item: -item[1])
        best_crime_ids = {crime_id for crime_id, _ in crime_candidates[:5]}

        scored_rows = []
        for row in rows:
            if row["crime_id"] not in best_crime_ids:
                continue
            crime_name_norm = normalize_text(row["crime_name"])
            conditions_norm = [normalize_text(x) for x in (row.get("conditions") or []) if x]
            score = 0
            for term in prompt_terms:
                score += score_text(term, crime_name_norm, 40, 20)
                score += max([score_text(term, cond, 20, 10) for cond in conditions_norm] or [0])
            for term in search_terms:
                score += score_text(term, crime_name_norm, 12, 6)
                score += max([score_text(term, cond, 10, 5) for cond in conditions_norm] or [0])
            score += max([score_text(condition_hint_norm, cond, 60, 30) for cond in conditions_norm] or [0])
            score += infer_amount_bonus(row, amount_value, crime_rules)
            if score > 0:
                row["match_score"] = score
                scored_rows.append(row)

        scored_rows.sort(
            key=lambda item: (
                -safe_number(item.get("match_score"), 0),
                safe_number(item.get("priority"), 999),
                -safe_number(item.get("clause"), 0),
                safe_number(item.get("article"), 999999),
            )
        )

        top_rows = scored_rows[:top_k]
        explanation = None
        if top_rows:
            top = top_rows[0]
            rule_details = self._find_rule_details(top["rule_id"])
            point_text = ""
            best_point = self._choose_best_point(rule_details, question, condition_hint_norm, search_terms)
            if best_point:
                point_text = f", diem {best_point['point']}"
            explanation = (
                f"Theo truong hop cua ban, ban da vi pham tai Dieu {top['article']}, "
                f"khoan {top['clause']}{point_text}, {top['crime_name']}. "
                f"Ban se bi {self._format_penalty_text(top)}."
            )

        return {
            "hints": hints.model_dump(),
            "search_terms": search_terms,
            "prompt_terms": prompt_terms,
            "amount_value": amount_value,
            "rows": top_rows,
            "explanation": explanation,
        }

    def generate(self, question: str, retrieved: dict[str, Any] | None = None, top_k: int = 5) -> dict[str, Any]:
        retrieved = retrieved or self.retrieve(question, top_k=top_k)
        context_lines = []
        for row in retrieved["rows"]:
            context_lines.append(
                json.dumps(
                    {
                        "crime_name": row["crime_name"],
                        "article": row["article"],
                        "rule_id": row["rule_id"],
                        "clause": row["clause"],
                        "logic": row["logic"],
                        "conditions": row.get("conditions", []),
                        "penalty_min": row.get("penalty_min"),
                        "penalty_max": row.get("penalty_max"),
                        "penalty_extra": row.get("penalty_extra"),
                        "penalty_note": row.get("penalty_note"),
                        "match_score": row.get("match_score"),
                    },
                    ensure_ascii=False,
                )
            )
        if retrieved.get("explanation"):
            context_lines.append(f"Giai thich xac dinh: {retrieved['explanation']}")
        context = "\n".join(context_lines) if context_lines else "Khong tim thay ket qua retrieve phu hop."
        response = self.answer_chain.invoke({"question": question, "context": context})
        answer_text = response.content if hasattr(response, "content") else str(response)
        return {
            **retrieved,
            "final_answer": answer_text,
        }