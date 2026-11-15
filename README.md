# Лабораторна робота №6: Інтернет-магазин на 2PC (Двофазне підтвердження)

## Структура репозиторію
- `warehouse/` — мікросервіс Складу (порт 8081).
- `bank/` — мікросервіс Банку (порт 8082).
- `shop/` — мікросервіс Магазину / Координатора (порт 8080).
- `terraform/` — конфігурація для автоматичного розгортання в AWS Academy Learner Lab.
- `backup.sh` — скрипт створення бекапів MySQL у S3.
- `check_state.py` — скрипт валідації інваріантів системи (Розділ 8).
- `test_scenarios.sh` — скрипти для тестування сценаріїв навантаження.

---

## 1. Локальний запуск (через Docker Compose)

```bash
cd lab/6_lab/src
docker compose up --build -d
```
Перевірка стану системи:
```bash
curl http://localhost:8080/state
```

---

## 2. Автоматичне розгортання в AWS Academy (Terraform)

### Крок 1. Налаштування облікових даних AWS
На початку сесії AWS Academy Learner Lab скопіюйте `AWS Details` -> `AWS CLI credentials` та вставте їх у файл `~/.aws/credentials`:
```ini
[default]
aws_access_key_id = ASIA...
aws_secret_access_key = ...
aws_session_token = ...
```

### Крок 2. Розгортання системи
Перейдіть у папку з Terraform:
```bash
cd terraform
terraform init
terraform apply -auto-approve
```
Після завершення (5-10 хв через ініціалізацію RDS) у терміналі відобразиться публічна IP-адреса Магазину (`shop_public_ip`) та URL для тестування.

---

## 3. Виконання перевірок і сценаріїв

Всі сценарії запускаються з терміналу зверненням до публічної адреси Магазину:
```bash
# Скидання даних
curl -X POST http://<SHOP_IP>:8080/admin/reset

# Сценарій 1.1: Звичайна покупка
curl -i -X POST http://<SHOP_IP>:8080/orders -H "Content-Type: application/json" -d '{"user": "u1", "product": "p1", "qty": 1}'

# Перевірка інваріантів
python3 check_state.py http://<SHOP_IP>:8080
```

---

## 4. Створення резервної копії (backup.sh)
Згідно з вимогами до звіту:
```bash
./backup.sh <RDS_ENDPOINT> admin Lab6Password123! <S3_BUCKET_NAME>
```

---

## 5. Повне видалення ресурсів
Наприкінці роботи (щоб не витрачати бюджет Learner Lab):
```bash
cd terraform
terraform destroy -auto-approve
```
