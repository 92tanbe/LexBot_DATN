from __future__ import annotations

import re
import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models.conversation import ClarificationForm, ClarificationOption, ClarificationQuestion, FactPatch, IssuedQuestionSet
from app.models.facts import ExtractedFacts
from app.models.legal_output import CandidateArticle, LegalReasoningItem
from app.services.context_builder import citations_from_contexts
from app.services.fulltext_retriever import search_fulltext
from app.services.graph_retriever import fetch_contexts, search_exact_articles
from app.utils.text import normalize_text


_PENALTY_QUESTION_TERMS = [
    "may nam tu",
    "bao nhieu nam tu",
    "tu bao nhieu nam",
    "di tu bao lau",
    "di tu bao nhieu nam",
    "di may nam",
    "di tu",
    "phat bao nhieu nam",
    "bi phat bao nhieu",
    "bi phat nhu the nao",
    "phat nhu the nao",
    "bi xu phat nhu the nao",
    "xu phat nhu the nao",
    "bi xu phat",
    "xu phat",
    "muc phat",
    "khung hinh phat",
    "khung nao",
    "nhung khung nao",
    "voi nhung khung nao",
    "cac khung",
    "phat tu",
    "thi sao",
    "ra sao",
    "xu ly the nao",
    "xu ly ra sao",
    "xu ly sao",
    "giai quyet the nao",
]
_LEGAL_LOOKUP_TERMS = ["toi", "dieu", "blhs", "bo luat hinh su", "pham toi"]
_POINT_ORDER = ["a", "b", "c", "d", "đ", "e", "g", "h", "i", "k", "l", "m", "n", "o", "p", "q"]
_LOOKUP_NOISE_PHRASES = [
    "bo luat hinh su",
    "blhs",
    "khung hinh phat",
    "khung nao",
    "nhung khung nao",
    "voi nhung khung nao",
    "cac khung",
    "muc hinh phat",
    "hinh phat",
    "phat bao nhieu nam",
    "bi phat bao nhieu",
    "bi phat nhu the nao",
    "phat nhu the nao",
    "bi xu phat nhu the nao",
    "xu phat nhu the nao",
    "bi xu phat",
    "xu phat",
    "bao nhieu nam tu",
    "di tu bao lau",
    "di tu bao nhieu nam",
    "di may nam",
    "may nam tu",
    "muc phat",
    "phat tu",
    "di tu",
    "xu ly the nao",
    "xu ly ra sao",
    "xu ly sao",
    "giai quyet the nao",
    "nhu the nao",
    "the nao",
    "thi sao",
    "ra sao",
    "bao nhieu",
    "bao lau",
    "tra cuu",
    "quy dinh",
    "pham toi",
    "toi",
    "dieu",
]
_LOOKUP_STOP_TOKENS = {
    "bo",
    "luat",
    "hinh",
    "su",
    "blhs",
    "dieu",
    "toi",
    "pham",
    "phat",
    "muc",
    "khung",
    "voi",
    "nhung",
    "cac",
    "nam",
    "tu",
    "bao",
    "nhieu",
    "may",
    "di",
    "lau",
    "quy",
    "dinh",
    "tra",
    "cuu",
    "nhu",
    "the",
    "nao",
    "thi",
    "sao",
    "ra",
    "xu",
    "ly",
    "giai",
    "quyet",
}
_LOOKUP_SYNONYMS = [
    ("buon ban", "mua ban"),
]
_DIRECT_CATALOG_ALIASES: list[tuple[str, list[str]]] = [
    ("phan dong to quoc", ["109", "108"]),
    ("phan dong", ["109"]),
]
_MIN_RETRIEVAL_MATCH_SCORE = 35.0
_CATALOG_STOP_TOKENS = _LOOKUP_STOP_TOKENS | {
    "trai",
    "phep",
    "trai phep",
    "quy",
    "dinh",
    "ve",
    "va",
    "hoac",
    "cac",
    "hanh",
    "vi",
}


