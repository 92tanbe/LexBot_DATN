from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.models.conversation import CaseSession, IssuedQuestionSet


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, CaseSession] = {}

    def create(self) -> CaseSession:
        session = CaseSession(case_id=str(uuid4()))
        self._sessions[session.case_id] = session
        return session

    def get(self, case_id: str) -> CaseSession | None:
        return self._sessions.get(case_id)

    def get_or_create(self, case_id: str | None) -> CaseSession:
        if case_id:
            existing = self.get(case_id)
            if existing:
                return existing
        return self.create()

    def save(self, session: CaseSession) -> CaseSession:
        session.updated_at = datetime.utcnow()
        self._sessions[session.case_id] = session
        return session

    def latest_question_set(self, session: CaseSession) -> IssuedQuestionSet | None:
        if not session.issued_question_sets:
            return None
        return session.issued_question_sets[-1]

    def question_owner_case_id(self, question_id: str) -> str | None:
        for case_id, session in self._sessions.items():
            for question_set in session.issued_question_sets:
                if any(question.id == question_id for question in question_set.questions):
                    return case_id
        return None

    def clear(self) -> None:
        self._sessions.clear()


session_store = InMemorySessionStore()
