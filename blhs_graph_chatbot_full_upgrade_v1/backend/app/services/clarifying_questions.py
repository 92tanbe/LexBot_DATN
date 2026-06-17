from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.models.conversation import (
    ClarificationForm,
    ClarificationOption,
    ClarificationQuestion,
    FactPatch,
    IssuedQuestionSet,
)
from app.models.facts import ExtractedFacts
from app.services.slot_schema import ELECTRONIC_EVIDENCE_OPTIONS, FORENSIC_SUBSTANCE_OPTIONS, OptionTemplate
from app.utils.text import dedupe_keep_order, normalize_text


def _is_drug_related(facts: ExtractedFacts, scenario: str, missing: list[str]) -> bool:
    norm = normalize_text(scenario)
    return bool(
        facts.substances
        or "ma tuy" in norm
        or "thuoc lac" in norm
        or "ketamin" in norm
        or any(item.startswith("Ma túy:") for item in missing)
    )


def user_declines_or_lacks_more_info(scenario: str) -> bool:
    norm = normalize_text(scenario)
    return any(
        term in norm
        for term in [
            "toi khong biet",
            "minh khong biet",
            "khong biet them",
            "khong ro them",
            "khong co thong tin them",
            "khong nam duoc",
            "khong biet tang vat",
            "khong biet dinh luong",
            "khong ro dinh luong",
            "khong ro khoi luong",
        ]
    )


def build_clarifying_questions(facts: ExtractedFacts, scenario: str, missing: list[str]) -> list[str]:
    if not missing:
        return []
    if user_declines_or_lacks_more_info(scenario):
        return []

    questions: list[str] = []
    norm = normalize_text(scenario)
    action_norms = {normalize_text(action) for action in facts.actions}

    if _is_drug_related(facts, scenario, missing):
        structured = facts.structured_facts
        has_money_source = bool(structured.get("transactions.drug_purchase.money_source"))
        has_supplier_info = bool(structured.get("transactions.drug_purchase.supplier")) or any(
            term in norm for term in ["nguoi ban", "cung cap", "ban cho", "giao ma tuy", "tu doi tuong ten"]
        )
        has_benefit_info = (
            structured.get("transactions.drug_purchase.delivery_fee") is not None
            or any(path.endswith(".profit_or_benefit") for path in structured)
            or any(term in norm for term in ["phi giao hang", "tien cong", "chenh lech", "huong loi", "chia loi ich"])
        )
        exhibit_statuses = {exhibit.status for exhibit in facts.exhibits}
        no_exhibit_known = bool(exhibit_statuses & {"consumed", "not_seized"}) or any("không còn tang vật" in item for item in facts.evidence + facts.unknowns) or any(
            term in norm for term in ["khong con tang vat", "tieu thu het", "su dung het", "khong thu giu duoc"]
        )
        if not facts.exhibits and not no_exhibit_known:
            questions.append(
                "Tình trạng tang vật là trường hợp nào: đã tiêu thụ/sử dụng hết nên không còn hiện vật khi bị bắt, "
                "hay còn tang vật bị thu giữ?"
            )
        if not facts.quantities and not no_exhibit_known:
            questions.append(
                "Nếu còn tang vật bị thu giữ, khối lượng/hàm lượng cụ thể là bao nhiêu gam; hoặc số lượng bao nhiêu viên/gói?"
            )
        if no_exhibit_known:
            questions.append(
                "Nếu tang vật đã bị tiêu thụ hết hoặc không còn hiện vật, hiện có căn cứ nào khác không: xét nghiệm dương tính, "
                "lời khai, camera, tin nhắn, chuyển khoản hoặc người cung cấp?"
            )
        if not any("giám định" in item or "dương tính" in item for item in facts.evidence):
            questions.append("Đã có kết luận giám định xác định loại chất ma túy chưa?")
        if not has_money_source and not any(term in norm for term in ["nguoi mua", "mua cua ai", "mua tu ai"]):
            questions.append("Ai là người mua hoặc đặt mua chất ma túy?")
        if not has_supplier_info:
            questions.append("Ai là người bán, giao hoặc cung cấp chất ma túy?")
        if "to chuc su dung" not in action_norms:
            questions.append("Có ai rủ rê, chuẩn bị địa điểm, dụng cụ hoặc phân công người khác sử dụng ma túy không?")
        if not any(term in norm for term in ["su dung", "duong tinh"]):
            questions.append("Ai là người trực tiếp sử dụng hoặc bị xác định dương tính với ma túy?")
        if not facts.intent:
            questions.append("Mục đích giữ chất ma túy là để sử dụng, bán lại, vận chuyển hay mục đích khác?")
        if not has_benefit_info:
            questions.append("Có ai hưởng lợi, nhận tiền công hoặc được chia lợi ích từ việc mua bán/tổ chức sử dụng không?")

    if len(facts.actors) >= 2 and not any(actor.role for actor in facts.actors):
        questions.append("Vai trò cụ thể của từng người là gì: người khởi xướng, người mua, người bán, người giúp sức hay người sử dụng?")
    if facts.age_info and not facts.actors:
        questions.append("Tuổi cụ thể gắn với từng người trong tình huống là bao nhiêu?")
    if any("Yếu tố lỗi/mục đích" in item for item in missing):
        questions.append("Người thực hiện có biết rõ hành vi và hậu quả pháp lý của việc mình làm không?")

    return dedupe_keep_order(questions)


