#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise SystemExit("Thiếu thư viện pymupdf. Cài bằng: pip install pymupdf") from exc


# ---------------------------------------------------------------------------
# 1. Regex cấu trúc văn bản luật
# ---------------------------------------------------------------------------

ROMAN_RE = r"[IVXLCDM]+"
PART_RE = re.compile(r"^Phần\s+thứ\s+(.+)$", re.IGNORECASE)
CHAPTER_RE = re.compile(r"^Chương\s+(" + ROMAN_RE + r")$", re.IGNORECASE)
SECTION_RE = re.compile(r"^Mục\s+(\d+)\.\s*(.*)$", re.IGNORECASE)
ARTICLE_RE = re.compile(r"^Điều\s+(\d+[a-zA-ZđĐ]?)\.\s*(.*)$")
CLAUSE_RE = re.compile(r"^(\d+)\.\s+(.*)$")
POINT_RE = re.compile(r"^([a-zA-ZđĐ])\)\s+(.*)$")

# Các dòng thường là bắt đầu thân điều, không phải nối tiếp tiêu đề Điều.
BODY_START_PREFIXES = (
    "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.",
    "Người ", "Bộ ", "Tội ", "Phạt ", "Không ", "Các ", "Khi ", "Hình ",
    "Cấm ", "Tù ", "Trục ", "Cảnh ", "Miễn ", "Trong ", "Đối với ",
)

PENALTY_PRISON_RE = re.compile(
    r"phạt\s+tù\s+từ\s+(\d+)\s+(tháng|năm)\s+đến\s+(\d+)\s+(tháng|năm)",
    re.IGNORECASE,
)
PENALTY_FINE_RE = re.compile(
    r"phạt\s+tiền\s+từ\s+([\d\.]+)\s+đồng\s+đến\s+([\d\.]+)\s+đồng",
    re.IGNORECASE,
)
QUANTITY_RANGE_RE = re.compile(
    r"từ\s+([\d\.,]+)\s*(gam|g|kg|kilôgam|m3|m³|viên|cây|con|mét khối)"
    r"\s+đến\s+dưới\s+([\d\.,]+)\s*(gam|g|kg|kilôgam|m3|m³|viên|cây|con|mét khối)",
    re.IGNORECASE,
)
REFERENCE_ARTICLE_RE = re.compile(r"Điều\s+(\d+[a-zA-ZđĐ]?)")

@dataclass
class PdfLine:
    page: int
    text: str


@dataclass
class ArticleDraft:
    id: str
    article_code: str
    article_number: int
    article_suffix: Optional[str]
    title: str
    full_text: str
    body_text: str
    page_start: int
    page_end: int
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_name: Optional[str] = None
    section_id: Optional[str] = None
    section_name: Optional[str] = None
    status: str = "active"
    source_file: str = ""


@dataclass
class Node:
    id: str
    label: str
    properties: Dict[str, Any]


@dataclass
class Relationship:
    source_id: str
    target_id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. Utility functions
# ---------------------------------------------------------------------------

def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def safe_id(text: Any) -> str:
    raw = strip_accents(str(text))
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_").lower()
    if raw:
        return raw
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()[:10]


def as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def parse_money_vnd(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.replace(".", "").replace(",", "").strip()
    m = re.search(r"\d+", raw)
    return int(m.group(0)) if m else None


def parse_float_vn(raw: str) -> Optional[float]:
    if not raw:
        return None
    raw = raw.strip().replace(".", "").replace(",", ".") if "," in raw else raw.strip()
    try:
        return float(raw)
    except Exception:
        return None


def duration_to_months(number: str, unit: str) -> int:
    n = int(number)
    unit = unit.lower()
    return n * 12 if "năm" in unit else n


def is_upper_heading(line: str) -> bool:
    letters = [ch for ch in line if ch.isalpha()]
    if not letters:
        return False
    upper_letters = [ch for ch in letters if ch.upper() == ch]
    return len(upper_letters) / max(len(letters), 1) > 0.75


def is_structure_line(line: str) -> bool:
    return bool(PART_RE.match(line) or CHAPTER_RE.match(line) or SECTION_RE.match(line) or ARTICLE_RE.match(line))


def is_title_continuation(line: str) -> bool:
    if not line or is_structure_line(line):
        return False
    if CLAUSE_RE.match(line) or POINT_RE.match(line):
        return False
    if line.startswith(BODY_START_PREFIXES):
        return False
    if is_upper_heading(line):
        return False
    # Tiêu đề điều bị xuống dòng thường bắt đầu bằng chữ thường:
    # Ví dụ: "thổ nước Cộng hòa..."
    if line[0].islower():
        return True
    # Nếu dòng ngắn và không phải câu thân luật, vẫn cho nối tiêu đề.
    if len(line.split()) <= 8 and not line.endswith("."):
        return True
    return False


def infer_condition_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["không áp dụng", "không phải", "miễn", "trừ trường hợp"]):
        return "exception"
    if any(k in t for k in ["phạt tù", "phạt tiền", "tử hình", "tù chung thân"]):
        return "penalty"
    if any(k in t for k in ["tuổi", "dưới 18", "từ đủ 14", "từ đủ 16"]):
        return "subject_age"
    if any(k in t for k in ["gây thiệt hại", "gây hậu quả", "làm chết", "thương tích", "tử vong"]):
        return "consequence"
    if any(k in t for k in ["tàng trữ", "vận chuyển", "mua bán", "sản xuất", "chiếm đoạt", "sử dụng", "tổ chức"]):
        return "act"
    if any(k in t for k in ["gam", "kg", "m3", "m³", "đồng", "triệu", "tỷ"]):
        return "quantity"
    return "legal_text"


def infer_rule_logic(text: str) -> str:
    t = text.lower()
    if "là" in t and len(t) < 500:
        return "DEFINITION"
    if any(k in t for k in ["không áp dụng", "không phải", "miễn", "trừ trường hợp"]):
        return "EXCEPTION"
    if any(k in t for k in ["phạt tù", "phạt tiền", "tử hình", "tù chung thân"]):
        return "PENALTY_FRAME"
    if "người nào" in t:
        return "BASE"
    return "BASE"


def clean_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Loại None để CSV JSON gọn hơn."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# 4. Đọc PDF và parse cấu trúc luật
# ---------------------------------------------------------------------------

def extract_pdf_lines(pdf_path: Path) -> List[PdfLine]:
    doc = fitz.open(str(pdf_path))
    result: List[PdfLine] = []
    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text("text")
        page_no = page_idx + 1
        for raw_line in text.splitlines():
            line = normalize_ws(raw_line)
            if not line:
                continue
            # Bỏ dòng chỉ chứa số trang.
            if line.isdigit() and int(line) == page_no:
                continue
            result.append(PdfLine(page=page_no, text=line))
    return result


def read_heading_name(lines: List[PdfLine], start_idx: int) -> Tuple[Optional[str], int]:
    """
    Đọc tên Part/Chapter nếu tiêu đề nằm ở dòng kế tiếp.
    Trả về (name, next_index).
    """
    parts: List[str] = []
    i = start_idx
    while i < len(lines):
        line = lines[i].text
        if is_structure_line(line):
            break
        if CLAUSE_RE.match(line) or POINT_RE.match(line):
            break
        # Tiêu đề chương/phần thường là uppercase, nhưng có thể xuống dòng.
        parts.append(line)
        i += 1
        # Dừng nếu dòng sau là Article/Chapter/Section/Part.
        if i < len(lines) and is_structure_line(lines[i].text):
            break
        # Tránh nuốt quá nhiều thân bài nếu gặp điều lạ.
        if len(parts) >= 3:
            break
    name = normalize_ws(" ".join(parts)) if parts else None
    return name, i


