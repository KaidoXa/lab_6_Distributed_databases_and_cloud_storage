import sys
import json
import httpx

def check_invariants(shop_url: str):
    print(f"Checking state on {shop_url}...")
    try:
        r = httpx.get(f"{shop_url}/state", timeout=5.0)
    except Exception as e:
        print(f"Error fetching state: {e}")
        sys.exit(1)

    if r.status_code != 200:
        print(f"Failed to fetch state: HTTP {r.status_code} - {r.text}")
        sys.exit(1)

    data = r.json()
    print("Received state:\n", json.dumps(data, indent=2, ensure_ascii=False))

    stock = data.get("stock", {}).get("p1", None)
    balances = data.get("balances", {})
    orders = data.get("orders", {})

    confirmed = orders.get("CONFIRMED", 0)
    failed = orders.get("FAILED", 0)
    pending = orders.get("PENDING", 0)

    errors = []

    # Інваріант 1: залишок на складі не від'ємний, а продано + залишок = 10
    if stock is None:
        errors.append("Не вдалося отримати залишок складу (stock.p1 is missing).")
    else:
        if stock < 0:
            errors.append(f"Залишок товару від'ємний: {stock} < 0")
        if stock + confirmed != 10:
            errors.append(f"Порушено баланс залишку: stock ({stock}) + confirmed ({confirmed}) != 10")

    # Інваріант 2: баланс жодного покупця не від'ємний
    for user, bal in balances.items():
        if isinstance(bal, (int, float)) and bal < 0:
            errors.append(f"Баланс покупця {user} від'ємний: {bal}")

    # Інваріант 3: сума списаних грошей = кількість підтверджених замовлень * 1000 грн
    total_spent = sum(1500 - bal for bal in balances.values() if isinstance(bal, (int, float)))
    expected_spent = confirmed * 1000
    if total_spent != expected_spent:
        errors.append(f"Сума списаних грошей ({total_spent}) != очікувана сума ({expected_spent})")

    # Інваріант 4: немає замовлень у стані PENDING
    if pending != 0:
        errors.append(f"Є незавершені замовлення в PENDING: {pending}")

    print("\n" + "="*40)
    if errors:
        print("❌ ВИЯВЛЕНО ПОРУШЕННЯ ІНВАРІАНТІВ (Розділ 8):")
        for err in errors:
            print(f" - {err}")
        sys.exit(1)
    else:
        print("✅ ВСІ ІНВАРІАНТИ ВИКОНАНО УСПІШНО!")
        print(f" - Залишок: {stock}, Підтверджено: {confirmed}, Разом: 10")
        print(f" - Усі баланси >= 0, сума списання: {total_spent} грн")
        print(f" - PENDING замовлень: 0")
    print("="*40)

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    check_invariants(url)
