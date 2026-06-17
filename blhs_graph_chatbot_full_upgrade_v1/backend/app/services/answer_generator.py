from __future__ import annotations

import json
import logging
import re
import zlib

from app.core.config import settings
from app.models.facts import ExtractedFacts
from app.models.legal_output import LegalReasoningItem
from app.prompts.answer_prompt import ANSWER_SYSTEM, ANSWER_USER
from app.services.clarifying_questions import user_declines_or_lacks_more_info
from app.services.context_builder import build_context_text
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)


STYLE_GUIDANCE: dict[str, str] = {
    "balanced": "Trả lời tự nhiên, có đoạn ngắn và gạch đầu dòng khi thật sự cần.",
    "conversational": "Trả lời như đang trao đổi với người dùng, mềm hơn nhưng vẫn thận trọng pháp lý.",
    "brief": "Trả lời ngắn gọn, ưu tiên kết luận có điều kiện và các điểm cần hỏi thêm.",
    "educational": "Giải thích theo hướng học thuật dễ hiểu, nêu vì sao dữ kiện đó quan trọng.",
    "structured": "Dùng các mục rõ ràng, nhưng không lặp lại khuôn 6 phần cố định.",
}


def _resolve_answer_style(answer_style: str, facts: ExtractedFacts, reasoning: list[LegalReasoningItem], missing: list[str], scenario: str = "") -> str:
    if answer_style != "auto":
        return answer_style if answer_style in STYLE_GUIDANCE else "balanced"
    if user_declines_or_lacks_more_info(scenario):
        return "brief"
    if missing:
        return "conversational" if zlib.crc32(scenario.encode("utf-8")) % 2 else "educational"
    if len(reasoning) > 3:
        return "educational"
    if len(facts.actions) <= 1 and len(facts.actors) <= 1:
        return "brief"
    return "balanced"


def _top_articles(reasoning: list[LegalReasoningItem]) -> str:
    articles = [f"Điều {item.article_code} ({item.title})" for item in reasoning[:4]]
    return ", ".join(articles) if articles else "chưa xác định được điều luật ứng viên đủ tin cậy"


def _fallback_summary(facts: ExtractedFacts) -> str:
    actors = ", ".join(a.name + (f" ({a.age} tuổi)" if a.age else "") for a in facts.actors) or "chủ thể chưa rõ"
    actions = ", ".join(facts.actions) or "hành vi chưa rõ"
    objects = ", ".join(facts.objects + [s.name for s in facts.substances] + facts.consequences) or "đối tượng/hậu quả chưa rõ"
    exhibits = ", ".join(exhibit.description for exhibit in facts.exhibits) or "tang vật chưa rõ"
    return f"Hiện mình nhận diện được {actors}; hành vi/tín hiệu là {actions}; đối tượng hoặc hậu quả liên quan là {objects}; tình trạng tang vật: {exhibits}."


def _pick(seed: str, options: list[str]) -> str:
    return options[zlib.crc32(seed.encode("utf-8")) % len(options)]


def _question_block(clarifying_questions: list[str]) -> list[str]:
    if not clarifying_questions:
        return []
    return ["", "Để chắc hơn, mình cần hỏi thêm:", *[f"- {question}" for question in clarifying_questions[:6]]]


def _penalty_preview(item: LegalReasoningItem) -> str:
    frames = [str(frame.get("text") or "").strip() for frame in item.possible_penalty_frames if frame.get("text")]
    frames = list(dict.fromkeys(frames))
    return "; ".join(frames[:3]) if frames else "khung phạt cần đối chiếu theo khoản/điểm cụ thể trong Neo4j"


def _is_victim_actor(actor_name: str, scenario: str) -> bool:
    aliases = _actor_aliases(actor_name)
    if not aliases:
        return False
    victim_terms = ["hy sinh", "trung dan", "tu vong", "chet", "bi ban chet", "nan nhan", "bi hai"]
    for sentence in re.split(r"[\n.;!?]+", scenario):
        sentence_norm = normalize_text(sentence)
        if not _mentions_actor(sentence_norm, aliases):
            continue
        compact_sentence = re.sub(r"\([^)]*\)", " ", sentence_norm)
        for alias in aliases:
            for alias_match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", compact_sentence):
                tail = compact_sentence[alias_match.end(): alias_match.end() + 180]
                head = compact_sentence[max(0, alias_match.start() - 80): alias_match.start()]
                if any(term in tail for term in victim_terms) or any(term in head for term in ["nan nhan", "bi hai"]):
                    return True
            for alias_match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", sentence_norm):
                tail = sentence_norm[alias_match.end(): alias_match.end() + 220]
                if any(term in tail for term in ["hy sinh", "trung dan", "tu vong", "bi ban chet"]):
                    return True
    return False


