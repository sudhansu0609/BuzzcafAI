import requests
import json

res = requests.post(
    "http://localhost:8095/api/chat/completions",
    json={
        "agentId": "agent-sudhanshu-clone",
        "userMessage": "Hello Sudhanshu! How are you doing today?"
    }
)
data = res.json()
print("API Response Text:", json.dumps(data, ensure_ascii=False))
