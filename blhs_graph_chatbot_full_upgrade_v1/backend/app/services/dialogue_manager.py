from __future__ import annotations

import logging

from fastapi import HTTPException

from app.core.config import settings
from app.models.conversation import (
    CaseSession,
    CaseStatus,
    ClarificationAnswer,
    ClarificationQuestion,
    ConversationTurn,
    FactPatch,
    IssuedQuestionSet,
    LegalChatResponse,
    ProvisionalFinding,
)
from app.services.answer_gate import evaluate_answer_gate
from app.services.answer_generator import generate_answer
from app.services.article_lookup import build_general_article_lookup, build_selected_article_answer, is_general_penalty_lookup
from app.services.clarifying_questions import build_clarifying_questions, build_structured_clarification
from app.services.fact_extractor import extract_facts
from app.services.fact_merger import apply_fact_patches, merge_facts
from app.services.input_understanding import InputUnderstanding, understand_input
from app.services.legal_matcher import detect_missing_facts
from app.services.legal_pipeline import run_legal_analysis
from app.services.session_store import session_store
from app.services.validator import validate_answer
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)


def _append_message(existing: str, message: str) -> str:
    if not message:
        return existing
    if not existing:
        return message
    return f"{existing}\n{message}"


def _collecting_answer(questions: list[str], warnings: list[str], provisional_summary: str | None = None) -> str:
    lines = ["Chưa đủ dữ kiện để kết luận cuối cùng."]
    if provisional_summary:
        lines.append(provisional_summary)
    if warnings:
        lines.append("Vì còn thiếu dữ kiện trọng yếu, mình chưa chốt tội danh/khoản hoặc khung hình phạt.")
    if questions:
        lines.append("Cần làm rõ:")
        lines.extend(f"{idx}. {question}" for idx, question in enumerate(questions[:8], start=1))
    else:
        lines.append("Hiện chưa có thêm thông tin để hỏi tiếp; chỉ có thể ghi nhận vụ việc ở mức sơ bộ.")
    lines.append("Phân tích dưới đây, nếu có, chỉ là tham khảo và không thay thế kết luận của cơ quan có thẩm quyền.")
    return "\n".join(lines)


def _provisional_from_missing(missing: list[str]) -> list[ProvisionalFinding]:
    if not missing:
        return []
    return [
        ProvisionalFinding(
            status="insufficient_evidence",
            text="Chưa đủ dữ kiện trọng yếu để chuyển giả thuyết pháp lý thành kết luận.",
            confidence=0.2,
        )
    ]


def _provisional_article_codes(facts, scenario: str) -> list[str]:
    norm = normalize_text(scenario)
    action_norms = {normalize_text(action) for action in facts.actions}
    object_norm = normalize_text(" ".join(facts.objects))
    codes: list[str] = []
    if any(term in norm for term in ["ban thang", "no sung", "sung ak", "trung dan", "hy sinh", "chet nguoi", "tu vong"]):
        codes.append("123")
    if any(term in norm for term in ["sung ak", "hop tiep dan", "luu dan", "vu khi quan dung"]) or "vu khi quan dung" in object_norm:
        codes.append("304")
    if any(term in norm for term in ["lam hu hong xe", "hu hong xe", "thiet hai tai san", "lam hu hong tai san"]):
        codes.append("178")
    if "to chuc su dung" in action_norms or "to chuc su dung" in norm:
        codes.append("255")
    has_buy_sell_drug = {"mua", "mua ban"} & action_norms or any(term in norm for term in ["mua ma tuy", "mua ban ma tuy", "giao ma tuy", "cung cap ma tuy", "giao dich ma tuy", "duong day mua ban", "tieu thu"])
    if ("van chuyen" in action_norms or "van chuyen ma tuy" in norm) and not has_buy_sell_drug:
        codes.append("250")
    if has_buy_sell_drug:
        codes.append("251")
    if "su dung" in action_norms or any(term in norm for term in ["su dung ma tuy", "duong tinh"]):
        codes.append("256a")
    if "tang tru" in action_norms or any(term in norm for term in ["cat giu ma tuy", "giu ma tuy", "mua ma tuy"]):
        codes.append("249")
    return list(dict.fromkeys(codes))


