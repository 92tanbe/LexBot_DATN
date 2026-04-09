from DataModel import RAG
rag = RAG()
while True:
    try:
        user_input = input("Người dùng: ")
        if user_input.strip() == "END":
            break

        response = rag.generate_response(user_input)
        print("CHATBOT: ", response)
        print()
    except KeyboardInterrupt:
        break