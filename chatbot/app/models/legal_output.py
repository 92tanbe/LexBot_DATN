"""Pydantic schema cho output cua LLM tra ve.

Bat buoc LLM gen JSON theo dung shape: actor -> toi danh -> hinh phat -> citation.
Nho do hau xu ly co the validate, downgrade confidence khi citation sai.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def normalize_vai_tro_value(raw: object) -> str:
    """CHuyen 'chính phạm', 'nan nhan' (co dau) -> literal ASCII trong schema."""
    if raw is None:
        return "khong xac dinh"
    s = str(raw).strip().lower()
    if not s:
        return "khong xac dinh"
    s = s.replace("đ", "d")
    nk = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in nk if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip()

    alias_map = {
        "bi hai": "nan nhan",
    }
    s = alias_map.get(s, s)

    allowed = frozenset(
        {
            "chinh pham",
            "dong pham",
            "chu muu",
            "giup suc",
            "xui giuc",
            "thuc hanh",
            "tong hop",
            "khong xac dinh",
            "nan nhan",
        }
    )
    if s in allowed:
        return s
    return "khong xac dinh"

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
    "khong xac dinh",
    "nan nhan",
]

ConfidenceLiteral = Literal["high", "medium", "low"]


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
    def _coerce_vai_tro_toi(cls, v: object) -> str:
        return normalize_vai_tro_value(v)


class ActorAnalysis(BaseModel):
    name: str
    vai_tro: VaiTroLiteral = "khong xac dinh"
    toi_danh: list[ToiDanhOutput] = Field(default_factory=list)
    nhan_xet: str | None = None

    @field_validator("vai_tro", mode="before")
    @classmethod
    def _coerce_vai_tro_actor(cls, v: object) -> str:
        return normalize_vai_tro_value(v)


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