@dataclass
class _QuestionPlan:
    question: ClarificationQuestion
    option_patches: dict[str, list[FactPatch]]
    value_patches: list[FactPatch]
    priority: float


def _actor_id(name: str) -> str:
    return normalize_text(name).replace(" ", "_") or "actor"


def _options(options: tuple[OptionTemplate, ...]) -> list[ClarificationOption]:
    return [
        ClarificationOption(
            id=option.id,
            label=option.label,
            requires_value=option.requires_value,
            value_type=option.value_type,
            placeholder=option.placeholder,
        )
        for option in options
    ]


def _priority(
    *,
    critical: bool,
    legal_impact: float,
    uncertainty: float,
    information_gain: float,
    repetition_penalty: float = 0.0,
    unknown_answer_penalty: float = 0.0,
) -> float:
    criticality = 1.0 if critical else 0.35
    return (
        criticality * 0.35
        + legal_impact * 0.30
        + uncertainty * 0.20
        + information_gain * 0.15
        - repetition_penalty
        - unknown_answer_penalty
    )


def _is_drug_case(facts: ExtractedFacts, scenario: str) -> bool:
    norm = normalize_text(scenario)
    return bool(facts.substances or "ma tuy" in norm or "ketamin" in norm or "ketamine" in norm or "thuoc lac" in norm)


def _has_incident_time(facts: ExtractedFacts, scenario: str) -> bool:
    if facts.structured_facts.get("incident.time"):
        return True
    norm = normalize_text(scenario)
    return any(term in norm for term in ["ngay", "thang", "nam 20", "luc", "khoang", "hom qua"])


def _get_exhibit(facts: ExtractedFacts, exhibit_id: str):
    for exhibit in facts.exhibits:
        if exhibit.id == exhibit_id:
            return exhibit
    return None


def _has_confirmed_substance(facts: ExtractedFacts, exhibit_id: str) -> bool:
    exhibit = _get_exhibit(facts, exhibit_id)
    if exhibit and exhibit.confirmed_substance:
        return True
    value = facts.structured_facts.get(f"exhibits.{exhibit_id}.confirmed_substance")
    return bool(value and value not in {"unknown", "not_narcotic"})


def _has_quantity(facts: ExtractedFacts, exhibit_id: str) -> bool:
    exhibit = _get_exhibit(facts, exhibit_id)
    if exhibit and exhibit.quantity and exhibit.quantity.value is not None and (exhibit.quantity.unit or "").lower() in {"g", "gam", "kg", "mg"}:
        return True
    return facts.structured_facts.get(f"exhibits.{exhibit_id}.quantity.value") is not None


