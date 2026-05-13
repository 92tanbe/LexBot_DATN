"""Fast path cho cau hoi khong can chay RAG.

Module nay xu ly cac cau rat ngan nhu loi chao/cam on/tam biet va cac cau hoi
ngoai pham vi phap luat hinh su. Muc tieu la tra loi ngay, tranh goi NER,
Neo4j, reranker va LLM khi chac chan khong can retrieval.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from app.models.schemas import ChatResponse, ChatResponseDebug


@dataclass(frozen=True)
class FastIntent:
    kind: str
    answer: str


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s?]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _word_count(norm: str) -> int:
    return len([part for part in norm.split(" ") if part])


# Thong diep thong nhat: ngan, chuyen huong, khong tranh luan ngoai luat
_SCOPE_NOTICE = (
    "**Phạm vi chatbot:** chỉ hỗ trợ **phân tích tình huống** liên quan **Bộ luật Hình sự (BLHS)** "
    "và **tra cứu nhanh điều, khoản** trong BLHS. "
    "Câu không thuộc phạm vi này xin phép không trả lời chi tiết."
)

# Bat ngoai le nhe nhang truoc khi nhac pham vi + moi ho tro
_OUT_OF_SCOPE_BANTER = (
    "Mình đang “đeo kính BLHS” chứ không phải bản tin thời tiết hay hộp thư tình cảm nên với vài câu lạc đề "
    "thế này mình xin phép **né nhẹ** cho vui vậy thôi."
)

_HELP_INVITE_LINE = (
    "**Bạn cần hỗ trợ tìm kiếm hay phân tích gì không?** "
    "Cứ nhắn rõ (ví dụ **Điều/khoản**, **Chương**, hay **mô tả tình huống hình sự**)—**tôi sẽ giúp.**"
)


def _out_of_scope_answer() -> str:
    return f"{_OUT_OF_SCOPE_BANTER}\n\n{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}"


_LEGAL_TERMS = (
    "blhs",
    "bo luat hinh su",
    "luat hinh su",
    "phap luat",
    "toi gi",
    "toi danh",
    "pham toi",
    "cau thanh toi",
    "hinh phat",
    "khung hinh phat",
    "muc an",
    "di tu",
    "tu hinh",
    "chung than",
    "an treo",
    # Khong dua "dieu"/"khoan" đơn lẻ: de tranh tai khoan, triệu,... — dung regex trong _looks_like_article_or_clause_hint
    "dieu khoan",
    "dong pham",
    "chu muu",
    "giup suc",
    "xui giuc",
    "truy cuu",
    "trach nhiem hinh su",
    "hanh vi",
    "bi hai",
    "nan nhan",
    "giet",
    "cuop",
    "trom",
    "lua dao",
    "ma tuy",
    "danh bac",
    "bao hanh",
    "co y gay thuong tich",
    "vo y lam chet",
    "tham o",
    "nhan hoi lo",
)

_MAX_GREETING_WORDS = 10

_GREETING_LOOSE_FULLMATCH = (
    r"^(xin\s+)?chao(\s+[a-z0-9]+){0,6}(\s+(nhe|nha|nhi|oi|cac\s+ban|dong\s+chi)){0,2}$",
    r"^(hi|hello|hey|alo)(\s+[a-z0-9]+){0,4}$",
)

_GREETING_PATTERNS = (
    r"^(hi|hello|hey|alo|xin chao|chao|chao ban|chao anh|chao chi|chao em|ban oi|ad oi)$",
    r"^(buoi sang|buoi chieu|buoi toi) vui ve$",
)

_THANKS_PATTERNS = (
    r"^(cam on|cam on ban|thank|thanks|thank you|ok cam on|da hieu|hieu roi)$",
)

_GOODBYE_PATTERNS = (
    r"^(tam biet|bye|goodbye|hen gap lai|chao tam biet)$",
)

_ABOUT_PATTERNS = (
    r"^(ban la ai|ban lam duoc gi|ban co the lam gi|day la chatbot gi|chatbot nay lam gi)\??$",
)


def _matches_any(norm: str, patterns: tuple[str, ...]) -> bool:
    return any(re.match(pattern, norm) for pattern in patterns)


def _has_legal_signal(norm: str) -> bool:
    return any(term in norm for term in _LEGAL_TERMS)


def _looks_like_article_or_clause_hint(norm: str) -> bool:
    """Tranh chap nhan nham khi dong co nhac cu the dieu khoan."""
    return bool(re.search(r"\bdieu\s+\d{1,4}\b", norm) or re.search(r"\bkhoan\s+\d{1,2}\b", norm))


def _is_greeting(norm: str) -> bool:
    if _looks_like_article_or_clause_hint(norm):
        return False
    wc = _word_count(norm)
    if wc <= 8 and _matches_any(norm, _GREETING_PATTERNS):
        return True
    if wc > _MAX_GREETING_WORDS:
        return False
    return any(re.fullmatch(p, norm) for p in _GREETING_LOOSE_FULLMATCH)


def _is_thanks(norm: str) -> bool:
    wc = _word_count(norm)
    if wc > 12:
        return False
    if _looks_like_article_or_clause_hint(norm):
        return False
    if wc <= 8 and _matches_any(norm, _THANKS_PATTERNS):
        return True
    return bool(re.fullmatch(r"^cam\s+on(\s+[a-z0-9]+){0,6}$", norm))


def _is_goodbye(norm: str) -> bool:
    wc = _word_count(norm)
    if wc > 12 or _looks_like_article_or_clause_hint(norm):
        return False
    if wc <= 8 and _matches_any(norm, _GOODBYE_PATTERNS):
        return True
    return bool(re.fullmatch(r"^(tam\s+biet|bye|goodbye)(\s+[a-z0-9]+){0,5}$", norm))


# Them goi goi vu phap luat ngan (bo sung _LEGAL_TERMS) de khong ganh out-of-scope nham
_EXTRA_BLHS_SCENARIO_HINTS = (
    "hanh hung",
    "danh nhau",
    "gay thuong",
    "gay tu vong",
    "lua dao chiem doat",
    "bi khoi to",
    "bi bat",
)


def question_targets_blhs_content(question: str) -> bool:
    """True khi cau hoi lien quan tra cuu/phan tich BLHS (khong chap nhan chi tro chuyen/thoi tiet/doc)."""
    norm = _normalize(question)
    if not norm:
        return False
    if _looks_like_article_or_clause_hint(norm):
        return True
    if re.search(r"\bchuong\s+(\d{1,3}|[ivxlcdm]{1,10})\b", norm):
        return True
    if _has_legal_signal(norm):
        return True
    return any(term in norm for term in _EXTRA_BLHS_SCENARIO_HINTS)


def detect_fast_intent(
    question: str,
    *,
    skip_general_out_of_scope: bool = False,
) -> FastIntent | None:
    """Nhan dien cac cau co the tra loi nhanh ma khong can RAG."""
    norm = _normalize(question)
    if not norm:
        return FastIntent(
            kind="empty",
            answer=(
                f"Ơ, chưa thấy câu hỏi đâu cả—bạn thử gõ nội dung nhé.\n\n"
                f"{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}"
            ),
        )

    if _is_greeting(norm):
        return FastIntent(
            kind="greeting",
            answer=f"Chào bạn!\n\n{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}",
        )

    if _is_thanks(norm):
        return FastIntent(
            kind="thanks",
            answer=f"Cảm ơn bạn.\n\n{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}",
        )

    if _is_goodbye(norm):
        return FastIntent(
            kind="goodbye",
            answer=f"Tạm biệt bạn.\n\n{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}",
        )

    if _matches_any(norm, _ABOUT_PATTERNS):
        return FastIntent(
            kind="about",
            answer=f"{_SCOPE_NOTICE}\n\n{_HELP_INVITE_LINE}",
        )

    if question_targets_blhs_content(question):
        return None

    if skip_general_out_of_scope:
        return None

    return FastIntent(
        kind="out_of_scope",
        answer=_out_of_scope_answer(),
    )


def build_fast_response(
    question: str,
    include_debug: bool = False,
    *,
    skip_general_out_of_scope: bool = False,
) -> ChatResponse | None:
    """Tra ChatResponse nhanh neu cau hoi thuoc fast path."""
    t0 = time.time()
    intent = detect_fast_intent(question, skip_general_out_of_scope=skip_general_out_of_scope)
    if intent is None:
        return None

    debug = None
    if include_debug:
        debug = ChatResponseDebug()
        debug.timings_ms["fast_path_ms"] = round((time.time() - t0) * 1000, 1)
        debug.warnings.append(f"fast_path:{intent.kind}")

    return ChatResponse(
        question=question,
        final_answer=intent.answer,
        structured={
            "type": "fast_response",
            "intent": intent.kind,
            "handled_by": "rule_based_fast_path",
        },
        citations=[],
        confidence="high",
        debug=debug,
    )
