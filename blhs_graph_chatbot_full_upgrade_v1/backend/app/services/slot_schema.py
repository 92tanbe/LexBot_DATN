from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SlotDefinition:
    key: str
    label: str
    description: str
    required: bool
    critical: bool
    suggested_question: str


@dataclass(frozen=True)
class OptionTemplate:
    id: str
    label: str
    requires_value: bool = False
    value_type: Literal["text", "number", "date"] | None = None
    placeholder: str | None = None


@dataclass(frozen=True)
class StructuredQuestionTemplate:
    id: str
    fact_path: str
    group: str
    text: str
    input_type: Literal[
        "single_choice",
        "multi_choice",
        "number",
        "text",
        "date",
        "boolean",
        "actor_matrix",
    ]
    reason: str
    required: bool = False
    critical: bool = False
    allow_free_text: bool = False
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    affected_articles: tuple[str, ...] = ()
    options: tuple[OptionTemplate, ...] = ()
    legal_impact: float = 0.5
    uncertainty: float = 0.5
    information_gain: float = 0.5


DRUG_SLOTS: list[SlotDefinition] = [
    SlotDefinition("drug_action", "Hành vi chính", "Tàng trữ, mua bán, vận chuyển, tổ chức sử dụng, chứa chấp.", True, True, "Hành vi chính là tàng trữ, mua bán, vận chuyển hay tổ chức sử dụng?"),
    SlotDefinition("substance_type", "Loại chất", "Tên chất ma túy hoặc kết luận giám định xác định chất.", True, True, "Đã có kết luận giám định xác định loại chất ma túy chưa?"),
    SlotDefinition("quantity", "Định lượng", "Khối lượng, hàm lượng hoặc số lượng viên/gói.", True, True, "Khối lượng/hàm lượng hoặc số lượng cụ thể là bao nhiêu?"),
    SlotDefinition("exhibit_status", "Tình trạng tang vật", "Còn thu giữ, đã sử dụng hết, hoặc không thu giữ được.", True, True, "Tang vật còn bị thu giữ hay đã sử dụng hết/không thu giữ được?"),
    SlotDefinition("forensic_conclusion", "Kết luận giám định", "Kết quả giám định chất và định lượng.", True, True, "Hồ sơ đã có kết luận giám định chưa?"),
    SlotDefinition("buyer", "Người mua", "Ai mua hoặc đặt mua.", False, True, "Ai là người mua hoặc đặt mua chất ma túy?"),
    SlotDefinition("seller_or_supplier", "Người bán/cung cấp", "Ai bán, giao hoặc cung cấp.", False, True, "Ai là người bán, giao hoặc cung cấp chất ma túy?"),
    SlotDefinition("organizer", "Người tổ chức", "Ai chuẩn bị địa điểm, dụng cụ, phân công hoặc rủ rê.", False, True, "Ai rủ rê, chuẩn bị địa điểm/dụng cụ hoặc tổ chức việc sử dụng?"),
    SlotDefinition("users", "Người sử dụng", "Ai trực tiếp sử dụng hoặc dương tính.", False, True, "Ai trực tiếp sử dụng hoặc có xét nghiệm dương tính?"),
    SlotDefinition("purpose", "Mục đích", "Để dùng, bán lại, vận chuyển, tổ chức cho người khác dùng.", True, True, "Mục đích là để sử dụng, bán lại, vận chuyển hay tổ chức cho người khác dùng?"),
    SlotDefinition("profit", "Hưởng lợi", "Tiền công, lợi ích hoặc chia lợi.", False, True, "Có ai hưởng lợi, nhận tiền công hoặc được chia lợi ích không?"),
    SlotDefinition("roles", "Vai trò", "Vai trò cụ thể của từng người.", True, True, "Vai trò cụ thể của từng người là gì?"),
    SlotDefinition("age_of_actors", "Tuổi", "Tuổi từng người nếu ảnh hưởng TNHS.", False, False, "Tuổi của từng người là bao nhiêu?"),
    SlotDefinition("evidence", "Chứng cứ", "Lời khai, camera, tin nhắn, chuyển khoản, xét nghiệm.", False, False, "Có chứng cứ nào ngoài lời khai không?"),
]

