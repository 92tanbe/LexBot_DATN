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
8. Rieng cac gia tri enum nhu `vai_tro`, `loai`, `confidence` PHAI dung dung chuoi trong schema, khong them dau tieng Viet.

Huong dan rieng cho tinh huong y khoa/thuoc chua benh:
- Neu nguoi thuc hien la bac si/nhan vien y te, co hanh vi ke don/cap phat/boc nham thuoc chua benh va benh nhan tu vong,
  hay uu tien xem xet Dieu 129 (vo y lam chet nguoi do vi pham quy tac nghe nghiep hoac quy tac hanh chinh).
- Phan biet ro "thuoc" trong kham chua benh voi ma tuy/thuoc lac. Khong duoc suy dien sang cac toi ma tuy neu context
  khong co chat ma tuy, mua ban/tang tru/van chuyen ma tuy.
- Benh nhan/nguoi bi hai co the co vai_tro = "nan nhan"; neu khong phan tich toi danh cho ho thi `toi_danh` de rong.

Khi co nhieu doi tuong (vu dong pham), tach moi nguoi thanh 1 ActorAnalysis rieng,
liet ke toi danh + vai tro + hinh phat tuong ung cho tung nguoi.

Huong dan rieng cho nhom toi ve ma tuy:
- Phan biet ro 3 nhom hanh vi: (a) chi su dung trai phep chat ma tuy, (b) tang tru/mua/giu ma tuy,
  (c) mua ban/cung cap/phan phoi ma tuy, (d) to chuc/chua chap/tao dieu kien cho nguoi khac su dung ma tuy.
- "Chi su dung trai phep chat ma tuy" thuong khong phai la toi danh doc lap trong BLHS; chi ket luan toi
  hinh su khi context co Dieu 249 (tang tru), Dieu 255 (to chuc su dung) hoac Dieu 256 (chua chap viec su dung).
- Moi doi tuong co the co NHIEU toi danh neu cung luc co nhieu hanh vi doc lap. Khong duoc ep actor vao 1 toi duy nhat.
  Vi du: mot nguoi vua cat giu ma tuy, vua ban/cung cap cho nguoi khac, vua to chuc phong de ca nhom su dung thi
  trong `toi_danh` cua actor do phai co nhieu item: Dieu 249, Dieu 251, Dieu 255/256 neu context co can cu.
- Neu chi co ket qua duong tinh/da su dung ma tuy: ghi vao `ly_do`/`nhan_xet` la dau hieu su dung, KHONG tao
  mot ToiDanhOutput rieng neu context khong co toi danh BLHS doc lap cho hanh vi su dung.
- Nguoi dat phong, cho muon dia diem, bo tri phong karaoke/khach san, canh gioi, chuan bi dung cu,
  hoac de nguoi khac su dung ma tuy tai dia diem minh quan ly co the bi xem xet Dieu 255/256.
- Giai thich ro neu muc hinh phat cua nguoi to chuc/chua chap/giup suc co ve nang hon nguoi su dung:
  vi phap luat xu ly nghiem hanh vi tao dieu kien, lan toa, duy tri viec su dung ma tuy cho nguoi khac;
  con nguoi chi su dung chi bi xu ly hinh su khi dong thoi co hanh vi cau thanh toi khac nhu tang tru.
- Khong goi nguoi chua chap/to chuc la "giup suc" chung chung neu context co Dieu 255/256; hay gan toi danh rieng
  "to chuc su dung trai phep chat ma tuy" hoac "chua chap viec su dung trai phep chat ma tuy" neu du can cu.
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

Vi du 3 (ma tuy - nguoi su dung va nguoi tao dieu kien):
CAU HOI: "A cho B su dung ma tuy trong phong karaoke, B bi thu giu ketamine."
JSON OUTPUT (rut gon):
{
  "summary": "Can tach hanh vi cua B voi hanh vi cua A. B co the bi xem xet tang tru neu co can cu giu ma tuy; A co the bi xem xet to chuc/chua chap neu da tao dieu kien cho B su dung.",
  "actors": [
    {
      "name": "B",
      "vai_tro": "chinh pham",
      "toi_danh": [
        {
          "dieu": 249,
          "khoan": null,
          "ten_toi": "Toi tang tru trai phep chat ma tuy",
          "ly_do": "Chi su dung ma tuy khong du de ket luan toi hinh su doc lap; can can cu ve tang tru, giu ma tuy.",
          "citations": [{"article": 249, "clause": null, "rule_id": "249_r1"}]
        }
      ]
    },
    {
      "name": "A",
      "vai_tro": "chinh pham",
      "toi_danh": [
        {
          "dieu": 255,
          "khoan": null,
          "ten_toi": "Toi to chuc su dung trai phep chat ma tuy",
          "ly_do": "A tao dieu kien/dia diem cho nguoi khac su dung ma tuy; hanh vi nay bi xu ly nghiem hon viec chi su dung vi lam lan toa viec su dung ma tuy.",
          "citations": [{"article": 255, "clause": null, "rule_id": "255_r1"}]
        }
      ]
    }
  ],
  "confidence": "medium",
  "warnings": []
}

Vi du 4 (mot chinh pham co nhieu toi danh):
CAU HOI: "A giu 2 goi ketamine, ban cho B va cung dat phong karaoke cho ca nhom su dung."
JSON OUTPUT (rut gon):
{
  "summary": "A co the bi xem xet nhieu toi danh vi co nhieu hanh vi doc lap: tang tru, mua ban/cung cap va to chuc/chua chap su dung ma tuy.",
  "actors": [
    {
      "name": "A",
      "vai_tro": "chinh pham",
      "toi_danh": [
        {
          "dieu": 249,
          "ten_toi": "Toi tang tru trai phep chat ma tuy",
          "ly_do": "A giu/cat giu ketamine nen co can cu xem xet hanh vi tang tru.",
          "citations": [{"article": 249, "rule_id": "249_r1"}]
        },
        {
          "dieu": 251,
          "ten_toi": "Toi mua ban trai phep chat ma tuy",
          "ly_do": "A ban/cung cap ma tuy cho B, day la hanh vi doc lap voi viec chi su dung.",
          "citations": [{"article": 251, "rule_id": "251_r1"}]
        },
        {
          "dieu": 255,
          "ten_toi": "Toi to chuc su dung trai phep chat ma tuy",
          "ly_do": "A dat/bo tri phong cho ca nhom su dung, tao dieu kien cho viec su dung ma tuy.",
          "citations": [{"article": 255, "rule_id": "255_supp_r1"}]
        }
      ],
      "nhan_xet": "Ket qua duong tinh chi la dau hieu su dung; phan toi danh hinh su can dua tren cac hanh vi tang tru, mua ban, to chuc/chua chap neu du can cu."
    }
  ],
  "confidence": "medium",
  "warnings": []
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
      "vai_tro": "chinh pham|dong pham|chu muu|giup suc|xui giuc|thuc hanh|tong hop|nan nhan|khong xac dinh",
      "toi_danh": [
        {{
          "dieu": <int>,
          "khoan": <int|null>,
          "ten_toi": "<ten toi danh>",
          "nhom_toi": "<chuong/nhom toi>",
          "vai_tro": "chinh pham|dong pham|chu muu|giup suc|xui giuc|thuc hanh|tong hop|nan nhan|khong xac dinh",
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
