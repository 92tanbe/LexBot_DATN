"""Pydantic schema cho output cua LLM tra ve.

Bat buoc LLM gen JSON theo dung shape: actor -> toi danh -> hinh phat -> citation.
Nho do hau xu ly co the validate, downgrade confidence khi citation sai.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


PenaltyType = Literal[
    "tu",
    "tu_chung_than",
    "tu_hinh",
    "cai_tao_khong_giam_giu",
    "phat_tien",
    "canh_cao",
    "quan_che",
    "cam_dam_nhiem",
    "khac",
]

VaiTroLiteral = Literal[
    "chinh pham",
    "dong pham",
    "chu muu",
    "giup suc",
    "xui giuc",
    "thuc hanh",
    "tong hop",
    "nan nhan",
    "khong xac dinh",
]

ConfidenceLiteral = Literal["high", "medium", "low"]


def _normalize_role_literal(value: str) -> str:
    """Chuan hoa vai tro LLM tra ve ve literal noi bo khong dau."""
    text = (value or "").strip().lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip()
    mapping = {
        "chinh pham": "chinh pham",
        "dong pham": "dong pham",
        "chu muu": "chu muu",
        "giup suc": "giup suc",
        "xui giuc": "xui giuc",
        "thuc hanh": "thuc hanh",
        "tong hop": "tong hop",
        "nan nhan": "nan nhan",
        "khong xac dinh": "khong xac dinh",
    }
    return mapping.get(text, text)


class HinhPhatOutput(BaseModel):
    loai: PenaltyType = "khac"
    min: float | None = None
    max: float | None = None
    don_vi: str | None = None  # nam, thang, dong
    extra: str | None = None


class CitationOutput(BaseModel):
    article: int
    clause: int | None = None
    rule_id: str | None = None
    ten_toi: str | None = None
    snippet: str | None = None


class ToiDanhOutput(BaseModel):
    dieu: int
    khoan: int | None = None
    ten_toi: str
    nhom_toi: str | None = None
    vai_tro: VaiTroLiteral = "khong xac dinh"
    tinh_tiet_tang_nang: list[str] = Field(default_factory=list)
    tinh_tiet_giam_nhe: list[str] = Field(default_factory=list)
    hinh_phat: HinhPhatOutput = Field(default_factory=HinhPhatOutput)
    ly_do: str | None = None
    citations: list[CitationOutput] = Field(default_factory=list)

    @field_validator("vai_tro", mode="before")
    @classmethod
    def _normalize_vai_tro(cls, v: str) -> str:
        return _normalize_role_literal(v)


class ActorAnalysis(BaseModel):
    name: str
    vai_tro: VaiTroLiteral = "khong xac dinh"
    toi_danh: list[ToiDanhOutput] = Field(default_factory=list)
    nhan_xet: str | None = None

    @field_validator("vai_tro", mode="before")
    @classmethod
    def _normalize_vai_tro(cls, v: str) -> str:
        return _normalize_role_literal(v)


class CaseAnalysis(BaseModel):
    summary: str
    actors: list[ActorAnalysis] = Field(default_factory=list)
    overall_advice: str | None = None
    confidence: ConfidenceLiteral = "medium"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _summary_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            return "Khong co tom tat."
        return v.strip()
