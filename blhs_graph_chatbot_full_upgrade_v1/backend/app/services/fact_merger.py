from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from app.models.conversation import FactPatch
from app.models.facts import Actor, EvidenceSource, ExhibitFact, ExhibitStatus, ExtractedFacts, FactConflict, ForensicStatus, Quantity, SubstanceFact
from app.utils.text import normalize_text

T = TypeVar("T", bound=BaseModel)


def _key(value: object) -> str:
    return normalize_text(str(value or "")).strip()


def _source_rank(source: str | EvidenceSource | None) -> int:
    value = source.value if isinstance(source, EvidenceSource) else str(source or "")
    return {
        EvidenceSource.forensic_report.value: 5,
        EvidenceSource.police_record.value: 4,
        EvidenceSource.electronic_evidence.value: 3,
        EvidenceSource.toxicology_test.value: 2,
        EvidenceSource.user_statement.value: 1,
        EvidenceSource.system_inference.value: 0,
        EvidenceSource.unknown.value: 0,
    }.get(value, 0)


def _evidence_source(value: str | None) -> EvidenceSource:
    try:
        return EvidenceSource(value or EvidenceSource.user_statement.value)
    except ValueError:
        return EvidenceSource.user_statement


def _forensic_status(value: Any) -> ForensicStatus:
    try:
        return ForensicStatus(str(value))
    except ValueError:
        return ForensicStatus.unknown


def _set_structured_fact(facts: ExtractedFacts, path: str, value: Any) -> None:
    existing = facts.structured_facts.get(path)
    if existing not in (None, "", [], {}) and value not in (None, "", [], {}) and existing != value:
        facts.conflicts.append(FactConflict(path=path, existing_value=existing, incoming_value=value))
    facts.structured_facts[path] = value


def _is_specific(text: str | None) -> bool:
    if not text:
        return False
    norm = normalize_text(text)
    return not any(term in norm for term in ["chua ro", "khong ro", "khong biet", "khong xac dinh", "co"])


def _merge_strings(old: list[str], new: list[str]) -> list[str]:
    merged = list(old)
    seen = {_key(item) for item in merged}
    for item in new:
        key = _key(item)
        if key and key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _merge_quantities(old: list[Quantity], new: list[Quantity]) -> list[Quantity]:
    merged = list(old)
    seen = {(_key(q.raw_text), _key(q.unit), q.value) for q in merged}
    for quantity in new:
        key = (_key(quantity.raw_text), _key(quantity.unit), quantity.value)
        if key not in seen:
            merged.append(quantity)
            seen.add(key)
    return merged


def _merge_actors(old: list[Actor], new: list[Actor]) -> list[Actor]:
    merged = [actor.model_copy(deep=True) for actor in old]
    by_name = {_key(actor.name): actor for actor in merged}
    for actor in new:
        key = _key(actor.name)
        if not key:
            continue
        current = by_name.get(key)
        if not current:
            copied = actor.model_copy(deep=True)
            merged.append(copied)
            by_name[key] = copied
            continue
        if actor.age is not None:
            current.age = actor.age
        if _is_specific(actor.role) and not _is_specific(current.role):
            current.role = actor.role
        if _is_specific(actor.notes) and not _is_specific(current.notes):
            current.notes = actor.notes
    return merged


def _merge_substances(old: list[SubstanceFact], new: list[SubstanceFact]) -> list[SubstanceFact]:
    merged = [substance.model_copy(deep=True) for substance in old]
    by_name = {_key(substance.name): substance for substance in merged}
    for substance in new:
        key = _key(substance.name)
        if not key:
            continue
        current = by_name.get(key)
        if not current:
            copied = substance.model_copy(deep=True)
            merged.append(copied)
            by_name[key] = copied
            continue
        if not current.quantity and substance.quantity:
            current.quantity = substance.quantity
        if not current.alias and substance.alias:
            current.alias = substance.alias
        current.confidence = max(current.confidence, substance.confidence)
    return merged


