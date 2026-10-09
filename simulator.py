import sys, time, requests

BASE = "http://localhost:8000"
key = sys.argv[1]
plate = sys.argv[2] if len(sys.argv) > 2 else "01A123BC"

def post(path, **body):
    r = requests.post(BASE + path, json={"device_key": key, **body})
    print(path, r.status_code, r.json())

post("/api/device/heartbeat")
post("/api/anpr/plate", plate=plate)
for _ in range(3):
    time.sleep(1)
    post("/api/device/pulse", count=1, amount=5000)
time.sleep(1)
post("/api/device/exit")
