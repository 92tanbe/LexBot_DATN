from __future__ import annotations

from app.models.facts import ExtractedFacts
from app.models.legal_output import MatchedElement
from app.utils.scoring import clamp
from app.utils.text import normalize_text


def detect_missing_facts(facts: ExtractedFacts, scenario: str) -> list[str]:
    norm = normalize_text(scenario)
    missing: list[str] = []
    structured = facts.structured_facts
    if facts.substances or "ma tuy" in norm:
        exhibit_statuses = {str(exhibit.status.value if hasattr(exhibit.status, "value") else exhibit.status) for exhibit in facts.exhibits}
        has_forensic_exhibit = any(
            str(exhibit.forensic_status.value if hasattr(exhibit.forensic_status, "value") else exhibit.forensic_status) == "forensic_confirmed"
            for exhibit in facts.exhibits
        ) or any("giám định" in e for e in facts.evidence)
        has_net_mass = any((q.unit or "").lower() in {"g", "gam", "kg", "mg"} for q in facts.quantities)
        if not exhibit_statuses:
            missing.append("Tang vật: chưa rõ còn bị thu giữ, đã bị tiêu thụ/sử dụng hết, hay không thu giữ được.")
        if not has_forensic_exhibit:
            if any("dương tính" in e for e in facts.evidence):
                missing.append("Ma túy: xét nghiệm dương tính chỉ là kết quả trên cơ thể người, chưa thay thế kết luận giám định tang vật.")
            missing.append("Ma túy: thiếu kết luận giám định về loại chất của tang vật.")
        for exhibit in facts.exhibits:
            if exhibit.id == "powder" and not exhibit.confirmed_substance and str(exhibit.forensic_status.value if hasattr(exhibit.forensic_status, "value") else exhibit.forensic_status) not in {"denied", "not_available", "unknown"}:
                missing.append("Tang vật và giám định: thiếu hoạt chất của gói bột/gói nghi Ketamine theo kết luận giám định.")
            if exhibit.id == "tablets" and not exhibit.confirmed_substance and str(exhibit.forensic_status.value if hasattr(exhibit.forensic_status, "value") else exhibit.forensic_status) not in {"denied", "not_available", "unknown"}:
                missing.append("Tang vật và giám định: thiếu hoạt chất của viên nén theo kết luận giám định.")
        if not has_net_mass and not (exhibit_statuses & {"consumed", "not_seized"}):
            missing.append("Ma túy: thiếu khối lượng tịnh/hàm lượng bằng gam để xác định khoản.")
        elif not has_net_mass:
            missing.append("Ma túy: không có định lượng do không còn/không thu giữ được tang vật; cần chứng cứ thay thế để đánh giá ở mức có dấu hiệu.")
        role_gaps: list[str] = []
        has_supplier_info = bool(structured.get("transactions.drug_purchase.supplier")) or any(
            x in norm for x in ["tu doi tuong ten", "cung cap", "nguoi ban", "ban cho", "giao ma tuy"]
        )
        has_benefit_info = (
            structured.get("transactions.drug_purchase.delivery_fee") is not None
            or any(path.endswith(".profit_or_benefit") for path in structured)
            or any(x in norm for x in ["phi giao hang", "tien cong", "chenh lech", "huong loi", "chia loi ich"])
        )
        if not has_supplier_info:
            role_gaps.append("ai cung cấp")
        if "to chuc su dung" not in [normalize_text(a) for a in facts.actions]:
            role_gaps.append("ai tổ chức")
        if not any(x in norm for x in ["su dung", "duong tinh"]):
            role_gaps.append("ai sử dụng")
        if not facts.intent and "de" not in norm:
            role_gaps.append("mục đích")
        if not has_benefit_info:
            role_gaps.append("hưởng lợi")
        if role_gaps:
            missing.append("Ma túy: cần làm rõ " + ", ".join(role_gaps) + ".")
    tokens = set(norm.split())
    if "go" in tokens or "lam san" in norm or "rung" in tokens:
        if not any(q.unit in {"m3", "m³", "mét khối"} for q in facts.quantities):
            missing.append("Lâm sản/gỗ: thiếu khối lượng m3.")
        missing.append("Lâm sản/gỗ: thiếu loại gỗ/nhóm IA-IIA, nguồn gốc và hành vi chính xác.")
    if facts.age_info and not facts.actors:
        missing.append("Tuổi: cần xác định tuổi gắn với từng người cụ thể.")
    if len(facts.actors) >= 2 and not any(a.role for a in facts.actors):
        missing.append("Đồng phạm: thiếu vai trò cụ thể của từng người.")
    if any(x in norm for x in ["thuong tich", "chet nguoi", "tu vong", "thiet hai"]) and not facts.consequences:
        missing.append("Tội có hậu quả: thiếu hậu quả, tỷ lệ thương tật hoặc thiệt hại tài sản.")
    if not facts.intent and not facts.mental_state:
        missing.append("Yếu tố lỗi/mục đích: cần làm rõ cố ý/vô ý, biết hay không biết, mục đích thực hiện.")
    return list(dict.fromkeys(missing))


def score_context(ctx: dict, facts: ExtractedFacts, normalized: list[dict], missing: list[str]) -> tuple[float, list[MatchedElement]]:
    text_parts: list[str] = []
    for key in ["article", "crime"]:
        node = ctx.get(key) or {}
        text_parts.extend(str(v) for v in node.values() if isinstance(v, str))
    for key in ["conditions", "act_requirements", "object_requirements", "consequence_requirements", "quantity_thresholds"]:
        for node in ctx.get(key) or []:
            text_parts.extend(str(v) for v in node.values() if isinstance(v, str))
    haystack = normalize_text(" ".join(text_parts))
    score = 0.0
    matched: list[MatchedElement] = []
    def add(kind: str, value: str, points: float, reason: str) -> None:
        nonlocal score
        if value and normalize_text(value) in haystack:
            score += points
            matched.append(MatchedElement(type=kind, text=value, score=points, reason=reason))
    for action in facts.actions:
        add("action", action, 0.25, "Hành vi trong tình huống khớp context.")
    for obj in facts.objects:
        add("object", obj, 0.20, "Đối tượng/vật chứng khớp context.")
    for sub in facts.substances:
        add("substance", sub.name, 0.20, "Chất/nhóm chất khớp context.")
    if facts.quantities and (ctx.get("quantity_thresholds") or ctx.get("conditions")):
        score += 0.20
        matched.append(MatchedElement(type="quantity", text=", ".join(q.raw_text for q in facts.quantities), score=0.20, reason="Có định lượng cần đối chiếu ngưỡng."))
    if facts.age_info and (ctx.get("subject_requirements") or (ctx.get("article") or {}).get("article_code") == "12"):
        score += 0.15
    for consequence in facts.consequences:
        add("consequence", consequence, 0.15, "Hậu quả khớp context.")
    code = str((ctx.get("article") or {}).get("article_code") or "")
    if code in facts.article_refs:
        score += 0.30
    title = str((ctx.get("article") or {}).get("title") or "")
    if title and any(normalize_text(title) in normalize_text(h) or normalize_text(h) in normalize_text(title) for h in facts.crime_hints):
        score += 0.20
    if normalized:
        score += 0.10
    if ctx.get("penalty_frames"):
        score += 0.05
    article = ctx.get("article") or {}
    domain_text = normalize_text(" ".join(str(article.get(k) or "") for k in ["title", "chapter_name", "full_text"]))
    code = str(article.get("article_code") or "")
    action_norms = {normalize_text(a) for a in facts.actions}
    fact_object_text = normalize_text(" ".join(facts.objects))
    if facts.substances:
        non_drug_event_code = code in {"123", "178", "304"}
        if "ma tuy" in domain_text or any(normalize_text(s.name) in haystack for s in facts.substances):
            score += 0.25
        elif not non_drug_event_code:
            score -= 0.60
    if "to chuc su dung" in action_norms and code == "255":
        score += 0.35
    if "su dung" in action_norms and code == "256a":
        score += 0.25
    if ("mua" in action_norms or "mua ban" in action_norms) and code == "251":
        score += 0.30
    if "van chuyen" in action_norms and code == "250":
        score += 0.30
    if code == "123" and (
        {"ban", "no sung", "giet"} & action_norms
        or any(term in fact_object_text for term in ["sung", "sung ak"])
        or any(normalize_text(c) in {"chet nguoi", "tu vong", "hy sinh"} for c in facts.consequences)
    ):
        score += 0.70
    if code == "304" and any(term in fact_object_text for term in ["sung", "sung ak", "luu dan", "vu khi quan dung"]):
        score += 0.65
    if code == "178" and (
        "lam hu hong" in action_norms
        or any(normalize_text(c) in {"thiet hai", "hu hong"} for c in facts.consequences)
        or any(term in fact_object_text for term in ["xe", "tai san"])
    ):
        score += 0.55
    if code == "248" and "san xuat" not in action_norms:
        score -= 0.90
    if code == "252" and "chiem doat" not in action_norms:
        score -= 0.70
    if code == "250" and "van chuyen" not in action_norms:
        score -= 0.35
    if code == "254" and not any(x in fact_object_text for x in ["phuong tien", "dung cu"]):
        score -= 0.95
    score -= 0.15 * len(missing)
    return clamp(score), matched
