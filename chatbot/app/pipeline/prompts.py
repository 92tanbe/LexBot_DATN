"""Prompt + few-shot example cho LLM sinh CaseAnalysis."""
from __future__ import annotations

SYSTEM_PROMPT = """\
Ban la tro ly phap ly chuyen sau ve Bo luat Hinh su Viet Nam (BLHS 2025 hop nhat).

Yeu cau bat buoc:
1. Chi su dung dieu/khoan co trong CONTEXT duoc cap. Tuyet doi khong tu suy dien tu kien thuc bao chung.
2. Voi moi nhan dinh, phai trich dan it nhat 1 citation co dang `rule_id=...` hoac `Dieu X khoan Y` lay tu CONTEXT.
3. Neu CONTEXT khong du can cu de ket luan, hay ghi nhan vao truong `warnings` va de `confidence = "low"`.
4. Phan biet ro `chinh pham`, `dong pham`, `chu muu`, `giup suc`, `xui giuc` cho tung doi tuong.
5. Tinh tiet tang nang/giam nhe phai lay nguyen van tu CONTEXT (DieuKien co type aggravating/mitigating).
6. Output PHAI tuan thu CHINH XAC schema JSON da cho. Khong them comment, khong markdown.
7. Tra loi bang tieng Viet co dau, gon, ro, dung thuat ngu phap ly.

Khi co nhieu doi tuong (vu dong pham), tach moi nguoi thanh 1 ActorAnalysis rieng,
liet ke toi danh + vai tro + hinh phat tuong ung cho tung nguoi.
"""


# Few-shot tom luoc - chi minh hoa cau truc, khong yeu cau LLM dung dung text
FEWSHOT_EXAMPLES = """\
Vi du 1 (1 doi tuong don gian):
CAU HOI: "Toi cuop tai san gia tri 100 trieu thi bi xu phat the nao?"
JSON OUTPUT:
{
  "summary": "Cuop tai san tri gia 100 trieu dong thuoc khung tang nang Dieu 168 khoan 2.",
  "actors": [{
    "name": "Nguoi pham toi",
    "vai_tro": "chinh pham",
    "toi_danh": [{
      "dieu": 168, "khoan": 2,
      "ten_toi": "Toi cuop tai san",
      "vai_tro": "chinh pham",
      "tinh_tiet_tang_nang": ["Chiem doat tai san tri gia tu 50.000.000 dong den duoi 200.000.000 dong"],
      "hinh_phat": {"loai": "tu", "min": 7, "max": 15, "don_vi": "nam", "extra": null},
      "citations": [{"article": 168, "clause": 2, "rule_id": "168_r2"}]
    }],
    "nhan_xet": "Phai chiu phat tu tu 7 den 15 nam."
  }],
  "overall_advice": "Can luat su bao chua phan tich tinh tiet giam nhe.",
  "confidence": "high",
  "warnings": []
}

Vi du 2 (dong pham 2 nguoi):
CAU HOI: "A va B cung cuop, A dung dao, B canh gac."
JSON OUTPUT (rut gon):
{
  "summary": "Vu dong pham cuop tai san: A la chinh pham co vu khi, B la nguoi giup suc.",
  "actors": [
    {"name": "A", "vai_tro": "chinh pham", "toi_danh": [...], "nhan_xet": "..."},
    {"name": "B", "vai_tro": "giup suc", "toi_danh": [...], "nhan_xet": "..."}
  ],
  ...
}
"""


USER_PROMPT_TEMPLATE = """\
CAU HOI NGUOI DUNG:
{question}

ENTITIES TRICH XUAT:
{entities_json}

CONTEXT (dieu luat lien quan, danh so theo #):
{context}

Hay tra ve JSON DUNG SCHEMA CaseAnalysis nhu sau:
{{
  "summary": "<tom tat ngan tinh huong>",
  "actors": [
    {{
      "name": "<ten doi tuong>",
      "vai_tro": "chinh pham|dong pham|chu muu|giup suc|xui giuc|thuc hanh|tong hop|khong xac dinh",
      "toi_danh": [
        {{
          "dieu": <int>,
          "khoan": <int|null>,
          "ten_toi": "<ten toi danh>",
          "nhom_toi": "<chuong/nhom toi>",
          "vai_tro": "<vai tro tai khoan nay>",
          "tinh_tiet_tang_nang": ["..."],
          "tinh_tiet_giam_nhe": ["..."],
          "hinh_phat": {{
            "loai": "tu|tu_chung_than|tu_hinh|cai_tao_khong_giam_giu|phat_tien|canh_cao|quan_che|cam_dam_nhiem|khac",
            "min": <number|null>, "max": <number|null>,
            "don_vi": "nam|thang|dong|null",
            "extra": "<mo ta hinh phat bo sung>"
          }},
          "ly_do": "<ly do dinh toi/khoan nay>",
          "citations": [{{"article": <int>, "clause": <int|null>, "rule_id": "<rule_id tu CONTEXT>"}}]
        }}
      ],
      "nhan_xet": "<nhan xet ngan>"
    }}
  ],
  "overall_advice": "<loi khuyen tong>",
  "confidence": "high|medium|low",
  "warnings": ["..."]
}}

Tra loi BANG JSON THUAN, khong them ` ``` ` hoac giai thich.
"""


def build_user_prompt(question: str, entities_json: str, context: str) -> str:
    return USER_PROMPT_TEMPLATE.format(
        question=question.strip(),
        entities_json=entities_json,
        context=context,
    )
