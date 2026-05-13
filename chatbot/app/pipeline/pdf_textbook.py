"""Tra cứu nội dung BLHS trực tiếp từ file PDF VB hợp nhất.

Dùng cho chế độ ``tra_cuu_pdf``: trích các phần theo Điều, Chương hoặc tìm khớp
từ khoá đơn giản trong toàn văn, không đi qua Neo4j / reranker / pipeline phân tích.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from app.core.config import settings
from app.models.schemas import ChatResponse, ChatResponseDebug, Citation
from app.pipeline.fast_response import build_fast_response, question_targets_blhs_content

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache_text: str | None = None
_cache_path_mtime: tuple[Path, float | None] | None = None

# Repo root = thư mục chứa `app/` (vd .../chatbot)
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DIEU_HEADER = re.compile(
    r"(?m)^(Điều|ĐIỀU)\s+(\d{1,4})\s*[\.:,-]?\s*",
)

_CHUONG_HEADER = re.compile(
    r"(?m)^(CHƯƠNG|Chương|CHUONG)\s+([IVXLCDMivxlcdm\d]+)(?:[^\n]*)",
)


def _normalize_query(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t)


def _normalize_article_text(raw: str) -> str:
    """Chuan hoa van ban dai (bo dau tieng viet) cho tim tu khoa."""
    flattened = raw.replace("\n", " ").replace("\r", " ")
    return _normalize_query(flattened)


def roman_to_int(roman: str) -> int | None:
    roman = roman.strip().upper()
    if roman.isdigit():
        return int(roman)
    if not roman or not set(roman).issubset(set("IVXLCDM")):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(roman):
        v = values.get(ch)
        if v is None:
            return None
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total if total > 0 else None


def _resolve_pdf_path() -> Path:
    raw = (settings.blhs_pdf_path or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (_REPO_ROOT / p).resolve()
        return p
    return (_REPO_ROOT / "dataset" / "P1 VB-Hop-nhat-BLHS-2025.pdf").resolve()


def extract_pdf_plain_text(path: Path) -> str:
    """Trích full text từ PDF (lazy import pypdf)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - môi trường thiếu gói
        raise RuntimeError(
            "Cần gói pypdf để đọc PDF. Chạy: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(parts)


def load_blhs_pdf_text() -> tuple[str, Path]:
    """Đọc (và cache) toàn văn PDF đã chỉnh định trong cấu hình."""
    global _cache_text, _cache_path_mtime

    path = _resolve_pdf_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None

    with _lock:
        if _cache_text is not None and _cache_path_mtime == (path, mtime):
            return _cache_text, path

        if not path.is_file():
            raise FileNotFoundError(path)

        logger.info("Đang đọc PDF BLHS: %s", path)
        text = extract_pdf_plain_text(path)
        _cache_text = text
        _cache_path_mtime = (path, mtime)
        return text, path


@dataclass
class ChuongSpan:
    index_from_one: int
    heading: str
    body: str


@dataclass
class DieuSpan:
    article: int
    body: str


def split_chapters(full_text: str) -> list[ChuongSpan]:
    starts = sorted(match.start() for match in _CHUONG_HEADER.finditer(full_text))
    if not starts:
        return []

    out: list[ChuongSpan] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(full_text)
        slice_ = full_text[start:end].strip()
        first_line = slice_.split("\n", 1)[0].strip()
        out.append(ChuongSpan(index_from_one=i + 1, heading=first_line, body=slice_))

    return out


def split_articles(full_text: str) -> dict[int, DieuSpan]:
    matches = list(_DIEU_HEADER.finditer(full_text))
    articles: dict[int, DieuSpan] = {}

    if not matches:
        return {}

    for i, m in enumerate(matches):
        article_num = int(m.group(2))
        body_start = m.start()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[body_start:body_end].strip()
        if article_num not in articles:
            articles[article_num] = DieuSpan(article=article_num, body=body)

    return articles


def parse_article_refs_from_question(question: str) -> list[int]:
    """Điều được nêu rõ trong câu (hỗ trợ nhiều Điều)."""
    numbers: list[int] = []

    patterns = (
        r"(?:Điều|ĐIỀU|dieu)\s+(\d{1,4})",
        r"(?:Điều|ĐIỀU|dieu)\s*(\d{1,4})",
        r"\bĐ\s*(\d{1,4})\b",
    )

    lowered = question
    seen: set[int] = set()

    for pat in patterns:
        for m in re.finditer(pat, lowered, flags=re.IGNORECASE):
            n = int(m.group(1))
            if n not in seen and 1 <= n <= 4999:
                seen.add(n)
                numbers.append(n)

    numbers.sort()
    return numbers[:6]


def _chapter_number_from_heading(heading: str) -> int | None:
    heading_norm = _normalize_query(heading)
    mo = re.search(r"chuong\s+(\d+)\b", heading_norm)
    if mo:
        return int(mo.group(1))

    mr = re.search(r"chuong\s+([ivxlcdm]+)\b", heading_norm)
    if mr:
        return roman_to_int(mr.group(1))

    prefix = heading.split("\n", 1)[0]
    arabic_space = re.search(r"(?:CHƯƠNG|Chương)\s+(\d+)", prefix)
    if arabic_space:
        return int(arabic_space.group(1))

    roman_inline = re.search(
        r"(?:CHƯƠNG|Chương)\s+([IVXLCDM]{1,6})\b",
        prefix,
        flags=re.IGNORECASE,
    )
    if roman_inline:
        return roman_to_int(roman_inline.group(1))

    return None


def find_chapters_for_question(question: str, chapters: list[ChuongSpan]) -> list[ChuongSpan]:
    if not chapters:
        return []

    qn = _normalize_query(question)
    chosen: list[ChuongSpan] = []

    # Vị trí số arabic trong câu: "chương 15"
    for m in re.finditer(r"chuong\s+(\d+)\b", qn):
        idx = int(m.group(1))
        if 1 <= idx <= len(chapters):
            chosen.append(chapters[idx - 1])

    # Số La Mã trong câu: "chương iii"
    for m in re.finditer(r"chuong\s+([ivxlcdm]+)\b", qn):
        val = roman_to_int(m.group(1))
        if val is None:
            continue

        matched = []
        for ch in chapters:
            nh = _chapter_number_from_heading(ch.heading)
            if nh == val:
                matched.append(ch)

        if len(matched) == 1:
            chosen.extend(matched)
        elif matched:
            shortest = min(matched, key=lambda c: len(c.body))
            chosen.append(shortest)

    dedup_keys: set[int] = set()
    out: list[ChuongSpan] = []

    def _chapter_key(entry: ChuongSpan) -> int:
        num = _chapter_number_from_heading(entry.heading)
        return num if num is not None else entry.index_from_one

    for ch in chosen:
        ky = _chapter_key(ch)
        if ky not in dedup_keys:
            dedup_keys.add(ky)
            out.append(ch)

    return out[:2]


def _tokens_for_keyword_search(question: str) -> list[str]:
    qn = _normalize_query(question)
    chunks = [t for t in re.split(r"[^\w]+", qn) if t]
    stop = {
        "la",
        "nhung",
        "thi",
        "hoac",
        "va",
        "voi",
        "cua",
        "cac",
        "mot",
        "may",
        "nao",
        "gi",
        "the",
        "ve",
        "trong",
        "toi",
        "ban",
        "cho",
        "duoc",
        "khong",
    }
    return list({x for x in chunks if len(x) > 2 and x not in stop})


def _keyword_best_articles(
    question: str,
    articles: dict[int, DieuSpan],
    *,
    limit: int = 3,
) -> list[int]:
    toks = _tokens_for_keyword_search(question)
    if not toks or not articles:
        return []

    scores: dict[int, int] = {}

    lowered_cache: dict[int, str] = {
        aid: _normalize_article_text(body.body) for aid, body in articles.items()
    }

    for aid, low in lowered_cache.items():
        score = 0
        for t in toks:
            score += low.count(t)
        if score > 0:
            scores[aid] = score

    ranked = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return ranked[:limit]


_MAX_SNIPPET = 900
_MAX_REPLY_CHARS = 14_000


def _truncate_block(text: str, limit: int) -> tuple[str, bool]:
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed, False
    return trimmed[:limit].rsplit("\n", 1)[0] + "\n\n[…văn bản bị cắt bớt trong phản hồi]", True


def _build_citations_from_articles(parts: Iterable[DieuSpan]) -> list[Citation]:
    cites: list[Citation] = []
    for ds in parts:
        first_lines = ds.body.split("\n")[:4]
        title_guess = " ".join(part.strip() for part in first_lines if part.strip())[:260]
        snip = ds.body[: _MAX_SNIPPET]
        cites.append(
            Citation(
                article=ds.article,
                clause=None,
                rule_id=None,
                ten_toi=title_guess[:200] or f"Điều {ds.article}",
                snippet=snip[:400],
            )
        )
    return cites


def run_pdf_lookup_pipeline(
    question: str,
    include_debug: bool = False,
) -> ChatResponse:
    """Đường tra cứu PDF nhanh: chào hỏi / Điều / Chương / từ khóa."""
    t0 = time.time()
    timings: dict[str, float] = {}

    fast = build_fast_response(
        question,
        include_debug=False,
        skip_general_out_of_scope=True,
    )
    if fast is not None:
        timings["pdf_fast_path_ms"] = round((time.time() - t0) * 1000, 1)
        out = ChatResponse(
            question=question,
            final_answer=fast.final_answer,
            structured={
                **fast.model_dump()["structured"],
                "pdf_mode": True,
                "source": settings.blhs_pdf_path or "dataset/P1 VB-Hop-nhat-BLHS-2025.pdf",
            },
            citations=[],
            confidence="high",
            debug=None,
        )
        if include_debug:
            dbg = ChatResponseDebug()
            dbg.timings_ms = timings
            dbg.warnings.append("pdf_lookup:chat_fast_path")
            out = out.model_copy(update={"debug": dbg})
        return out

    if not question_targets_blhs_content(question):
        gated = build_fast_response(
            question,
            include_debug=False,
            skip_general_out_of_scope=False,
        )
        if gated is not None:
            timings["pdf_scope_gate_ms"] = round((time.time() - t0) * 1000, 1)
            out = ChatResponse(
                question=question,
                final_answer=gated.final_answer,
                structured={
                    **gated.model_dump()["structured"],
                    "pdf_mode": True,
                    "source": settings.blhs_pdf_path or "dataset/P1 VB-Hop-nhat-BLHS-2025.pdf",
                    "scope_gate": "blhs_only",
                },
                citations=[],
                confidence="high",
                debug=None,
            )
            if include_debug:
                dbg = ChatResponseDebug()
                dbg.timings_ms = timings
                dbg.warnings.append("pdf_lookup:scope_rejected")
                out = out.model_copy(update={"debug": dbg})
            return out

    try:
        raw_text, path = load_blhs_pdf_text()
    except FileNotFoundError as missing:
        timings["pdf_error_ms"] = round((time.time() - t0) * 1000, 1)
        msg = (
            f"Chưa tìm thấy file PDF tại `{missing}`. "
            "Hãy đặt file `P1 VB-Hop-nhat-BLHS-2025.pdf` vào thư mục `dataset/` "
            "hoặc chỉnh biến môi trường `BLHS_PDF_PATH`."
        )
        dbg = ChatResponseDebug() if include_debug else None
        if dbg:
            dbg.timings_ms = timings
            dbg.warnings.append(f"pdf_not_found:{missing}")
        return ChatResponse(
            question=question,
            final_answer=msg,
            structured={
                "type": "pdf_lookup_error",
                "reason": "file_not_found",
                "expected_path": str(missing),
            },
            citations=[],
            confidence="low",
            debug=dbg,
        )

    except RuntimeError as exc:
        timings["pdf_error_ms"] = round((time.time() - t0) * 1000, 1)
        dbg = ChatResponseDebug() if include_debug else None
        if dbg:
            dbg.timings_ms = timings
            dbg.warnings.append(str(exc))
        return ChatResponse(
            question=question,
            final_answer=str(exc),
            structured={"type": "pdf_lookup_error", "reason": "dependency"},
            citations=[],
            confidence="low",
            debug=dbg,
        )

    chapters = split_chapters(raw_text)
    articles = split_articles(raw_text)

    matched_type = "keyword"
    final_blocks: list[str] = []

    refs = parse_article_refs_from_question(question)

    spans: list[DieuSpan] = []

    if refs:
        matched_type = "article"
        for num in refs:
            piece = articles.get(num)
            if piece:
                spans.append(piece)
            else:
                final_blocks.append(
                    f"*Không tìm thấy văn bản của **Điều {num}** trong PDF (có thể do bố cục trích sai hoặc số khác).*"
                )
    else:
        chapter_hits = find_chapters_for_question(question, chapters)
        if chapter_hits:
            matched_type = "chapter"
            for ch in chapter_hits:
                block, clipped = _truncate_block(ch.body, _MAX_REPLY_CHARS // max(len(chapter_hits), 1))
                hdr = "**" + ch.heading.strip() + "**"
                suffix = "_ (phần dài được cắt bớt)_" if clipped else ""
                final_blocks.append(f"{hdr}\n\n{block}{suffix}")

    citation_parts = list(spans)

    keyword_rank_ids: list[int] = []

    # Chưa trích được Điều cụ thể và không vào nhánh Chương → tìm theo từ khoá
    if not citation_parts and matched_type != "chapter":
        keyword_rank_ids = _keyword_best_articles(question, articles)
        if keyword_rank_ids:
            matched_type = "keyword_article"
            for aid in keyword_rank_ids:
                body = articles[aid].body
                block, clipped = _truncate_block(body, _MAX_REPLY_CHARS // len(keyword_rank_ids))
                hdr = f"**Điều {aid}** _(khớp từ khoá trong PDF)_"
                suffix = "_ (đoạn được cắt bớt)_" if clipped else ""
                final_blocks.append(hdr + "\n\n" + block + suffix)

    cites_out: list[Citation] = []

    if citation_parts:
        citation_parts = citation_parts[:3]
        cites_out.extend(_build_citations_from_articles(citation_parts))

        assembled: list[str] = []
        per_limit = max(_MAX_REPLY_CHARS // len(citation_parts), 2048)

        for ds in citation_parts:
            block, clipped = _truncate_block(ds.body, per_limit)
            first_line_end = block.find("\n")
            if first_line_end == -1:
                hdr_line = "**" + block.strip() + "**"
                body_rest = ""
            else:
                hdr_line = "**" + block[:first_line_end].strip() + "**"
                body_rest = block[first_line_end + 1 :].strip()

            suffix = "_ (đoạn được cắt bớt)_" if clipped else ""
            paragraph = hdr_line + ("\n\n" + body_rest if body_rest else "") + suffix
            assembled.append(paragraph)

        final_blocks.extend(assembled)

    keyword_spans = [articles[aid] for aid in keyword_rank_ids if aid in articles]

    if keyword_spans and not cites_out:
        cites_out = _build_citations_from_articles(keyword_spans[:3])

    if not final_blocks:
        matched_type = "no_match"
        final_blocks.append(
            "Không nhận diện được **Điều / Chương** trong câu hỏi và không có từ khoá nào "
            "trùng trong PDF. "
            "Hãy thử ví dụ: `Điều 123 nói về điều gì?` hoặc `Trích **Chương III**`."
        )

    answer = (
        "(Theo VB hợp nhất BLHS — trích trong file PDF của dự án)\n\n"
        + "\n\n---\n\n".join(final_blocks)
    )
    answer, clipped_total = _truncate_block(answer, _MAX_REPLY_CHARS + 512)

    debug = ChatResponseDebug() if include_debug else None
    timings["pdf_lookup_ms"] = round((time.time() - t0) * 1000, 1)

    structured: dict = {
        "type": "pdf_lookup",
        "matched_as": matched_type,
        "source_file": str(path),
        "articles_explicit": refs,
        "answer_truncated": clipped_total,
    }

    if cites_out:
        structured["preview_articles"] = [c.article for c in cites_out]

    if debug is not None:
        debug.timings_ms = timings
        debug.warnings.append(f"pdf_lookup:{matched_type}")

    if matched_type == "article" and cites_out:
        conf: Literal["high", "medium", "low"] = "high"
    elif matched_type in {"chapter", "keyword_article"}:
        conf = "medium"
    elif matched_type != "no_match":
        conf = "medium"
    else:
        conf = "low"

    return ChatResponse(
        question=question,
        final_answer=answer,
        structured=structured,
        citations=cites_out,
        confidence=conf,
        debug=debug,
    )
