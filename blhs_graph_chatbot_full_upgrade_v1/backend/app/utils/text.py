from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9.%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = normalize_text(item)
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def contains_any(text: str, terms: list[str]) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in terms)
