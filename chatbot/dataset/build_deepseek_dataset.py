#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xử lý PDF / văn bản BLHS thành JSON cùng cấu trúc deepseek_merged.json (chỉ xử lý local).

Cài đặt:
    pip install pypdf

Ví dụ:
    cd chatbot/dataset
    python build_deepseek_dataset.py --pdf "P1 VB-Hop-nhat-BLHS-2025.pdf" --out blhs_parsed.json
    python build_deepseek_dataset.py --text extracted.txt --out blhs_parsed.json
    python build_deepseek_dataset.py --merge-only --parts deepseek_part1.json deepseek_part2.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Regex cấu trúc
# ---------------------------------------------------------------------------

_RE_PART = re.compile(
    r"(?im)^\s*Phần\s+(thứ\s+(?:nhất|hai|ba|tư)|[IVXLCĐ]+)\s*$",
)
_RE_CHAPTER = re.compile(
    r"(?im)^\s*Chương\s+([IVXLCĐivxlcdđ]+)\s*$",
)
_RE_ARTICLE = re.compile(
    r"(?im)^\s*Điều\s+(\d{1,4}[a-z]?)\s*[\.\:,-]?\s*(.*?)\s*$",
)
_RE_CLAUSE = re.compile(r"(?m)(?:^|\n)\s*(\d{1,2})\.\s*")
_RE_SUBPOINT = re.compile(
    r"(?m)^\s*([a-zđ])(?:\)|\.)\s+",
    re.IGNORECASE,
)

_PART_NAMES = {
    1: "Những quy định chung",
    2: "Các tội phạm",
}

# Hình phạt
_RE_PRISON_YEAR = re.compile(
    r"phạt\s+tù\s+từ\s+(\d{1,2})\s*(?:năm|nam)\s*đến\s*(\d{1,2})\s*(?:năm|nam)",
    re.I,
)
_RE_PRISON_MONTH = re.compile(
    r"phạt\s+tù\s+từ\s+(\d{1,2})\s*tháng\s*đến\s*(\d{1,2})\s*(?:năm|tháng)",
    re.I,
)
_RE_SIMPLE_YEAR = re.compile(
    r"(?:bị\s+)?phạt\s+tù\s+từ\s+(\d{1,2})\s*đến\s*(\d{1,2})\s*(?:năm|nam)",
    re.I,
)
_RE_FINE = re.compile(
    r"phạt\s+tiền\s+từ\s+([^;,\n]+?)\s*đến\s*([^;,\n]+?)(?:\s*đồng|\.|,|;|$)",
    re.I,
)
_RE_REFORM = re.compile(
    r"cải\s+tạo\s+không\s+giam\s+giữ\s+(?:đến\s*)?(\d{1,2})\s*(?:năm|nam)",
    re.I,
)

# Số tiền trong điều kiện
_RE_AMOUNT = re.compile(
    r"(thu\s+lợi\s+bất\s+chính|gây\s+thiệt\s+hại|giá\s+trị|thiệt\s+hại|số\s+tiền)"
    r"[^.\n]{0,80}?"
    r"(\d[\d\.,]*)\s*(triệu|tỷ|nghìn|ngàn)?"
    r"(?:\s*đồng)?"
    r"(?:\s*đến\s*(?:dưới\s*)?(\d[\d\.,]*)\s*(triệu|tỷ|nghìn|ngàn)?)?"
    r"(?:\s*đồng)?"
    r"(?:\s*trở\s+lên)?",
    re.I,
)


@dataclass
class ArticleBlock:
    number: str
    title: str
    body: str


@dataclass
class ChapterBlock:
    chapter_id: str
    name: str
    part_id: int
    articles: list[ArticleBlock] = field(default_factory=list)


