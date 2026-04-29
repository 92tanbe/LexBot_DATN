"""Pydantic schema cho output cua LLM tra ve.

Bat buoc LLM gen JSON theo dung shape: actor -> toi danh -> hinh phat -> citation.
Nho do hau xu ly co the validate, downgrade confidence khi citation sai.
"""
from __future__ import annotations

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
    "khong xac dinh",
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


class ActorAnalysis(BaseModel):
    name: str
    vai_tro: VaiTroLiteral = "khong xac dinh"
    toi_danh: list[ToiDanhOutput] = Field(default_factory=list)
    nhan_xet: str | None = None


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