def _filter_by_article_codes(items, preferred_codes: list[str]):
    if not preferred_codes:
        return list(items)
    rank = {code: idx for idx, code in enumerate(preferred_codes)}

    def code_of(item) -> str:
        return str(getattr(item, "article_code", "") or "")

    filtered = [item for item in items if code_of(item) in rank]
    return sorted(filtered, key=lambda item: rank.get(code_of(item), 999)) if filtered else list(items)


def _is_analysis_mode(mode: str) -> bool:
    return str(mode or "").lower() in {"agentic", "thinking"}


def _context_dicts(analysis) -> list[dict]:
    contexts = getattr(analysis, "legal_contexts", None) or []
    return [
        context.model_dump() if hasattr(context, "model_dump") else context
        for context in contexts
        if context is not None
    ]


def _provisional_from_reasoning(reasoning, preferred_codes: list[str] | None = None) -> list[ProvisionalFinding]:
    findings: list[ProvisionalFinding] = []
    primary_items = [item for item in reasoning if item.classification == "crime_candidate"] or list(reasoning)
    primary_items = _filter_by_article_codes(primary_items, preferred_codes or [])
    for item in primary_items[:5]:
        status = item.finding_status
        if status == "insufficient_evidence" and item.classification == "crime_candidate":
            status = "possible_hypothesis"
        title = f"Điều {item.article_code} - {item.title}" if item.article_code else item.title
        text = f"{title}: có dấu hiệu cần đối chiếu theo dữ kiện hiện có từ tình huống và graph Neo4j."
        if item.crime_name and item.crime_name not in text:
            text += f" Tội danh ứng viên: {item.crime_name}."
        if item.missing_elements:
            missing_preview = [element.rstrip(". ") for element in item.missing_elements[:3]]
            text += " Chưa chốt vì còn thiếu: " + "; ".join(missing_preview) + "."
        findings.append(ProvisionalFinding(
            status=status,
            text=text,
            affected_articles=[item.article_code],
            confidence=item.confidence,
        ))
    return findings


def _provisional_summary(findings: list[ProvisionalFinding]) -> str | None:
    if not findings:
        return None
    lines = ["Nhận định tạm thời từ dữ liệu Neo4j:"]
    for finding in findings[:3]:
        lines.append(f"- {finding.text}")
    lines.append("Đây là hướng pháp lý cần kiểm tra tiếp, chưa phải kết luận cuối cùng về tội danh/khoản/khung hình phạt.")
    return "\n".join(lines)


