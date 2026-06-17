from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
IMPORT_DIR = ROOT / "neo4j_import"
BACKEND_DIR = ROOT / "backend" / "app"
TEST_DIR = ROOT / "backend" / "tests"
OUTPUT_DIR = ROOT / "docs" / "assets"
OUTPUT_PATH = OUTPUT_DIR / "blhs_project_dashboard.png"


NODE_FILES = {
    "Law": "laws.csv",
    "Part": "parts.csv",
    "Chapter": "chapters.csv",
    "Section": "sections.csv",
    "Article": "articles.csv",
    "Clause": "clauses.csv",
    "Point": "points.csv",
    "Crime": "crimes.csv",
    "Rule": "rules.csv",
    "Condition": "conditions.csv",
    "PenaltyFrame": "penalty_frames.csv",
    "Penalty": "penalties.csv",
    "LegalConcept": "legal_concepts.csv",
    "AggravatingFactor": "aggravating_factors.csv",
    "MitigatingFactor": "mitigating_factors.csv",
    "JudicialMeasure": "judicial_measures.csv",
    "SubjectRequirement": "subject_requirements.csv",
    "ObjectRequirement": "object_requirements.csv",
    "ActRequirement": "act_requirements.csv",
    "ConsequenceRequirement": "consequence_requirements.csv",
    "QuantityThreshold": "quantity_thresholds.csv",
    "Exception": "exceptions.csv",
    "Reference": "references.csv",
    "SlangTerm": "slang_terms.csv",
    "ActionAlias": "action_aliases.csv",
    "LegalSignal": "legal_signals.csv",
    "SubstanceAlias": "substance_aliases.csv",
    "Substance": "substances.csv",
}

RELATIONSHIP_FILES = {
    "SignalArticleLink": "signal_article_links.csv",
    "ScenarioFact": "scenario_facts.csv",
    "MatchedCondition": "matched_conditions.csv",
}


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        next(reader, None)
        return sum(1 for _ in reader)


def count_endpoint_routes() -> int:
    route_pattern = re.compile(r"@router\.(get|post|put|patch|delete)\(")
    count = 0
    for path in (BACKEND_DIR / "routers").glob("*.py"):
        count += len(route_pattern.findall(path.read_text(encoding="utf-8")))
    app_main = BACKEND_DIR / "main.py"
    if app_main.exists():
        count += len(re.findall(r"@app\.(get|post|put|patch|delete)\(", app_main.read_text(encoding="utf-8")))
    return count


def count_python_files(path: Path) -> int:
    return len(list(path.rglob("*.py"))) if path.exists() else 0


def add_bar_labels(ax, bars, *, fontsize: int = 8, integer: bool = True, pad: float = 0.01) -> None:
    for bar in bars:
        width = bar.get_width()
        label = f"{int(width):,}" if integer else f"{width:.2f}"
        ax.text(
            width + max(width * pad, 0.5),
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            fontsize=fontsize,
        )


def generate_dashboard() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts = {label: count_csv_rows(IMPORT_DIR / filename) for label, filename in NODE_FILES.items()}
    relationship_counts = {
        label: count_csv_rows(IMPORT_DIR / filename) for label, filename in RELATIONSHIP_FILES.items()
    }

    legal_structure = {
        "Law": counts["Law"],
        "Part": counts["Part"],
        "Chapter": counts["Chapter"],
        "Section": counts["Section"],
        "Article": counts["Article"],
        "Clause": counts["Clause"],
        "Point": counts["Point"],
    }
    semantic_groups = {
        "Crimes": counts["Crime"],
        "Rules": counts["Rule"],
        "Conditions": counts["Condition"],
        "Penalty frames": counts["PenaltyFrame"],
        "Penalties": counts["Penalty"],
        "References": counts["Reference"],
        "Quantity thresholds": counts["QuantityThreshold"],
        "Requirements": counts["SubjectRequirement"]
        + counts["ObjectRequirement"]
        + counts["ActRequirement"]
        + counts["ConsequenceRequirement"],
    }
    nlp_mapping = {
        "Legal concepts": counts["LegalConcept"],
        "Slang terms": counts["SlangTerm"],
        "Action aliases": counts["ActionAlias"],
        "Legal signals": counts["LegalSignal"],
        "Substances": counts["Substance"],
        "Substance aliases": counts["SubstanceAlias"],
        "Signal links": relationship_counts["SignalArticleLink"],
    }
    backend_kpis = {
        "API routes": count_endpoint_routes(),
        "Backend .py": count_python_files(BACKEND_DIR),
        "Services": count_python_files(BACKEND_DIR / "services"),
        "Routers": count_python_files(BACKEND_DIR / "routers"),
        "Tests": len([p for p in TEST_DIR.glob("test_*.py")]) if TEST_DIR.exists() else 0,
        "Cypher files": len(list((ROOT / "cypher").glob("*.cypher"))),
        "Import CSV": len(list(IMPORT_DIR.glob("*.csv"))),
    }

    total_static_nodes = sum(counts.values())
    total_runtime_rows = relationship_counts["ScenarioFact"] + relationship_counts["MatchedCondition"]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")

    fig = plt.figure(figsize=(16, 10), dpi=180)
    grid = fig.add_gridspec(3, 2, height_ratios=[0.9, 1.05, 1.05], hspace=0.58, wspace=0.28)
    ax_kpi = fig.add_subplot(grid[0, :])
    ax_structure = fig.add_subplot(grid[1, 0])
    ax_semantic = fig.add_subplot(grid[1, 1])
    ax_nlp = fig.add_subplot(grid[2, 0])
    ax_backend = fig.add_subplot(grid[2, 1])

    fig.suptitle(
        f"BLHS Graph Chatbot Project Dashboard | generated={generated_at}",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )

    kpi_labels = [
        "Static graph rows",
        "Articles",
        "Rules",
        "Conditions",
        "Quantity thresholds",
        "Penalty frames",
        "CSV files",
        "Backend routes",
    ]
    kpi_values = [
        total_static_nodes,
        counts["Article"],
        counts["Rule"],
        counts["Condition"],
        counts["QuantityThreshold"],
        counts["PenaltyFrame"],
        backend_kpis["Import CSV"],
        backend_kpis["API routes"],
    ]
    kpi_colors = ["#2c3e50", "#2980b9", "#16a085", "#27ae60", "#8e44ad", "#d35400", "#7f8c8d", "#c0392b"]
    x = np.arange(len(kpi_labels))
    bars = ax_kpi.bar(x, kpi_values, color=kpi_colors, edgecolor="white", linewidth=0.8)
    ax_kpi.set_title("Project KPIs from Current Repository Data", fontsize=10)
    ax_kpi.set_xticks(x)
    ax_kpi.set_xticklabels(kpi_labels, rotation=18, ha="right", fontsize=8)
    ax_kpi.set_yscale("log")
    ax_kpi.set_ylabel("Count (log scale)")
    ax_kpi.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, kpi_values):
        ax_kpi.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.09,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    structure_items = sorted(legal_structure.items(), key=lambda item: item[1])
    bars = ax_structure.barh(
        [item[0] for item in structure_items],
        [item[1] for item in structure_items],
        color="#2980b9",
    )
    ax_structure.set_title("Legal Structure Layer", fontsize=10)
    ax_structure.set_xlabel("Rows")
    ax_structure.grid(axis="x", alpha=0.25)
    add_bar_labels(ax_structure, bars)

    semantic_items = sorted(semantic_groups.items(), key=lambda item: item[1])
    bars = ax_semantic.barh(
        [item[0] for item in semantic_items],
        [item[1] for item in semantic_items],
        color="#27ae60",
    )
    ax_semantic.set_title("Legal Meaning, Rules and Penalty Data", fontsize=10)
    ax_semantic.set_xlabel("Rows")
    ax_semantic.grid(axis="x", alpha=0.25)
    add_bar_labels(ax_semantic, bars)

    nlp_items = sorted(nlp_mapping.items(), key=lambda item: item[1])
    bars = ax_nlp.barh(
        [item[0] for item in nlp_items],
        [item[1] for item in nlp_items],
        color="#8e44ad",
    )
    ax_nlp.set_title("NLP Mapping and Legal Signals", fontsize=10)
    ax_nlp.set_xlabel("Rows")
    ax_nlp.grid(axis="x", alpha=0.25)
    add_bar_labels(ax_nlp, bars)

    backend_items = sorted(backend_kpis.items(), key=lambda item: item[1])
    bars = ax_backend.barh(
        [item[0] for item in backend_items],
        [item[1] for item in backend_items],
        color="#d35400",
    )
    ax_backend.set_title("Backend, API and Tooling Coverage", fontsize=10)
    ax_backend.set_xlabel("Count")
    ax_backend.grid(axis="x", alpha=0.25)
    add_bar_labels(ax_backend, bars)

    fig.text(
        0.5,
        0.015,
        (
            "Nguồn số liệu: neo4j_import/*.csv, backend/app, backend/tests và cypher. "
            f"Runtime rows hiện tại: {total_runtime_rows:,}."
        ),
        ha="center",
        fontsize=9,
        style="italic",
    )

    fig.savefig(OUTPUT_PATH, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    generate_dashboard()
    print(OUTPUT_PATH)