@dataclass
class ArticleLookupPayload:
    facts: ExtractedFacts
    final_answer: str
    clarification: ClarificationForm | None
    issued_question_set: IssuedQuestionSet | None
    candidate_articles: list[CandidateArticle]
    legal_reasoning: list[LegalReasoningItem]
    citations: list[dict[str, Any]]
    confidence: float
    debug: dict[str, Any] | None = None


@dataclass(frozen=True)
class CatalogEntry:
    article_code: str
    title: str
    crime_name: str
    search_texts: tuple[str, ...]


def _import_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "neo4j_import"
        if candidate.exists():
            return candidate
    return current.parents[3] / "neo4j_import"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _crime_catalog() -> tuple[CatalogEntry, ...]:
    base = _import_dir()
    articles: dict[str, dict[str, str]] = {}
    for row in _read_csv_rows(base / "articles.csv"):
        code = str(row.get("article_code") or "").strip()
        if code:
            articles[code] = row

    grouped: dict[str, dict[str, Any]] = {}
    for code, row in articles.items():
        title = str(row.get("title") or "")
        grouped[code] = {
            "article_code": code,
            "title": title,
            "crime_name": "",
            "texts": {title},
        }

    for row in _read_csv_rows(base / "crimes.csv"):
        code = str(row.get("article_code") or "").strip()
        if not code:
            continue
        item = grouped.setdefault(code, {"article_code": code, "title": "", "crime_name": "", "texts": set()})
        name = str(row.get("name") or "")
        item["crime_name"] = name or item.get("crime_name") or ""
        item["title"] = item.get("title") or name
        item["texts"].update({name, str(row.get("normalized_name") or "")})

    for row in _read_csv_rows(base / "act_requirements.csv"):
        code = str(row.get("article_code") or "").strip()
        if not code or code not in grouped:
            continue
        grouped[code]["texts"].update({str(row.get("text") or ""), str(row.get("normalized_text") or "")})

    entries: list[CatalogEntry] = []
    for code, item in grouped.items():
        title = str(item.get("title") or "").strip()
        crime_name = str(item.get("crime_name") or "").strip()
        if not title and not crime_name:
            continue
        texts = tuple(
            dict.fromkeys(
                normalize_text(text)
                for text in item.get("texts", set())
                if normalize_text(text)
            )
        )
        entries.append(CatalogEntry(article_code=code, title=title or crime_name, crime_name=crime_name, search_texts=texts))
    return tuple(entries)


@lru_cache(maxsize=1)
def _action_alias_expansions() -> tuple[tuple[str, str], ...]:
    rows = _read_csv_rows(_import_dir() / "action_aliases.csv")
    pairs: list[tuple[str, str]] = []
    for row in rows:
        alias = normalize_text(row.get("text") or "")
        target = normalize_text(row.get("normalized_to") or "")
        if alias and target:
            pairs.append((alias, target))
    return tuple(pairs)


def is_general_penalty_lookup(message: str) -> bool:
    norm = normalize_text(message)
    if _article_refs_from_message(message) and (
        any(term in norm for term in _PENALTY_QUESTION_TERMS)
        or any(term in norm for term in ["dieu", "noi dung", "quy dinh", "la gi", "thi sao", "ra sao"])
    ):
        return True
    if any(term in norm for term in _PENALTY_QUESTION_TERMS):
        return True
    
    # Catch simple lookup by crime name: "tội mua bán trái phép chất ma tuý"
    if "toi " in norm and len(norm.split()) <= 12:
        return True
        
    # Catch generic definitions or encyclopedia questions about the criminal code
    if len(norm.split()) <= 15:
        if any(term in norm for term in ["la gi", "duoc hieu la", "nghia la"]):
            return True
        if any(term in norm for term in ["bo luat", "blhs", "hinh su", "hinh phat"]) and any(term in norm for term in ["nhiem vu", "nguyen tac", "hieu luc"]):
            return True
            
    return False


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _article_code(ctx: dict) -> str:
    return str((ctx.get("article") or {}).get("article_code") or "")