def _run_provisional_analysis(
    scenario_text: str,
    facts,
    top_k: int,
    include_debug: bool,
    answer_style: str,
):
    if not settings.use_provisional_neo4j_analysis or not scenario_text.strip():
        return None
    try:
        return run_legal_analysis(
            scenario=scenario_text,
            facts=facts,
            top_k=top_k,
            include_debug=include_debug,
            answer_style=answer_style,
            generate_final_answer=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Provisional Neo4j analysis skipped: %s", exc)
        return None


def _response_from_quick_understanding(
    session: CaseSession,
    message: str,
    understanding: InputUnderstanding,
    include_debug: bool,
) -> LegalChatResponse:
    session.version += 1
    session.status = CaseStatus.answered
    extracted = session.facts.__class__()
    turn = ConversationTurn(
        user_message=message,
        extracted_facts=extracted,
        bot_response_summary=(understanding.quick_answer or "")[:300],
    )
    session.turns.append(turn)
    session_store.save(session)
    return LegalChatResponse(
        case_id=session.case_id,
        case_version=session.version,
        status=CaseStatus.answered,
        facts=session.facts,
        provisional_findings=[],
        missing_facts=[],
        clarification=None,
        clarifying_questions=[],
        final_answer=understanding.quick_answer or "",
        confidence=0.95 if understanding.scope in {"greeting", "service_check", "thanks", "empty"} else 0.7,
        warnings=[f"input_scope:{understanding.scope}"],
        debug={"input_understanding": understanding.model_dump()} if include_debug else None,
    )


def _response_from_analysis(session: CaseSession, analysis, status: CaseStatus, debug: dict | None = None) -> LegalChatResponse:
    merged_debug = analysis.debug
    if debug:
        merged_debug = {**(merged_debug or {}), **debug}
    return LegalChatResponse(
        case_id=session.case_id,
        case_version=session.version,
        status=status,
        facts=analysis.facts,
        provisional_findings=_provisional_from_reasoning(analysis.legal_reasoning),
        missing_facts=[],
        clarification=None,
        clarifying_questions=analysis.clarifying_questions,
        candidate_articles=analysis.candidate_articles,
        legal_reasoning=analysis.legal_reasoning,
        final_answer=analysis.final_answer,
        confidence=analysis.confidence,
        citations=analysis.citations,
        warnings=analysis.warnings + ["Phân tích tham khảo; không thay thế kết luận của cơ quan có thẩm quyền."],
        debug=merged_debug,
    )


def _load_session(case_id: str | None, has_answers: bool) -> CaseSession:
    if has_answers:
        if not case_id:
            raise HTTPException(status_code=400, detail="answers yêu cầu case_id hiện có")
        session = session_store.get(case_id)
        if not session:
            raise HTTPException(status_code=404, detail="case_id không tồn tại hoặc session đã hết hạn")
        return session
    return session_store.get_or_create(case_id)


def _validate_case_version(session: CaseSession, case_version: int | None) -> None:
    if case_version is None:
        return
    if case_version != session.version:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "case_version_conflict",
                "message": "case_version của client không khớp version hiện tại của vụ việc",
                "current_case_version": session.version,
                "request_case_version": case_version,
            },
        )


def _find_issued_question(session: CaseSession, question_id: str) -> tuple[IssuedQuestionSet, ClarificationQuestion] | None:
    for question_set in reversed(session.issued_question_sets):
        for question in question_set.questions:
            if question.id == question_id:
                return question_set, question
    return None


