import sys
import httpx
import json

def run():
    shop_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    print(f"=== Сценарій 2.1: Успішна транзакція і голос NO ===")
    
    with httpx.Client(timeout=10.0) as client:
        # Скидання
        client.post(f"{shop_url}/admin/reset")
        print("Бази скинуто.")

        # Покупка 1
        print("\n--- 1. Перша покупка u1 (Очікуємо 201 CONFIRMED, обидва учасники YES) ---")
        r1 = client.post(f"{shop_url}/orders", json={"user": "u1", "product": "p1", "qty": 1})
        print(f"Відповідь: HTTP {r1.status_code} -> {r1.text}")
        data1 = r1.json()
        order_id_1 = data1.get("order_id")

        # Покупка 2
        print("\n--- 2. Друга покупка u1 (Очікуємо 402, Склад YES, Банк NO -> ABORT) ---")
        r2 = client.post(f"{shop_url}/orders", json={"user": "u1", "product": "p1", "qty": 1})
        print(f"Відповідь: HTTP {r2.status_code} -> {r2.text}")

        # Стан системи
        print("\n--- 3. Стан системи після двох покупок ---")
        r_state = client.get(f"{shop_url}/state")
        print(json.dumps(r_state.json(), indent=2))

if __name__ == "__main__":
    run()
