from __future__ import annotations

from copy import deepcopy
from typing import Any


def reciprocal_rank_fusion(result_lists: list[list[dict[str, Any]]], k: int = 60) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, item in enumerate(results, start=1):
            code = str(item.get("article_code") or "")
            if not code:
                continue
            scores[code] = scores.get(code, 0.0) + 1.0 / (k + rank)
            if code not in fused:
                fused[code] = deepcopy(item)
                fused[code]["sources"] = []
                fused[code]["matched_terms"] = list(item.get("matched_terms") or [])
                fused[code]["raw_scores"] = []
            source = item.get("source")
            if source and source not in fused[code]["sources"]:
                fused[code]["sources"].append(source)
            if item.get("score") is not None:
                fused[code]["raw_scores"].append({"source": source, "score": item.get("score")})
            for term in item.get("matched_terms") or []:
                if term not in fused[code]["matched_terms"]:
                    fused[code]["matched_terms"].append(term)
    out: list[dict[str, Any]] = []
    for code, item in fused.items():
        item["score"] = scores[code]
        item["source"] = "+".join(item.get("sources") or ["rrf"])
        out.append(item)
    return sorted(out, key=lambda x: x.get("score", 0.0), reverse=True)
