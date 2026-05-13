"""Smoke test ket noi OpenAI - xac nhan key, model, JSON mode hoat dong.

Cach chay:
    cd chatbot
    python -m ingestion.test_openai
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.core.config import settings  # noqa: E402


def main() -> None:
    print(f"Env file da load: {settings.env_file_path}")
    print(f"OPENAI_MODEL    : {settings.openai_model}")
    if not settings.openai_api_key:
        print("KHONG CO OPENAI_API_KEY trong env!")
        sys.exit(1)
    masked = settings.openai_api_key[:8] + "..." + settings.openai_api_key[-4:]
    print(f"OPENAI_API_KEY  : {masked}")

    try:
        from openai import OpenAI
    except ImportError as exc:
        print(f"openai SDK chua cai: {exc}")
        sys.exit(2)

    client = OpenAI(api_key=settings.openai_api_key)

    # Test 1: Plain completion
    print("\n[1] Test chat.completions ngan...")
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            max_tokens=20,
            messages=[
                {"role": "user", "content": "Tra ve duy nhat chuoi 'PONG' trong 1 dong."}
            ],
        )
        msg = resp.choices[0].message.content
        print(f"  -> response: {msg!r}")
        print(f"  -> finish_reason: {resp.choices[0].finish_reason}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        sys.exit(3)

    # Test 2: JSON mode
    print("\n[2] Test chat.completions voi JSON mode...")
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Tra ve JSON hop le."},
                {
                    "role": "user",
                    "content": (
                        "Tra ve JSON co cau truc:"
                        " {\"summary\":\"...\",\"actors\":[],\"confidence\":\"high\"}"
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content
        print(f"  -> raw: {raw}")
        data = json.loads(raw)
        print(f"  -> parsed keys: {list(data.keys())}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        sys.exit(4)

    # Test 3: Try the same model used in prompts
    print("\n[3] Test prompt thuc te (rut gon)...")
    try:
        from app.pipeline.prompts import SYSTEM_PROMPT, build_user_prompt

        user_prompt = build_user_prompt(
            question="Toi cuop tai san 100 trieu",
            entities_json="{}",
            context="[#1] Dieu 168 - Toi cuop tai san\nrule_id=168_r1\nVi du context.",
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            max_tokens=800,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content
        print(f"  -> usage: {getattr(resp, 'usage', None)}")
        print(f"  -> finish_reason: {resp.choices[0].finish_reason}")
        data = json.loads(raw)
        print(f"  -> parsed keys: {list(data.keys())}")
        if "actors" in data:
            print(f"  -> actors count: {len(data.get('actors', []))}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        sys.exit(5)

    print("\nAll tests PASS - LLM san sang.")


if __name__ == "__main__":
    main()
