# Лабораторна робота №6: інтернет-магазин на двофазному підтвердженні (2PC)

Три сервіси (Магазин-координатор, Склад і Банк-учасники), RDS MySQL і S3 в AWS Academy Learner Lab.

## Структура
| Шлях | Призначення |
|---|---|
| `shop/` | Магазин: координатор 2PC, журнал `tx_log`, відновлення, S3-чеки (порт 8080) |
| `warehouse/` | Склад: учасник 2PC, атомарне резервування товару (порт 8081) |
| `bank/` | Банк: учасник 2PC, атомарне списання (порт 8082) |
| `terraform/` | Автоматичне розгортання в AWS (`terraform apply` / `terraform destroy`) |
| `tests/local_e2e.py` | Локальний автотест усіх сценаріїв |
| `run_load_test.py`, `run_double_click.py`, `run_scenario_21.py`, `order.py` | Скрипти сценаріїв |
| `check_state.py` | Перевірка інваріантів |
| `backup.sh` | Резервна копія баз у S3 |
| `INSTRUCTIONS.md` | Покрокова інструкція: локальна перевірка і прогін в AWS |

## Секрети та запуск
У репозиторії немає паролів і ключів. Пароль БД та IP для SSH передаються змінними середовища до старту:
```%USERPROFILE%\.aws\credentials
[default]
aws_access_key_id = ...
aws_secret_access_key = ...
aws_session_token = ...
```

```powershell
$KEY = "$HOME\.ssh\labsuser.pem"
icacls $KEY /inheritance:r
icacls $KEY /grant:r "$($env:USERNAME):(R)"

$env:TF_VAR_db_password = "<8-41 символів: літери, цифри, _ або ->"
$env:TF_VAR_my_ip = "<ваша_публічна_IP>/32"
```

Створення проекту:
```powershell
cd terraform
terraform init
terraform apply -auto-approve
```

Секрети після повного запуску:
```powershell
$IP     = terraform output -raw shop_public_ip
$BUCKET = terraform output -raw s3_bucket_name
$RDS    = terraform output -raw rds_endpoint
cd ..
$URL = "http://${IP}:8080"
$WH   = aws ec2 describe-instances --filters "Name=tag:Name,Values=lab6-warehouse-ec2" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].PublicIpAddress" --output text
$BANK = aws ec2 describe-instances --filters "Name=tag:Name,Values=lab6-bank-ec2" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].PublicIpAddress" --output text
$SHOP = $IP

function rexec($ip, $cmd) { ssh -i $KEY -o StrictHostKeyChecking=accept-new ec2-user@$ip $cmd }
```