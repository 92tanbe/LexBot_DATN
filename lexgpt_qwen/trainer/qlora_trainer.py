# =============================================================================
# trainer/qlora_trainer.py
#
# Training loop QLoRA hoàn toàn tự viết — không dùng HuggingFace Trainer.
# Đây là phần GIẢNG VIÊN ĐÁNH GIÁ CHÍNH.
#
# Pipeline:
#   Batch → Tokenize → Forward (4-bit model) → Loss
#        → Backward (gradient chỉ qua LoRA params) → AdamW → Update LoRA
# =============================================================================

import os
import math
import time
import json
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.cuda.amp import GradScaler, autocast
from dataclasses import dataclass
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QLoRAConfig:
    # ── Dữ liệu ─────────────────────────────────────────────────
    train_jsonl:    str   = "data/legal_qa_train.jsonl"
    val_jsonl:      str   = "data/legal_qa_val.jsonl"
    output_dir:     str   = "checkpoints"
    max_length:     int   = 1024    # Qwen2.5 hỗ trợ đến 32K, nhưng 1K đủ cho luật

    # ── Training ─────────────────────────────────────────────────
    num_epochs:     int   = 3
    batch_size:     int   = 2       # Colab T4: batch=2, grad_accum=8 → eff=16
    grad_accum:     int   = 8

    # ── LR ───────────────────────────────────────────────────────
    lr:             float = 2e-4    # LoRA thường dùng LR cao hơn full fine-tune
    lr_min_ratio:   float = 0.1
    warmup_ratio:   float = 0.05

    # ── Regularization ────────────────────────────────────────────
    weight_decay:   float = 0.001
    grad_clip:      float = 1.0

    # ── Logging ───────────────────────────────────────────────────
    log_every:      int   = 10
    eval_every:     int   = 100
    save_every:     int   = 200
    early_stop:     int   = 5

    # ── Hardware ──────────────────────────────────────────────────
    use_bf16:       bool  = True    # Qwen2.5 được train với bf16


# ─────────────────────────────────────────────────────────────────────────────
# Learning Rate Scheduler (cosine + warmup) — tự viết
# ─────────────────────────────────────────────────────────────────────────────

class WarmupCosineScheduler:
    """
    LR Schedule (tự viết, không dùng thư viện):
        Warmup:  0 → lr_max  (tuyến tính)
        Decay :  lr_max → lr_min  (cosine)

    Lý do cần warmup đặc biệt quan trọng với LoRA:
    → LoRA weights khởi tạo gần 0, LR cao ngay từ đầu sẽ gây gradient spike
    """

    def __init__(self, optimizer, total_steps: int, warmup_steps: int,
                 lr_max: float, lr_min: float):
        self.opt          = optimizer
        self.total_steps  = total_steps
        self.warmup_steps = warmup_steps
        self.lr_max       = lr_max
        self.lr_min       = lr_min
        self._step        = 0

    def step(self) -> float:
        self._step += 1
        lr = self._compute_lr(self._step)
        for pg in self.opt.param_groups:
            pg["lr"] = lr
        return lr

    def _compute_lr(self, step: int) -> float:
        if step <= self.warmup_steps:
            return self.lr_max * step / max(1, self.warmup_steps)
        if step >= self.total_steps:
            return self.lr_min
        t = (step - self.warmup_steps) / (self.total_steps - self.warmup_steps)
        return self.lr_min + 0.5 * (self.lr_max - self.lr_min) * (1 + math.cos(math.pi * t))


# ─────────────────────────────────────────────────────────────────────────────
# Trainer
# ─────────────────────────────────────────────────────────────────────────────

