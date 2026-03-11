# =============================================================================
# dataset/build_dataset.py
#
# Mục đích:
#   Chuyển 2 file CSV luật → file JSONL theo chuẩn instruction-tuning
#   (giống format dùng bởi Alpaca, LLaMA-Factory, Unsloth)
#
# Format mỗi dòng (ChatML — chuẩn của Qwen2.5):
#   {
#     "messages": [
#       {"role": "system",    "content": "Bạn là chuyên gia pháp lý..."},
#       {"role": "user",      "content": "Điều 260 BLHS quy định gì?"},
#       {"role": "assistant", "content": "Điều 260 BLHS 2025 quy định về..."}
#     ]
#   }
#
# Tại sao dùng ChatML format?
#   Qwen2.5 đã được pretrain với format này. Fine-tune đúng format giúp
#   model hiểu role của từng phần, sinh câu trả lời chính xác hơn.
# =============================================================================

import csv
import json
import random
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Bạn là LexGPT, một chuyên gia pháp lý Việt Nam được đào tạo chuyên sâu "
    "về Bộ Luật Hình Sự 2025 và các Nghị định xử phạt vi phạm hành chính "
    "giao thông. Hãy trả lời chính xác, trích dẫn điều luật cụ thể, "
    "và phân biệt rõ xử phạt hành chính và truy cứu trách nhiệm hình sự."
)


# ─────────────────────────────────────────────────────────────────────────────
# Tạo Q&A pairs
# ─────────────────────────────────────────────────────────────────────────────