def _validate_answer_shape(question: ClarificationQuestion, answer: ClarificationAnswer) -> None:
    option_ids = {option.id for option in question.options}
    selected = answer.selected_option_ids
    if question.input_type == "single_choice" and len(selected) > 1:
        raise HTTPException(status_code=422, detail=f"{question.id}: single_choice chỉ được chọn một option")
    if question.input_type in {"single_choice", "multi_choice", "boolean"}:
        invalid = [option_id for option_id in selected if option_id not in option_ids]
        if invalid:
            raise HTTPException(status_code=422, detail=f"{question.id}: option không hợp lệ: {', '.join(invalid)}")
        if question.required and not selected:
            raise HTTPException(status_code=422, detail=f"{question.id}: câu hỏi bắt buộc phải có option")
    if question.input_type == "number":
        if answer.value is None:
            raise HTTPException(status_code=422, detail=f"{question.id}: cần nhập số")
        try:
            numeric_value = float(answer.value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{question.id}: giá trị phải là số") from exc
        if question.min_value is not None and numeric_value < question.min_value:
            raise HTTPException(status_code=422, detail=f"{question.id}: giá trị nhỏ hơn min_value")
        if question.max_value is not None and numeric_value > question.max_value:
            raise HTTPException(status_code=422, detail=f"{question.id}: giá trị lớn hơn max_value")
    if question.input_type in {"text", "date"} and question.required and not (answer.value or answer.free_text):
        raise HTTPException(status_code=422, detail=f"{question.id}: câu hỏi bắt buộc phải có giá trị")
    for option in question.options:
        if option.id in selected and option.requires_value and not (answer.free_text or answer.value):
            raise HTTPException(status_code=422, detail=f"{question.id}: option '{option.id}' yêu cầu nhập thêm giá trị")


def _materialize_patch(patch: FactPatch, answer: ClarificationAnswer, question: ClarificationQuestion) -> FactPatch:
    value = patch.value
    replacement_free_text = answer.free_text or answer.value
    replacement_value = answer.value if answer.value is not None else answer.free_text
    if isinstance(value, dict):
        value = {
            key: replacement_free_text if item == "__free_text__" else replacement_value if item == "__value__" else item
            for key, item in value.items()
        }
    elif value == "__free_text__":
        value = replacement_free_text
    elif value == "__value__":
        value = replacement_value
    if question.input_type == "number" and value is not None:
        value = float(value)
    return patch.model_copy(update={"value": value})


def _validate_answers_and_build_patches(session: CaseSession, answers: list[ClarificationAnswer]) -> list[FactPatch]:
    patches: list[FactPatch] = []
    for answer in answers:
        found = _find_issued_question(session, answer.question_id)
        if not found:
            owner = session_store.question_owner_case_id(answer.question_id)
            if owner and owner != session.case_id:
                raise HTTPException(status_code=400, detail="question_id thuộc case khác")
            raise HTTPException(status_code=422, detail=f"question_id không hợp lệ hoặc chưa được phát hành: {answer.question_id}")
        question_set, question = found
        if question.depends_on_question_id and question.depends_on_question_id not in session.answered_question_ids:
            raise HTTPException(status_code=422, detail=f"{question.id}: câu hỏi dependency chưa được kích hoạt")
        _validate_answer_shape(question, answer)
        option_mappings = question_set.option_patches.get(question.id, {})
        for option_id in answer.selected_option_ids:
            for patch in option_mappings.get(option_id, []):
                patches.append(_materialize_patch(patch, answer, question))
        for patch in question_set.value_patches.get(question.id, []):
            patches.append(_materialize_patch(patch, answer, question))
        if "unknown" in answer.selected_option_ids:
            if answer.question_id not in session.answered_unknown_question_ids:
                session.answered_unknown_question_ids.append(answer.question_id)
        elif answer.question_id not in session.answered_question_ids:
            session.answered_question_ids.append(answer.question_id)
    return patches


def _specific_substance_option(question: ClarificationQuestion, extracted) -> str | None:
    option_ids = {option.id for option in question.options}
    option_labels = {normalize_text(option.label): option.id for option in question.options}
    specific_names: list[str] = []
    seen_specific: set[str] = set()
    for substance in extracted.substances:
        name = str(substance.name or "").strip()
        if not name or normalize_text(name) in {"ma tuy", "chat ma tuy"}:
            continue
        if substance.confidence < 0.75:
            continue
        key = normalize_text(name)
        if key not in seen_specific:
            specific_names.append(name)
            seen_specific.add(key)
    if len(specific_names) != 1:
        return None
    norm_name = normalize_text(specific_names[0])
    if norm_name in option_ids:
        return norm_name
    return option_labels.get(norm_name)


def _infer_answer_patches_from_message(session: CaseSession, extracted) -> list[FactPatch]:
    """Map natural-language follow-up answers to the latest issued form question.

    This only bridges clear answers such as "đó là ma túy đá" after the server
    already issued a forensic-substance question. Initial scenario extraction
    still stays conservative and does not treat suspected substances as forensic
    confirmation.
    """
    patches: list[FactPatch] = []
    if not extracted.substances:
        return patches
    answered = set(session.answered_question_ids) | set(session.answered_unknown_question_ids)
    for question_set in reversed(session.issued_question_sets):
        for question in question_set.questions:
            if question.id in answered:
                continue
            if not question.id.endswith("_forensic_substance"):
                continue
            option_id = _specific_substance_option(question, extracted)
            if not option_id:
                continue
            answer = ClarificationAnswer(question_id=question.id, selected_option_ids=[option_id])
            for patch in question_set.option_patches.get(question.id, {}).get(option_id, []):
                patches.append(_materialize_patch(patch, answer, question))
            session.answered_question_ids.append(question.id)
            return patches
    return patches


def handle_legal_chat(
    message: str,
    case_id: str | None = None,
    case_version: int | None = None,
    answers: list[ClarificationAnswer] | None = None,
    top_k: int = 8,
    include_debug: bool = False,
    answer_style: str = "auto",
    mode: str = "auto",
) -> LegalChatResponse:
    answers = answers or []
    session = _load_session(case_id, bool(answers))
    _validate_case_version(session, case_version)

    input_understanding = understand_input(message) if message.strip() and not answers else None
    has_active_case_context = bool(session.scenario_text or session.issued_question_sets or session.turns)
    can_fast_reply = (
        input_understanding
        and not input_understanding.should_run_pipeline
        and (
            input_understanding.scope in {
                "empty",
                "greeting",
                "service_check",
                "thanks",
                "out_of_scope",
                "legal_other",
            }
            or not has_active_case_context
        )
    )
    if input_understanding and can_fast_reply:
        return _response_from_quick_understanding(session, message, input_understanding, include_debug)

    if message.strip() and not answers:
        next_version = session.version + 1
        article_lookup = build_general_article_lookup(message, session.case_id, next_version, include_debug)
        if article_lookup:
            session.version = next_version
            session.status = CaseStatus.answered
            session.facts = merge_facts(session.facts, article_lookup.facts)
            session.scenario_text = _append_message(session.scenario_text, message.strip())
            if article_lookup.issued_question_set:
                session.issued_question_sets.append(article_lookup.issued_question_set)
            turn = ConversationTurn(
                user_message=message,
                extracted_facts=article_lookup.facts,
                bot_response_summary=article_lookup.final_answer[:300],
            )
            session.turns.append(turn)
            session_store.save(session)
            debug = {"input_understanding": input_understanding.model_dump() if input_understanding else None}
            if include_debug and article_lookup.debug:
                debug = {**debug, **article_lookup.debug}
            return LegalChatResponse(
                case_id=session.case_id,
                case_version=session.version,
                status=CaseStatus.answered,
                facts=session.facts,
                provisional_findings=[],
                missing_facts=[],
                clarification=article_lookup.clarification,
                clarifying_questions=[],
                candidate_articles=article_lookup.candidate_articles,
                legal_reasoning=article_lookup.legal_reasoning,
                final_answer=article_lookup.final_answer,
                confidence=article_lookup.confidence,
                citations=article_lookup.citations,
                warnings=["Tra cứu điều luật chung từ Neo4j; chọn khoản/điểm nếu muốn đối chiếu tình huống cụ thể."],
                debug=debug if include_debug else None,
            )
        if is_general_penalty_lookup(message):
            session.version = next_version
            session.status = CaseStatus.answered
            final_answer = (
                "Mình chưa xác định được tội danh hoặc Điều luật BLHS khớp đủ chắc từ câu hỏi này trong Neo4j. "
                "Bạn vui lòng ghi rõ tên tội danh hoặc số điều, ví dụ: 'tội cướp tài sản', 'Điều 168', "
                "hoặc mô tả thêm hành vi chính."
            )
            turn = ConversationTurn(
                user_message=message,
                extracted_facts=session.facts.__class__(),
                bot_response_summary=final_answer[:300],
            )
            session.turns.append(turn)
            session_store.save(session)
            return LegalChatResponse(
                case_id=session.case_id,
                case_version=session.version,
                status=CaseStatus.answered,
                facts=session.facts,
                provisional_findings=[],
                missing_facts=[],
                clarification=None,
                clarifying_questions=[],
                candidate_articles=[],
                legal_reasoning=[],
                final_answer=final_answer,
                confidence=0.35,
                citations=[],
                warnings=["article_lookup:no_reliable_neo4j_match"],
                debug={"input_understanding": input_understanding.model_dump() if input_understanding else None} if include_debug else None,
            )

    extraction_text = message
    if input_understanding and input_understanding.normalized_message and input_understanding.scope != "criminal_law":
        extraction_text = input_understanding.normalized_message
    extracted = extract_facts(extraction_text) if message.strip() else session.facts.__class__()
    answer_patches = _validate_answers_and_build_patches(session, answers) if answers else []
    inferred_patches = (
        _infer_answer_patches_from_message(session, extracted)
        if message.strip() and not answers
        else []
    )
    merged = merge_facts(session.facts, extracted)
    if answer_patches:
        merged = apply_fact_patches(merged, answer_patches)
    if inferred_patches:
        merged = apply_fact_patches(merged, inferred_patches)
    scenario_text = _append_message(session.scenario_text, message.strip())

    selected_article_answer = build_selected_article_answer(merged) if answers else None
    if selected_article_answer:
        session.version += 1
        session.status = CaseStatus.answered
        session.facts = merged
        session.scenario_text = scenario_text
        turn = ConversationTurn(
            user_message=message,
            extracted_facts=extracted,
            answers=answers,
            bot_response_summary=selected_article_answer.final_answer[:300],
        )
        session.turns.append(turn)
        session_store.save(session)
        return LegalChatResponse(
            case_id=session.case_id,
            case_version=session.version,
            status=CaseStatus.answered,
            facts=merged,
            provisional_findings=[],
            missing_facts=[],
            clarification=None,
            clarifying_questions=[],
            candidate_articles=selected_article_answer.candidate_articles,
            legal_reasoning=selected_article_answer.legal_reasoning,
            final_answer=selected_article_answer.final_answer,
            confidence=selected_article_answer.confidence,
            citations=selected_article_answer.citations,
            warnings=["Đối chiếu theo lựa chọn khoản/điểm từ dữ liệu Neo4j."],
            debug={"answer_patch_count": len(answer_patches) + len(inferred_patches)} if include_debug else None,
        )

    missing = detect_missing_facts(merged, scenario_text)
    session.version += 1
    structured_form, issued_question_set = build_structured_clarification(
        merged,
        scenario_text,
        missing,
        case_id=session.case_id,
        case_version=session.version,
        answered_question_ids=set(session.answered_question_ids),
        answered_unknown_question_ids=set(session.answered_unknown_question_ids),
    )
    clarifying_questions = [question.text for question in structured_form.questions]
    if not clarifying_questions:
        clarifying_questions = build_clarifying_questions(merged, scenario_text, missing)
    status, missing_items, gate_warnings = evaluate_answer_gate(merged, scenario_text, missing, clarifying_questions)

    turn = ConversationTurn(user_message=message, extracted_facts=extracted, answers=answers)
    session.facts = merged
    session.scenario_text = scenario_text
    session.status = status
    if structured_form.questions:
        session.issued_question_sets.append(issued_question_set)

    if status == CaseStatus.ready_to_answer:
        analysis = run_legal_analysis(
            scenario=scenario_text,
            facts=merged,
            top_k=top_k,
            include_debug=include_debug,
            answer_style=answer_style,
        )
        session.status = CaseStatus.answered
        turn.bot_response_summary = analysis.final_answer[:300]
        session.turns.append(turn)
        session_store.save(session)
        debug = {"dialogue_status_before_answer": status.value, "case_turns": len(session.turns), "pipeline_rerun_after_answers": bool(answers)} if include_debug else None
        return _response_from_analysis(session, analysis, CaseStatus.answered, debug)

    provisional_analysis = _run_provisional_analysis(
        scenario_text,
        merged,
        top_k,
        include_debug,
        answer_style,
    )
    preferred_codes = _provisional_article_codes(merged, scenario_text)
    provisional_legal_reasoning = (
        _filter_by_article_codes(provisional_analysis.legal_reasoning, preferred_codes)
        if provisional_analysis
        else []
    )
    provisional_candidate_articles = (
        _filter_by_article_codes(provisional_analysis.candidate_articles, preferred_codes)
        if provisional_analysis
        else []
    )
    provisional_findings = (
        _provisional_from_reasoning(provisional_legal_reasoning, preferred_codes)
        if provisional_legal_reasoning
        else _provisional_from_missing(missing)
    )
    session.candidate_hypotheses = provisional_findings

    if _is_analysis_mode(mode) and provisional_analysis and (provisional_legal_reasoning or provisional_candidate_articles):
        contexts = _context_dicts(provisional_analysis)
        missing_texts = [item.description for item in missing_items] or missing
        analysis_style = "conversational" if answer_style == "auto" else answer_style
        final_answer = generate_answer(
            scenario_text,
            merged,
            contexts,
            provisional_legal_reasoning,
            missing_texts,
            analysis_style,
            clarifying_questions=[],
            force_actor_breakdown=True,
        )
        final_answer, confidence, answer_warnings = validate_answer(
            final_answer,
            contexts,
            missing_texts,
            provisional_legal_reasoning,
            min(provisional_analysis.confidence or 0.0, 0.75),
        )
        session.status = CaseStatus.answered
        turn.bot_response_summary = final_answer[:300]
        session.turns.append(turn)
        session_store.save(session)
        debug = None
        if include_debug:
            debug = {
                "extracted_facts": extracted.model_dump(),
                "input_understanding": input_understanding.model_dump() if input_understanding else None,
                "case_turns": len(session.turns),
                "scenario_text": scenario_text,
                "gate_status_before_analysis_answer": status.value,
                "gate_warnings": gate_warnings,
                "answer_patch_count": len(answer_patches) + len(inferred_patches),
                "analysis_mode": mode,
                "provisional_analysis": {
                    "enabled": settings.use_provisional_neo4j_analysis,
                    "ran": True,
                    "preferred_codes": preferred_codes,
                    "candidate_count": len(provisional_candidate_articles),
                    "reasoning_count": len(provisional_legal_reasoning),
                },
            }
        return LegalChatResponse(
            case_id=session.case_id,
            case_version=session.version,
            status=CaseStatus.answered,
            facts=merged,
            provisional_findings=provisional_findings,
            missing_facts=[],
            clarification=None,
            clarifying_questions=[],
            candidate_articles=provisional_candidate_articles,
            legal_reasoning=provisional_legal_reasoning,
            final_answer=final_answer,
            confidence=confidence or 0.45,
            citations=provisional_analysis.citations,
            warnings=gate_warnings + provisional_analysis.warnings + answer_warnings + [
                "analysis_mode_answer_from_neo4j",
                "Phân tích tham khảo; không thay thế kết luận của cơ quan có thẩm quyền.",
            ],
            debug=debug,
        )

    final_answer = _collecting_answer(clarifying_questions, gate_warnings, _provisional_summary(provisional_findings))
    if status == CaseStatus.insufficient_information:
        final_answer = (
            "Chưa đủ dữ kiện để kết luận cuối cùng. Người dùng cho biết không biết thêm thông tin, "
            "nên hệ thống dừng hỏi lặp. Chỉ có thể phân tích sơ bộ theo dữ kiện hiện có và không chốt "
            "tội danh/khoản hoặc khung hình phạt.\n"
            + ((_provisional_summary(provisional_findings) or "") + "\n" if provisional_findings else "")
            + "Phân tích tham khảo; không thay thế kết luận của cơ quan có thẩm quyền."
        )

    turn.bot_response_summary = final_answer[:300]
    session.turns.append(turn)
    session_store.save(session)
    debug = None
    if include_debug:
        debug = {
            "extracted_facts": extracted.model_dump(),
            "input_understanding": input_understanding.model_dump() if input_understanding else None,
            "case_turns": len(session.turns),
            "scenario_text": scenario_text,
            "gate_warnings": gate_warnings,
            "answer_patch_count": len(answer_patches) + len(inferred_patches),
            "question_set_id": structured_form.question_set_id,
            "answered_question_ids": session.answered_question_ids,
            "answered_unknown_question_ids": session.answered_unknown_question_ids,
            "provisional_analysis": {
                "enabled": settings.use_provisional_neo4j_analysis,
                "ran": provisional_analysis is not None,
                "preferred_codes": preferred_codes,
                "candidate_count": len(provisional_candidate_articles),
                "reasoning_count": len(provisional_legal_reasoning),
            },
        }
    return LegalChatResponse(
        case_id=session.case_id,
        case_version=session.version,
        status=status,
        facts=merged,
        provisional_findings=session.candidate_hypotheses,
        missing_facts=missing_items,
        clarification=structured_form,
        clarifying_questions=clarifying_questions,
        candidate_articles=provisional_candidate_articles,
        legal_reasoning=provisional_legal_reasoning,
        final_answer=final_answer,
        confidence=min(provisional_analysis.confidence, 0.65) if provisional_analysis else (0.25 if missing_items else 0.45),
        citations=provisional_analysis.citations if provisional_analysis else [],
        warnings=gate_warnings + (provisional_analysis.warnings if provisional_analysis else []) + ["Phân tích tham khảo; không thay thế kết luận của cơ quan có thẩm quyền."],
        debug=debug,
    )
