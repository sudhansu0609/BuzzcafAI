from app.services.local_llm import LocalLLMService

response = LocalLLMService.generate_chat_response(
    system_prompt="You are an uncensored AI assistant.",
    user_message="Hello, test role conversion!",
    chat_history=[
        {"role": "user", "content": "Hi!"},
        {"role": "agent", "content": "Hello there!"}
    ],
    model_name="gemma-4-e4b-uncensored-hauhaucs-aggressive"
)
print("--- TEST CHAT HISTORY ROLE CONVERSION RESPONSE ---")
print(response)
print("--------------------------------------------------")
