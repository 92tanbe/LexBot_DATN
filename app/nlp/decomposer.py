"""Query decomposition: tach 1 cau hoi nhieu doi tuong thanh nhieu sub-query.

Vi du:
    "A va B cung cuop tai san, A dung dao, B la nguoi giup suc"
    -> [
        "A cuop tai san dung dao (vai tro: chinh pham)",
        "B la nguoi giup suc trong vu cuop tai san (vai tro: dong pham)",
        "Cau hoi tong: vu dong pham cuop tai san"
    ]
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.nlp.ner import CaseEntities

logger = logging.getLogger(__name__)


@dataclass
class SubQuery:
    """1 sub-query phuc vu retrieval rieng."""

    text: str
    actor_name: str | None = None
    role_hint: str | None = None
    actions: list[str] = None  # type: ignore[assignment]
    is_overall: bool = False

    def __post_init__(self) -> None:
        if self.actions is None:
            self.actions = []


def _normalize_role(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower().strip()
    mapping = {
        "chu muu": "chu muu",
        "tham muu": "chu muu",
        "chinh pham": "chinh pham",
        "dong pham": "dong pham",
        "giup suc": "giup suc",
        "xui giuc": "xui giuc",
        "xui": "xui giuc",
        "nan nhan": "nan nhan",
    }
    for key, val in mapping.items():
        if key in t:
            return val
    return text.strip()


def decompose(question: str, entities: CaseEntities) -> list[SubQuery]:
    """Sinh sub-query tu entities.

    Quy uoc:
    - 0 actor -> 1 sub-query duy nhat (la chinh cau hoi).
    - 1 actor -> 1 sub-query gan vai tro neu co.
    - >= 2 actor -> moi actor 1 sub-query + 1 sub-query tong hop.
    """
    actors = entities.actors or []

    if not actors:
        return [SubQuery(text=question, is_overall=True)]

    sub_queries: list[SubQuery] = []
    actions_global = entities.actions or []

    for actor in actors:
        action_str = ", ".join(actor.hanh_vi or actions_global[:3]) or "thuc hien hanh vi"
        role_hint = _normalize_role(actor.vai_tro)
        if not role_hint:
            for r in entities.roles:
                if r:
                    role_hint = _normalize_role(r)
                    break

        if role_hint and role_hint != "nan nhan":
            text = f"{actor.name} {action_str} (vai tro: {role_hint})"
        else:
            text = f"{actor.name} {action_str}"

        sub_queries.append(
            SubQuery(
                text=text,
                actor_name=actor.name,
                role_hint=role_hint,
                actions=actor.hanh_vi or list(actions_global),
            )
        )

    if len(actors) >= 2:
        # Tong hop ca tinh huong (vu dong pham)
        crime = entities.crime_hints[0] if entities.crime_hints else None
        actions_str = ", ".join(actions_global[:3]) if actions_global else None
        overall_parts = []
        if crime:
            overall_parts.append(crime)
        if actions_str:
            overall_parts.append(actions_str)
        overall_parts.append("dong pham nhieu nguoi")
        sub_queries.append(
            SubQuery(
                text=" ".join(overall_parts),
                is_overall=True,
                role_hint="dong pham",
                actions=list(actions_global),
            )
        )

    # Chong trung
    seen: set[str] = set()
    deduped: list[SubQuery] = []
    for sq in sub_queries:
        key = re.sub(r"\s+", " ", sq.text.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sq)
    return deduped