def collect_articles(lines: List[PdfLine], source_file: str) -> Tuple[List[ArticleDraft], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Parse PDF lines thành ArticleDraft và metadata Part/Chapter/Section.
    """
    articles: List[ArticleDraft] = []
    parts: Dict[str, Dict[str, Any]] = {}
    chapters: Dict[str, Dict[str, Any]] = {}
    sections: Dict[str, Dict[str, Any]] = {}

    current_part_id: Optional[str] = None
    current_part_name: Optional[str] = None
    current_chapter_id: Optional[str] = None
    current_chapter_name: Optional[str] = None
    current_section_id: Optional[str] = None
    current_section_name: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i].text

        m = PART_RE.match(line)
        if m:
            raw_part = m.group(1).strip()
            current_part_id = f"part_{safe_id(raw_part)}"
            name, next_i = read_heading_name(lines, i + 1)
            current_part_name = name or f"Phần thứ {raw_part}"
            parts[current_part_id] = {
                "id": current_part_id,
                "part_id": raw_part,
                "name": current_part_name,
            }
            current_chapter_id = current_chapter_name = None
            current_section_id = current_section_name = None
            i = max(next_i, i + 1)
            continue

        m = CHAPTER_RE.match(line)
        if m:
            raw_chapter = m.group(1).strip().upper()
            current_chapter_id = f"chapter_{raw_chapter.lower()}"
            name, next_i = read_heading_name(lines, i + 1)
            current_chapter_name = name or f"Chương {raw_chapter}"
            chapters[current_chapter_id] = {
                "id": current_chapter_id,
                "chapter_id": raw_chapter,
                "name": current_chapter_name,
                "part_id": current_part_id,
            }
            current_section_id = current_section_name = None
            i = max(next_i, i + 1)
            continue

        m = SECTION_RE.match(line)
        if m:
            section_no = m.group(1)
            section_title = normalize_ws(m.group(2))
            if not section_title and i + 1 < len(lines):
                section_title, next_i = read_heading_name(lines, i + 1)
            else:
                next_i = i + 1
            current_section_id = f"section_{safe_id(current_chapter_id or 'none')}_{section_no}"
            current_section_name = section_title or f"Mục {section_no}"
            sections[current_section_id] = {
                "id": current_section_id,
                "section_id": section_no,
                "name": current_section_name,
                "chapter_id": current_chapter_id,
            }
            i = max(next_i, i + 1)
            continue

        m = ARTICLE_RE.match(line)
        if m:
            article_code = m.group(1).strip()
            title_parts = [m.group(2).strip()]
            page_start = lines[i].page
            j = i + 1
            while j < len(lines) and is_title_continuation(lines[j].text):
                title_parts.append(lines[j].text)
                j += 1

            title = normalize_ws(" ".join([p for p in title_parts if p]))
            body_lines: List[PdfLine] = []
            while j < len(lines):
                next_line = lines[j].text
                if ARTICLE_RE.match(next_line) or PART_RE.match(next_line) or CHAPTER_RE.match(next_line) or SECTION_RE.match(next_line):
                    break
                body_lines.append(lines[j])
                j += 1

            page_end = body_lines[-1].page if body_lines else page_start
            article_number_match = re.match(r"(\d+)", article_code)
            article_number = int(article_number_match.group(1)) if article_number_match else 0
            suffix = article_code.replace(str(article_number), "") or None
            body_text = "\n".join(x.text for x in body_lines).strip()
            full_text = f"Điều {article_code}. {title}\n{body_text}".strip()
            art_id = f"article_{article_code}"

            status = "abolished" if "bãi bỏ" in title.lower() or "được bãi bỏ" in full_text.lower() else "active"

            articles.append(ArticleDraft(
                id=art_id,
                article_code=article_code,
                article_number=article_number,
                article_suffix=suffix,
                title=title,
                full_text=full_text,
                body_text=body_text,
                page_start=page_start,
                page_end=page_end,
                part_id=current_part_id,
                part_name=current_part_name,
                chapter_id=current_chapter_id,
                chapter_name=current_chapter_name,
                section_id=current_section_id,
                section_name=current_section_name,
                status=status,
                source_file=source_file,
            ))
            i = j
            continue

        i += 1

    return articles, parts, chapters, sections


# ---------------------------------------------------------------------------
# 5. Tách Clause / Point / Penalty / Quantity / Reference
# ---------------------------------------------------------------------------

def split_clauses(article: ArticleDraft) -> List[Dict[str, Any]]:
    body = article.body_text.strip()
    lines = body.splitlines()
    # Tìm vị trí dòng bắt đầu khoản.
    starts = [(idx, CLAUSE_RE.match(line)) for idx, line in enumerate(lines) if CLAUSE_RE.match(line)]
    clauses: List[Dict[str, Any]] = []

    if not starts:
        if body:
            clauses.append({
                "id": f"{article.id}_clause_0",
                "article_id": article.id,
                "article_code": article.article_code,
                "clause_no": None,
                "text": normalize_ws(body),
                "role": "body",
            })
        return clauses

    for pos, (line_idx, match) in enumerate(starts):
        assert match is not None
        next_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        clause_no = int(match.group(1))
        text = normalize_ws("\n".join(lines[line_idx:next_idx]))
        clauses.append({
            "id": f"{article.id}_clause_{clause_no}",
            "article_id": article.id,
            "article_code": article.article_code,
            "clause_no": clause_no,
            "text": text,
            "role": "clause",
        })
    return clauses


def split_points(clause: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = clause["text"].splitlines() if "\n" in clause["text"] else re.split(r"(?=(?:^|\s)[a-zA-ZđĐ]\)\s)", clause["text"])
    # Cách chắc hơn: dùng regex multiline trên text đã normalize có thể mất newline.
    raw_text = clause["text"]
    pattern = re.compile(r"(?:(?<=\s)|^)([a-zA-ZđĐ])\)\s+")
    matches = list(pattern.finditer(raw_text))
    points: List[Dict[str, Any]] = []
    for idx, match in enumerate(matches):
        point = match.group(1).lower()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)
        text = normalize_ws(raw_text[start:end])
        points.append({
            "id": f"{clause['id']}_point_{safe_id(point)}",
            "clause_id": clause["id"],
            "article_code": clause["article_code"],
            "clause_no": clause.get("clause_no"),
            "point": point,
            "text": text,
            "role": "point",
        })
    return points


def extract_penalties(owner_id: str, article_code: str, clause_no: Optional[int], text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Relationship]]:
    frames: List[Dict[str, Any]] = []
    penalties: List[Dict[str, Any]] = []
    rels: List[Relationship] = []

    idx = 0
    for m in PENALTY_PRISON_RE.finditer(text):
        idx += 1
        min_months = duration_to_months(m.group(1), m.group(2))
        max_months = duration_to_months(m.group(3), m.group(4))
        pf_id = f"penalty_frame_{safe_id(owner_id)}_{idx}"
        p_id = f"penalty_{safe_id(owner_id)}_{idx}"
        frames.append({
            "id": pf_id,
            "article_code": article_code,
            "owner_id": owner_id,
            "clause_no": clause_no,
            "penalty_type": "imprisonment",
            "penalty_text": m.group(0),
            "min_imprisonment_months": min_months,
            "max_imprisonment_months": max_months,
            "has_life_imprisonment": False,
            "has_death_penalty": False,
        })
        penalties.append({
            "id": p_id,
            "type": "imprisonment",
            "text": m.group(0),
            "min_months": min_months,
            "max_months": max_months,
        })
        rels.append(Relationship(pf_id, p_id, "HAS_MAIN_PENALTY"))

    for m in PENALTY_FINE_RE.finditer(text):
        idx += 1
        fine_min = parse_money_vnd(m.group(1))
        fine_max = parse_money_vnd(m.group(2))
        pf_id = f"penalty_frame_{safe_id(owner_id)}_fine_{idx}"
        p_id = f"penalty_{safe_id(owner_id)}_fine_{idx}"
        frames.append({
            "id": pf_id,
            "article_code": article_code,
            "owner_id": owner_id,
            "clause_no": clause_no,
            "penalty_type": "fine",
            "penalty_text": m.group(0),
            "fine_min_vnd": fine_min,
            "fine_max_vnd": fine_max,
            "has_life_imprisonment": False,
            "has_death_penalty": False,
        })
        penalties.append({
            "id": p_id,
            "type": "fine",
            "text": m.group(0),
            "fine_min_vnd": fine_min,
            "fine_max_vnd": fine_max,
        })
        rels.append(Relationship(pf_id, p_id, "HAS_MAIN_PENALTY"))

    lower = text.lower()
    if "tù chung thân" in lower:
        idx += 1
        pf_id = f"penalty_frame_{safe_id(owner_id)}_life"
        p_id = f"penalty_{safe_id(owner_id)}_life"
        frames.append({
            "id": pf_id,
            "article_code": article_code,
            "owner_id": owner_id,
            "clause_no": clause_no,
            "penalty_type": "life_imprisonment",
            "penalty_text": "tù chung thân",
            "has_life_imprisonment": True,
            "has_death_penalty": False,
        })
        penalties.append({"id": p_id, "type": "life_imprisonment", "text": "tù chung thân"})
        rels.append(Relationship(pf_id, p_id, "HAS_MAIN_PENALTY"))

    if "tử hình" in lower:
        idx += 1
        pf_id = f"penalty_frame_{safe_id(owner_id)}_death"
        p_id = f"penalty_{safe_id(owner_id)}_death"
        frames.append({
            "id": pf_id,
            "article_code": article_code,
            "owner_id": owner_id,
            "clause_no": clause_no,
            "penalty_type": "death_penalty",
            "penalty_text": "tử hình",
            "has_life_imprisonment": False,
            "has_death_penalty": True,
        })
        penalties.append({"id": p_id, "type": "death_penalty", "text": "tử hình"})
        rels.append(Relationship(pf_id, p_id, "HAS_MAIN_PENALTY"))

    return frames, penalties, rels


def extract_quantity_thresholds(owner_id: str, article_code: str, text: str) -> List[Dict[str, Any]]:
    thresholds: List[Dict[str, Any]] = []
    for idx, m in enumerate(QUANTITY_RANGE_RE.finditer(text), start=1):
        thresholds.append({
            "id": f"quantity_threshold_{safe_id(owner_id)}_{idx}",
            "article_code": article_code,
            "owner_id": owner_id,
            "min_value": parse_float_vn(m.group(1)),
            "max_value": parse_float_vn(m.group(3)),
            "unit": m.group(2).lower().replace("m³", "m3").replace("mét khối", "m3"),
            "raw_text": m.group(0),
        })
    return thresholds


def extract_references(article: ArticleDraft) -> List[str]:
    refs = set()
    for m in REFERENCE_ARTICLE_RE.finditer(article.full_text):
        code = m.group(1)
        if code != article.article_code:
            refs.add(code)
    return sorted(refs, key=lambda x: (int(re.match(r"\d+", x).group(0)), x))


# ---------------------------------------------------------------------------
# 6. Enrichment: crime, requirements, factors, NLP mapping
# ---------------------------------------------------------------------------

def make_crime(article: ArticleDraft) -> Optional[Dict[str, Any]]:
    if not article.title.lower().startswith("tội"):
        return None
    return {
        "id": f"crime_{article.article_code}",
        "article_code": article.article_code,
        "name": article.title,
        "crime_group": article.chapter_name,
        "is_criminal_offense": True,
    }


def infer_act_requirement(crime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = crime["name"]
    # Lấy phần sau chữ "Tội" làm mô tả hành vi chính.
    text = re.sub(r"^Tội\s+", "", name, flags=re.IGNORECASE).strip()
    if not text:
        return None
    return {
        "id": f"act_req_{crime['article_code']}",
        "article_code": crime["article_code"],
        "text": text,
        "normalized_text": normalize_ws(text.lower()),
    }


def infer_object_requirement(crime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = crime["name"].lower()
    keywords = [
        "ma túy", "tài sản", "gỗ", "rừng", "người", "vũ khí", "chất nổ", "tiền", "dữ liệu",
        "mạng máy tính", "phương tiện giao thông", "môi trường", "động vật", "thực vật",
    ]
    found = [kw for kw in keywords if kw in t]
    if not found:
        return None
    text = ", ".join(found)
    return {
        "id": f"object_req_{crime['article_code']}",
        "article_code": crime["article_code"],
        "text": text,
        "normalized_text": text,
    }


def infer_subject_requirements(article: ArticleDraft) -> List[Dict[str, Any]]:
    t = article.full_text.lower()
    rows: List[Dict[str, Any]] = []
    if "người nào" in t or article.title.lower().startswith("tội"):
        rows.append({
            "id": f"subject_req_{article.article_code}_person",
            "article_code": article.article_code,
            "text": "Người có năng lực trách nhiệm hình sự",
            "subject_type": "person",
        })
    if "pháp nhân thương mại" in t:
        rows.append({
            "id": f"subject_req_{article.article_code}_commercial_legal_entity",
            "article_code": article.article_code,
            "text": "Pháp nhân thương mại",
            "subject_type": "commercial_legal_entity",
        })
    if "từ đủ 14 tuổi" in t or "từ đủ 16 tuổi" in t or "dưới 18 tuổi" in t:
        rows.append({
            "id": f"subject_req_{article.article_code}_age",
            "article_code": article.article_code,
            "text": "Có điều kiện về tuổi chịu trách nhiệm hình sự",
            "subject_type": "age_requirement",
        })
    return rows


def infer_consequence_requirements(article: ArticleDraft) -> List[Dict[str, Any]]:
    patterns = [
        "làm chết", "chết người", "gây thương tích", "gây thiệt hại", "hậu quả", "tỷ lệ tổn thương",
        "thiệt hại về tài sản", "nguy hại", "tử vong",
    ]
    t = article.full_text.lower()
    rows = []
    for idx, p in enumerate(patterns, start=1):
        if p in t:
            rows.append({
                "id": f"consequence_req_{article.article_code}_{idx}",
                "article_code": article.article_code,
                "text": p,
                "normalized_text": p,
            })
    return rows


def extract_exceptions(article: ArticleDraft, owners: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(owners, start=1):
        text = item.get("text", "")
        lower = text.lower()
        if any(k in lower for k in ["trừ trường hợp", "không áp dụng", "không phải", "miễn trách nhiệm", "không phải chịu"]):
            rows.append({
                "id": f"exception_{safe_id(item['id'])}_{idx}",
                "article_code": article.article_code,
                "owner_id": item["id"],
                "text": text,
            })
    return rows


def extract_mitigating_aggravating(article: ArticleDraft, points: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    mitigating: List[Dict[str, Any]] = []
    aggravating: List[Dict[str, Any]] = []
    if article.article_code == "51":
        for p in points:
            mitigating.append({
                "id": f"mitigating_{safe_id(p['point'])}",
                "article_code": article.article_code,
                "point": p["point"],
                "text": p["text"],
            })
    if article.article_code == "52":
        for p in points:
            aggravating.append({
                "id": f"aggravating_{safe_id(p['point'])}",
                "article_code": article.article_code,
                "point": p["point"],
                "text": p["text"],
            })
    return mitigating, aggravating


def static_nlp_mapping() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Relationship]]:
    legal_concepts = [
        {"id": "legal_concept_su_dung_ma_tuy", "name": "sử dụng trái phép chất ma túy", "type": "drug_use"},
        {"id": "legal_concept_dong_pham", "name": "đồng phạm", "type": "complicity"},
        {"id": "legal_concept_giup_suc", "name": "giúp sức", "type": "complicity_role"},
        {"id": "legal_concept_che_giau", "name": "che giấu tội phạm", "type": "concealment"},
        {"id": "legal_concept_khong_to_giac", "name": "không tố giác tội phạm", "type": "failure_to_report"},
    ]
    substances = [
        {"id": "substance_ketamine", "name": "ketamine", "category": "drug"},
        {"id": "substance_mdma", "name": "MDMA/thuốc lắc", "category": "drug"},
        {"id": "substance_methamphetamine", "name": "methamphetamine/ma túy đá", "category": "drug"},
        {"id": "substance_cannabis", "name": "cần sa", "category": "drug"},
    ]
    slang_terms = [
        {"id": "slang_bay_phong", "text": "bay phòng", "target_id": "legal_concept_su_dung_ma_tuy"},
        {"id": "slang_choi_ke", "text": "chơi ke", "target_id": "substance_ketamine"},
        {"id": "slang_ke", "text": "ke", "target_id": "substance_ketamine"},
        {"id": "slang_khay", "text": "khay", "target_id": "substance_ketamine"},
        {"id": "slang_keo", "text": "kẹo", "target_id": "substance_mdma"},
        {"id": "slang_da", "text": "đá", "target_id": "substance_methamphetamine"},
    ]
    action_aliases = [
        {"id": "action_ru_di_bay", "text": "rủ đi bay", "signal_id": "signal_loi_keo_su_dung_ma_tuy"},
        {"id": "action_dat_phong", "text": "đặt phòng", "signal_id": "signal_chua_chap_to_chuc_su_dung"},
        {"id": "action_giup_suc", "text": "giúp sức", "signal_id": "signal_dong_pham"},
        {"id": "action_che_giau", "text": "che giấu", "signal_id": "signal_che_giau_toi_pham"},
    ]
    legal_signals = [
        {"id": "signal_loi_keo_su_dung_ma_tuy", "name": "có dấu hiệu lôi kéo/tổ chức sử dụng ma túy"},
        {"id": "signal_chua_chap_to_chuc_su_dung", "name": "có dấu hiệu chứa chấp hoặc tổ chức sử dụng"},
        {"id": "signal_dong_pham", "name": "có dấu hiệu đồng phạm"},
        {"id": "signal_che_giau_toi_pham", "name": "có dấu hiệu che giấu tội phạm"},
    ]
    rels: List[Relationship] = []
    for s in slang_terms:
        rels.append(Relationship(s["id"], s["target_id"], "NORMALIZES_TO"))
    for a in action_aliases:
        rels.append(Relationship(a["id"], a["signal_id"], "MAY_INDICATE"))
    return legal_concepts, substances, slang_terms, action_aliases, legal_signals, rels


# ---------------------------------------------------------------------------
# 7. Build graph
# ---------------------------------------------------------------------------

def build_graph(pdf_path: Path) -> Tuple[List[Node], List[Relationship], Dict[str, Any]]:
    lines = extract_pdf_lines(pdf_path)
    articles, parts, chapters, sections = collect_articles(lines, source_file=pdf_path.name)

    nodes: List[Node] = []
    rels: List[Relationship] = []

    # Law root
    law_id = "law_blhs_2025"
    nodes.append(Node(law_id, "Law", {
        "id": law_id,
        "name": "Văn bản hợp nhất Bộ luật Hình sự năm 2025",
        "source_file": pdf_path.name,
    }))

    # Parts
    for p in parts.values():
        nodes.append(Node(p["id"], "Part", clean_dict(p)))
        rels.append(Relationship(law_id, p["id"], "HAS_PART"))

    # Chapters
    for ch in chapters.values():
        nodes.append(Node(ch["id"], "Chapter", clean_dict(ch)))
        if ch.get("part_id"):
            rels.append(Relationship(ch["part_id"], ch["id"], "HAS_CHAPTER"))

    # Sections
    for s in sections.values():
        nodes.append(Node(s["id"], "Section", clean_dict(s)))
        if s.get("chapter_id"):
            rels.append(Relationship(s["chapter_id"], s["id"], "HAS_SECTION"))

    legal_concepts, substances, slang_terms, action_aliases, legal_signals, mapping_rels = static_nlp_mapping()
    for row in legal_concepts:
        nodes.append(Node(row["id"], "LegalConcept", row))
    for row in substances:
        nodes.append(Node(row["id"], "Substance", row))
    for row in slang_terms:
        node_row = {k: v for k, v in row.items() if k != "target_id"}
        nodes.append(Node(row["id"], "SlangTerm", node_row))
    for row in action_aliases:
        node_row = {k: v for k, v in row.items() if k != "signal_id"}
        nodes.append(Node(row["id"], "ActionAlias", node_row))
    for row in legal_signals:
        nodes.append(Node(row["id"], "LegalSignal", row))
    rels.extend(mapping_rels)

    article_by_code: Dict[str, str] = {a.article_code: a.id for a in articles}

    # Article-level processing
    for article in articles:
        article_props = asdict(article)
        # body_text không cần lưu nếu đã có full_text, nhưng giữ để báo cáo/truy vết.
        nodes.append(Node(article.id, "Article", clean_dict(article_props)))
        if article.section_id:
            rels.append(Relationship(article.section_id, article.id, "HAS_ARTICLE"))
        elif article.chapter_id:
            rels.append(Relationship(article.chapter_id, article.id, "HAS_ARTICLE"))

        crime = make_crime(article)
        if crime:
            nodes.append(Node(crime["id"], "Crime", crime))
            rels.append(Relationship(article.id, crime["id"], "DEFINES_CRIME"))

            act = infer_act_requirement(crime)
            if act:
                nodes.append(Node(act["id"], "ActRequirement", act))
                rels.append(Relationship(crime["id"], act["id"], "HAS_ACT_REQUIREMENT"))
            obj = infer_object_requirement(crime)
            if obj:
                nodes.append(Node(obj["id"], "ObjectRequirement", obj))
                rels.append(Relationship(crime["id"], obj["id"], "HAS_OBJECT_REQUIREMENT"))

        # Subject requirements and consequences can apply to Article/Crime.
        subject_rows = infer_subject_requirements(article)
        consequence_rows = infer_consequence_requirements(article)
        for row in subject_rows:
            nodes.append(Node(row["id"], "SubjectRequirement", row))
            if crime:
                rels.append(Relationship(crime["id"], row["id"], "HAS_SUBJECT_REQUIREMENT"))
            else:
                rels.append(Relationship(article.id, row["id"], "HAS_SUBJECT_REQUIREMENT"))
        for row in consequence_rows:
            nodes.append(Node(row["id"], "ConsequenceRequirement", row))
            if crime:
                rels.append(Relationship(crime["id"], row["id"], "HAS_CONSEQUENCE_REQUIREMENT"))
            else:
                rels.append(Relationship(article.id, row["id"], "HAS_CONSEQUENCE_REQUIREMENT"))

        clauses = split_clauses(article)
        all_point_rows: List[Dict[str, Any]] = []
        owner_text_items: List[Dict[str, Any]] = []

        for clause in clauses:
            nodes.append(Node(clause["id"], "Clause", clause))
            rels.append(Relationship(article.id, clause["id"], "HAS_CLAUSE"))
            owner_text_items.append(clause)

            # Rule cho Clause
            rule_id = f"rule_{clause['id']}"
            rule = {
                "id": rule_id,
                "article_code": article.article_code,
                "owner_id": clause["id"],
                "level": "clause",
                "logic": infer_rule_logic(clause["text"]),
                "text": clause["text"],
            }
            nodes.append(Node(rule_id, "Rule", rule))
            rels.append(Relationship(article.id, rule_id, "HAS_RULE"))
            rels.append(Relationship(clause["id"], rule_id, "HAS_RULE"))

            # Condition cho Clause
            cond_id = f"condition_{clause['id']}"
            cond = {
                "id": cond_id,
                "article_code": article.article_code,
                "owner_id": clause["id"],
                "condition_type": infer_condition_type(clause["text"]),
                "text": clause["text"],
                "normalized_text": normalize_ws(clause["text"].lower()),
                "required": True,
            }
            nodes.append(Node(cond_id, "Condition", cond))
            rels.append(Relationship(clause["id"], cond_id, "HAS_CONDITION"))

            # Penalty / Quantity cho Clause
            frames, penalties, penalty_rels = extract_penalties(clause["id"], article.article_code, clause.get("clause_no"), clause["text"])
            for frame in frames:
                nodes.append(Node(frame["id"], "PenaltyFrame", frame))
                rels.append(Relationship(clause["id"], frame["id"], "HAS_PENALTY_FRAME"))
            for penalty in penalties:
                nodes.append(Node(penalty["id"], "Penalty", penalty))
            rels.extend(penalty_rels)

            qts = extract_quantity_thresholds(clause["id"], article.article_code, clause["text"])
            for qt in qts:
                nodes.append(Node(qt["id"], "QuantityThreshold", qt))
                if crime:
                    rels.append(Relationship(crime["id"], qt["id"], "HAS_QUANTITY_THRESHOLD"))
                else:
                    rels.append(Relationship(article.id, qt["id"], "HAS_QUANTITY_THRESHOLD"))

            # Points
            point_rows = split_points(clause)
            all_point_rows.extend(point_rows)
            for point in point_rows:
                nodes.append(Node(point["id"], "Point", point))
                rels.append(Relationship(clause["id"], point["id"], "HAS_POINT"))
                owner_text_items.append(point)

                point_rule_id = f"rule_{point['id']}"
                point_rule = {
                    "id": point_rule_id,
                    "article_code": article.article_code,
                    "owner_id": point["id"],
                    "level": "point",
                    "logic": infer_rule_logic(point["text"]),
                    "text": point["text"],
                }
                nodes.append(Node(point_rule_id, "Rule", point_rule))
                rels.append(Relationship(point["id"], point_rule_id, "HAS_RULE"))

                point_cond_id = f"condition_{point['id']}"
                point_cond = {
                    "id": point_cond_id,
                    "article_code": article.article_code,
                    "owner_id": point["id"],
                    "condition_type": infer_condition_type(point["text"]),
                    "text": point["text"],
                    "normalized_text": normalize_ws(point["text"].lower()),
                    "required": True,
                }
                nodes.append(Node(point_cond_id, "Condition", point_cond))
                rels.append(Relationship(point["id"], point_cond_id, "HAS_CONDITION"))

                p_frames, p_penalties, p_rels = extract_penalties(point["id"], article.article_code, point.get("clause_no"), point["text"])
                for frame in p_frames:
                    nodes.append(Node(frame["id"], "PenaltyFrame", frame))
                    rels.append(Relationship(point["id"], frame["id"], "HAS_PENALTY_FRAME"))
                for penalty in p_penalties:
                    nodes.append(Node(penalty["id"], "Penalty", penalty))
                rels.extend(p_rels)

                point_qts = extract_quantity_thresholds(point["id"], article.article_code, point["text"])
                for qt in point_qts:
                    nodes.append(Node(qt["id"], "QuantityThreshold", qt))
                    if crime:
                        rels.append(Relationship(crime["id"], qt["id"], "HAS_QUANTITY_THRESHOLD"))
                    else:
                        rels.append(Relationship(article.id, qt["id"], "HAS_QUANTITY_THRESHOLD"))

        # Exceptions
        exceptions = extract_exceptions(article, owner_text_items)
        for ex in exceptions:
            nodes.append(Node(ex["id"], "Exception", ex))
            rels.append(Relationship(article.id, ex["id"], "HAS_EXCEPTION"))

        # Mitigating / Aggravating factors
        mitigating, aggravating = extract_mitigating_aggravating(article, all_point_rows)
        for row in mitigating:
            nodes.append(Node(row["id"], "MitigatingFactor", row))
            rels.append(Relationship(article.id, row["id"], "HAS_MITIGATING_FACTOR"))
        for row in aggravating:
            nodes.append(Node(row["id"], "AggravatingFactor", row))
            rels.append(Relationship(article.id, row["id"], "HAS_AGGRAVATING_FACTOR"))

        # References
        for ref_code in extract_references(article):
            ref_id = article_by_code.get(ref_code)
            if not ref_id:
                # Reference-only article node để không mất quan hệ nếu điều chưa parse được.
                ref_id = f"article_{ref_code}"
            if ref_id != article.id:
                rels.append(Relationship(article.id, ref_id, "REFERENCES", {"ref_article_code": ref_code}))

    # Deduplicate nodes by (label,id), relationships by tuple.
    node_map: Dict[Tuple[str, str], Node] = {}
    for n in nodes:
        node_map[(n.label, n.id)] = n
    rel_map: Dict[Tuple[str, str, str, str], Relationship] = {}
    for r in rels:
        key = (r.source_id, r.target_id, r.type, json.dumps(r.properties, sort_keys=True, ensure_ascii=False))
        rel_map[key] = r

    final_nodes = list(node_map.values())
    final_rels = list(rel_map.values())

    stats: Dict[str, Any] = {
        "pdf_file": pdf_path.name,
        "articles": len(articles),
        "nodes": len(final_nodes),
        "relationships": len(final_rels),
        "labels": {},
        "relationship_types": {},
    }
    for n in final_nodes:
        stats["labels"][n.label] = stats["labels"].get(n.label, 0) + 1
    for r in final_rels:
        stats["relationship_types"][r.type] = stats["relationship_types"].get(r.type, 0) + 1

    return final_nodes, final_rels, stats


# ---------------------------------------------------------------------------
# 8. Export JSON/CSV/Cypher/Docker/README
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def export_package(nodes: List[Node], rels: List[Relationship], stats: Dict[str, Any], out_dir: Path) -> None:
    data_dir = out_dir / "data"
    import_dir = out_dir / "neo4j_import"
    cypher_dir = out_dir / "cypher"
    scripts_dir = out_dir / "scripts"
    for d in [data_dir, import_dir, cypher_dir, scripts_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # JSON normalized / graph
    graph_json = {
        "nodes": [asdict(n) for n in nodes],
        "relationships": [asdict(r) for r in rels],
        "stats": stats,
    }
    (data_dir / "blhs_graph.json").write_text(json.dumps(graph_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # Universal CSV: dùng APOC import động label/relationship.
    node_rows = []
    for n in nodes:
        props = dict(n.properties)
        props["id"] = n.id
        node_rows.append({
            "id": n.id,
            "label": n.label,
            "properties_json": json.dumps(clean_dict(props), ensure_ascii=False),
        })
    write_csv(import_dir / "nodes.csv", node_rows, ["id", "label", "properties_json"])

    rel_rows = []
    for r in rels:
        rel_rows.append({
            "source_id": r.source_id,
            "target_id": r.target_id,
            "type": r.type,
            "properties_json": json.dumps(clean_dict(r.properties), ensure_ascii=False),
        })
    write_csv(import_dir / "relationships.csv", rel_rows, ["source_id", "target_id", "type", "properties_json"])

    # Per-label CSV để dễ báo cáo/đọc bằng Excel.
    by_label: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        by_label.setdefault(n.label, []).append(clean_dict(n.properties))
    for label, rows in by_label.items():
        keys = sorted({k for row in rows for k in row.keys()})
        if "id" in keys:
            keys.remove("id")
            keys = ["id"] + keys
        write_csv(import_dir / f"{safe_id(label)}.csv", rows, keys)

    write_cypher_files(cypher_dir)
    write_docker_compose(out_dir)
    write_readme(out_dir, stats)


def write_cypher_files(cypher_dir: Path) -> None:
    (cypher_dir / "00_reset_database.cypher").write_text(
        "MATCH (n) DETACH DELETE n;\n", encoding="utf-8"
    )

    (cypher_dir / "01_constraints_indexes.cypher").write_text(
        """
CREATE CONSTRAINT node_id_unique IF NOT EXISTS
FOR (n:GraphNode) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT article_id_unique IF NOT EXISTS
FOR (a:Article) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT article_code_unique IF NOT EXISTS
FOR (a:Article) REQUIRE a.article_code IS UNIQUE;

CREATE CONSTRAINT crime_id_unique IF NOT EXISTS
FOR (c:Crime) REQUIRE c.id IS UNIQUE;

CREATE FULLTEXT INDEX article_fulltext IF NOT EXISTS
FOR (a:Article)
ON EACH [a.title, a.full_text];

CREATE FULLTEXT INDEX condition_fulltext IF NOT EXISTS
FOR (c:Condition)
ON EACH [c.text, c.normalized_text];

CREATE FULLTEXT INDEX crime_fulltext IF NOT EXISTS
FOR (c:Crime)
ON EACH [c.name];
""".strip() + "\n",
        encoding="utf-8",
    )

    # Dùng APOC để tạo dynamic labels/relationship types từ CSV tổng quát.
    (cypher_dir / "02_import_graph.cypher").write_text(
        """
// Import node động từ nodes.csv.
// Yêu cầu Neo4j bật APOC. Docker compose trong package đã bật APOC.
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row, apoc.convert.fromJsonMap(row.properties_json) AS props
CALL apoc.create.node(['GraphNode', row.label], props) YIELD node
RETURN count(node) AS imported_nodes;

// Import relationship động từ relationships.csv.
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
MATCH (src:GraphNode {id: row.source_id})
MATCH (dst:GraphNode {id: row.target_id})
WITH src, dst, row, apoc.convert.fromJsonMap(row.properties_json) AS props
CALL apoc.create.relationship(src, row.type, props, dst) YIELD rel
RETURN count(rel) AS imported_relationships;
""".strip() + "\n",
        encoding="utf-8",
    )

    (cypher_dir / "03_query_examples.cypher").write_text(
        """
// Đếm node theo label
MATCH (n)
RETURN labels(n) AS labels, count(n) AS total
ORDER BY total DESC;

// Lấy điều luật đầu tiên
MATCH (a:Article)
RETURN a.article_code, a.title
ORDER BY a.article_number, a.article_code
LIMIT 20;

// Lấy khung phạt của Điều 249 nếu có
MATCH (a:Article {article_code:'249'})-[:HAS_CLAUSE]->(cl:Clause)
OPTIONAL MATCH (cl)-[:HAS_PENALTY_FRAME]->(pf:PenaltyFrame)
RETURN a.article_code, a.title, cl.clause_no, cl.text, collect(pf.penalty_text) AS penalty_frames
ORDER BY cl.clause_no;

// Tình tiết giảm nhẹ Điều 51
MATCH (a:Article {article_code:'51'})-[:HAS_MITIGATING_FACTOR]->(m:MitigatingFactor)
RETURN m.point, m.text
ORDER BY m.point;

// Tình tiết tăng nặng Điều 52
MATCH (a:Article {article_code:'52'})-[:HAS_AGGRAVATING_FACTOR]->(g:AggravatingFactor)
RETURN g.point, g.text
ORDER BY g.point;
""".strip() + "\n",
        encoding="utf-8",
    )


def write_docker_compose(out_dir: Path) -> None:
    (out_dir / "docker-compose.yml").write_text(
        """
services:
  neo4j:
    image: neo4j:5.22.0
    container_name: blhs-neo4j-report
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password123456
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_security_procedures_unrestricted: apoc.*
      NEO4J_dbms_security_procedures_allowlist: apoc.*
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - ./neo4j_import:/var/lib/neo4j/import
      - ./cypher:/cypher

volumes:
  neo4j_data:
  neo4j_logs:
""".strip() + "\n",
        encoding="utf-8",
    )


def write_readme(out_dir: Path, stats: Dict[str, Any]) -> None:
    readme = f"""
# BLHS PDF -> Neo4j Knowledge Graph Package

Package này được sinh tự động từ PDF `{stats.get('pdf_file')}`.

## Pipeline

```text
PDF BLHS
→ PyMuPDF extract text
→ Regex parser tách Part / Chapter / Section / Article / Clause / Point
→ Rule-based extractor tách Crime / Rule / Condition / PenaltyFrame / Penalty / Requirement / Exception / Reference
→ Bổ sung NLP mapping: SlangTerm / ActionAlias / SubstanceAlias
→ Xuất JSON + CSV
→ Import Neo4j bằng Cypher + APOC
```

## Thống kê

```json
{json.dumps(stats, ensure_ascii=False, indent=2)}
```

## Chạy Neo4j

```bash
docker compose up -d
```

Mở Neo4j Browser:

```text
http://localhost:7474
user: neo4j
password: password123456
```

## Import dữ liệu

```bash
docker exec -i blhs-neo4j-report cypher-shell -u neo4j -p password123456 < cypher/00_reset_database.cypher
docker exec -i blhs-neo4j-report cypher-shell -u neo4j -p password123456 < cypher/01_constraints_indexes.cypher
docker exec -i blhs-neo4j-report cypher-shell -u neo4j -p password123456 < cypher/02_import_graph.cypher
```

## Kiểm tra

```cypher
MATCH (n)
RETURN labels(n) AS labels, count(n) AS total
ORDER BY total DESC;
```

## Lưu ý báo cáo

Đây là pipeline rule-based. Các điều luật có nhiều ngưỡng định lượng phức tạp
như ma túy, lâm sản, môi trường, tham nhũng cần manual review trước khi dùng
như dữ liệu pháp lý chính thức.
""".strip() + "\n"
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def copy_self_to_scripts(out_dir: Path) -> None:
    try:
        src = Path(__file__).resolve()
        dst = out_dir / "scripts" / "build_from_pdf.py"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception:
        pass


def zip_dir(folder: Path) -> Path:
    zip_path = folder.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(folder.parent))
    return zip_path


# ---------------------------------------------------------------------------
# 9. CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert BLHS PDF to Neo4j graph package")
    parser.add_argument("--pdf", required=True, help="Path to BLHS PDF")
    parser.add_argument("--out", default="blhs_graph_package", help="Output folder")
    parser.add_argument("--zip", action="store_true", help="Create zip package")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out).resolve()

    if not pdf_path.exists():
        raise SystemExit(f"Không tìm thấy PDF: {pdf_path}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Đọc và parse PDF: {pdf_path}")
    nodes, rels, stats = build_graph(pdf_path)

    print("[2/4] Xuất JSON/CSV/Cypher/Docker/README")
    export_package(nodes, rels, stats, out_dir)
    copy_self_to_scripts(out_dir)

    print("[3/4] Thống kê")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if args.zip:
        print("[4/4] Nén ZIP")
        zip_path = zip_dir(out_dir)
        print(f"ZIP created: {zip_path}")
    else:
        print("[4/4] Bỏ qua nén ZIP")

    print(f"Done. Output folder: {out_dir}")


if __name__ == "__main__":
    main()
