# =============================================================================
# chatbot/cli_chat.py
# Giao diện chatbot chạy trên terminal
# =============================================================================

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from rag.rag_engine import RAGEngine

BANNER = """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ⚖️  LexBot – AI Tư Vấn Pháp Lý Giao Thông Việt Nam   ║
║                                                          ║
║   Nguồn dữ liệu:                                        ║
║   • Bộ Luật Hình Sự 2025 (BLHS_2025)                   ║
║   • Nghị định xử phạt giao thông (ND_GIAOTHONG)         ║
║   • Graph Database: Neo4j                                ║
║                                                          ║
║   Lệnh: 'quit' thoát | 'reset' cuộc hội thoại mới      ║
║         'help' xem ví dụ câu hỏi                        ║
╚══════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
📌 Ví dụ câu hỏi bạn có thể hỏi:

  1. Lái xe say rượu (0.4mg/L) gây tai nạn chết người bị xử lý thế nào?
  2. Vượt đèn đỏ trong khu dân cư phạt bao nhiêu tiền?
  3. Chạy quá tốc độ 50km/h gây tai nạn thương tích nặng bị tội gì?
  4. Không có giấy phép lái xe gây tai nạn chết người thì sao?
  5. Ô tô đi ngược chiều cao tốc gây tai nạn liên hoàn 3 xe xử lý ra sao?
  6. Tra cứu Điều 260 BLHS 2025
  7. Mức phạt nồng độ cồn xe máy là bao nhiêu?
"""


def run_chatbot():
    print(BANNER)

    # Khởi động RAG Engine
    try:
        engine = RAGEngine()
    except Exception as e:
        print(f"❌ Lỗi khởi động: {e}")
        print("\n💡 Kiểm tra lại:")
        print("  1. Neo4j đang chạy? → config/settings.py")
        print("  2. ANTHROPIC_API_KEY đã set?")
        print("  3. Đã chạy etl/load_to_neo4j.py chưa?")
        return

    print("✅ Hệ thống sẵn sàng! Gõ câu hỏi của bạn:\n")

    while True:
        try:
            user_input = input("👤 Bạn: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Tạm biệt!")
            break

        if not user_input:
            continue

        # Xử lý các lệnh đặc biệt
        if user_input.lower() in ("quit", "exit", "thoát"):
            print("👋 Tạm biệt!")
            break

        if user_input.lower() == "reset":
            engine.reset_conversation()
            continue

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        # Gửi câu hỏi đến RAG Engine
        print("\n⚖️  LexBot: ", end="", flush=True)
        print("(đang tra cứu Graph DB...)\n")

        try:
            answer = engine.query(user_input)
            print(f"⚖️  LexBot:\n{answer}\n")
            print("─" * 60)
        except Exception as e:
            print(f"❌ Lỗi: {e}\n")

    engine.close()


if __name__ == "__main__":
    run_chatbot()