def _article_title(ctx: dict) -> str:
    article = ctx.get("article") or {}
    crime = ctx.get("crime") or {}
    return str(article.get("title") or crime.get("name") or "")


def _article_refs_from_message(message: str) -> list[str]:
    norm = normalize_text(message)
    return list(dict.fromkeys(re.findall(r"\bdieu\s+(\d+[a-z]?)\b", norm)))


def _strip_lookup_noise(message: str) -> str:
    core = normalize_text(message)
    for old, new in _LOOKUP_SYNONYMS:
        core = re.sub(rf"\b{re.escape(old)}\b", new, core)
    core = re.sub(r"\bdieu\s+\d+[a-z]?\b", " ", core)
    for phrase in sorted(_LOOKUP_NOISE_PHRASES, key=len, reverse=True):
        core = re.sub(rf"\b{re.escape(phrase)}\b", " ", core)
    return re.sub(r"\s+", " ", core).strip()


def _title_core(value: Any) -> str:
    core = normalize_text(str(value or ""))
    core = re.sub(r"^toi\s+", "", core).strip()
    return core


def _lookup_tokens(text: str) -> set[str]:
    return {token for token in normalize_text(text).split() if token and token not in _LOOKUP_STOP_TOKENS}


def _lookup_queries(message: str) -> list[str]:
    core = _strip_lookup_noise(message)
    canonical_message = normalize_text(message)
    for old, new in _LOOKUP_SYNONYMS:
        canonical_message = re.sub(rf"\b{re.escape(old)}\b", new, canonical_message)
    queries = [message, canonical_message]
    if core:
        queries.extend([core, f"Tội {core}"])
    out: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = normalize_text(query)
        if key and key not in seen:
            out.append(query)
            seen.add(key)
    return out


def _direct_lookup_article_codes(message: str) -> list[str]:
    return _catalog_lookup_article_codes(message)


def _catalog_tokens(text: str) -> set[str]:
    return {token for token in normalize_text(text).split() if token and token not in _CATALOG_STOP_TOKENS}


def _expanded_lookup_core(message: str) -> str:
    core = _strip_lookup_noise(message)
    norm = normalize_text(message)
    expansions = [
        target
        for alias, target in _action_alias_expansions()
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", norm)
    ]
    return re.sub(r"\s+", " ", " ".join([core, *expansions])).strip()


def _catalog_entry_score(entry: CatalogEntry, query_core: str) -> float:
    query_norm = normalize_text(query_core)
    query_tokens = _catalog_tokens(query_norm)
    if not query_tokens:
        return 0.0

    best = 0.0
    for text in entry.search_texts:
        text_norm = normalize_text(text)
        if not text_norm:
            continue
        title_norm = re.sub(r"^toi\s+", "", text_norm).strip()
        text_tokens = _catalog_tokens(title_norm)
        if not text_tokens:
            continue
        overlap = len(query_tokens & text_tokens)
        precision = overlap / len(query_tokens)
        recall = overlap / len(text_tokens)
        score = (100.0 * precision) + (70.0 * recall) + (8.0 * overlap)
        if query_norm == title_norm:
            score += 500.0
        elif query_norm and query_norm in title_norm:
            score += 260.0
        elif title_norm and title_norm in query_norm:
            score += 220.0
        if "ma tuy" in query_norm and not any(term in query_norm for term in ["tien chat", "phuong tien", "dung cu"]):
            if "tien chat" in title_norm or "phuong tien" in title_norm or "dung cu" in title_norm:
                score -= 85.0
        if "danh" in query_tokens and "co y gay thuong tich" in title_norm:
            score += 55.0
        if {"gay", "thuong", "tich"} <= query_tokens:
            special_injury_terms = [
                "trang thai tinh than",
                "phong ve chinh dang",
                "thi hanh cong vu",
                "vo y",
                "quy tac nghe nghiep",
                "quy tac hanh chinh",
            ]
            if any(term in title_norm for term in special_injury_terms) and not any(term in query_norm for term in special_injury_terms):
                score -= 45.0
        if entry.title.lower().startswith("Tội".lower()):
            score += 5.0
        best = max(best, score)
    return best