def _needs_forensic_question(facts: ExtractedFacts, scenario: str, exhibit_id: str) -> bool:
    exhibit = _get_exhibit(facts, exhibit_id)
    if exhibit and exhibit.confirmed_substance:
        return False
    status = facts.structured_facts.get(f"exhibits.{exhibit_id}.forensic_status")
    if status in {"forensic_confirmed", "denied", "not_available", "unknown"}:
        return False
    if exhibit_id == "tablets":
        return bool(exhibit) or any(term in normalize_text(scenario) for term in ["vien ma tuy", "thuoc lac", "vien nen", "ma tuy tong hop"])
    if exhibit_id == "powder":
        return bool(exhibit) or any(term in normalize_text(scenario) for term in ["goi nghi", "ketamin", "ketamine", "bot"])
    return False


def _forensic_option_patches(exhibit_id: str) -> dict[str, list[FactPatch]]:
    base = f"exhibits.{exhibit_id}"
    labels = {
        "mdma": "MDMA",
        "methamphetamine": "Methamphetamine",
        "ketamine": "Ketamine",
        "other": "__free_text__",
    }
    mappings: dict[str, list[FactPatch]] = {}
    for option_id, value in labels.items():
        mappings[option_id] = [
            FactPatch(path=f"{base}.confirmed_substance", value=value, evidence_source="forensic_report", confidence=0.97),
            FactPatch(path=f"{base}.forensic_status", value="forensic_confirmed", evidence_source="forensic_report", confidence=0.97),
            FactPatch(path="substances", value={"name": value, "confidence": 0.97, "evidence_source": "forensic_report"}, evidence_source="forensic_report", confidence=0.97, merge_strategy="append"),
        ]
    mappings["not_narcotic"] = [
        FactPatch(path=f"{base}.confirmed_substance", value="not_narcotic", evidence_source="forensic_report", confidence=0.97),
        FactPatch(path=f"{base}.forensic_status", value="denied", evidence_source="forensic_report", confidence=0.97),
    ]
    mappings["no_forensic_report"] = [
        FactPatch(path=f"{base}.forensic_status", value="not_available", evidence_source="user_statement", confidence=0.8),
        FactPatch(path="unknowns", value=f"Chưa có kết luận giám định cho tang vật {exhibit_id}.", confidence=0.8, merge_strategy="append"),
    ]
    mappings["unknown"] = [
        FactPatch(path=f"{base}.forensic_status", value="unknown", evidence_source="user_statement", confidence=0.7),
        FactPatch(path="unknowns", value=f"Người dùng không biết kết luận giám định cho tang vật {exhibit_id}.", confidence=0.7, merge_strategy="append"),
    ]
    return mappings


def _actor_options(facts: ExtractedFacts, include_other: bool = True) -> list[ClarificationOption]:
    options = [ClarificationOption(id=_actor_id(actor.name), label=actor.name) for actor in facts.actors]
    if include_other:
        options.append(ClarificationOption(id="other", label="Người khác", requires_value=True, value_type="text", placeholder="Nhập tên người liên quan"))
    options.append(ClarificationOption(id="unknown", label="Không rõ"))
    return options


def _actor_value_for_option(facts: ExtractedFacts, option_id: str) -> str:
    if option_id == "unknown":
        return "unknown"
    if option_id == "other":
        return "__free_text__"
    for actor in facts.actors:
        if _actor_id(actor.name) == option_id:
            return actor.name
    return option_id


def _requester_label(facts: ExtractedFacts) -> str:
    for actor in facts.actors:
        if "nguoi nho" in normalize_text(actor.role or ""):
            return actor.name
    return "người nhờ"


def _money_source_patches(facts: ExtractedFacts) -> dict[str, list[FactPatch]]:
    patches: dict[str, list[FactPatch]] = {}
    for option in _actor_options(facts):
        patches[option.id] = [
            FactPatch(path="transactions.drug_purchase.money_source", value=_actor_value_for_option(facts, option.id), confidence=0.85),
        ]
    return patches


