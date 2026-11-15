#!/bin/bash
# test_scenarios.sh - Автоматизований запуск сценаріїв з методички

SHOP_URL="${1:-http://localhost:8080}"
echo "Цільовий Магазин: $SHOP_URL"

run_check() {
  echo -e "\n--- Перевірка інваріантів (Розділ 8) ---"
  STATE=$(curl -s "$SHOP_URL/state")
  echo "State: $STATE"
  python3 -c "
import sys, json
data = json.loads('''$STATE''')
stock = data.get('stock', {}).get('p1', 0)
confirmed = data.get('orders', {}).get('CONFIRMED', 0)
pending = data.get('orders', {}).get('PENDING', 0)

print(f'Перевірка 1: stock ({stock}) >= 0 and confirmed ({confirmed}) + stock ({stock}) == 10: {stock >= 0 and confirmed + stock == 10}')
print(f'Перевірка 2: pending == 0: {pending == 0}')
"
}

case "$2" in
  reset)
    echo "=== Скидання системи: POST /admin/reset ==="
    curl -i -X POST "$SHOP_URL/admin/reset"
    run_check
    ;;

  s11)
    echo "=== Сценарій 1.1: Звичайна покупка (u1) ==="
    curl -X POST "$SHOP_URL/admin/reset"
    echo -e "\nВиконуємо замовлення u1:"
    curl -i -X POST "$SHOP_URL/orders" -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}'
    run_check
    ;;

  s12)
    echo "=== Сценарій 1.2: Розпродаж (20 одночасних запитів u1-u20) ==="
    curl -X POST "$SHOP_URL/admin/reset"
    echo -e "\nЗапуск 20 клієнтів паралельно..."
    for i in {1..20}; do
      curl -s -w "User u$i -> HTTP %{http_code}\n" -X POST "$SHOP_URL/orders" \
        -H "Content-Type: application/json" \
        -d "{\"user\": \"u$i\", \"product\": \"p1\", \"qty\": 1}" &
    done
    wait
    run_check
    ;;

  s13)
    echo "=== Сценарій 1.3: Подвійне натискання (два запити u1) ==="
    curl -X POST "$SHOP_URL/admin/reset"
    echo -e "\nОдночасне відправлення двох запитів від u1..."
    curl -s -w "Req 1 -> HTTP %{http_code}\n" -X POST "$SHOP_URL/orders" -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}' &
    curl -s -w "Req 2 -> HTTP %{http_code}\n" -X POST "$SHOP_URL/orders" -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}' &
    wait
    run_check
    ;;

  s21)
    echo "=== Сценарій 2.1: Успішна транзакція і голос NO ==="
    curl -X POST "$SHOP_URL/admin/reset"
    echo "Покупка 1 (u1, успішно):"
    curl -i -X POST "$SHOP_URL/orders" -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}'
    echo -e "\nПокупка 2 (u1, не вистачає грошей, очікуємо 402):"
    curl -i -X POST "$SHOP_URL/orders" -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}'
    run_check
    ;;

  *)
    echo "Використання: ./test_scenarios.sh <SHOP_URL> <reset|s11|s12|s13|s21>"
    ;;
esac