def _actor_aliases(actor_name: str) -> list[str]:
    norm_name = normalize_text(actor_name)
    if not norm_name:
        return []
    aliases = [norm_name]
    parts = norm_name.split()
    if len(parts) >= 2:
        aliases.append(parts[-1])
        aliases.append(" ".join(parts[-2:]))
    return list(dict.fromkeys(alias for alias in aliases if len(alias) >= 2))


def _mentions_actor(sentence_norm: str, aliases: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", sentence_norm) for alias in aliases)


def _actor_role_hint(actor_name: str, scenario: str) -> str:
    aliases = _actor_aliases(actor_name)
    windows = [
        normalize_text(sentence)
        for sentence in re.split(r"[\n.;!?]+", scenario)
        if _mentions_actor(normalize_text(sentence), aliases)
    ]
    text = " ".join(windows)
    if any(term in text for term in ["ban thang", "no sung", "sung ak", "giet", "lam hu hong"]):
        return "người trực tiếp thực hiện hành vi bạo lực/vũ khí theo mô tả"
    if any(term in text for term in ["duong day", "mua ban", "giao dich", "cat giau", "heroin", "ma tuy"]):
        return "người liên quan trực tiếp đến đường dây ma túy theo mô tả"
    if any(term in text for term in ["dong bon", "dong pham", "ap giai", "bi khong che"]):
        return "người được nêu là đồng phạm/đồng bọn nhưng vai trò cụ thể còn cần làm rõ"
    return "người được nêu trong tình huống, cần làm rõ vai trò cụ thể"


def _reasoning_for_actor(actor_name: str, scenario: str, reasoning: list[LegalReasoningItem]) -> list[LegalReasoningItem]:
    aliases = _actor_aliases(actor_name)
    actor_sentences = [
        normalize_text(sentence)
        for sentence in re.split(r"[\n.;!?]+", scenario)
        if _mentions_actor(normalize_text(sentence), aliases)
    ]
    actor_text = " ".join(actor_sentences)
    if any(term in actor_text for term in ["ban thang", "no sung", "sung ak", "giet", "lam hu hong"]):
        preferred = {"123", "304", "178", "251", "250"}
    elif any(term in actor_text for term in ["duong day", "mua ban", "giao dich", "cat giau", "heroin", "ma tuy"]):
        preferred = {"251", "250", "249", "255", "17"}
    elif any(term in actor_text for term in ["dong bon", "dong pham", "bi khong che", "ap giai"]):
        preferred = {"17", "251", "250"}
    else:
        preferred = {item.article_code for item in reasoning if item.classification == "crime_candidate"}
    selected = [item for item in reasoning if item.article_code in preferred and item.classification == "crime_candidate"]
    return selected[:5] or [item for item in reasoning if item.classification == "crime_candidate"][:4]


def _actor_breakdown_answer(
    scenario: str,
    facts: ExtractedFacts,
    reasoning: list[LegalReasoningItem],
    missing: list[str],
    clarifying_questions: list[str] | None = None,
) -> str:
    clarifying_questions = clarifying_questions or []
    actors = facts.actors
    if not actors:
        return ""

    lines = [
        "Có thể phân tích trách nhiệm theo từng đối tượng như sau:",
        "",
    ]
    offender_count = 0
    for idx, actor in enumerate(actors, start=1):
        if _is_victim_actor(actor.name, scenario):
            lines.extend([
                f"{idx}. {actor.name}:",
                "Người này được mô tả là người bị hại/nạn nhân trong tình huống, không phải đối tượng phạm tội cần xem xét trách nhiệm hình sự.",
                "",
            ])
            continue
        offender_count += 1
        actor_reasoning = _reasoning_for_actor(actor.name, scenario, reasoning)
        inferred_role = _actor_role_hint(actor.name, scenario)
        role_hint = actor.role or inferred_role
        if actor.role == "người sử dụng" and any(term in normalize_text(inferred_role) for term in ["bao luc", "vu khi"]):
            role_hint = inferred_role
        lines.append(f"{idx}. {actor.name}:")
        lines.append(f"Vai trò nhận diện: {role_hint}.")
        if actor_reasoning:
            lines.append("Các tội danh/điều luật có thể xem xét:")
            for item in actor_reasoning:
                lines.append(f"- Điều {item.article_code} - {item.title}: {item.why_relevant} Khung có thể đối chiếu: {_penalty_preview(item)}.")
        else:
            lines.append("Chưa truy được điều luật ứng viên đủ rõ cho người này từ Neo4j.")
        lines.append("")

    if offender_count == 0:
        lines.append("Chưa xác định được đối tượng phạm tội trong các tên đã nhận diện; cần bổ sung người thực hiện hành vi.")
        lines.append("")
    if missing:
        lines.append("Lưu ý dữ kiện còn ảnh hưởng kết luận:")
        lines.extend(f"- {item}" for item in missing[:5])
        lines.append("")
    if clarifying_questions:
        lines.extend(_question_block(clarifying_questions))
    lines.append("Các nhận định trên là phân tích tham khảo theo dữ kiện đã nêu và context Neo4j; kết luận cuối cùng phụ thuộc hồ sơ, giám định và đánh giá của cơ quan có thẩm quyền.")
    return "\n".join(lines).strip()


def _template_answer(
    scenario: str,
    facts: ExtractedFacts,
    reasoning: list[LegalReasoningItem],
    missing: list[str],
    answer_style: str = "auto",
    clarifying_questions: list[str] | None = None,
    force_actor_breakdown: bool = False,
) -> str:
    clarifying_questions = clarifying_questions or []
    if force_actor_breakdown:
        actor_answer = _actor_breakdown_answer(scenario, facts, reasoning, missing, clarifying_questions)
        if actor_answer:
            return actor_answer
    style = _resolve_answer_style(answer_style, facts, reasoning, missing, scenario)
    no_more_info = user_declines_or_lacks_more_info(scenario)
    summary = _fallback_summary(facts)
    articles = _top_articles(reasoning)
    frames = [
        f"Điều {item.article_code}, khung [{pf.get('id')}]: {pf.get('text')}"
        for item in reasoning
        for pf in item.possible_penalty_frames[:2]
        if pf.get("text")
    ]

    if style == "brief":
        opener = _pick(scenario, [
            "Mình chốt ở mức sơ bộ như sau:",
            "Với phần dữ kiện hiện có, hướng xử lý thận trọng là:",
            "Nếu chưa có thêm tài liệu, có thể kết luận tạm thời:",
        ])
        lines = [
            f"{opener} {summary} Có thể xem xét {articles}, nhưng chưa nên chốt tội danh/khoản nếu các dữ kiện trọng yếu chưa rõ.",
        ]
        if missing:
            prefix = "Do bạn chưa có thêm dữ liệu, các điểm này được ghi nhận như giới hạn của kết luận: " if no_more_info else "Điểm còn thiếu chính: "
            lines.append(prefix + "; ".join(missing[:3]))
        lines.extend(_question_block(clarifying_questions))
        return "\n".join(lines)

    if style == "conversational":
        opener = _pick(scenario, [
            "Mình sẽ đi chậm một nhịp để tránh kết luận quá tay.",
            "Ở tình huống này, điểm quan trọng là tách điều đã biết khỏi điều còn phải chứng minh.",
            "Có cơ sở để phân tích, nhưng chưa nên xem đây là kết luận cuối.",
        ])
        lines = [
            f"{opener} {summary}",
            f"Hướng pháp lý có thể đặt ra là {articles}. Tuy vậy, kết luận cuối cùng còn phụ thuộc vào chứng cứ, kết quả giám định và vai trò cụ thể của từng người.",
        ]
        if frames:
            lines.append("Một số khung phạt có thể phải đối chiếu: " + "; ".join(frames[:3]))
        if missing:
            label = "Vì chưa có thêm thông tin, mình coi đây là giới hạn của kết luận: " if no_more_info else "Những điểm đang làm kết luận chưa chắc: "
            lines.append(label + "; ".join(missing[:4]))
        lines.extend(_question_block(clarifying_questions))
        return "\n".join(lines)

    if style == "educational":
        opener = _pick(scenario, [
            "Có thể đọc tình huống này theo ba lớp: dữ kiện, điều luật, rồi mức độ chắc chắn.",
            "Cách chắc nhất là bắt đầu từ các yếu tố cấu thành trước khi nói đến khung phạt.",
            "Mình sẽ xem đây là nhận định có điều kiện, vì một vài dữ kiện còn quyết định trực tiếp đến khoản áp dụng.",
        ])
        lines = [
            f"{opener} {summary}",
            f"Sau đó mới đối chiếu với điều luật. Các điều nổi bật hiện tại là {articles}.",
        ]
        if missing:
            lines.append("Các dữ kiện còn thiếu quan trọng vì chúng quyết định đúng tội danh, đúng khoản và đúng vai trò: " + "; ".join(missing[:5]))
        if frames:
            lines.append("Khung hình phạt chỉ nên xem là khả năng tham khảo lúc này: " + "; ".join(frames[:4]))
        if no_more_info:
            lines.append("Vì bạn chưa có thêm thông tin, kết luận nên dừng ở mức có dấu hiệu/có thể xem xét theo dữ kiện hiện có.")
        else:
            lines.append("Vì vậy, câu trả lời nên dừng ở mức có dấu hiệu/có thể xem xét, chưa đủ căn cứ để kết luận chắc chắn.")
        lines.extend(_question_block(clarifying_questions))
        return "\n".join(lines)

    if style == "structured":
        lines = [
            "Nhận định sơ bộ",
            summary,
            "",
            "Điều luật cần đối chiếu",
            f"- {articles}",
            "",
            "Lưu ý trước khi kết luận",
        ]
        lines.extend([f"- {m}" for m in missing[:6]] or ["- Chưa phát hiện thiếu dữ kiện trọng yếu, nhưng vẫn cần kiểm tra chứng cứ thực tế."])
        if frames:
            lines.extend(["", "Khung phạt có thể liên quan", *[f"- {frame}" for frame in frames[:5]]])
        lines.extend(_question_block(clarifying_questions))
        return "\n".join(lines)

    lines: list[str] = []
    lines.append(_pick(scenario, [
        summary,
        f"Tóm lại phần dữ kiện trước: {summary}",
        f"Mình đang nhìn thấy các điểm chính này: {summary}",
    ]))
    lines.append(f"Các điều luật có thể liên quan gồm {articles}. Đây mới là hướng đối chiếu, không phải kết luận chắc chắn.")
    if frames:
        lines.append("Khung phạt có thể phải kiểm tra thêm: " + "; ".join(frames[:4]))
    if missing:
        prefix = "Do chưa có thêm dữ liệu, kết luận bị giới hạn bởi: " if no_more_info else "Những dữ kiện còn thiếu đang ảnh hưởng trực tiếp đến kết luận: "
        lines.append(prefix + "; ".join(missing[:5]))
    lines.append("Kết luận nên giữ ở mức thận trọng: có dấu hiệu/có thể xem xét theo điều luật ứng viên, nhưng chưa đủ căn cứ để khẳng định chắc chắn tội danh hoặc khung cụ thể.")
    lines.extend(_question_block(clarifying_questions))
    return "\n".join(lines)


def generate_answer(
    scenario: str,
    facts: ExtractedFacts,
    contexts: list[dict],
    reasoning: list[LegalReasoningItem],
    missing: list[str],
    answer_style: str = "auto",
    clarifying_questions: list[str] | None = None,
    force_actor_breakdown: bool = False,
) -> str:
    clarifying_questions = clarifying_questions or []
    resolved_style = _resolve_answer_style(answer_style, facts, reasoning, missing, scenario)
    if force_actor_breakdown:
        actor_answer = _actor_breakdown_answer(scenario, facts, reasoning, missing, clarifying_questions)
        if actor_answer and not settings.openai_api_key:
            return actor_answer
    if not settings.openai_api_key:
        return _template_answer(scenario, facts, reasoning, missing, resolved_style, clarifying_questions, force_actor_breakdown=force_actor_breakdown)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.35 if resolved_style in {"conversational", "educational"} else 0.25,
            messages=[
                {"role": "system", "content": ANSWER_SYSTEM},
                {"role": "user", "content": ANSWER_USER.format(
                    scenario=scenario,
                    facts=json.dumps(facts.model_dump(), ensure_ascii=False),
                    context=build_context_text(contexts),
                    missing_facts=json.dumps(missing, ensure_ascii=False),
                    clarifying_questions=json.dumps(clarifying_questions, ensure_ascii=False),
                    answer_style=(
                        f"{resolved_style}: {STYLE_GUIDANCE[resolved_style]}. "
                        "BẮT BUỘC chia câu trả lời theo từng đối tượng/người được nêu; với nạn nhân thì ghi rõ không phải đối tượng phạm tội."
                        if force_actor_breakdown
                        else f"{resolved_style}: {STYLE_GUIDANCE[resolved_style]}"
                    ),
                )},
            ],
        )
        answer = resp.choices[0].message.content or ""
        if force_actor_breakdown and not any(actor.name in answer for actor in facts.actors[:2]):
            return actor_answer or _template_answer(scenario, facts, reasoning, missing, resolved_style, clarifying_questions, force_actor_breakdown=True)
        return answer or _template_answer(scenario, facts, reasoning, missing, resolved_style, clarifying_questions, force_actor_breakdown=force_actor_breakdown)
    except Exception as exc:
        logger.warning("LLM answer skipped: %s", exc)
        return _template_answer(scenario, facts, reasoning, missing, resolved_style, clarifying_questions, force_actor_breakdown=force_actor_breakdown)