def _knowledge_patches(actor_id: str) -> dict[str, list[FactPatch]]:
    base = f"actors.{actor_id}.mental_state"
    labels = {
        "no_knowledge": "Không biết mục đích sử dụng ma túy của người nhờ.",
        "knew_private_use": "Biết người nhờ mua/đặt phòng để tự sử dụng ma túy.",
        "knew_group_use": "Biết việc mua/đặt phòng để nhiều người cùng sử dụng ma túy.",
        "participated_in_arrangement": "Biết và cùng tham gia sắp xếp việc sử dụng ma túy.",
        "unknown": "Không rõ nhận thức của actor.",
    }
    return {
        option_id: [
            FactPatch(path=base, value=value, confidence=0.86),
            FactPatch(path="mental_state", value=f"{actor_id}: {value}", confidence=0.86, merge_strategy="append"),
        ]
        for option_id, value in labels.items()
    }


def _profit_patches(actor_id: str) -> dict[str, list[FactPatch]]:
    base = f"actors.{actor_id}.profit_or_benefit"
    labels = {
        "no_profit": "Không hưởng lợi, chỉ mua hộ/liên hệ hộ.",
        "received_fee": "Có nhận tiền công.",
        "price_difference": "Có hưởng chênh lệch giá.",
        "shared_drugs": "Được chia ma túy/lợi ích khác.",
        "unknown": "Không rõ có hưởng lợi hay không.",
    }
    return {option_id: [FactPatch(path=base, value=value, confidence=0.85)] for option_id, value in labels.items()}


def _has_answered(question_id: str, answered_question_ids: set[str], answered_unknown_question_ids: set[str]) -> bool:
    return question_id in answered_question_ids or question_id in answered_unknown_question_ids


def _build_question_set(
    *,
    case_id: str,
    case_version: int,
    plans: list[_QuestionPlan],
) -> tuple[ClarificationForm, IssuedQuestionSet]:
    question_set_id = f"qs-{uuid4()}"
    questions = [plan.question for plan in plans]
    issued = IssuedQuestionSet(
        question_set_id=question_set_id,
        case_id=case_id,
        case_version=case_version,
        questions=questions,
        option_patches={plan.question.id: plan.option_patches for plan in plans if plan.option_patches},
        value_patches={plan.question.id: plan.value_patches for plan in plans if plan.value_patches},
    )
    return ClarificationForm(question_set_id=question_set_id, questions=questions), issued