ACCOMPLICE_SLOTS: list[SlotDefinition] = [
    SlotDefinition("roles", "Vai trò từng người", "Ai thực hành, tổ chức, xúi giục, giúp sức.", True, True, "Vai trò cụ thể của từng người trong vụ việc là gì?"),
    SlotDefinition("intent", "Ý chí chung", "Có cùng bàn bạc, thống nhất hoặc biết việc nhau làm không.", True, True, "Các bên có bàn bạc/thống nhất hoặc biết rõ hành vi của nhau không?"),
]

AGE_SLOTS: list[SlotDefinition] = [
    SlotDefinition("age_of_actors", "Tuổi từng người", "Tuổi tại thời điểm thực hiện hành vi.", True, True, "Tuổi của từng người tại thời điểm xảy ra vụ việc là bao nhiêu?"),
]

FORESTRY_SLOTS: list[SlotDefinition] = [
    SlotDefinition("wood_type", "Loại gỗ/lâm sản", "Nhóm gỗ, loài nguy cấp hoặc nguồn gốc.", True, True, "Loại gỗ/lâm sản là gì, thuộc nhóm nào và nguồn gốc ra sao?"),
    SlotDefinition("quantity", "Khối lượng", "Khối lượng m3 hoặc số lượng tương ứng.", True, True, "Khối lượng gỗ/lâm sản là bao nhiêu m3?"),
    SlotDefinition("action", "Hành vi", "Khai thác, vận chuyển, mua bán, tàng trữ.", True, True, "Hành vi chính là khai thác, vận chuyển, mua bán hay tàng trữ?"),
]

DOMAIN_SLOTS: dict[str, list[SlotDefinition]] = {
    "drug": DRUG_SLOTS,
    "accomplice": ACCOMPLICE_SLOTS,
    "age": AGE_SLOTS,
    "forestry": FORESTRY_SLOTS,
}

FORENSIC_SUBSTANCE_OPTIONS: tuple[OptionTemplate, ...] = (
    OptionTemplate("mdma", "MDMA"),
    OptionTemplate("methamphetamine", "Methamphetamine"),
    OptionTemplate("ketamine", "Ketamine"),
    OptionTemplate("other", "Chất khác", requires_value=True, value_type="text", placeholder="Nhập tên hoạt chất theo kết luận giám định"),
    OptionTemplate("not_narcotic", "Không phải chất ma túy"),
    OptionTemplate("no_forensic_report", "Chưa có kết luận giám định"),
    OptionTemplate("unknown", "Không biết"),
)

ELECTRONIC_EVIDENCE_OPTIONS: tuple[OptionTemplate, ...] = (
    OptionTemplate("messages", "Tin nhắn"),
    OptionTemplate("bank_transfer", "Chuyển khoản"),
    OptionTemplate("calls", "Cuộc gọi"),
    OptionTemplate("camera", "Camera"),
    OptionTemplate("none", "Không có"),
    OptionTemplate("unknown", "Không rõ"),
)

STRUCTURED_DRUG_QUESTION_GROUPS: tuple[str, ...] = (
    "incident_time",
    "forensic_substance",
    "forensic_status",
    "drug_net_mass",
    "tablet_count",
    "money_source",
    "purchase_actor",
    "delivery_actor",
    "recipient_actor",
    "profit_or_benefit",
    "actor_knowledge",
    "actor_intent",
    "location_preparation",
    "tool_preparation",
    "drug_distribution",
    "group_coordination",
    "toxicology_result",
    "rehabilitation_or_management_status",
    "electronic_evidence",
)