@dataclass
class PartBlock:
    part_id: int
    name: str
    chapters: list[ChapterBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tiện ích văn bản
# ---------------------------------------------------------------------------


def clean_pdf_text(text: str) -> str:
    """Chuẩn hóa text trích từ PDF (giữ khoảng trắng, chỉ bỏ số trang)."""
    text = text.replace("\r", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line or re.fullmatch(r"\d{1,3}", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Cần cài pypdf: pip install pypdf") from exc

    reader = PdfReader(str(pdf_path))
    return clean_pdf_text("\n".join(page.extract_text() or "" for page in reader.pages))


def parse_money(value: str, unit: str | None) -> int | None:
    value = value.replace(",", "").replace(".", "").strip()
    if not value.isdigit():
        return None
    num = int(value)
    u = (unit or "").lower()
    if u in ("tỷ", "ty"):
        return num * 1_000_000_000
    if u in ("triệu", "trieu"):
        return num * 1_000_000
    if u in ("nghìn", "ngàn", "nghin"):
        return num * 1_000
    return num


def extract_amounts(text: str) -> dict[str, Any] | None:
    m = _RE_AMOUNT.search(text)
    if not m:
        return None
    kind_raw = m.group(1).lower()
    if "lợi" in kind_raw or "profit" in kind_raw:
        kind = "profit"
    elif "thiệt hại" in kind_raw or "damage" in kind_raw:
        kind = "damage"
    else:
        kind = "amount"

    vmin = parse_money(m.group(2), m.group(3))
    vmax = parse_money(m.group(4), m.group(5)) if m.group(4) else None
    if "trở lên" in text.lower():
        vmax = None
    if vmin is None:
        return None
    return {"type": kind, "unit": "VND", "min": vmin, "max": vmax}


def extract_penalty(clause_text: str) -> dict[str, Any]:
    """Trích hình phạt từ nội dung một khoản."""
    penalty: dict[str, Any] = {"note": clause_text.strip()[:2000]}

    m = _RE_PRISON_YEAR.search(clause_text)
    if m:
        penalty["min"] = int(m.group(1))
        penalty["max"] = int(m.group(2))
        return penalty

    m = _RE_PRISON_MONTH.search(clause_text)
    if m:
        penalty["prison"] = {
            "min": int(m.group(1)),
            "max": int(m.group(2)),
            "unit": "month" if "tháng" in m.group(0).lower() else "year",
        }

    m = _RE_FINE.search(clause_text)
    if m:
        lo = parse_money(re.sub(r"\D", "", m.group(1).split()[0]), None)
        hi = parse_money(re.sub(r"\D", "", m.group(2).split()[0]), None)
        # Thử parse có đơn vị triệu/tỷ trong chuỗi
        for part, key in ((m.group(1), "fine_min"), (m.group(2), "fine_max")):
            mm = re.search(r"(\d+)\s*(triệu|tỷ)", part, re.I)
            if mm:
                val = parse_money(mm.group(1), mm.group(2))
                if key == "fine_min":
                    lo = val
                else:
                    hi = val
        if lo is not None and hi is not None:
            penalty["fine"] = {"min": lo, "max": hi}

    m = _RE_REFORM.search(clause_text)
    if m:
        penalty["reform"] = {"min": 0, "max": int(m.group(1)), "unit": "year"}

    m = _RE_SIMPLE_YEAR.search(clause_text)
    if m and "min" not in penalty and "prison" not in penalty:
        penalty["min"] = int(m.group(1))
        penalty["max"] = int(m.group(2))

    return penalty


def guess_logic(clause_num: int | None, text: str, article_title: str) -> str:
    t = text.lower()
    title = article_title.lower()
    if "hình phạt bổ sung" in title or "bổ sung" in title and clause_num is None:
        return "ADDITIONAL_PENALTY"
    if any(k in t for k in ("chuẩn bị phạm tội", "chuẩn bị ", "phạm tội chưa ")):
        return "PREPARATION"
    if any(k in t for k in ("định nghĩa", "khái niệm", "hiểu như sau")):
        return "DEFINITION"
    if "nguyên tắc" in title:
        return "PRINCIPLE"
    if any(k in t for k in ("không có hiệu lực", "không được áp dụng")):
        return "NON_RETROACTIVE"
    if "có lợi cho người phạm tội" in t:
        return "RETROACTIVE_FAVORABLE"
    if clause_num and clause_num >= 2 and any(
        k in t for k in ("tăng nặng", "nặng hơn", "phạm tội trong trường hợp", "trở lên")
    ):
        return "AGGRAVATION"
    if "có thể bị" in t and any(k in t for k in ("cấm", "tước", "bổ sung")):
        return "ADDITIONAL_PENALTY"
    if "pháp nhân thương mại" in t and clause_num and clause_num >= 4:
        return "ENTITY_PENALTY"
    if clause_num == 1 or clause_num is None:
        return "BASE"
    return "AGGRAVATION"


def guess_condition_type(text: str, logic: str, point: str | None) -> str:
    t = text.lower()
    if logic == "PRINCIPLE":
        return "principle"
    if logic == "AGGRAVATION" or "tăng nặng" in t:
        return "aggravating"
    if any(k in t for k in ("phạm tội", "thực hiện", "gây ra", "chiếm đoạt", "giết")):
        return "action"
    if "pháp nhân" in t:
        return "entity"
    if "người" in t and any(k in t for k in ("công dân", "đối tượng")):
        return "actor"
    if point:
        return "condition"
    return "scope"


def split_clauses(body: str) -> list[tuple[int | None, str]]:
    """Tách các khoản 1. 2. 3. trong thân điều."""
    matches = list(_RE_CLAUSE.finditer(body))
    if not matches:
        return [(None, body.strip())]

    chunks: list[tuple[int | None, str]] = []
    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        # Bỏ tiền tố "1. "
        chunk = re.sub(r"^\d{1,2}\.\s+", "", chunk)
        chunks.append((num, chunk))
    return chunks


def parse_subpoints(clause_text: str) -> list[dict[str, Any]]:
    """Tách tiểu mục a) b) c) đ) ..."""
    matches = list(_RE_SUBPOINT.finditer(clause_text))
    if not matches:
        return []

    items: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        point = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(clause_text)
        text = clause_text[start:end].strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) < 3:
            continue
        cond: dict[str, Any] = {"type": "condition", "point": point, "text": text}
        amt = extract_amounts(text)
        if amt:
            cond["amount"] = amt
        items.append(cond)
    return items


def article_to_json(art: ArticleBlock) -> dict[str, Any]:
    """Chuyển một Điều thành {crime, rules}."""
    article_num = re.match(r"(\d+)", art.number)
    article_int = int(article_num.group(1)) if article_num else 0
    crime_id = art.number if art.number else str(article_int)

    rules: list[dict[str, Any]] = []
    clauses = split_clauses(art.body)

    for priority, (clause_num, clause_text) in enumerate(clauses, start=1):
        logic = guess_logic(clause_num, clause_text, art.title)
        conditions = parse_subpoints(clause_text)
        if not conditions and clause_text:
            # Một điều kiện tổng quát từ câu đầu khoản
            first_sent = re.split(r"[.;]\s+", clause_text, maxsplit=1)[0].strip()
            if len(first_sent) > 10 and logic in ("BASE", "DEFINITION", "PRINCIPLE"):
                conditions = [
                    {
                        "type": guess_condition_type(first_sent, logic, None),
                        "text": first_sent[:500],
                    }
                ]

        for c in conditions:
            c["type"] = guess_condition_type(c.get("text", ""), logic, c.get("point"))

        penalty = extract_penalty(clause_text)
        rule_id = f"{crime_id}_r{priority}"

        rules.append(
            {
                "rule_id": rule_id,
                "clause": clause_num,
                "logic": logic,
                "priority": priority,
                "conditions": conditions,
                "penalty": penalty,
            }
        )

    return {
        "crime": {
            "id": crime_id,
            "name": art.title or f"Điều {crime_id}",
            "article": article_int,
        },
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# Tách cấu trúc Phần / Chương / Điều
# ---------------------------------------------------------------------------


def _part_id_from_heading(heading: str, index: int) -> int:
    h = heading.lower()
    if "thứ nhất" in h:
        return 1
    if "thứ hai" in h:
        return 2
    return index


def split_structure(full_text: str) -> list[PartBlock]:
    part_starts = [m.start() for m in _RE_PART.finditer(full_text)]
    if not part_starts:
        part_starts = [0]

    parts: list[PartBlock] = []
    for pi, pstart in enumerate(part_starts):
        pend = part_starts[pi + 1] if pi + 1 < len(part_starts) else len(full_text)
        part_slice = full_text[pstart:pend]
        pid = _part_id_from_heading(part_slice.split("\n", 1)[0], pi + 1)
        pname = _PART_NAMES.get(pid, f"Phần {pid}")
        part = PartBlock(part_id=pid, name=pname)

        chap_starts = [m.start() for m in _RE_CHAPTER.finditer(part_slice)]
        if not chap_starts:
            chap_starts = [0]

        for ci, cstart in enumerate(chap_starts):
            cend = chap_starts[ci + 1] if ci + 1 < len(chap_starts) else len(part_slice)
            chap_slice = part_slice[cstart:cend].strip()
            chap_match = _RE_CHAPTER.search(chap_slice)
            chap_id = (chap_match.group(1) if chap_match else str(ci + 1)).upper()

            chap_name = ""
            for line in chap_slice.split("\n")[1:5]:
                if line and not _RE_ARTICLE.match(line) and not _RE_CHAPTER.match(line):
                    chap_name = line.strip()
                    break
            if not chap_name:
                chap_name = f"Chương {chap_id}"

            chapter = ChapterBlock(
                chapter_id=chap_id,
                name=chap_name,
                part_id=part.part_id,
            )

            art_matches = list(_RE_ARTICLE.finditer(chap_slice))
            for ai, am in enumerate(art_matches):
                aend = art_matches[ai + 1].start() if ai + 1 < len(art_matches) else len(chap_slice)
                body = chap_slice[am.start():aend].strip()
                num = am.group(1)
                title = (am.group(2) or "").strip()
                # Bỏ dòng tiêu đề khỏi body
                body = re.sub(
                    rf"^Điều\s+{re.escape(num)}\s*[\.\:,-]?\s*{re.escape(title)}\s*",
                    "",
                    body,
                    count=1,
                    flags=re.I,
                ).strip()
                chapter.articles.append(ArticleBlock(number=num, title=title, body=body))

            if chapter.articles:
                part.chapters.append(chapter)

        if part.chapters:
            parts.append(part)

    return parts


def structure_to_dataset(parts: list[PartBlock]) -> dict[str, Any]:
    out_parts: list[dict[str, Any]] = []
    for part in parts:
        chapters_json: list[dict[str, Any]] = []
        for ch in part.chapters:
            articles_json = [article_to_json(a) for a in ch.articles]
            chapters_json.append(
                {
                    "chapter_id": ch.chapter_id,
                    "name": ch.name,
                    "articles": articles_json,
                }
            )
        out_parts.append(
            {
                "part": {"part_id": part.part_id, "name": part.name},
                "chapters": chapters_json,
            }
        )
    return {"parts": out_parts}


def merge_part_files(paths: list[Path], out: Path) -> None:
    all_parts: list[dict[str, Any]] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        all_parts.extend(data.get("parts", []))
    out.write_text(
        json.dumps({"parts": all_parts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n_ch = sum(len(pt.get("chapters", [])) for pt in all_parts)
    n_art = sum(
        len(ch.get("articles", []))
        for pt in all_parts
        for ch in pt.get("chapters", [])
    )
    print(f"Đã gộp -> {out} | {len(all_parts)} phần, {n_ch} chương, {n_art} điều")


def print_stats(dataset: dict[str, Any]) -> None:
    for pt in dataset["parts"]:
        n_ch = len(pt["chapters"])
        n_art = sum(len(ch["articles"]) for ch in pt["chapters"])
        n_rules = sum(
            len(a["rules"])
            for ch in pt["chapters"]
            for a in ch["articles"]
        )
        print(
            f"  Phần {pt['part']['part_id']}: {pt['part']['name']} — "
            f"{n_ch} chương, {n_art} điều, {n_rules} quy tắc"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Xử lý PDF/văn bản BLHS -> JSON (local, không gọi API)",
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--pdf", default="P1 VB-Hop-nhat-BLHS-2025.pdf", help="File PDF đầu vào")
    src.add_argument("--text", help="File .txt đã trích từ PDF")
    p.add_argument("--out", default="blhs_parsed.json", help="File JSON đầu ra")
    p.add_argument("--part-id", type=int, choices=[1, 2], help="Chỉ xử lý một phần")
    p.add_argument("--article-from", type=int, help="Lọc từ Điều (số)")
    p.add_argument("--article-to", type=int, help="Lọc đến Điều (số)")
    p.add_argument("--merge-only", action="store_true", help="Gộp file part JSON")
    p.add_argument(
        "--parts",
        nargs="+",
        default=["deepseek_part1.json", "deepseek_part2.json"],
    )
    return p.parse_args()


def filter_dataset(
    dataset: dict[str, Any],
    part_id: int | None,
    article_from: int | None,
    article_to: int | None,
) -> dict[str, Any]:
    parts = dataset["parts"]
    if part_id:
        parts = [p for p in parts if p["part"]["part_id"] == part_id]

    if article_from is None and article_to is None:
        return {"parts": parts}

    filtered: list[dict[str, Any]] = []
    for pt in parts:
        chapters = []
        for ch in pt["chapters"]:
            arts = []
            for a in ch["articles"]:
                num = a["crime"]["article"]
                if article_from and num < article_from:
                    continue
                if article_to and num > article_to:
                    continue
                arts.append(a)
            if arts:
                chapters.append({**ch, "articles": arts})
        if chapters:
            filtered.append({**pt, "chapters": chapters})
    return {"parts": filtered}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()

    if args.merge_only:
        merge_part_files([Path(p) for p in args.parts], Path(args.out))
        return

    if args.text:
        text = clean_pdf_text(Path(args.text).read_text(encoding="utf-8"))
        print(f"Đọc text: {args.text}")
    else:
        pdf_path = Path(args.pdf)
        if not pdf_path.is_file():
            print(f"Không tìm thấy PDF: {pdf_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Đọc PDF: {pdf_path}")
        text = extract_pdf_text(pdf_path)

    print(f"  {len(text):,} ký tự")
    structure = split_structure(text)
    dataset = structure_to_dataset(structure)
    dataset = filter_dataset(dataset, args.part_id, args.article_from, args.article_to)

    out = Path(args.out)
    out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã ghi: {out.resolve()}")
    print_stats(dataset)


if __name__ == "__main__":
    main()