class QLoRATrainer:

    def __init__(self, cfg: QLoRAConfig):
        self.cfg    = cfg
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        os.makedirs(cfg.output_dir, exist_ok=True)
        print(f"🖥️  Device : {self.device}")
        if self.device == "cuda":
            props = torch.cuda.get_device_properties(0)
            print(f"   GPU    : {props.name}")
            print(f"   VRAM   : {props.total_memory/1e9:.1f} GB")

    def train(self, model, tokenizer, train_loader: DataLoader,
              val_loader: DataLoader):

        cfg = self.cfg

        # ── Optimizer: chỉ update LoRA params ────────────────────
        # trainable_params = chỉ A và B matrices của LoRA
        # Không update các weight 4-bit đã quantize!
        trainable_params = [p for p in model.parameters() if p.requires_grad]
        print(f"\n⚙️  Optimizer: AdamW trên {len(trainable_params)} LoRA param groups")

        optimizer = torch.optim.AdamW(
            trainable_params,
            lr           = cfg.lr,
            betas        = (0.9, 0.999),
            eps          = 1e-8,
            weight_decay = cfg.weight_decay,
        )

        # ── LR Scheduler ─────────────────────────────────────────
        total_steps  = cfg.num_epochs * len(train_loader) // cfg.grad_accum
        warmup_steps = max(10, int(cfg.warmup_ratio * total_steps))
        lr_min       = cfg.lr * cfg.lr_min_ratio

        scheduler = WarmupCosineScheduler(
            optimizer, total_steps, warmup_steps, cfg.lr, lr_min
        )

        # ── Mixed Precision ───────────────────────────────────────
        # bf16 thay vì fp16 vì:
        # → bf16 có range lớn hơn fp16 (quan trọng với LLM lớn)
        # → T4 hỗ trợ bf16 từ driver mới
        use_amp    = (self.device == "cuda" and cfg.use_bf16)
        amp_dtype  = torch.bfloat16 if use_amp else torch.float32
        scaler     = GradScaler(enabled=False)  # bf16 không cần scaler

        print(f"\n📅 Training schedule:")
        print(f"   Epochs          : {cfg.num_epochs}")
        print(f"   Steps/epoch     : {len(train_loader)}")
        print(f"   Grad accum      : {cfg.grad_accum}")
        print(f"   Effective batch : {cfg.batch_size * cfg.grad_accum}")
        print(f"   Total opt steps : {total_steps}")
        print(f"   Warmup steps    : {warmup_steps}")
        print(f"   LR max → min    : {cfg.lr:.1e} → {lr_min:.1e}")

        # ── Training state ────────────────────────────────────────
        best_val_loss    = float("inf")
        no_improve_count = 0
        global_step      = 0
        history          = {"train_loss": [], "val_loss": [], "lr": []}

        print("\n" + "═"*65)
        print("  🚀 Bắt đầu QLoRA Fine-tuning Qwen2.5-7B")
        print("═"*65)

        for epoch in range(1, cfg.num_epochs + 1):
            model.train()
            epoch_loss  = 0.0
            epoch_start = time.time()
            optimizer.zero_grad()

            for local_step, batch in enumerate(train_loader):

                # Đưa lên GPU
                input_ids      = batch["input_ids"].to(self.device)
                attention_mask = batch["attention_mask"].to(self.device)
                labels         = batch["labels"].to(self.device)

                # ── Forward pass ──────────────────────────────────
                with torch.autocast(device_type=self.device,
                                    dtype=amp_dtype, enabled=use_amp):
                    outputs = model(
                        input_ids      = input_ids,
                        attention_mask = attention_mask,
                        labels         = labels,
                    )
                    # Chia loss cho grad_accum (normalize)
                    loss = outputs.loss / cfg.grad_accum

                # ── Backward ──────────────────────────────────────
                # Gradient chỉ chảy qua LoRA params (A, B matrices)
                # Các params 4-bit quantize không có gradient
                loss.backward()
                epoch_loss += loss.item() * cfg.grad_accum

                # ── Update mỗi grad_accum steps ───────────────────
                if (local_step + 1) % cfg.grad_accum == 0 or \
                   (local_step + 1) == len(train_loader):

                    # Gradient clipping — quan trọng với LoRA
                    grad_norm = nn.utils.clip_grad_norm_(
                        trainable_params, cfg.grad_clip
                    )
                    optimizer.step()
                    lr = scheduler.step()
                    optimizer.zero_grad()
                    global_step += 1

                    # ── Log ───────────────────────────────────────
                    if global_step % cfg.log_every == 0:
                        avg_loss = epoch_loss / (local_step + 1)
                        ppl      = math.exp(min(avg_loss, 20))
                        elapsed  = time.time() - epoch_start

                        # VRAM usage
                        vram = ""
                        if self.device == "cuda":
                            vram = f"| VRAM {torch.cuda.memory_allocated()/1e9:.1f}GB"

                        print(
                            f"[E{epoch}|S{global_step:4d}] "
                            f"loss={avg_loss:.4f} ppl={ppl:.1f} "
                            f"lr={lr:.2e} ‖∇‖={grad_norm:.3f} "
                            f"{vram} t={elapsed:.0f}s"
                        )
                        history["train_loss"].append(avg_loss)
                        history["lr"].append(lr)

                    # ── Eval ──────────────────────────────────────
                    if global_step % cfg.eval_every == 0:
                        val_loss, val_ppl = self._eval(model, val_loader, amp_dtype)
                        print(f"\n📊 [Step {global_step}] "
                              f"val_loss={val_loss:.4f} | val_ppl={val_ppl:.1f}")
                        history["val_loss"].append(val_loss)

                        if val_loss < best_val_loss:
                            best_val_loss    = val_loss
                            no_improve_count = 0
                            self._save_lora(model, tokenizer, "best_model")
                            print(f"   💾 Best LoRA saved! (val_loss={val_loss:.4f})")
                        else:
                            no_improve_count += 1
                            if no_improve_count >= cfg.early_stop:
                                print("\n🛑 Early stopping!")
                                self._save_history(history)
                                return model

                        model.train()

                    # ── Periodic save ─────────────────────────────
                    if global_step % cfg.save_every == 0:
                        self._save_lora(model, tokenizer, f"step_{global_step}")

            # End of epoch
            avg = epoch_loss / len(train_loader)
            print(f"\n✅ Epoch {epoch} | avg_loss={avg:.4f} | "
                  f"time={time.time()-epoch_start:.0f}s\n")

        self._save_history(history)
        print("🎉 Fine-tuning xong!")
        return model

    # ─────────────────────────────────────────────
    @torch.no_grad()
    def _eval(self, model, val_loader, amp_dtype, max_batches=20):
        model.eval()
        losses = []
        for i, batch in enumerate(val_loader):
            if i >= max_batches:
                break
            input_ids      = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels         = batch["labels"].to(self.device)

            with torch.autocast(device_type=self.device,
                                dtype=amp_dtype, enabled=(self.device=="cuda")):
                outputs = model(input_ids=input_ids,
                                attention_mask=attention_mask,
                                labels=labels)
            losses.append(outputs.loss.item())

        avg = sum(losses) / len(losses) if losses else float("inf")
        return avg, math.exp(min(avg, 20))

    def _save_lora(self, model, tokenizer, name: str):
        """
        Lưu CHỈ LoRA weights (vài MB) thay vì toàn bộ model (14GB).
        Khi deploy: merge LoRA vào base model.
        """
        path = os.path.join(self.cfg.output_dir, name)
        model.save_pretrained(path)       # lưu LoRA adapter weights
        tokenizer.save_pretrained(path)   # lưu tokenizer
        print(f"   💾 LoRA saved → {path}/  "
              f"({sum(os.path.getsize(os.path.join(path,f)) for f in os.listdir(path))/1e6:.1f} MB)")

    def _save_history(self, history: dict):
        path = os.path.join(self.cfg.output_dir, "training_history.json")
        with open(path, "w") as f:
            json.dump(history, f, indent=2)
        print(f"   📈 History → {path}")


# ==============================================================================
if __name__ == "__main__":
    # Smoke test với model nhỏ
    print("Smoke test QLoRAConfig...")
    cfg = QLoRAConfig()
    opt = torch.optim.AdamW([torch.zeros(10, requires_grad=True)], lr=cfg.lr)
    sched = WarmupCosineScheduler(opt, 100, 10, cfg.lr, cfg.lr * 0.1)
    lrs = [sched._compute_lr(s) for s in range(0, 100, 5)]
    print("LR values:", [f"{lr:.2e}" for lr in lrs])
    print("✅ Config OK")
