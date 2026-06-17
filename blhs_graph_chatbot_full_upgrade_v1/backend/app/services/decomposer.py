from __future__ import annotations

from dataclasses import dataclass, field

from app.models.facts import ExtractedFacts


@dataclass
class SubQuery:
    text: str
    actor_name: str | None = None
    role_hint: str | None = None
    actions: list[str] = field(default_factory=list)
    is_overall: bool = False


def decompose_query(scenario: str, facts: ExtractedFacts) -> list[SubQuery]:
    if not facts.actors:
        return [SubQuery(text=scenario, actions=facts.actions, is_overall=True)]
    out: list[SubQuery] = []
    for actor in facts.actors:
        role = actor.role
        if not role:
            for hint in ["giúp sức", "xúi giục", "chủ mưu", "cầm đầu", "che giấu", "không tố giác"]:
                if hint in facts.actions:
                    role = hint
                    break
        text = " ".join([actor.name, role or "", ", ".join(facts.actions[:4]), ", ".join(facts.objects[:3])]).strip()
        out.append(SubQuery(text=text or scenario, actor_name=actor.name, role_hint=role, actions=facts.actions))
    if len(facts.actors) >= 2:
        out.append(SubQuery(text=f"{scenario} đồng phạm nhiều người vai trò từng người", role_hint="đồng phạm", actions=facts.actions, is_overall=True))
    else:
        out.append(SubQuery(text=scenario, actions=facts.actions, is_overall=True))
    seen: set[str] = set()
    deduped: list[SubQuery] = []
    for item in out:
        key = item.text.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped
