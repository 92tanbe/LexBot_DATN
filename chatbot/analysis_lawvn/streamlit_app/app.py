"""Streamlit demo cho Chatbot RAG BLHS.

Chay:
    cd <repo>
    streamlit run chatbot/streamlit_app/app.py

Co the dung 2 mode:
    1. local: import truc tiep pipeline (khong qua HTTP) - tien debug.
    2. http : goi service FastAPI dang chay.

Chinh qua sidebar.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


st.set_page_config(
    page_title="Chatbot RAG BLHS",
    # Khong dung shortcode ":...:" (co dau hai cham): tren Windows Streamlit co the
    # map thanh duong static loi, gay OSError WinError 123.
    page_icon="⚖️",
    layout="wide",
)


# ----------------------------- Sidebar -------------------------------------

with st.sidebar:
    st.title("LexBot RAG - Demo")
    st.caption("Hybrid RAG tren Bo luat Hinh su Viet Nam")

    mode = st.radio(
        "Mode",
        options=["local", "http"],
        index=0,
        help="local: import pipeline truc tiep | http: goi FastAPI dang chay",
    )

    api_url = st.text_input(
        "API URL",
        value=os.getenv("CHATBOT_API_URL", "http://127.0.0.1:8001"),
        disabled=(mode == "local"),
    )

    chat_mode_demo = st.radio(
        "Che do hoi",
        options=[
            ("Tra cuu VB PDF + chat nhanh (mac dinh)", "tra_cuu_pdf"),
            ("Phan tich tinh huong (Neo4j + LLM)", "phan_tich"),
        ],
        format_func=lambda item: item[0],
        index=0,
        help="PDF: dat file P1 VB-Hop-nhat-BLHS-2025.pdf vao dataset/ hoac BLHS_PDF_PATH.",
    )
    chat_mode_value = chat_mode_demo[1]

    top_k = st.slider("Top-K (sau rerank)", min_value=3, max_value=20, value=8)
    show_debug = st.toggle("Hien thi debug retrieval", value=True)
    use_stream = st.toggle("Stream tung giai doan (mode http)", value=False)

    st.divider()
    st.caption("Cac vi du nhanh:")
    examples = [
        "Toi cuop tai san tri gia 100 trieu thi bi xu phat the nao?",
        "A va B cung cuop, A dung dao, B canh gac. Hinh phat ra sao?",
        "Giet 2 nguoi co bi tu hinh khong?",
        "Tham o tai san nha nuoc 1 ty dong bi xu the nao?",
        "Lai xe gay tai nan chet 1 nguoi, vuot den do, bi xu phat sao?",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["question"] = ex


# --------------------------- Main ------------------------------------------

st.markdown("## Chatbot RAG Bo luat Hinh su")

question = st.text_area(
    "Nhap tinh huong / cau hoi phap ly:",
    value=st.session_state.get("question", ""),
    height=120,
    placeholder="VD: Toi cuop xe may co dung dao, gia tri 30 trieu, bi xu phat the nao?",
)

run_btn = st.button("Phan tich", type="primary", use_container_width=True)


# ---------------------- Helper functions -----------------------------------


def _format_chunk_card(chunk: dict, idx: int) -> None:
    """Render 1 chunk dang card."""
    with st.container(border=True):
        head_parts = [f"#{idx}"]
        if chunk.get("article") is not None:
            head_parts.append(f"Dieu {chunk['article']}")
        if chunk.get("clause") is not None:
            head_parts.append(f"khoan {chunk['clause']}")
        if chunk.get("dieu_name"):
            head_parts.append(f"- {chunk['dieu_name']}")
        st.markdown("**" + " ".join(str(p) for p in head_parts) + "**")

        score_parts = []
        if chunk.get("rerank_score") is not None:
            score_parts.append(f"rerank={chunk['rerank_score']:.3f}")
        if chunk.get("rrf_score") is not None:
            score_parts.append(f"rrf={chunk['rrf_score']:.4f}")
        if chunk.get("source"):
            score_parts.append(f"src={chunk['source']}")
        if score_parts:
            st.caption(" | ".join(score_parts))

        text = chunk.get("text") or ""
        if text:
            st.text(text[:600] + (" ..." if len(text) > 600 else ""))
        if chunk.get("rule_id"):
            st.caption(f"rule_id={chunk['rule_id']}")


def _render_response(resp: dict) -> None:
    """Render ChatResponse."""
    final = resp.get("final_answer", "")
    confidence = resp.get("confidence", "medium")
    color = {"high": "green", "medium": "blue", "low": "red"}.get(confidence, "gray")

    st.markdown(f":{color}[**Do tin cay: {confidence.upper()}**]")
    st.markdown(final)

    citations = resp.get("citations", [])
    if citations:
        st.markdown("### Trich dan")
        for c in citations:
            head = f"- **Dieu {c['article']}**"
            if c.get("clause"):
                head += f" khoan {c['clause']}"
            if c.get("ten_toi"):
                head += f" - {c['ten_toi']}"
            if c.get("rule_id"):
                head += f" (`{c['rule_id']}`)"
            st.markdown(head)
            if c.get("snippet"):
                st.caption(c["snippet"])

    if show_debug and resp.get("debug"):
        debug = resp["debug"]
        with st.expander("Debug - Entities + Sub-queries"):
            st.json(debug.get("entities") or {})
            st.write("**Sub-queries**:", debug.get("sub_queries", []))
            st.write("**Cypher used**:", debug.get("cypher_used", []))
            if debug.get("timings_ms"):
                st.write("**Timings (ms)**:", debug["timings_ms"])
            if debug.get("warnings"):
                st.warning("\n".join(debug["warnings"]))

        with st.expander(f"Debug - Retrieved ({len(debug.get('retrieved', []))})"):
            for i, ch in enumerate(debug.get("retrieved", []), start=1):
                _format_chunk_card(ch, i)

        with st.expander(f"Debug - Reranked ({len(debug.get('reranked', []))})"):
            for i, ch in enumerate(debug.get("reranked", []), start=1):
                _format_chunk_card(ch, i)

    with st.expander("Structured output (Pydantic)"):
        st.json(resp.get("structured", {}))


def _call_local(
    question: str,
    top_k: int,
    include_debug: bool,
    chat_mode: str,
) -> dict:
    if chat_mode == "tra_cuu_pdf":
        from app.pipeline.pdf_textbook import run_pdf_lookup_pipeline

        resp = run_pdf_lookup_pipeline(question=question, include_debug=include_debug)
    else:
        from app.pipeline.orchestrator import run_pipeline

        resp = run_pipeline(
            question=question, top_k=top_k, include_debug=include_debug
        )

    return resp.model_dump()


def _call_http(
    api_url: str, question: str, top_k: int, include_debug: bool, chat_mode: str
) -> dict:
    import requests

    r = requests.post(
        f"{api_url.rstrip('/')}/rag/query",
        json={
            "question": question,
            "top_k": top_k,
            "include_debug": include_debug,
            "chat_mode": chat_mode,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _stream_http(
    api_url: str,
    question: str,
    top_k: int,
    include_debug: bool,
    chat_mode: str,
):
    import requests

    with requests.post(
        f"{api_url.rstrip('/')}/rag/query/stream",
        json={
            "question": question,
            "top_k": top_k,
            "include_debug": include_debug,
            "chat_mode": chat_mode,
        },
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        current_event = None
        for raw_line in r.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            line = raw_line.strip()
            if not line:
                current_event = None
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"raw": payload}
                yield current_event or "message", data


# ----------------------------- Submit handler -------------------------------

if run_btn and question.strip():
    placeholder = st.empty()
    progress_box = st.container()
    with placeholder.container():
        with st.spinner("Dang phan tich..."):
            t0 = time.time()
            try:
                if mode == "local":
                    resp = _call_local(
                        question.strip(), top_k, show_debug, chat_mode_value
                    )
                elif use_stream:
                    log_area = progress_box.empty()
                    log_lines: list[str] = []
                    final_resp: dict = {}
                    for event, data in _stream_http(
                        api_url,
                        question.strip(),
                        top_k,
                        show_debug,
                        chat_mode_value,
                    ):
                        log_lines.append(f"**{event}**: {json.dumps(data, ensure_ascii=False)[:300]}")
                        log_area.markdown("\n\n".join(log_lines[-12:]))
                        if event == "final":
                            final_resp = {
                                "question": question.strip(),
                                "final_answer": data.get("final_answer", ""),
                                "structured": data.get("structured", {}),
                                "citations": data.get("citations", []),
                                "confidence": data.get("confidence", "medium"),
                                "debug": None,
                            }
                    resp = final_resp or {"final_answer": "(Khong nhan duoc final event)"}
                else:
                    resp = _call_http(
                        api_url,
                        question.strip(),
                        top_k,
                        show_debug,
                        chat_mode_value,
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Loi khi goi pipeline: {exc}")
                resp = None

    if resp:
        st.success(f"Hoan tat sau {time.time() - t0:.1f}s")
        _render_response(resp)
