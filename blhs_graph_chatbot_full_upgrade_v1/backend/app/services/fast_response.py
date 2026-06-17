from __future__ import annotations

import re

from app.utils.text import normalize_text

LEGAL_HINTS = [
    "blhs",
    "hinh su",
    "pham toi",
    "toi danh",
    "dieu",
    "khoan",
    "hinh phat",
    "ma tuy",
    "ketamin",
    "ketamine",
    "thuoc lac",
    "keo",
    "khay",
    "bay phong",
    "dong pham",
    "giup suc",
    "che giau",
    "khong to giac",
    "tuoi",
    "thuong tich",
    "go",
    "lam san",
    "rung",
]

SERVICE_CHECK_HINTS = [
    "alo alo",
    "test",
    "testing",
    "ping",
    "kiem tra",
    "thu xem",
    "bot oi",
    "con hoat dong",
    "co hoat dong",
    "dang hoat dong",
    "nghe ro",
    "ban co day",
    "ban o do",
    "are you there",
    "are you alive",
]


def _is_service_check(norm: str) -> bool:
    if re.fullmatch(r"(alo|alo alo|test|testing|ping|bot oi|hello bot|hi bot)", norm):
        return True
    return any(hint in norm for hint in SERVICE_CHECK_HINTS)


def detect_fast_response(text: str) -> dict | None:
    norm = normalize_text(text)
    if not norm:
        return {"kind": "empty", "answer": "Bạn hãy nhập tình huống hoặc điều luật cần tra cứu trong phạm vi BLHS."}
    if _is_service_check(norm):
        return {
            "kind": "service_check",
            "answer": (
                "Tôi ở đây và đang hoạt động. Tôi có thể hỗ trợ bạn tra cứu hoặc "
                "phân tích tình huống theo Bộ luật Hình sự Việt Nam."
            ),
        }
    if re.fullmatch(r"(xin chao|chao|hi|hello|alo)( ban| anh| chi| em)?", norm):
        return {"kind": "greeting", "answer": "Chào bạn. Mình hỗ trợ tra cứu và phân tích tình huống theo BLHS; bạn gửi tình huống cụ thể nhé."}
    if re.fullmatch(r"(cam on|thanks|thank you|ok cam on|da hieu).*", norm):
        return {"kind": "thanks", "answer": "Không có gì. Khi cần phân tích tình huống hình sự hoặc tra cứu điều luật BLHS, bạn cứ gửi tiếp."}
    if not any(hint in norm for hint in LEGAL_HINTS) and len(norm.split()) <= 12:
        return {"kind": "out_of_scope", "answer": "Mình chỉ hỗ trợ nội dung liên quan Bộ luật Hình sự. Câu này chưa đủ dấu hiệu để phân tích pháp lý hình sự."}
    return None
