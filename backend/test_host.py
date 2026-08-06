import urllib.request

try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Host': 'midnightbuzz.buzzcaf.com'
    }
    req = urllib.request.Request('http://127.0.0.1:3005/', headers=headers)
    resp = urllib.request.urlopen(req)
    print("Vite status code with Browser User-Agent =>", resp.status)
except Exception as e:
    print("Vite error:", e)
