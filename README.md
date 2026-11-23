# Лабораторна робота №6: інтернет-магазин на двофазному підтвердженні (2PC)

Три сервіси (Магазин-координатор, Склад і Банк-учасники), RDS MySQL і S3 в AWS Academy Learner Lab.

## Структура
| Шлях | Призначення |
|---|---|
| `shop/` | Магазин: координатор 2PC, журнал `tx_log`, відновлення, S3-чеки (порт 8080) |
| `warehouse/` | Склад: учасник 2PC, атомарне резервування товару (порт 8081) |
| `bank/` | Банк: учасник 2PC, атомарне списання (порт 8082) |
| `terraform/` | Автоматичне розгортання в AWS (`terraform apply` / `terraform destroy`) |
| `tests/local_e2e.py` | Локальний автотест усіх сценаріїв зі справжнім SIGKILL |
| `run_load_test.py`, `run_double_click.py`, `run_scenario_21.py`, `order.py` | Скрипти сценаріїв |
| `check_state.py` | Перевірка інваріантів (розділ 8 методички) |
| `backup.sh` | Резервна копія баз у S3 |
| `INSTRUCTIONS.md` | Покрокова інструкція: локальна перевірка і прогін в AWS |

## Секрети
У репозиторії немає паролів і ключів. Пароль БД та IP для SSH передаються змінними середовища:
```powershell
$env:TF_VAR_db_password = "<8-41 символів: літери, цифри, _ або ->"
$env:TF_VAR_my_ip = "<ваша_публічна_IP>/32"
```

## Швидкий старт
Локально: `docker compose up --build -d`, далі `python check_state.py http://localhost:8080`.
AWS: `cd terraform && terraform init && terraform apply -auto-approve` (облікові дані Learner Lab у `~/.aws/credentials`),
видалення: `terraform destroy -auto-approve`. Усі кроки та сценарії: див. `INSTRUCTIONS.md`.