def _merge_exhibits(old: list[ExhibitFact], new: list[ExhibitFact]) -> list[ExhibitFact]:
    merged = [exhibit.model_copy(deep=True) for exhibit in old]
    by_id = {_key(exhibit.id): exhibit for exhibit in merged if exhibit.id}
    seen = {(_key(exhibit.status), _key(exhibit.description)) for exhibit in merged}
    for exhibit in new:
        current = by_id.get(_key(exhibit.id))
        if current:
            incoming_rank = _source_rank(exhibit.evidence_source)
            current_rank = _source_rank(current.evidence_source)
            if exhibit.quantity and (not current.quantity or incoming_rank >= current_rank):
                current.quantity = exhibit.quantity
            if exhibit.suspected_substance and not current.suspected_substance:
                current.suspected_substance = exhibit.suspected_substance
            if exhibit.confirmed_substance:
                if current.confirmed_substance and current.confirmed_substance != exhibit.confirmed_substance and incoming_rank < current_rank:
                    continue
                current.confirmed_substance = exhibit.confirmed_substance
                current.forensic_status = ForensicStatus.forensic_confirmed
            if exhibit.forensic_status != ForensicStatus.unknown and incoming_rank >= current_rank:
                current.forensic_status = exhibit.forensic_status
            current.confidence = max(current.confidence, exhibit.confidence)
            if incoming_rank >= current_rank:
                current.evidence_source = exhibit.evidence_source
            continue
        key = (_key(exhibit.status), _key(exhibit.description))
        if key in seen:
            continue
        copied = exhibit.model_copy(deep=True)
        merged.append(copied)
        if copied.id:
            by_id[_key(copied.id)] = copied
        seen.add(key)
    return merged


def _infer_exhibit_from_forensic(facts: ExtractedFacts) -> None:
    has_forensic = any("giám định" in item for item in facts.evidence)
    if has_forensic and facts.quantities and facts.substances and not facts.exhibits:
        facts.exhibits.append(ExhibitFact(
            status=ExhibitStatus.seized,
            description="Có kết luận giám định và định lượng được nêu trong hồ sơ.",
            quantity=facts.quantities[0],
            source_text="kết luận giám định/định lượng",
            evidence_source=EvidenceSource.forensic_report,
            forensic_status=ForensicStatus.forensic_confirmed,
            confirmed_substance=facts.substances[0].name,
            confidence=0.95,
        ))
    if has_forensic and facts.substances:
        net_quantities = [q for q in facts.quantities if (q.unit or "").lower() in {"g", "gam", "kg", "mg"}]
        for idx, exhibit in enumerate(facts.exhibits):
            if not exhibit.confirmed_substance:
                substance = facts.substances[min(idx, len(facts.substances) - 1)].name
                exhibit.confirmed_substance = exhibit.suspected_substance or substance
            exhibit.forensic_status = ForensicStatus.forensic_confirmed
            exhibit.evidence_source = EvidenceSource.forensic_report
            exhibit.confidence = max(exhibit.confidence, 0.95)
            if not exhibit.quantity and net_quantities:
                exhibit.quantity = net_quantities[min(idx, len(net_quantities) - 1)]


def merge_facts(old: ExtractedFacts | None, new: ExtractedFacts) -> ExtractedFacts:
    base = (old or ExtractedFacts()).model_copy(deep=True)
    base.actors = _merge_actors(base.actors, new.actors)
    base.actions = _merge_strings(base.actions, new.actions)
    base.objects = _merge_strings(base.objects, new.objects)
    base.substances = _merge_substances(base.substances, new.substances)
    base.exhibits = _merge_exhibits(base.exhibits, new.exhibits)
    base.quantities = _merge_quantities(base.quantities, new.quantities)
    base.consequences = _merge_strings(base.consequences, new.consequences)
    base.age_info = _merge_strings(base.age_info, new.age_info)
    base.intent = _merge_strings(base.intent, new.intent)
    base.mental_state = _merge_strings(base.mental_state, new.mental_state)
    base.evidence = _merge_strings(base.evidence, new.evidence)
    base.location = _merge_strings(base.location, new.location)
    base.article_refs = _merge_strings(base.article_refs, new.article_refs)
    base.crime_hints = _merge_strings(base.crime_hints, new.crime_hints)
    base.mitigating_signals = _merge_strings(base.mitigating_signals, new.mitigating_signals)
    base.aggravating_signals = _merge_strings(base.aggravating_signals, new.aggravating_signals)
    base.unknowns = _merge_strings(base.unknowns, new.unknowns)
    for path, value in new.structured_facts.items():
        _set_structured_fact(base, path, value)
    _infer_exhibit_from_forensic(base)
    return base


