from __future__ import annotations

from app.models.facts import ExtractedFacts
from app.models.legal_output import CandidateArticle, LegalContext, ScenarioAnalysisResponse
from app.services.answer_generator import generate_answer
from app.services.clarifying_questions import build_clarifying_questions
from app.services.context_builder import citations_from_contexts
from app.services.decomposer import decompose_query
from app.services.fact_extractor import extract_facts
from app.services.fast_response import detect_fast_response
from app.services.graph_retriever import fetch_contexts
from app.services.hybrid_retriever import retrieve_candidates
from app.services.legal_matcher import detect_missing_facts
from app.services.legal_reasoner import reason_over_contexts
from app.services.normalizer import normalize_text_with_graph
from app.services.query_rewriter import rewrite_queries
from app.services.reranker import rerank
from app.services.validator import validate_answer
from app.utils.text import normalize_text


def _required_event_codes_from_scenario(scenario: str, facts: ExtractedFacts) -> list[dict]:
    norm = normalize_text(scenario)
    action_norms = {normalize_text(action) for action in facts.actions}
    object_norm = normalize_text(" ".join(facts.objects))
    codes: list[tuple[str, str, list[str], float]] = []

    if any(term in norm for term in ["ban thang", "no sung", "sung ak", "trung dan", "hy sinh", "chet nguoi", "tu vong"]):
        codes.append(("123", "Tội giết người", ["bắn", "nổ súng", "hy sinh", "chết người"], 2.6))
    if any(term in norm for term in ["sung ak", "hop tiep dan", "luu dan", "vu khi quan dung"]) or "vu khi quan dung" in object_norm:
        codes.append(("304", "Tội tàng trữ, sử dụng trái phép vũ khí quân dụng", ["súng AK", "lựu đạn", "vũ khí quân dụng"], 2.4))
    if any(term in norm for term in ["lam hu hong xe", "hu hong xe", "thiet hai tai san", "lam hu hong tai san"]):
        codes.append(("178", "Tội cố ý làm hư hỏng tài sản", ["làm hư hỏng xe", "thiệt hại tài sản"], 2.2))
    if facts.substances or "ma tuy" in norm or "heroin" in norm:
        has_buy_sell_drug = {"mua", "mua ban"} & action_norms or any(term in norm for term in ["mua ban ma tuy", "giao dich ma tuy", "duong day mua ban", "tieu thu"])
        if "van chuyen" in action_norms or "van chuyen ma tuy" in norm:
            if not has_buy_sell_drug:
                codes.append(("250", "Tội vận chuyển trái phép chất ma túy", ["vận chuyển ma túy"], 2.1))
        if has_buy_sell_drug:
            codes.append(("251", "Tội mua bán trái phép chất ma túy", ["mua bán ma túy", "heroin"], 2.5))

    seen: set[str] = set()
    out: list[dict] = []
    for code, title, terms, score in codes:
        if code in seen:
            continue
        seen.add(code)
        out.append({
            "article_code": code,
            "title": title,
            "score": score,
            "source": "required_multi_event_signal",
            "matched_terms": terms,
            "reason": "multi_event_signal_from_scenario",
        })
    return out


def _append_supporting_candidates(candidates_raw: list[dict], facts: ExtractedFacts) -> None:
    support_codes: list[str] = []
    ages = [actor.age for actor in facts.actors if actor.age is not None]
    if any(age < 18 for age in ages):
        support_codes.append("12")
    if any(age >= 70 for age in ages):
        support_codes.append("51")
    if any(a in facts.actions for a in ["giúp sức", "xúi giục", "chủ mưu", "cầm đầu"]) or len(facts.actors) >= 2:
        support_codes.append("17")
    if any(a in facts.actions for a in ["chuẩn bị"]):
        support_codes.append("14")
    if any(a in facts.actions for a in ["chưa đạt"]):
        support_codes.append("15")
    if facts.mitigating_signals:
        support_codes.append("51")
    if facts.aggravating_signals:
        support_codes.append("52")

    seen = {str(c.get("article_code")) for c in candidates_raw}
    for code in support_codes:
        if code not in seen:
            candidates_raw.append({
                "article_code": code,
                "title": f"Điều {code}",
                "score": 0.01,
                "source": "supporting_rule_inference",
                "matched_terms": [f"Điều {code}"],
            })
            seen.add(code)

    action_norms = {a.lower() for a in facts.actions}
    required_crime_codes: list[str] = []
    if facts.substances:
        if "tổ chức sử dụng" in action_norms:
            required_crime_codes.append("255")
        if "sử dụng" in action_norms:
            required_crime_codes.append("256a")
        if "mua" in action_norms or "mua bán" in action_norms:
            required_crime_codes.extend(["251", "249"])
    for code in required_crime_codes:
        if code not in seen:
            candidates_raw.append({
                "article_code": code,
                "title": f"Điều {code}",
                "score": 0.05,
                "source": "required_drug_action",
                "matched_terms": [f"Điều {code}"],
            })
            seen.add(code)


