"""Одне замовлення з позначкою часу (зручно для скріншотів): python order.py http://<SHOP_IP>:8080 u1 [qty]"""
import sys
from datetime import datetime

import httpx


def now():
    return datetime.now().strftime("%H:%M:%S")


url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
user = sys.argv[2] if len(sys.argv) > 2 else "u1"
qty = int(sys.argv[3]) if len(sys.argv) > 3 else 1
print(f"[{now()}] POST /orders user={user} qty={qty}", flush=True)
try:
    r = httpx.post(f"{url}/orders", json={"user": user, "product": "p1", "qty": qty}, timeout=180)
    print(f"[{now()}] HTTP {r.status_code} {r.text}")
except Exception as e:
    print(f"[{now()}] відповіді немає: {type(e).__name__}")
