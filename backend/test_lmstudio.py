import requests

res = requests.post(
    "http://localhost:1234/v1/chat/completions",
    json={
        "model": "google/gemma-4-26b-a4b-qat",
        "messages": [{"role": "user", "content": "Hello! Who are you?"}],
        "max_tokens": 100
    }
)
print("LM Studio response status:", res.status_code)
print("Response json:", res.json())