def _catalog_lookup_article_codes(message: str, limit: int = 5) -> list[str]:
    norm = normalize_text(message)
    for phrase, codes in _DIRECT_CATALOG_ALIASES:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", norm):
            return codes[:limit]

    query_core = _expanded_lookup_core(message)
    scored: list[tuple[str, float]] = []
    for entry in _crime_catalog():
        score = _catalog_entry_score(entry, query_core)
        if score >= 95.0:
            scored.append((entry.article_code, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        return []
    floor = max(95.0, scored[0][1] - 28.0)
    return list(dict.fromkeys(code for code, score in scored if score >= floor))[:limit]


def _score_lookup_hit(hit: dict, message: str, core: str, rank: int) -> float:
    source = str(hit.get("source") or "")
    if source.startswith("exact_article"):
        hit["lookup_phrase_match"] = True
        hit["lookup_precision"] = 1.0
        hit["lookup_overlap"] = 1
        hit["lookup_core_token_count"] = 1
        return 1000.0 - rank

    core_norm = normalize_text(core)
    core_tokens = _lookup_tokens(core_norm)
    raw_score = float(hit.get("score") or 0.0)
    text_candidates = [
        hit.get("title"),
        hit.get("crime_name"),
        *(hit.get("matched_terms") or []),
        hit.get("matched_text"),
    ]
    score = raw_score - (rank * 0.01)
    phrase_match = False
    max_precision = 0.0
    max_overlap = 0
    for candidate in text_candidates:
        title_norm = _title_core(candidate)
        if not title_norm:
            continue
        if core_norm and core_norm == title_norm:
            score += 300.0
            phrase_match = True
        elif core_norm and core_norm in title_norm:
            score += 160.0
            phrase_match = True
        elif core_norm and title_norm in core_norm:
            score += 120.0
            phrase_match = True
        title_tokens = _lookup_tokens(title_norm)
        if core_tokens and title_tokens:
            overlap = len(core_tokens & title_tokens)
            precision = overlap / len(core_tokens)
            recall = overlap / len(title_tokens)
            max_overlap = max(max_overlap, overlap)
            max_precision = max(max_precision, precision)
            score += (80.0 * precision) + (40.0 * recall)
    hit["lookup_phrase_match"] = phrase_match
    hit["lookup_precision"] = max_precision
    hit["lookup_overlap"] = max_overlap
    hit["lookup_core_token_count"] = len(core_tokens)
    return score


def _rank_hits(message: str, hits: list[dict]) -> list[dict]:
    core = _strip_lookup_noise(message)
    best: dict[str, dict] = {}
    for rank, hit in enumerate(hits, start=1):
        code = str(hit.get("article_code") or "")
        if not code:
            continue
        scored = dict(hit)
        scored["lookup_score"] = _score_lookup_hit(scored, message, core, rank)
        scored["lookup_core"] = core
        current = best.get(code)
        if current is None or float(scored.get("lookup_score") or 0.0) > float(current.get("lookup_score") or 0.0):
            best[code] = scored
    return sorted(best.values(), key=lambda item: float(item.get("lookup_score") or 0.0), reverse=True)


def _is_reliable_top_hit(hit: dict | None) -> bool:
    if not hit:
        return False
    if str(hit.get("source") or "").startswith("exact_article"):
        return True
    if float(hit.get("lookup_score") or 0.0) < _MIN_RETRIEVAL_MATCH_SCORE:
        return False
    if hit.get("lookup_phrase_match"):
        return True
    core_token_count = int(hit.get("lookup_core_token_count") or 0)
    overlap = int(hit.get("lookup_overlap") or 0)
    precision = float(hit.get("lookup_precision") or 0.0)
    return core_token_count >= 2 and overlap >= 2 and precision >= 0.67


def _penalty_text(frame: dict | None) -> str:
    if not frame:
        return ""
    text = _clean(frame.get("text"))
    extras: list[str] = []
    if frame.get("has_life_imprisonment") is True:
        extras.append("tù chung thân")
    if frame.get("has_death_penalty") is True:
        extras.append("tử hình")
    if extras:
        text = f"{text}, {', '.join(extras)}" if text else ", ".join(extras)
    return text


def _penalty_text_by_owner(ctx: dict) -> dict[str, str]:
    frames_by_owner: dict[str, list[dict]] = {}
    for frame in ctx.get("penalty_frames") or []:
        owner_id = str(frame.get("owner_id") or "")
        if owner_id:
            frames_by_owner.setdefault(owner_id, []).append(frame)
    out: dict[str, str] = {}
    type_rank = {
        "imprisonment": 0,
        "life_imprisonment": 1,
        "death_penalty": 2,
        "fine": 3,
    }
    for owner_id, frames in frames_by_owner.items():
        texts: list[str] = []
        for frame in sorted(frames, key=lambda item: type_rank.get(str(item.get("penalty_type") or ""), 99)):
            text = _penalty_text(frame)
            if text and text not in texts:
                texts.append(text)
        if texts:
            out[owner_id] = "; ".join(texts)
    return out


def _sort_clause_key(clause: dict) -> tuple[int, str]:
    try:
        return int(clause.get("clause_no") or 999), str(clause.get("id") or "")
    except (TypeError, ValueError):
        return 999, str(clause.get("id") or "")


def _sort_point_key(point: dict) -> tuple[int, str]:
    label = str(point.get("point") or "")
    try:
        point_rank = _POINT_ORDER.index(label)
    except ValueError:
        point_rank = 999
    return int(point.get("clause_no") or 999), f"{point_rank:03d}-{label}-{point.get('text') or ''}"


def _points_from_clause_text(clause: dict) -> list[dict]:
    text = _clean(clause.get("text"))
    clause_no = clause.get("clause_no")
    clause_id = clause.get("id")
    article_code = clause.get("article_code")
    if not text or clause_no is None or clause_id is None:
        return []
    points: list[dict] = []
    pattern = r"(?:^|[;:])\s*([a-zđ])\)\s*(.*?)(?=(?:;\s*[a-zđ]\))|(?:\.\s*$)|$)"
    for idx, match in enumerate(re.finditer(pattern, text, flags=re.I | re.S), start=1):
        point = match.group(1).lower()
        point_text = _clean(match.group(2)).rstrip(";.")
        if not point or not point_text:
            continue
        points.append({
            "id": f"{clause_id}_parsed_point_{point}_{idx}",
            "article_code": article_code,
            "clause_id": clause_id,
            "clause_no": clause_no,
            "point": point,
            "text": point_text,
            "role": "parsed_from_clause_text",
        })
    return points


def _merged_points(ctx: dict) -> list[dict]:
    points = list(ctx.get("points") or [])
    seen = {(str(point.get("clause_no") or ""), str(point.get("point") or "")) for point in points}
    for clause in ctx.get("clauses") or []:
        for parsed in _points_from_clause_text(clause):
            key = (str(parsed.get("clause_no") or ""), str(parsed.get("point") or ""))
            if key in seen:
                continue
            points.append(parsed)
            seen.add(key)
    return sorted(points, key=_sort_point_key)


def _selection_patch(selection: dict[str, Any]) -> list[FactPatch]:
    return [
        FactPatch(path="article_lookup.article_code", value=selection.get("article_code"), confidence=0.95),
        FactPatch(path="article_lookup.article_title", value=selection.get("article_title"), confidence=0.95),
        FactPatch(path="article_lookup.selection", value=selection, confidence=0.95),
    ]


def _build_option_data(ctx: dict) -> tuple[list[ClarificationOption], dict[str, list[FactPatch]]]:
    code = _article_code(ctx)
    title = _article_title(ctx)
    clauses = sorted(ctx.get("clauses") or [], key=_sort_clause_key)
    points = _merged_points(ctx)
    points_by_clause: dict[str, list[dict]] = {}
    for point in points:
        points_by_clause.setdefault(str(point.get("clause_no") or ""), []).append(point)
    penalty_by_owner = _penalty_text_by_owner(ctx)
    options: list[ClarificationOption] = []
    patches: dict[str, list[FactPatch]] = {}
    seen_option_ids: set[str] = set()

    option_index = 0
    for clause in clauses:
        clause_no = str(clause.get("clause_no") or "")
        clause_id = str(clause.get("id") or "")
        role = str(clause.get("role") or "")
        if not clause_no or role == "additional_penalty":
            continue
        clause_points = points_by_clause.get(clause_no) or []
        if clause_points:
            for point in clause_points:
                option_index += 1
                point_id = str(point.get("id") or "")
                point_no = str(point.get("point") or "")
                penalty = penalty_by_owner.get(point_id) or penalty_by_owner.get(clause_id) or ""
                point_text = _clean(point.get("text")).rstrip(";")
                if not point_no or not point_text:
                    continue
                option_id = f"{code}_k{clause_no}_d{normalize_text(point_no) or option_index}_{option_index}"
                if option_id in seen_option_ids:
                    option_id = f"{option_id}_{len(seen_option_ids)}"
                seen_option_ids.add(option_id)
                label = f"Khoản {clause_no}, điểm {point_no}: {point_text}"
                if penalty:
                    label = f"{label} ({penalty})"
                selection = {
                    "article_code": code,
                    "article_title": title,
                    "clause_no": clause_no,
                    "point": point_no,
                    "condition_text": point_text,
                    "penalty_text": penalty,
                    "option_label": label,
                    "source": "neo4j_clause_text_point" if point.get("role") == "parsed_from_clause_text" else "neo4j_point",
                }
                options.append(ClarificationOption(id=option_id, label=label))
                patches[option_id] = _selection_patch(selection)
            continue

        penalty = penalty_by_owner.get(clause_id) or ""
        clause_text = _clean(clause.get("text"))
        option_index += 1
        option_id = f"{code}_k{clause_no}"
        label = f"Khoản {clause_no}: {clause_text}"
        if penalty:
            label = f"{label} ({penalty})"
        selection = {
            "article_code": code,
            "article_title": title,
            "clause_no": clause_no,
            "condition_text": clause_text,
            "penalty_text": penalty,
            "option_label": label,
            "source": "neo4j_clause",
        }
        options.append(ClarificationOption(id=option_id, label=label))
        patches[option_id] = _selection_patch(selection)

    summary_text = _article_summary(ctx)
    unknown_selection = {
        "article_code": code,
        "article_title": title,
        "condition_text": "Chưa rõ tình tiết/khoản áp dụng.",
        "penalty_text": summary_text,
        "option_label": "Chưa rõ tình tiết cụ thể",
        "source": "unknown",
    }
    options.append(ClarificationOption(id="unknown", label="Chưa rõ tình tiết cụ thể"))
    patches["unknown"] = _selection_patch(unknown_selection)
    return options, patches


def _article_summary(ctx: dict) -> str:
    clauses = sorted(ctx.get("clauses") or [], key=_sort_clause_key)
    penalty_by_owner = _penalty_text_by_owner(ctx)
    lines: list[str] = []
    for clause in clauses:
        clause_no = str(clause.get("clause_no") or "")
        clause_id = str(clause.get("id") or "")
        role = str(clause.get("role") or "")
        text = _clean(clause.get("text"))
        if not clause_no or not text:
            continue
        penalty = penalty_by_owner.get(clause_id) or ""
        if role == "additional_penalty":
            lines.append(f"Khoản {clause_no}: hình phạt bổ sung/có thể áp dụng thêm - {text}")
        elif penalty:
            lines.append(f"Khoản {clause_no}: {penalty}. Điều kiện: {text}")
        else:
            lines.append(f"Khoản {clause_no}: {text}")
    return "\n".join(lines)


def _answer_intro(ctx: dict) -> str:
    code = _article_code(ctx)
    title = _article_title(ctx)
    summary = _article_summary(ctx)
    return (
        f"Tra cứu từ Neo4j: Điều {code} - {title}.\n"
        f"{summary}\n\n"
        "Điều này có nhiều khoản/điểm nên mức phạt phụ thuộc tình tiết cụ thể. "
        "Bạn chọn trường hợp gần nhất bên dưới, mình sẽ đối chiếu khung tương ứng."
    )


def _answer_lookup_contexts(contexts: list[dict]) -> str:
    lines = ["Tra cứu khung hình phạt từ Neo4j:"]
    for ctx in contexts:
        code = _article_code(ctx)
        title = _article_title(ctx)
        summary = _article_summary(ctx)
        if not code or not title:
            continue
        lines.append("")
        lines.append(f"Điều {code} - {title}")
        lines.append(summary or "Chưa có dữ liệu khoản/khung phạt trong context Neo4j.")
    lines.append("")
    lines.append("Đây là tra cứu điều luật chung. Nếu đưa tình huống cụ thể, khoản/điểm áp dụng còn phụ thuộc loại chất, khối lượng và các tình tiết định khung.")
    return "\n".join(lines).strip()


def _top_article_context(message: str) -> tuple[dict | None, list[dict]]:
    hits: list[dict] = []
    article_refs = _article_refs_from_message(message)
    for hit in search_exact_articles(article_refs, 8):
        hits.append({**hit, "score": max(float(hit.get("score") or 0.0), 1000.0), "source": "exact_article_lookup"})
    for query in _lookup_queries(message):
        hits.extend(search_fulltext(query, 12))
    hits = _rank_hits(message, hits)
    if not _is_reliable_top_hit(hits[0] if hits else None):
        return None, hits
    article_codes = [str(hit.get("article_code")) for hit in hits if hit.get("article_code")]
    if not article_codes:
        return None, hits
    contexts = fetch_contexts(article_codes[:1])
    return (contexts[0] if contexts else None), hits


def _lookup_contexts(message: str) -> tuple[list[dict], list[dict]]:
    direct_codes = _direct_lookup_article_codes(message)
    if direct_codes:
        contexts = fetch_contexts(direct_codes)
        hits = [
            {
                "article_code": _article_code(ctx),
                "title": _article_title(ctx),
                "crime_name": (ctx.get("crime") or {}).get("name"),
                "score": 1000.0 - idx,
                "source": "direct_article_lookup",
                "matched_terms": [f"Điều {_article_code(ctx)}", _article_title(ctx)],
            }
            for idx, ctx in enumerate(contexts)
            if _article_code(ctx)
        ]
        return contexts, hits
    ctx, hits = _top_article_context(message)
    return ([ctx] if ctx else []), hits


def build_general_article_lookup(message: str, case_id: str, case_version: int, include_debug: bool = False) -> ArticleLookupPayload | None:
    if not is_general_penalty_lookup(message):
        return None
    contexts, hits = _lookup_contexts(message)
    if not contexts:
        return None
    primary_ctx = contexts[0]
    primary_code = _article_code(primary_ctx)
    primary_title = _article_title(primary_ctx)
    if not primary_code or not primary_title:
        return None

    confidence = min(max(float(hits[0].get("score") or 0.0) / 8.0, 0.35), 0.95) if hits else 0.7
    facts = ExtractedFacts(
        article_refs=[_article_code(ctx) for ctx in contexts if _article_code(ctx)],
        crime_hints=[_article_title(ctx) for ctx in contexts if _article_title(ctx)],
        structured_facts={
            "article_lookup.article_codes": [_article_code(ctx) for ctx in contexts if _article_code(ctx)],
            "article_lookup.article_titles": [_article_title(ctx) for ctx in contexts if _article_title(ctx)],
        },
    )
    candidate_articles = [
        CandidateArticle(
            article_code=str(hit.get("article_code")),
            title=str(hit.get("title") or ""),
            crime_name=hit.get("crime_name"),
            score=min(max(float(hit.get("score") or 0.0) / 8.0, 0.0), 1.0),
            source=str(hit.get("source") or "neo4j_fulltext"),
            matched_terms=list(hit.get("matched_terms") or []),
        )
        for hit in hits[:5]
        if hit.get("article_code")
    ]
    legal_reasoning = [
        LegalReasoningItem(
            article_code=_article_code(ctx),
            title=_article_title(ctx),
            crime_name=(ctx.get("crime") or {}).get("name"),
            classification="crime_candidate",
            finding_status="provisional_finding",
            why_relevant="Câu hỏi chung về mức phạt/khung phạt khớp điều luật được truy xuất từ Neo4j.",
            possible_penalty_frames=ctx.get("penalty_frames") or [],
            confidence=confidence,
        )
        for ctx in contexts
        if _article_code(ctx)
    ]
    return ArticleLookupPayload(
        facts=facts,
        final_answer=_answer_lookup_contexts(contexts),
        clarification=None,
        issued_question_set=None,
        candidate_articles=candidate_articles,
        legal_reasoning=legal_reasoning,
        citations=citations_from_contexts(contexts),
        confidence=confidence,
        debug={"article_lookup_hits": hits[:5], "article_codes": facts.article_refs} if include_debug else None,
    )


def build_selected_article_answer(facts: ExtractedFacts) -> ArticleLookupPayload | None:
    selection = facts.structured_facts.get("article_lookup.selection")
    if not isinstance(selection, dict):
        return None
    code = str(selection.get("article_code") or "").strip()
    title = str(selection.get("article_title") or "").strip()
    if not code or not title:
        return None

    condition = _clean(selection.get("condition_text"))
    penalty = _clean(selection.get("penalty_text"))
    if selection.get("source") == "unknown":
        answer = (
            f"Bạn chưa chọn tình tiết cụ thể cho Điều {code} - {title}.\n"
            f"Các khung cần đối chiếu là:\n{penalty}\n\n"
            "Muốn xác định chính xác khoản/điểm, cần biết vụ việc có thuộc một trong các tình tiết định khung hay không."
        )
        confidence = 0.55
    else:
        clause = selection.get("clause_no")
        point = selection.get("point")
        ref = f"khoản {clause}" if clause else "điều luật đã chọn"
        if point:
            ref += f", điểm {point}"
        answer = (
            f"Theo lựa chọn của bạn, trường hợp đang đối chiếu là Điều {code} - {title}, {ref}.\n"
            f"Tình tiết/điều kiện: {condition}.\n"
            f"Khung hình phạt tương ứng: {penalty or 'chưa có khung phạt chính trong dữ liệu truy xuất'}.\n\n"
            "Đây là đối chiếu theo dữ liệu Neo4j/BLHS; kết luận thực tế vẫn phụ thuộc hồ sơ, chứng cứ và quyết định của cơ quan có thẩm quyền."
        )
        confidence = 0.85
    return ArticleLookupPayload(
        facts=facts,
        final_answer=answer,
        clarification=None,
        issued_question_set=None,
        candidate_articles=[
            CandidateArticle(article_code=code, title=title, score=confidence, source="selected_article_lookup")
        ],
        legal_reasoning=[],
        citations=[],
        confidence=confidence,
    )