def _append_required_event_candidates(candidates_raw: list[dict], scenario: str, facts: ExtractedFacts) -> None:
    seen = {str(c.get("article_code")) for c in candidates_raw}
    for candidate in _required_event_codes_from_scenario(scenario, facts):
        code = str(candidate.get("article_code"))
        if code in seen:
            for current in candidates_raw:
                if str(current.get("article_code")) == code:
                    current["score"] = max(float(current.get("score") or 0.0), float(candidate.get("score") or 0.0))
                    current["source"] = f"{current.get('source') or ''}+required_multi_event_signal".strip("+")
                    current["matched_terms"] = list(dict.fromkeys([*(current.get("matched_terms") or []), *(candidate.get("matched_terms") or [])]))
                    current["reason"] = candidate.get("reason")
                    break
            continue
        candidates_raw.append(candidate)
        seen.add(code)


def run_legal_analysis(
    scenario: str,
    facts: ExtractedFacts | None = None,
    top_k: int = 8,
    include_debug: bool = False,
    answer_style: str = "auto",
    generate_final_answer: bool = True,
) -> ScenarioAnalysisResponse:
    fast = detect_fast_response(scenario)
    if fast and fast["kind"] in {"greeting", "service_check", "thanks", "empty", "out_of_scope"}:
        extracted = facts or extract_facts(scenario)
        return ScenarioAnalysisResponse(
            facts=extracted,
            final_answer=fast["answer"],
            confidence=0.9 if fast["kind"] != "out_of_scope" else 0.6,
            warnings=[f"fast_response:{fast['kind']}"],
            debug={"fast_response": fast} if include_debug else None,
        )

    extracted = facts or extract_facts(scenario)
    normalized = normalize_text_with_graph(scenario)
    sub_queries = decompose_query(scenario, extracted)
    rewritten = rewrite_queries(scenario, extracted, sub_queries, normalized)
    candidates_raw, retrieval_debug = retrieve_candidates(rewritten, extracted, normalized, top_k)
    candidates_raw = rerank(scenario, candidates_raw, top_k)
    _append_required_event_candidates(candidates_raw, scenario, extracted)
    _append_supporting_candidates(candidates_raw, extracted)

    contexts = fetch_contexts([str(c.get("article_code")) for c in candidates_raw if c.get("article_code")])
    missing = detect_missing_facts(extracted, scenario)
    clarifying_questions = build_clarifying_questions(extracted, scenario, missing)
    reasoning = reason_over_contexts(contexts, extracted, normalized, missing)
    reasoning_rank = {item.article_code: idx for idx, item in enumerate(reasoning)}
    reasoning_score = {item.article_code: item.confidence for item in reasoning}
    contexts = sorted(contexts, key=lambda ctx: reasoning_rank.get(str((ctx.get("article") or {}).get("article_code")), 999))
    context_titles = {
        str((ctx.get("article") or {}).get("article_code")): str((ctx.get("article") or {}).get("title") or "")
        for ctx in contexts
    }
    for candidate in candidates_raw:
        code = str(candidate.get("article_code"))
        if code in reasoning_score:
            candidate["score"] = max(float(candidate.get("score") or 0.0), float(reasoning_score[code]))
            candidate["reason"] = "ranked_by_legal_reasoning"
        if context_titles.get(code):
            candidate["title"] = context_titles[code]
    candidates_raw = sorted(candidates_raw, key=lambda c: reasoning_rank.get(str(c.get("article_code")), 999))
    confidence = max([r.confidence for r in reasoning], default=0.3)
    warnings: list[str] = []
    if generate_final_answer:
        answer = generate_answer(
            scenario,
            extracted,
            contexts,
            reasoning,
            missing,
            answer_style=answer_style,
            clarifying_questions=clarifying_questions,
        )
        answer, confidence, warnings = validate_answer(answer, contexts, missing, reasoning, confidence)
    else:
        answer = ""
        warnings = ["provisional_analysis_from_neo4j"]

    candidates = [
        CandidateArticle(
            article_code=str(c.get("article_code")),
            title=str(c.get("title") or ""),
            crime_name=c.get("crime_name"),
            score=float(c.get("score") or 0.0),
            source=str(c.get("source") or ""),
            matched_terms=list(c.get("matched_terms") or []),
            reason=c.get("reason"),
        )
        for c in candidates_raw
    ]
    legal_contexts = [LegalContext.model_validate(ctx) for ctx in contexts]
    possible_penalty_frames = [pf for ctx in contexts for pf in (ctx.get("penalty_frames") or [])]
    matched_conditions = [
        m
        for r in reasoning
        for m in r.matched_elements
        if m.type in {"condition", "quantity", "action", "substance"}
    ]
    debug = None
    if include_debug:
        debug = {
            "normalized": normalized,
            "sub_queries": [s.__dict__ for s in sub_queries],
            "rewritten_queries": rewritten,
            "retrieval": retrieval_debug,
        }
    return ScenarioAnalysisResponse(
        facts=extracted,
        normalized_signals=normalized,
        candidate_articles=candidates,
        legal_contexts=legal_contexts,
        matched_conditions=matched_conditions,
        possible_penalty_frames=possible_penalty_frames,
        missing_facts=missing,
        clarifying_questions=clarifying_questions,
        legal_reasoning=reasoning,
        final_answer=answer,
        confidence=confidence,
        citations=citations_from_contexts(contexts),
        warnings=warnings,
        debug=debug,
    )
