"""Evaluation pipeline RAG bang RAGAS metrics + retrieval recall.

Cach chay:
    cd <repo>
    python -m chatbot.eval.ragas_eval --limit 5 --skip-ragas
    python -m chatbot.eval.ragas_eval --report-out chatbot/eval/report.json

Metrics duoc bao cao:
- retrieval_recall@k : ti le case ma >= 1 expected_article xuat hien trong reranked.
- retrieval_full_recall@k : ti le case ma TAT CA expected_articles xuat hien.
- citation_match : ti le citation cuoi cung trung khop expected_articles.
- ragas (optional) : faithfulness, answer_relevancy, context_precision/recall.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.core.logging import setup_logging  # noqa: E402
from app.core.neo4j_driver import close_driver  # noqa: E402
from app.pipeline.orchestrator import run_pipeline  # noqa: E402

logger = logging.getLogger(__name__)


def load_cases(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    """Chay 1 case va tinh metrics."""
    question = case["question"]
    expected_articles = set(case.get("expected_articles") or [])

    t0 = time.time()
    resp = run_pipeline(question=question, top_k=10, include_debug=True)
    elapsed = time.time() - t0

    debug = resp.debug
    reranked_articles: set[int] = set()
    retrieved_articles: set[int] = set()
    if debug:
        for c in debug.reranked or []:
            if c.article is not None:
                reranked_articles.add(int(c.article))
        for c in debug.retrieved or []:
            if c.article is not None:
                retrieved_articles.add(int(c.article))

    citations_articles = {c.article for c in resp.citations}

    if expected_articles:
        recall_any = 1.0 if expected_articles & reranked_articles else 0.0
        recall_full = 1.0 if expected_articles.issubset(reranked_articles) else 0.0
        citation_recall = (
            len(expected_articles & citations_articles) / len(expected_articles)
        )
    else:
        recall_any = recall_full = citation_recall = None  # type: ignore[assignment]

    return {
        "id": case.get("id"),
        "question": question,
        "expected_articles": sorted(expected_articles),
        "retrieved_articles": sorted(retrieved_articles),
        "reranked_articles": sorted(reranked_articles),
        "citations_articles": sorted(citations_articles),
        "confidence": resp.confidence,
        "elapsed_s": round(elapsed, 2),
        "metrics": {
            "recall_any@10": recall_any,
            "recall_full@10": recall_full,
            "citation_recall": citation_recall,
        },
        "warnings": (debug.warnings if debug else []) or [],
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _avg(name: str) -> float | None:
        vals = [r["metrics"][name] for r in rows if r["metrics"].get(name) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    return {
        "n_cases": len(rows),
        "avg_recall_any@10": _avg("recall_any@10"),
        "avg_recall_full@10": _avg("recall_full@10"),
        "avg_citation_recall": _avg("citation_recall"),
        "avg_elapsed_s": round(sum(r["elapsed_s"] for r in rows) / max(1, len(rows)), 2),
        "low_confidence_rate": round(
            sum(1 for r in rows if r["confidence"] == "low") / max(1, len(rows)), 4
        ),
    }


def run_ragas(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """RAGAS optional - chi chay khi cai dat duoc va co OPENAI_API_KEY."""
    try:
        from datasets import Dataset
        from ragas import evaluate as ragas_evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("RAGAS chua san sang: %s. Bo qua.", exc)
        return None

    return None  # placeholder: cau hinh chuan se can ground-truth answer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases-file",
        default=str(Path(__file__).parent / "test_cases.yaml"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report-out", default=None)
    parser.add_argument("--skip-ragas", action="store_true", default=True)
    args = parser.parse_args()

    setup_logging()
    cases = load_cases(Path(args.cases_file))
    if args.limit:
        cases = cases[: args.limit]
    logger.info("Tong so case: %d", len(cases))

    rows: list[dict[str, Any]] = []
    try:
        for i, case in enumerate(cases, start=1):
            logger.info("[%d/%d] %s", i, len(cases), case.get("id"))
            try:
                result = evaluate_case(case)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Case %s loi", case.get("id"))
                result = {
                    "id": case.get("id"),
                    "question": case.get("question"),
                    "error": str(exc),
                }
            rows.append(result)
    finally:
        close_driver()

    summary = aggregate([r for r in rows if "error" not in r])
    logger.info("\n=== Summary ===")
    logger.info(json.dumps(summary, indent=2, ensure_ascii=False))

    report = {"summary": summary, "rows": rows}
    if args.report_out:
        out_path = Path(args.report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info("Da ghi report ra %s", out_path)


if __name__ == "__main__":
    main()
