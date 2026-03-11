# =============================================================================
# run_finetune.py  —  Entry point pipeline QLoRA Qwen2.5-7B
# =============================================================================
#
# Chạy:
#   python run_finetune.py --step 1    ← build dataset
#   python run_finetune.py --step 2    ← fine-tune
#   python run_finetune.py --step 3    ← chat
#   python run_finetune.py --step all  ← 1→2→3

import os
import argparse
import torch


def step1_build_dataset():
    print("\n" + "═"*60)
    print("  BƯỚC 1: Xây dựng Dataset")
    print("═"*60)
    from dataset.build_dataset import build_and_save
    train_path, val_path = build_and_save(
        blhs_path   = "data/blhs_2025_from_text.csv",
        gt_path     = "data/giaothong.csv",
        output_path = "data/legal_qa.jsonl",
    )
    return train_path, val_path


def step2_finetune():
    print("\n" + "═"*60)
    print("  BƯỚC 2: QLoRA Fine-tuning Qwen2.5-7B")
    print("═"*60)
    from functools import partial
    from torch.utils.data import DataLoader

    # Load tokenizer + model
    from model.load_qwen_qlora import load_qwen_qlora
    tokenizer, model = load_qwen_qlora(
        model_name = "Qwen/Qwen2.5-7B-Instruct",
        lora_r     = 16,
    )

    # Build datasets
    from dataset.build_dataset import LegalChatDataset, collate_fn, build_and_save

    if not os.path.exists("data/legal_qa_train.jsonl"):
        build_and_save("data/blhs_2025_from_text.csv", "data/giaothong.csv")

    train_ds = LegalChatDataset("data/legal_qa_train.jsonl", tokenizer, max_length=1024)
    val_ds   = LegalChatDataset("data/legal_qa_val.jsonl",   tokenizer, max_length=1024)

    pad_id   = tokenizer.pad_token_id
    train_loader = DataLoader(
        train_ds, batch_size=2, shuffle=True, num_workers=2, pin_memory=True,
        collate_fn=partial(collate_fn, pad_token_id=pad_id)
    )
    val_loader = DataLoader(
        val_ds, batch_size=2, shuffle=False, num_workers=2,
        collate_fn=partial(collate_fn, pad_token_id=pad_id)
    )

    # Fine-tune
    from trainer.qlora_trainer import QLoRATrainer, QLoRAConfig
    cfg     = QLoRAConfig()
    trainer = QLoRATrainer(cfg)
    trainer.train(model, tokenizer, train_loader, val_loader)


def step3_chat():
    print("\n" + "═"*60)
    print("  BƯỚC 3: Chat với model đã fine-tune")
    print("═"*60)
    from inference.chatbot import LexGPTQwen
    bot = LexGPTQwen("checkpoints/best_model")
    bot.chat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", default="all",
                        choices=["1", "2", "3", "all"])
    args = parser.parse_args()

    os.makedirs("data",        exist_ok=True)
    os.makedirs("checkpoints", exist_ok=True)

    if args.step in ("1", "all"):
        step1_build_dataset()
    if args.step in ("2", "all"):
        step2_finetune()
    if args.step in ("3", "all"):
        step3_chat()