def build_structured_clarification(
    facts: ExtractedFacts,
    scenario: str,
    missing: list[str],
    *,
    case_id: str,
    case_version: int,
    answered_question_ids: set[str] | None = None,
    answered_unknown_question_ids: set[str] | None = None,
    max_questions: int = 5,
) -> tuple[ClarificationForm, IssuedQuestionSet]:
    answered_question_ids = answered_question_ids or set()
    answered_unknown_question_ids = answered_unknown_question_ids or set()
    if not missing or user_declines_or_lacks_more_info(scenario):
        return _build_question_set(case_id=case_id, case_version=case_version, plans=[])

    plans: list[_QuestionPlan] = []

    def add(plan: _QuestionPlan) -> None:
        if not _has_answered(plan.question.id, answered_question_ids, answered_unknown_question_ids):
            plans.append(plan)

    if _is_drug_case(facts, scenario) and not _has_incident_time(facts, scenario):
        question = ClarificationQuestion(
            id="q_incident_time",
            fact_path="incident.time",
            group="Thời điểm vụ việc",
            text="Vụ việc xảy ra vào ngày hoặc khoảng thời gian nào?",
            input_type="date",
            required=True,
            critical=True,
            allow_free_text=True,
            reason="Thời điểm có thể ảnh hưởng văn bản áp dụng, tuổi, thời hiệu và bối cảnh chứng cứ.",
            affected_articles=["249", "250", "251", "255", "256"],
        )
        add(_QuestionPlan(
            question=question,
            option_patches={},
            value_patches=[FactPatch(path="incident.time", value="__value__", confidence=0.85)],
            priority=_priority(critical=True, legal_impact=0.9, uncertainty=0.9, information_gain=0.75),
        ))

    for exhibit_id, text, reason in [
        (
            "powder",
            "Kết luận giám định xác định hoạt chất trong gói bột/chất bột bị thu giữ là chất nào?",
            "Mô tả về bột hoặc gói bột chưa thay thế kết luận giám định xác định hoạt chất.",
        ),
        (
            "tablets",
            "Kết luận giám định xác định hoạt chất trong hai viên nén là chất nào?",
            "Cụm 'ma túy tổng hợp' không tự động đồng nghĩa với MDMA; cần kết luận giám định.",
        ),
    ]:
        question_id = f"q_{exhibit_id}_forensic_substance"
        if _needs_forensic_question(facts, scenario, exhibit_id):
            question = ClarificationQuestion(
                id=question_id,
                fact_path=f"exhibits.{exhibit_id}.forensic_substance",
                group="Tang vật và giám định",
                text=text,
                input_type="single_choice",
                options=_options(FORENSIC_SUBSTANCE_OPTIONS),
                required=True,
                critical=True,
                allow_free_text=True,
                reason=reason,
                affected_articles=["249", "250", "251", "255"],
            )
            add(_QuestionPlan(
                question=question,
                option_patches=_forensic_option_patches(exhibit_id),
                value_patches=[],
                priority=_priority(critical=True, legal_impact=1.0, uncertainty=1.0, information_gain=0.95),
            ))

    for exhibit_id, label, depends_on in [
        ("powder", "Khối lượng tịnh của chất đã giám định trong gói bột là bao nhiêu gam?", "q_powder_forensic_substance"),
        ("tablets", "Tổng khối lượng tịnh của hoạt chất trong các viên nén là bao nhiêu gam?", "q_tablets_forensic_substance"),
    ]:
        question_id = f"q_{exhibit_id}_net_mass"
        if _has_confirmed_substance(facts, exhibit_id) and not _has_quantity(facts, exhibit_id):
            question = ClarificationQuestion(
                id=question_id,
                fact_path=f"exhibits.{exhibit_id}.quantity.value",
                group="Định lượng tang vật",
                text=label,
                input_type="number",
                required=True,
                critical=True,
                unit="g",
                min_value=0.0,
                reason="Định lượng là dữ kiện trọng yếu để đối chiếu ngưỡng cấu thành và khung hình phạt.",
                affected_articles=["249", "250", "251"],
                depends_on_question_id=depends_on,
                depends_on_option_ids=["mdma", "methamphetamine", "ketamine", "other"],
            )
            add(_QuestionPlan(
                question=question,
                option_patches={},
                value_patches=[FactPatch(path=f"exhibits.{exhibit_id}.quantity.value", value="__value__", evidence_source="forensic_report", confidence=0.95)],
                priority=_priority(critical=True, legal_impact=1.0, uncertainty=0.85, information_gain=0.9),
            ))

    if _is_drug_case(facts, scenario) and "transactions.drug_purchase.money_source" not in facts.structured_facts:
        question = ClarificationQuestion(
            id="q_money_source",
            fact_path="transactions.drug_purchase.money_source",
            group="Dòng tiền và mua ma túy",
            text="Ai là người đưa tiền hoặc nguồn tiền để mua ma túy?",
            input_type="single_choice",
            options=_actor_options(facts),
            required=True,
            critical=True,
            allow_free_text=True,
            reason="Nguồn tiền giúp phân biệt mua hộ, đồng phạm mua bán, cung cấp hoặc tổ chức sử dụng.",
            affected_articles=["249", "251", "255"],
        )
        add(_QuestionPlan(
            question=question,
            option_patches=_money_source_patches(facts),
            value_patches=[],
            priority=_priority(critical=True, legal_impact=0.85, uncertainty=0.85, information_gain=0.8),
        ))

    requester_label = _requester_label(facts)
    knowledge_options = [
        ClarificationOption(id="no_knowledge", label=f"Không biết {requester_label} sẽ sử dụng ma túy"),
        ClarificationOption(id="knew_private_use", label=f"Biết {requester_label} mua để tự sử dụng"),
        ClarificationOption(id="knew_group_use", label=f"Biết {requester_label} mua để nhiều người cùng sử dụng"),
        ClarificationOption(id="participated_in_arrangement", label="Biết và cùng tham gia sắp xếp việc sử dụng"),
        ClarificationOption(id="unknown", label="Không rõ"),
    ]
    for actor in facts.actors:
        actor_id = _actor_id(actor.name)
        role_norm = normalize_text(actor.role or "")
        if not any(term in role_norm for term in ["duoc nho", "dat phong"]):
            continue
        question_id = f"q_{actor_id}_knowledge"
        question = ClarificationQuestion(
            id=question_id,
            fact_path=f"actors.{actor_id}.mental_state",
            group="Nhận thức và vai trò",
            text=f"Khi đặt phòng hoặc liên hệ mua ma túy, {actor.name} biết mục đích của người nhờ ở mức nào?",
            input_type="single_choice",
            options=knowledge_options,
            required=True,
            critical=True,
            reason="Nhận thức và ý chí của từng actor quyết định có đồng phạm/tổ chức/cung cấp hay không.",
            affected_articles=["17", "251", "255"],
            actor_id=actor_id,
        )
        add(_QuestionPlan(
            question=question,
            option_patches=_knowledge_patches(actor_id),
            value_patches=[],
            priority=_priority(critical=True, legal_impact=0.92, uncertainty=0.9, information_gain=0.82),
        ))

    profit_options = [
        ClarificationOption(id="no_profit", label="Không hưởng lợi, chỉ mua hộ/liên hệ hộ"),
        ClarificationOption(id="received_fee", label="Có nhận tiền công"),
        ClarificationOption(id="price_difference", label="Có hưởng chênh lệch giá"),
        ClarificationOption(id="shared_drugs", label="Được chia ma túy hoặc lợi ích khác"),
        ClarificationOption(id="unknown", label="Không rõ"),
    ]
    for actor in facts.actors:
        actor_id = _actor_id(actor.name)
        role_norm = normalize_text(actor.role or "")
        if not any(term in role_norm for term in ["trung gian", "cung cap", "ban"]):
            continue
        question_id = f"q_{actor_id}_profit_or_benefit"
        if f"actors.{actor_id}.profit_or_benefit" in facts.structured_facts:
            continue
        question = ClarificationQuestion(
            id=question_id,
            fact_path=f"actors.{actor_id}.profit_or_benefit",
            group="Hưởng lợi",
            text=f"{actor.name} mua hộ/liên hệ hộ hay có nhận tiền công, chênh lệch hoặc lợi ích khác?",
            input_type="single_choice",
            options=profit_options,
            required=True,
            critical=True,
            reason="Hưởng lợi là dữ kiện quan trọng để phân biệt mua hộ với mua bán/cung cấp hoặc vai trò đồng phạm.",
            affected_articles=["251", "255"],
            actor_id=actor_id,
        )
        add(_QuestionPlan(
            question=question,
            option_patches=_profit_patches(actor_id),
            value_patches=[],
            priority=_priority(critical=True, legal_impact=0.83, uncertainty=0.82, information_gain=0.78),
        ))

    if _is_drug_case(facts, scenario) and "evidence.electronic" not in facts.structured_facts:
        question = ClarificationQuestion(
            id="q_electronic_evidence",
            fact_path="evidence.electronic",
            group="Chứng cứ",
            text="Có tin nhắn, chuyển khoản, cuộc gọi hoặc camera liên quan đến việc đặt phòng/mua/giao ma túy không?",
            input_type="multi_choice",
            options=_options(ELECTRONIC_EVIDENCE_OPTIONS),
            required=False,
            critical=False,
            reason="Chứng cứ điện tử hỗ trợ kiểm tra nguồn tiền, liên hệ mua bán, giao nhận và nhận thức của từng người.",
            affected_articles=["17", "251", "255"],
        )
        add(_QuestionPlan(
            question=question,
            option_patches={
                option.id: [FactPatch(path="evidence.electronic", value=option.id, evidence_source="electronic_evidence", confidence=0.8, merge_strategy="append")]
                for option in _options(ELECTRONIC_EVIDENCE_OPTIONS)
            },
            value_patches=[],
            priority=_priority(critical=False, legal_impact=0.65, uncertainty=0.75, information_gain=0.7),
        ))

    plans = sorted(plans, key=lambda plan: plan.priority, reverse=True)[:max_questions]
    return _build_question_set(case_id=case_id, case_version=case_version, plans=plans)
