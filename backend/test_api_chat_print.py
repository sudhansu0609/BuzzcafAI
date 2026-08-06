import requests

res = requests.post(
    "http://localhost:8095/api/chat/completions",
    json={
        "agentId": "agent-sudhanshu-clone",
        "userMessage": "Who are you and what local model are you using?"
    }
)
data = res.json()
print("Agent Name:", data.get("agentName"))
print("Agent Response Text:")
print(data.get("text"))
