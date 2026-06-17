from __future__ import annotations

from app.models.conversation import CaseStatus, MissingFactItem
from app.models.facts import ExtractedFacts
from app.services.clarifying_questions import user_declines_or_lacks_more_info
from app.utils.text import normalize_text


DRUG_ACTIONS = {"tàng trữ", "mua", "mua bán", "vận chuyển", "tổ chức sử dụng", "chứa chấp", "sử dụng", "cung cấp"}


def _is_drug_case(facts: ExtractedFacts, scenario: str) -> bool:
    norm = normalize_text(scenario)
    return bool(facts.substances or "ma tuy" in norm or "ketamin" in norm or "thuoc lac" in norm or "mdma" in norm)


def _has_forensic(facts: ExtractedFacts) -> bool:
    return any("giám định" in item for item in facts.evidence) or any(
        str(exhibit.forensic_status.value if hasattr(exhibit.forensic_status, "value") else exhibit.forensic_status) == "forensic_confirmed"
        for exhibit in facts.exhibits
    )


def _has_confirmed_exhibit_substance(facts: ExtractedFacts) -> bool:
    return any(exhibit.confirmed_substance and exhibit.confirmed_substance != "not_narcotic" for exhibit in facts.exhibits)


def _has_net_mass(facts: ExtractedFacts) -> bool:
    return any((quantity.unit or "").lower() in {"g", "gam", "kg", "mg"} and quantity.value is not None for quantity in facts.quantities)


def _has_role_info(facts: ExtractedFacts) -> bool:
    if len(facts.actors) < 2:
        return True
    return any(actor.role for actor in facts.actors) or any(action in facts.actions for action in ["rủ", "nhờ", "đặt phòng", "giúp sức", "xúi giục", "chủ mưu", "cầm đầu"])


def _has_purpose(facts: ExtractedFacts) -> bool:
    action_norms = {normalize_text(action) for action in facts.actions}
    return bool(facts.intent or {"su dung", "mua ban", "van chuyen", "to chuc su dung"} & action_norms)


def _drug_core_ready(facts: ExtractedFacts) -> bool:
    action_norms = {normalize_text(action) for action in facts.actions}
    has_action = bool(action_norms & {normalize_text(action) for action in DRUG_ACTIONS})
    has_exhibit_or_substitute = bool(facts.exhibits) or (_has_forensic(facts) and _has_net_mass(facts))
    return all([
        _has_confirmed_exhibit_substance(facts),
        _has_net_mass(facts),
        has_exhibit_or_substitute,
        _has_forensic(facts),
        has_action,
        _has_role_info(facts),
        _has_purpose(facts),
    ])


def _critical_from_text(item: str, facts: ExtractedFacts, scenario: str) -> bool:
    norm = normalize_text(item)
    if "tang vat va giam dinh" in norm or "hoat chat" in norm:
        return True
    if "ma tuy" in norm:
        if any(term in norm for term in ["giam dinh", "khoi luong", "ham luong", "so luong", "tang vat", "muc dich"]):
            return True
        if any(term in norm for term in ["cung cap", "to chuc", "su dung", "huong loi"]):
            return _is_drug_case(facts, scenario)
    if "dong pham" in norm or "vai tro" in norm:
        return True
    if "tuoi" in norm and "tung nguoi" in norm:
        return True
    if "lam san" in norm or "go" in norm:
        return True
    if "yeu to loi" in norm or "muc dich" in norm:
        return True
    return False


