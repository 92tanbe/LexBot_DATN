from __future__ import annotations

from uuid import uuid4

from app.models.agentic import ConversationState, LegalFacts


class InMemoryConversationStateStore:
    """Small replaceable state store for multi-turn Agentic RAG."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def get_state(self, conversation_id: str | None) -> ConversationState:
        if conversation_id and conversation_id in self._states:
            return self._states[conversation_id]
        state = ConversationState(conversation_id=conversation_id or str(uuid4()))
        self._states[state.conversation_id] = state
        return state

    def merge_facts(self, conversation_id: str, new_facts: LegalFacts) -> ConversationState:
        state = self.get_state(conversation_id)
        merged = state.facts.model_copy(deep=True)
        for field, value in new_facts.model_dump().items():
            if field == "raw_text":
                continue
            current = getattr(merged, field)
            if field == "article_refs":
                refs = list(dict.fromkeys([*current, *(value or [])]))
                setattr(merged, field, refs)
            elif value not in (None, "", "unknown", []):
                setattr(merged, field, value)
        merged.raw_text = " ".join([*state.raw_messages, new_facts.raw_text]).strip()
        state.facts = merged
        if new_facts.raw_text:
            state.raw_messages.append(new_facts.raw_text)
        self._states[state.conversation_id] = state
        return state

    def update_last_question(self, conversation_id: str, question: str) -> None:
        state = self.get_state(conversation_id)
        state.last_question = question
        self._states[state.conversation_id] = state

    def clear_state(self, conversation_id: str) -> None:
        self._states.pop(conversation_id, None)


conversation_state_store = InMemoryConversationStateStore()