def _get_or_create_exhibit(facts: ExtractedFacts, exhibit_id: str, evidence_source: EvidenceSource) -> ExhibitFact:
    for exhibit in facts.exhibits:
        if _key(exhibit.id) == _key(exhibit_id):
            return exhibit
    exhibit = ExhibitFact(
        id=exhibit_id,
        status=ExhibitStatus.seized if evidence_source == EvidenceSource.forensic_report else ExhibitStatus.mentioned,
        description=f"Tang vật {exhibit_id}",
        form="tablets" if exhibit_id == "tablets" else "powder" if exhibit_id == "powder" else None,
        evidence_source=evidence_source,
        confidence=0.8,
    )
    facts.exhibits.append(exhibit)
    return exhibit


def _append_string(values: list[str], value: str) -> list[str]:
    return _merge_strings(values, [value])


def _apply_exhibit_patch(facts: ExtractedFacts, patch: FactPatch, parts: list[str], value: Any) -> None:
    if len(parts) < 3:
        _set_structured_fact(facts, patch.path, value)
        return
    exhibit_id, field = parts[1], parts[2]
    evidence_source = _evidence_source(patch.evidence_source)
    exhibit = _get_or_create_exhibit(facts, exhibit_id, evidence_source)
    incoming_rank = _source_rank(evidence_source)
    current_rank = _source_rank(exhibit.evidence_source)

    if field == "confirmed_substance":
        if exhibit.confirmed_substance and exhibit.confirmed_substance != value and incoming_rank < current_rank:
            facts.conflicts.append(FactConflict(
                path=patch.path,
                existing_value=exhibit.confirmed_substance,
                incoming_value=value,
                existing_source=exhibit.evidence_source.value,
                incoming_source=evidence_source.value,
            ))
            return
        exhibit.confirmed_substance = str(value)
        if value == "not_narcotic":
            exhibit.forensic_status = ForensicStatus.denied
        elif value not in {"unknown", "not_available"}:
            exhibit.forensic_status = ForensicStatus.forensic_confirmed
        exhibit.evidence_source = evidence_source if incoming_rank >= current_rank else exhibit.evidence_source
        exhibit.confidence = max(exhibit.confidence, patch.confidence)
    elif field == "forensic_status":
        status = _forensic_status(value)
        if incoming_rank >= current_rank or exhibit.forensic_status in {ForensicStatus.unknown, ForensicStatus.mentioned, ForensicStatus.suspected}:
            exhibit.forensic_status = status
            exhibit.evidence_source = evidence_source if incoming_rank >= current_rank else exhibit.evidence_source
            exhibit.confidence = max(exhibit.confidence, patch.confidence)
    elif field == "quantity" and len(parts) >= 4 and parts[3] == "value":
        numeric_value = float(value)
        exhibit.quantity = Quantity(value=numeric_value, unit="g", raw_text=f"{numeric_value:g} g", object=exhibit_id)
        facts.quantities = _merge_quantities(facts.quantities, [exhibit.quantity])
    else:
        setattr(exhibit, field, value)
    _set_structured_fact(facts, patch.path, value)


def apply_fact_patches(old: ExtractedFacts | None, patches: list[FactPatch]) -> ExtractedFacts:
    facts = (old or ExtractedFacts()).model_copy(deep=True)
    for patch in patches:
        value = patch.value
        if value in (None, ""):
            continue
        parts = patch.path.split(".")
        if patch.path == "unknowns":
            facts.unknowns = _append_string(facts.unknowns, str(value))
            continue
        if patch.path in {"mental_state", "intent", "evidence"}:
            current = getattr(facts, patch.path)
            setattr(facts, patch.path, _append_string(current, str(value)))
            continue
        if patch.path == "substances":
            if isinstance(value, dict):
                name = str(value.get("name") or "").strip()
                if name and name not in {"__free_text__", "not_narcotic", "unknown"}:
                    facts.substances = _merge_substances(facts.substances, [
                        SubstanceFact(
                            name=name,
                            confidence=float(value.get("confidence") or patch.confidence),
                            evidence_source=_evidence_source(str(value.get("evidence_source") or patch.evidence_source or EvidenceSource.user_statement.value)),
                        )
                    ])
            continue
        if parts[0] == "exhibits":
            _apply_exhibit_patch(facts, patch, parts, value)
            continue
        _set_structured_fact(facts, patch.path, value)
    return facts
