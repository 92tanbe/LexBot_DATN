# =============================================================================
# inference/chatbot.py
# Chatbot sử dụng Qwen2.5-7B đã QLoRA fine-tune
# Hỗ trợ: streaming output, merge LoRA vào base model, RAG context
# =============================================================================

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, TextStreamer
from peft import PeftModel, PeftConfig
from typing import Generator


# ─────────────────────────────────────────────────────────────────────────────
# Option A: Load LoRA adapter (tiết kiệm VRAM, load nhanh)
# ─────────────────────────────────────────────────────────────────────────────

def load_with_adapter(lora_path: str, load_in_4bit: bool = True):
    """
    Load base model + LoRA adapter riêng lẽ.
    Dùng khi cần tiết kiệm bộ nhớ lưu trữ.
    """
    from transformers import BitsAndBytesConfig

    cfg = PeftConfig.from_pretrained(lora_path)
    base_model_name = cfg.base_model_name_or_path
    print(f"⏳ Loading base: {base_model_name}")

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    ) if load_in_4bit else None

    tokenizer = AutoTokenizer.from_pretrained(lora_path)
    base      = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config = bnb_cfg,
        device_map          = "auto",
        torch_dtype         = torch.bfloat16,
        trust_remote_code   = True,
    )
    model = PeftModel.from_pretrained(base, lora_path)
    model.eval()
    return tokenizer, model


# ─────────────────────────────────────────────────────────────────────────────
# Option B: Load merged model (hiệu suất cao nhất cho production)
# ─────────────────────────────────────────────────────────────────────────────

def merge_and_save(lora_path: str, output_path: str):
    """
    Merge LoRA weights vào base model → 1 model đầy đủ.
    Dùng khi cần deploy production hoặc dùng với Ollama/llama.cpp.

    Quá trình: W_merged = W_base + A×B  (với mỗi LoRA layer)
    Kết quả: model bình thường, không cần PEFT khi inference.
    """
    print("⏳ Merging LoRA vào base model...")
    cfg       = PeftConfig.from_pretrained(lora_path)
    tokenizer = AutoTokenizer.from_pretrained(lora_path)

    # Load base model với float16 (không quantize khi merge)
    base = AutoModelForCausalLM.from_pretrained(
        cfg.base_model_name_or_path,
        torch_dtype       = torch.float16,
        device_map        = "cpu",     # merge trên CPU để tránh OOM
        trust_remote_code = True,
    )
    model  = PeftModel.from_pretrained(base, lora_path)
    merged = model.merge_and_unload()  # ← merge LoRA vào weights

    merged.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    print(f"✅ Merged model lưu tại: {output_path}/")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Chatbot class
# ─────────────────────────────────────────────────────────────────────────────