def _make_blhs_pairs(blhs_path: str) -> list[dict]:
    """Tạo Q&A từ Bộ Luật Hình Sự"""
    pairs = []

    # Gom các khoản theo điều
    by_dieu: dict[str, dict] = {}
    with open(blhs_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            so = row.get("Số điều", "").strip()
            if not so:
                continue
            if so not in by_dieu:
                by_dieu[so] = {
                    "ten":    row.get("Tiêu đề điều", "").strip(),
                    "nd":     row.get("Nội dung điều", "").strip(),
                    "khoan":  [],
                }
            k = row.get("Nội dung khoản", "").strip()
            d = row.get("Nội dung điểm", "").strip()
            if d:
                by_dieu[so]["khoan"].append(d)
            elif k:
                by_dieu[so]["khoan"].append(k)

    for so, data in by_dieu.items():
        ten  = data["ten"]
        body = data["nd"] or " ".join(data["khoan"][:3])
        body = body[:600]
        if not ten or not body:
            continue

        # 4 template câu hỏi khác nhau cho mỗi điều
        pairs += [
            _qa(f"Điều {so} Bộ Luật Hình Sự 2025 quy định về điều gì?",
                f"Điều {so} BLHS 2025 quy định về **{ten}**.\n\n{body}"),

            _qa(f"Tội {ten.lower()} theo BLHS 2025 bị xử lý như thế nào?",
                f"Theo **Điều {so}** Bộ Luật Hình Sự 2025:\n\n{body}"),

            _qa(f"Hãy trích dẫn nội dung Điều {so} BLHS.",
                f"**Điều {so}. {ten}**\n\n{body}"),

            _qa(f"Người phạm tội {ten.lower()} bị truy cứu theo điều luật nào?",
                f"Hành vi {ten.lower()} bị truy cứu trách nhiệm hình sự theo "
                f"**Điều {so}** BLHS 2025. Cụ thể: {body}"),
        ]
    return pairs


def _make_gt_pairs(gt_path: str) -> list[dict]:
    """Tạo Q&A từ Nghị định xử phạt vi phạm giao thông"""
    pairs = []

    by_dieu: dict[str, dict] = {}
    with open(gt_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            so = row.get("Số điều", "").strip()
            if not so:
                continue
            if so not in by_dieu:
                by_dieu[so] = {
                    "ten":   row.get("Tiêu đề điều", "").strip(),
                    "parts": [],
                }
            for col in ["Nội dung khoản", "Nội dung điểm"]:
                v = row.get(col, "").strip()
                if v:
                    by_dieu[so]["parts"].append(v)

    for so, data in by_dieu.items():
        ten  = data["ten"]
        body = " ".join(data["parts"][:4])[:600]
        if not ten or not body:
            continue

        pairs += [
            _qa(f"Mức xử phạt vi phạm hành chính quy định tại Điều {so} Nghị định giao thông là gì?",
                f"Theo **Điều {so}** Nghị định xử phạt vi phạm hành chính giao thông "
                f"({ten}):\n\n{body}"),

            _qa(f"Vi phạm {ten.lower()} bị phạt bao nhiêu tiền?",
                f"Căn cứ **Điều {so}** về {ten}:\n\n{body}"),

            _qa(f"Điều {so} Nghị định giao thông nói về điều gì?",
                f"**Điều {so}. {ten}**\n\n{body}"),
        ]
    return pairs


def _make_combined_pairs() -> list[dict]:
    """
    Tạo Q&A tổng hợp: khi nào phạt hành chính, khi nào truy cứu hình sự.
    Đây là loại câu hỏi quan trọng nhất trong thực tế.
    """
    return [
        _qa(
            "Sự khác nhau giữa xử phạt hành chính và truy cứu trách nhiệm hình sự trong vi phạm giao thông?",
            "Có hai hình thức xử lý vi phạm giao thông:\n\n"
            "**1. Xử phạt vi phạm hành chính** (Nghị định):\n"
            "- Áp dụng khi vi phạm chưa đến mức hình sự\n"
            "- Hình thức: phạt tiền, tước GPLX, tịch thu phương tiện\n"
            "- Ví dụ: vượt đèn đỏ, quá tốc độ, nồng độ cồn nhẹ\n\n"
            "**2. Truy cứu trách nhiệm hình sự** (BLHS 2025):\n"
            "- Áp dụng khi có hậu quả nghiêm trọng (chết người, thương tích nặng)\n"
            "- Hình thức: phạt tù, cải tạo không giam giữ\n"
            "- Căn cứ: Điều 260 BLHS (vi phạm quy định tham gia giao thông)"
        ),
        _qa(
            "Uống rượu bia lái xe bị xử lý thế nào theo pháp luật Việt Nam hiện hành?",
            "Tùy mức độ nồng độ cồn và hậu quả, có 2 hướng xử lý:\n\n"
            "**Xử phạt hành chính** (Nghị định giao thông):\n"
            "- Nồng độ cồn > 0: phạt tiền + tước GPLX\n"
            "- Mức phạt tăng dần theo nồng độ cồn\n\n"
            "**Truy cứu hình sự** (nếu gây tai nạn):\n"
            "- Theo Điều 260 BLHS 2025: phạt tù từ 3 năm đến 15 năm\n"
            "- Tùy hậu quả (chết người, nhiều người chết, tài sản lớn)"
        ),
    ]


def _qa(question: str, answer: str) -> dict:
    """Tạo 1 sample theo ChatML format"""
    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main: build & save
# ─────────────────────────────────────────────────────────────────────────────

def build_and_save(blhs_path: str, gt_path: str,
                   output_path: str = "data/legal_qa.jsonl",
                   val_ratio: float = 0.1) -> tuple[str, str]:
    """
    Build toàn bộ dataset, chia train/val, lưu ra file JSONL.
    Trả về (train_path, val_path).
    """
    print("📚 Đang tạo dataset từ CSV luật...")
    all_pairs = (
        _make_blhs_pairs(blhs_path)
        + _make_gt_pairs(gt_path)
        + _make_combined_pairs()
    )
    random.shuffle(all_pairs)
    print(f"   Tổng: {len(all_pairs)} samples")

    # Train / Val split
    n_val   = max(50, int(len(all_pairs) * val_ratio))
    n_train = len(all_pairs) - n_val
    train_data = all_pairs[:n_train]
    val_data   = all_pairs[n_train:]
    print(f"   Train: {n_train}  |  Val: {n_val}")

    # Lưu JSONL
    train_path = output_path.replace(".jsonl", "_train.jsonl")
    val_path   = output_path.replace(".jsonl", "_val.jsonl")

    for path, data in [(train_path, train_data), (val_path, val_data)]:
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"   💾 {path}")

    return train_path, val_path


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch Dataset
# ─────────────────────────────────────────────────────────────────────────────

import torch
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizer


class LegalChatDataset(Dataset):
    """
    PyTorch Dataset cho QLoRA fine-tuning Qwen2.5.

    Tokenize theo ChatML template của Qwen2.5:
        <|im_start|>system\n{system}<|im_end|>\n
        <|im_start|>user\n{question}<|im_end|>\n
        <|im_start|>assistant\n{answer}<|im_end|>

    Labels:
        - Phần system + user → -100 (không tính loss)
        - Phần assistant     → token IDs (tính loss ở đây)

    Lý do: model cần học CÁCH TRẢ LỜI, không học thuộc câu hỏi.
    """

    def __init__(self, jsonl_path: str, tokenizer: PreTrainedTokenizer,
                 max_length: int = 2048):
        self.samples   = []
        self.tokenizer = tokenizer

        # Đọc JSONL
        with open(jsonl_path, encoding="utf-8") as f:
            raw = [json.loads(line) for line in f]

        # Token IDs của delimiters
        im_end_id    = tokenizer.convert_tokens_to_ids("<|im_end|>")
        assistant_id = tokenizer.convert_tokens_to_ids("assistant")

        for item in raw:
            msgs = item["messages"]

            # Apply chat template của Qwen2.5
            text = tokenizer.apply_chat_template(
                msgs,
                tokenize=False,
                add_generation_prompt=False,
            )

            enc = tokenizer(
                text,
                max_length  = max_length,
                truncation  = True,
                padding     = False,
                return_tensors = "pt",
            )
            input_ids = enc["input_ids"].squeeze(0)
            labels    = input_ids.clone()

            # Mask tất cả trừ phần assistant
            # Tìm vị trí cuối cùng của "assistant" token
            # (phần assistant bắt đầu sau "<|im_start|>assistant\n")
            assistant_positions = (input_ids == assistant_id).nonzero(as_tuple=True)[0]
            if len(assistant_positions) > 0:
                # Lấy vị trí assistant cuối (có thể có nhiều turns)
                last_assistant = assistant_positions[-1].item()
                labels[:last_assistant + 2] = -100   # +2 để skip "assistant\n"
            else:
                labels[:] = -100   # không tìm thấy → skip sample

            self.samples.append({
                "input_ids": input_ids,
                "labels":    labels,
            })

        print(f"✅ Dataset loaded: {len(self.samples)} samples từ {jsonl_path}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        return self.samples[idx]


def collate_fn(batch: list[dict], pad_token_id: int) -> dict:
    """
    Padding động: pad đến độ dài dài nhất trong batch (tiết kiệm hơn fix length).
    """
    max_len = max(s["input_ids"].shape[0] for s in batch)
    input_ids_list = []
    labels_list    = []
    masks_list     = []

    for s in batch:
        seq_len = s["input_ids"].shape[0]
        pad_len = max_len - seq_len

        input_ids_list.append(
            torch.cat([s["input_ids"],
                       torch.full((pad_len,), pad_token_id, dtype=torch.long)])
        )
        labels_list.append(
            torch.cat([s["labels"],
                       torch.full((pad_len,), -100, dtype=torch.long)])
        )
        masks_list.append(
            torch.cat([torch.ones(seq_len, dtype=torch.long),
                       torch.zeros(pad_len, dtype=torch.long)])
        )

    return {
        "input_ids":      torch.stack(input_ids_list),
        "labels":         torch.stack(labels_list),
        "attention_mask": torch.stack(masks_list),
    }


# ==============================================================================
if __name__ == "__main__":
    build_and_save(
        blhs_path   = "data/blhs_2025_from_text.csv",
        gt_path     = "data/giaothong.csv",
        output_path = "data/legal_qa.jsonl",
    )
