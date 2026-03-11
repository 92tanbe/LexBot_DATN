# =============================================================================
# model/load_qwen_qlora.py
#
# Mục đích:
#   Load Qwen2.5-7B với QLoRA (Quantized Low-Rank Adaptation).
#
# ┌─────────────────────────────────────────────────────────────┐
# │  QLoRA = Quantization + LoRA                                │
# │                                                             │
# │  Quantization (BitsAndBytes 4-bit NF4):                    │
# │    Weights gốc: float32 (4 bytes/param)                    │
# │    Sau quantize: 4-bit NF4 (0.5 bytes/param)               │
# │    7B params × 0.5 bytes ≈ 3.5 GB  ← fit trong T4!        │
# │                                                             │
# │  LoRA (Low-Rank Adaptation):                               │
# │    Không update toàn bộ W (7B params)                      │
# │    Thay vào đó: W' = W + ΔW = W + A×B                     │
# │    A ∈ R^(d×r), B ∈ R^(r×k), r << d,k  (r=16 hoặc 64)   │
# │    Chỉ train A và B → ~0.1% số params → nhanh + ít VRAM   │
# └─────────────────────────────────────────────────────────────┘
#
# VRAM usage ước tính trên Colab T4 (15GB):
#   Model weights (4-bit)   : ~4.5 GB
#   LoRA params (fp32)      : ~0.3 GB
#   Activations + optimizer : ~6 GB
#   Tổng                    : ~11 GB  ← an toàn với T4
# =============================================================================

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
)
from peft import (
    LoraConfig,
    get_peft_model,
    prepare_model_for_kbit_training,
    TaskType,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tokenizer
# ─────────────────────────────────────────────────────────────────────────────

def load_tokenizer(model_name: str = "Qwen/Qwen2.5-7B-Instruct") -> AutoTokenizer:
    """
    Load Qwen2.5 tokenizer.

    Qwen2.5 dùng tiktoken-based tokenizer, hỗ trợ sẵn tiếng Việt.
    Vocab size: 151,936 tokens (lớn hơn GPT-2 rất nhiều → tiếng Việt tốt hơn).
    """
    print(f"⏳ Loading tokenizer: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code = True,
        padding_side      = "right",   # quan trọng khi training
    )

    # Qwen2.5 đã có pad_token = eos_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"   Vocab size : {len(tokenizer)}")
    print(f"   BOS token  : {tokenizer.bos_token}")
    print(f"   EOS token  : {tokenizer.eos_token}")
    print(f"   Chat template: {'✅' if tokenizer.chat_template else '❌'}")
    return tokenizer


# ─────────────────────────────────────────────────────────────────────────────
# 2. Quantization Config (4-bit NF4)
# ─────────────────────────────────────────────────────────────────────────────

def get_bnb_config() -> BitsAndBytesConfig:
    """
    BitsAndBytes 4-bit NF4 quantization config.

    NF4 (Normal Float 4) là kiểu dữ liệu 4-bit đặc biệt:
    → Phân phối các giá trị theo normal distribution
    → Phù hợp với phân phối weights của LLM hơn INT4 thông thường
    → Ít mất mát thông tin hơn

    double_quant=True: quantize thêm cả quantization constants
    → Tiết kiệm thêm ~0.4 GB VRAM nữa
    """
    return BitsAndBytesConfig(
        load_in_4bit               = True,
        bnb_4bit_quant_type        = "nf4",         # Normal Float 4
        bnb_4bit_use_double_quant  = True,           # quantize quantization constants
        bnb_4bit_compute_dtype     = torch.bfloat16, # tính toán trong bfloat16
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Load Model với Quantization
# ─────────────────────────────────────────────────────────────────────────────

def load_model_4bit(model_name: str = "Qwen/Qwen2.5-7B-Instruct",
                    device_map: str = "auto") -> AutoModelForCausalLM:
    """
    Load Qwen2.5-7B với 4-bit quantization.

    device_map="auto": HuggingFace tự động chia model lên GPU/CPU
    → Nếu chỉ có 1 GPU (Colab T4): toàn bộ lên GPU
    → Nếu có nhiều GPU: tự cân bằng
    """
    print(f"⏳ Loading {model_name} với 4-bit quantization...")
    print(f"   (Lần đầu download ~14GB, sau đó dùng cache)")

    bnb_config = get_bnb_config()

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config = bnb_config,
        device_map          = device_map,
        trust_remote_code   = True,
        torch_dtype         = torch.bfloat16,
        attn_implementation = "eager",   # "flash_attention_2" nếu có flash-attn
    )

    # In VRAM usage
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        print(f"   VRAM sử dụng sau load: {allocated:.1f} GB")

    return model


# ─────────────────────────────────────────────────────────────────────────────
# 4. Thêm LoRA adapters
# ─────────────────────────────────────────────────────────────────────────────

def add_lora_adapters(model: AutoModelForCausalLM,
                      r: int          = 16,
                      lora_alpha: int = 32,
                      dropout: float  = 0.05) -> AutoModelForCausalLM:
    """
    Thêm LoRA adapters vào Qwen2.5.

    Tham số LoRA:
        r (rank): kích thước của ma trận A và B
            - r=8  : ít params hơn, train nhanh hơn, có thể kém hơn
            - r=16 : cân bằng tốt  ← KHUYẾN NGHỊ
            - r=64 : nhiều params hơn, có thể học tốt hơn nhưng tốn VRAM

        lora_alpha: scaling factor = lora_alpha / r
            - Thường đặt = 2×r (r=16 → alpha=32)

        target_modules: các layer nào sẽ được LoRA
            - Qwen2.5 dùng: q_proj, k_proj, v_proj (attention)
                           + gate_proj, up_proj, down_proj (MLP)
            - Thêm nhiều modules → học tốt hơn nhưng tốn VRAM hơn

    Số LoRA params ước tính:
        Mỗi module: 2 × hidden_dim × r = 2 × 4096 × 16 = 131,072
        6 modules × 32 layers = 192 modules
        Tổng: ~25M params ← chỉ 0.36% của 7B!
    """

    # Chuẩn bị model cho k-bit training
    # (quan trọng: phải gọi trước khi thêm LoRA)
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing = True,   # tiết kiệm VRAM khi backward
    )

    lora_config = LoraConfig(
        r              = r,
        lora_alpha     = lora_alpha,
        lora_dropout   = dropout,
        bias           = "none",
        task_type      = TaskType.CAUSAL_LM,

        # Các attention + MLP projections của Qwen2.5
        target_modules = [
            "q_proj", "k_proj", "v_proj", "o_proj",  # Attention
            "gate_proj", "up_proj", "down_proj",       # MLP (SwiGLU)
        ],
    )

    model = get_peft_model(model, lora_config)

    # In thống kê params
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total     = sum(p.numel() for p in model.parameters())
    print(f"\n🔧 LoRA config:")
    print(f"   rank (r)          : {r}")
    print(f"   alpha             : {lora_alpha}")
    print(f"   Trainable params  : {trainable:,}  ({100*trainable/total:.2f}%)")
    print(f"   Frozen params     : {total-trainable:,}  ({100*(total-trainable)/total:.2f}%)")

    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        print(f"   VRAM sau LoRA     : {allocated:.1f} GB")

    return model


# ─────────────────────────────────────────────────────────────────────────────
# 5. Convenience function: load all
# ─────────────────────────────────────────────────────────────────────────────

def load_qwen_qlora(model_name: str = "Qwen/Qwen2.5-7B-Instruct",
                    lora_r: int = 16) -> tuple:
    """Load tokenizer + model với QLoRA trong 1 lần gọi"""
    tokenizer = load_tokenizer(model_name)
    model     = load_model_4bit(model_name)
    model     = add_lora_adapters(model, r=lora_r)
    return tokenizer, model


# ==============================================================================
if __name__ == "__main__":
    tokenizer, model = load_qwen_qlora()
    print("\n✅ Qwen2.5-7B + QLoRA sẵn sàng fine-tune!")

    # Test forward pass
    text = "<|im_start|>user\nĐiều 260 BLHS quy định gì?<|im_end|>\n<|im_start|>assistant\n"
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model(**inputs)
    print(f"   Logits shape: {out.logits.shape}")  # (1, seq_len, vocab_size)