def _missing_key_label(text: str, idx: int) -> tuple[str, str]:
    norm = normalize_text(text)
    if "vien nen" in norm or "vien" in norm:
        return "exhibits.tablets.forensic_substance", "Hoạt chất của viên nén"
    if "goi bot" in norm or "nghi ketamine" in norm or "ketamine" in norm:
        return "exhibits.powder.forensic_substance", "Hoạt chất của gói bột"
    if "duong tinh" in norm:
        return "evidence.toxicology_result", "Kết quả xét nghiệm cơ thể người"
    if "khoi luong" in norm or "dinh luong" in norm or "ham luong" in norm:
        return "exhibits.drug_net_mass", "Khối lượng tịnh tang vật"
    if "tang vat" in norm:
        return "exhibits.status", "Tình trạng tang vật"
    if "loi" in norm or "muc dich" in norm:
        return "actors.mental_state", "Nhận thức và mục đích"
    if "vai tro" in norm or "dong pham" in norm:
        return "actors.roles", "Vai trò từng người"
    return f"missing_{idx + 1}", text.split(":", 1)[0]


def _question_matches_missing(key: str, question: str) -> bool:
    norm_question = normalize_text(question)
    if key == "exhibits.tablets.forensic_substance":
        return "vien" in norm_question or "vien nen" in norm_question
    if key == "exhibits.powder.forensic_substance":
        return "goi bot" in norm_question or "chat bot" in norm_question or "bot" in norm_question
    if key == "evidence.toxicology_result":
        return "duong tinh" in norm_question or "xet nghiem" in norm_question
    if key == "exhibits.drug_net_mass":
        return "khoi luong" in norm_question or "dinh luong" in norm_question or "gam" in norm_question
    if key == "exhibits.status":
        return "tang vat" in norm_question and not any(term in norm_question for term in ["hoat chat", "giam dinh"])
    if key == "actors.mental_state":
        return any(term in norm_question for term in ["biet", "nhan thuc", "muc dich"])
    if key == "actors.roles":
        return any(term in norm_question for term in ["vai tro", "dong pham"])
    return False


def _question_for_missing(key: str, clarifying_questions: list[str]) -> str | None:
    for question in clarifying_questions:
        if _question_matches_missing(key, question):
            return question
    return None


def to_missing_items(missing: list[str], clarifying_questions: list[str], facts: ExtractedFacts, scenario: str) -> list[MissingFactItem]:
    items: list[MissingFactItem] = []
    for idx, text in enumerate(missing):
        norm = normalize_text(text)
        tokens = set(norm.split())
        domain = "drug" if ("ma tuy" in norm or "tang vat va giam dinh" in norm) else "forestry" if ("lam san" in norm or "go" in tokens) else "general"
        key, label = _missing_key_label(text, idx)
        question = _question_for_missing(key, clarifying_questions)
        items.append(MissingFactItem(
            key=key,
            label=label,
            description=text,
            critical=_critical_from_text(text, facts, scenario),
            domain=domain,
            question=question,
        ))
    return items


def evaluate_answer_gate(
    facts: ExtractedFacts,
    scenario: str,
    missing: list[str],
    clarifying_questions: list[str],
) -> tuple[CaseStatus, list[MissingFactItem], list[str]]:
    missing_items = to_missing_items(missing, clarifying_questions, facts, scenario)
    warnings: list[str] = []
    if user_declines_or_lacks_more_info(scenario):
        warnings.append("Người dùng cho biết không có thêm thông tin; dừng hỏi lặp và chỉ phân tích giới hạn theo hồ sơ hiện có.")
        return CaseStatus.insufficient_information, missing_items, warnings

    if _is_drug_case(facts, scenario):
        if not _drug_core_ready(facts):
            warnings.append("Thiếu dữ kiện trọng yếu của nhóm tội ma túy; không chốt tội danh/khoản hoặc khung hình phạt.")
            return CaseStatus.collecting_facts, missing_items, warnings
        if missing_items:
            warnings.append("Dữ kiện cốt lõi của nhóm tội ma túy đã đủ để phân tích, nhưng vẫn còn điểm phụ cần nêu điều kiện.")
        return CaseStatus.ready_to_answer, missing_items, warnings

    if any(item.critical for item in missing_items):
        warnings.append("Còn dữ kiện trọng yếu; câu trả lời cuối cùng bị chặn để hỏi làm rõ.")
        return CaseStatus.collecting_facts, missing_items, warnings

    return CaseStatus.ready_to_answer, missing_items, warnings
