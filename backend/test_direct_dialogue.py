from app.services.local_llm import LocalLLMService

response = LocalLLMService.generate_chat_response(
    system_prompt="teran nam shilpi hai aur tu office worker hai.",
    user_message="Hello shilpi, kya kar rahi ho?",
    chat_history=[],
    model_name="google/gemma-4-26b-a4b-qat"
)

print("=== DIRECT HUMAN DIALOGUE OUTPUT ===")
print(response)
print("====================================")