class LexGPTQwen:
    """
    Chatbot pháp lý dùng Qwen2.5-7B đã QLoRA fine-tune.

    Hỗ trợ:
    - Streaming output (hiển thị từng token khi sinh)
    - Multi-turn conversation
    - RAG context injection (từ Neo4j)
    """

    SYSTEM_PROMPT = (
        "Bạn là LexGPT, chuyên gia pháp lý Việt Nam về BLHS 2025 "
        "và Nghị định xử phạt vi phạm hành chính giao thông. "
        "Trả lời chính xác, trích dẫn điều luật cụ thể."
    )

    def __init__(self, lora_path: str, load_in_4bit: bool = True):
        self.tokenizer, self.model = load_with_adapter(lora_path, load_in_4bit)
        self.device      = next(self.model.parameters()).device
        self.history: list[dict] = []

        print(f"✅ LexGPT-Qwen2.5 sẵn sàng!")
        if torch.cuda.is_available():
            print(f"   VRAM: {torch.cuda.memory_allocated()/1e9:.1f} GB")

    @torch.no_grad()
    def generate(self, question: str,
                 context: str          = "",
                 max_new_tokens: int   = 512,
                 temperature: float    = 0.3,
                 top_p: float          = 0.9,
                 stream: bool          = True) -> str:
        """
        Sinh câu trả lời từ câu hỏi.

        context: text từ Neo4j RAG (nếu có)
        stream:  True → in ra màn hình từng token khi sinh
        """

        # Nếu có RAG context, chèn vào câu hỏi
        if context:
            user_content = (
                f"[Thông tin tham khảo từ cơ sở dữ liệu pháp luật]\n"
                f"{context}\n\n"
                f"[Câu hỏi]\n{question}"
            )
        else:
            user_content = question

        # Build messages với lịch sử hội thoại
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        messages += self.history[-6:]  # Giữ 3 turns gần nhất
        messages.append({"role": "user", "content": user_content})

        # Apply Qwen2.5 chat template
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize            = False,
            add_generation_prompt = True,  # thêm <|im_start|>assistant\n ở cuối
        )

        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        input_len = inputs["input_ids"].shape[1]

        # Streaming: hiển thị token khi sinh
        streamer = TextStreamer(self.tokenizer, skip_prompt=True,
                                skip_special_tokens=True) if stream else None

        if stream:
            print("⚖️  LexGPT: ", end="", flush=True)

        outputs = self.model.generate(
            **inputs,
            max_new_tokens  = max_new_tokens,
            temperature     = temperature,
            top_p           = top_p,
            do_sample       = temperature > 0,
            pad_token_id    = self.tokenizer.eos_token_id,
            eos_token_id    = self.tokenizer.eos_token_id,
            streamer        = streamer,
        )

        # Decode chỉ phần mới sinh
        new_tokens  = outputs[0][input_len:]
        answer_text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)

        # Cập nhật lịch sử
        self.history.append({"role": "user",      "content": question})
        self.history.append({"role": "assistant",  "content": answer_text})

        return answer_text.strip()

    def reset(self):
        """Xóa lịch sử hội thoại"""
        self.history = []
        print("🔄 Đã xóa lịch sử hội thoại")

    def chat(self):
        """Vòng lặp chat terminal với multi-turn"""
        banner = """
╔══════════════════════════════════════════════════════════╗
║  ⚖️  LexGPT  —  Qwen2.5-7B QLoRA Fine-tuned           ║
║  Chuyên gia pháp lý: BLHS 2025 + Nghị định Giao thông ║
║  Lệnh: 'reset' = xóa lịch sử, 'quit' = thoát          ║
╚══════════════════════════════════════════════════════════╝
"""
        print(banner)
        while True:
            try:
                q = input("\n👤 Bạn: ").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not q:
                continue
            if q.lower() == "reset":
                self.reset()
                continue
            if q.lower() in ("quit", "exit", "thoát"):
                break

            self.generate(q, stream=True)
            print()  # newline sau streaming

    def evaluate_samples(self, questions: list[str]):
        """Chạy test với danh sách câu hỏi, in kết quả"""
        print("\n" + "═"*60)
        print("  📋 Evaluation")
        print("═"*60)
        for i, q in enumerate(questions, 1):
            print(f"\n[{i}] ❓ {q}")
            ans = self.generate(q, stream=False, temperature=0.1)
            print(f"    ✅ {ans[:400]}")
            print("─"*60)
            self.reset()


# ==============================================================================
if __name__ == "__main__":
    bot = LexGPTQwen("checkpoints/best_model")

    bot.evaluate_samples([
        "Điều 260 BLHS 2025 quy định về tội gì và mức phạt tù tối đa là bao nhiêu?",
        "Uống rượu lái xe ô tô gây tai nạn chết người bị xử lý thế nào?",
        "Phân biệt xử phạt hành chính và truy cứu hình sự trong vi phạm giao thông.",
        "Tốc độ vượt quá quy định bao nhiêu km/h thì bị tước giấy phép lái xe?",
    ])

    bot.chat()
