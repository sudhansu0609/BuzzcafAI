import requests

url = "http://localhost:8095/api/chat/completions"
headers = {"X-User-ID": "user-sudhanshu"}
payload = {
    "agentId": "agent-1785451513950",
    "userMessage": "Hello shilpi, testing chat completion after saving voice!",
    "chatHistory": []
}

res = requests.post(url, json=payload, headers=headers)
print("STATUS CODE:", res.status_code)
print("RESPONSE BODY:", res.text[:300])
