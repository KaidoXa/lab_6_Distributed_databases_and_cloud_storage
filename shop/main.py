import os
import json
import uuid
import time
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
import httpx
import boto3
from botocore.exceptions import ClientError
from db import init_db, get_connection

WAREHOUSE_URL = os.getenv("WAREHOUSE_URL", "http://localhost:8081")
BANK_URL = os.getenv("BANK_URL", "http://localhost:8082")
S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PRICE_PER_ITEM = int(os.getenv("PRICE_PER_ITEM", "1000"))

# Ініціалізація клієнта S3
s3_client = None
if S3_BUCKET:
    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
    except Exception as e:
        print(f"Warning: S3 client initialization failed: {e}")

def save_receipt_to_s3(order_id: str, user_id: str, product_id: str, qty: int, amount: int):
    if not S3_BUCKET or not s3_client:
        return
    receipt_data = {
        "order_id": order_id,
        "user": user_id,
        "product": product_id,
        "qty": qty,
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat()
    }
    key = f"receipts/{order_id}.json"
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(receipt_data, indent=2),
            ContentType="application/json"
        )
    except Exception as e:
        print(f"Failed to upload receipt to S3: {e}")

# Функція відновлення після збою координатора (розділ 7 методички)
async def recovery_worker():
    """
    Періодично перевіряє журнал tx_log:
    - Якщо транзакція у стані STARTED -> надсилає abort учасникам і фіксує ABORT.
    - Якщо транзакція у стані COMMIT, але ще не завершена (IN_PROGRESS) -> повторює надсилання commit доки учасники не підтвердять.
    """
    while True:
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tx_log WHERE status = 'IN_PROGRESS';")
                pending_txs = cur.fetchall()
            conn.close()

            if pending_txs:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    for tx in pending_txs:
                        tx_id = tx["tx_id"]
                        decision = tx["decision"]

                        if decision == "STARTED":
                            # Збій стався до прийняття рішення -> ABORT
                            print(f"[Recovery] Found unfinalized STARTED tx {tx_id}. Aborting...")
                            try:
                                await client.post(f"{WAREHOUSE_URL}/tx/{tx_id}/abort")
                            except Exception:
                                pass
                            try:
                                await client.post(f"{BANK_URL}/tx/{tx_id}/abort")
                            except Exception:
                                pass

                            conn = get_connection()
                            with conn.cursor() as cur:
                                cur.execute("UPDATE tx_log SET decision = 'ABORT', status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))
                                cur.execute("UPDATE orders SET status = 'FAILED' WHERE order_id = %s;", (tx["order_id"],))
                            conn.close()

                        elif decision == "COMMIT":
                            # Рішення було прийнято, але можливо не всі учасники отримали його (наприклад, Банк впав)
                            print(f"[Recovery] Retrying COMMIT for tx {tx_id}...")
                            w_ok = False
                            b_ok = False
                            try:
                                r_w = await client.post(f"{WAREHOUSE_URL}/tx/{tx_id}/commit")
                                if r_w.status_code == 200:
                                    w_ok = True
                            except Exception:
                                pass

                            try:
                                r_b = await client.post(f"{BANK_URL}/tx/{tx_id}/commit")
                                if r_b.status_code == 200:
                                    b_ok = True
                            except Exception:
                                pass

                            if w_ok and b_ok:
                                conn = get_connection()
                                with conn.cursor() as cur:
                                    cur.execute("UPDATE tx_log SET status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))
                                conn.close()
                                print(f"[Recovery] Successfully confirmed COMMIT for tx {tx_id}")

        except Exception as e:
            print(f"[Recovery Worker Error]: {e}")

        await asyncio.sleep(5)  # Кожні 5 секунд за методичкою

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ініціалізація БД при старті
    retry_count = 10
    while retry_count > 0:
        try:
            init_db()
            break
        except Exception as e:
            print(f"Waiting for DB... error: {e}")
            time.sleep(2)
            retry_count -= 1

    # Запуск фонового процесу відновлення
    recovery_task = asyncio.create_task(recovery_worker())
    yield
    recovery_task.cancel()

app = FastAPI(title="Shop Coordinator Service", lifespan=lifespan)

class OrderRequest(BaseModel):
    user: str
    product: str
    qty: int

@app.post("/admin/reset")
async def reset_all():
    # Скидаємо власні таблиці
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE tx_log;")
        cur.execute("TRUNCATE TABLE orders;")
    conn.close()

    # Скидаємо Склад і Банк
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{WAREHOUSE_URL}/admin/reset")
        except Exception as e:
            print(f"Reset warehouse error: {e}")
        try:
            await client.post(f"{BANK_URL}/admin/reset")
        except Exception as e:
            print(f"Reset bank error: {e}")

    return {"status": "ok"}

@app.get("/orders/{order_id}")
def get_order(order_id: str, response: Response):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT order_id, user_id AS user, product_id AS product, qty, status FROM orders WHERE order_id = %s;", (order_id,))
        row = cur.fetchone()
    conn.close()
    if not row:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "order_not_found"}
    return row

@app.get("/state")
async def get_system_state():
    # 1. Залишки зі Складу
    stock_data = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{WAREHOUSE_URL}/stock")
            if r.status_code == 200:
                stock_data = r.json()
        except Exception:
            stock_data = {"error": "warehouse_unavailable"}

        # 2. Баланси з Банку
        balances_data = {}
        try:
            r = await client.get(f"{BANK_URL}/balances")
            if r.status_code == 200:
                balances_data = r.json()
        except Exception:
            balances_data = {"error": "bank_unavailable"}

    # 3. Статуси замовлень з власної бази
    orders_summary = {"CONFIRMED": 0, "FAILED": 0, "PENDING": 0}
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status;")
        rows = cur.fetchall()
        for row in rows:
            if row["status"] in orders_summary:
                orders_summary[row["status"]] = row["cnt"]
    conn.close()

    return {
        "stock": stock_data,
        "balances": balances_data,
        "orders": orders_summary
    }

@app.post("/orders")
async def create_order(req: OrderRequest, response: Response):
    order_id = str(uuid.uuid4())
    tx_id = str(uuid.uuid4())
    amount = req.qty * PRICE_PER_ITEM

    # Запис початкового стану замовлення та транзакції
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (order_id, user_id, product_id, qty, status) VALUES (%s, %s, %s, %s, 'PENDING');",
            (order_id, req.user, req.product, req.qty)
        )
        cur.execute(
            """INSERT INTO tx_log (tx_id, order_id, user_id, product_id, qty, amount, decision, status) 
               VALUES (%s, %s, %s, %s, %s, %s, 'STARTED', 'IN_PROGRESS');""",
            (tx_id, order_id, req.user, req.product, req.qty, amount)
        )
    conn.close()

    # Фаза 1 (prepare): паралельно або послідовно опитуємо учасників
    w_vote = "NO"
    w_reason = "service_unavailable"
    b_vote = "NO"
    b_reason = "service_unavailable"

    async with httpx.AsyncClient(timeout=3.0) as client:
        # Prepare Warehouse
        try:
            res_w = await client.post(f"{WAREHOUSE_URL}/tx/{tx_id}/prepare", json={"product": req.product, "qty": req.qty})
            if res_w.status_code == 200:
                data_w = res_w.json()
                w_vote = data_w.get("vote", "NO")
                w_reason = data_w.get("reason", "out_of_stock")
        except Exception:
            w_vote = "NO"
            w_reason = "service_unavailable"

        # Prepare Bank
        try:
            res_b = await client.post(f"{BANK_URL}/tx/{tx_id}/prepare", json={"user": req.user, "amount": amount})
            if res_b.status_code == 200:
                data_b = res_b.json()
                b_vote = data_b.get("vote", "NO")
                b_reason = data_b.get("reason", "insufficient_funds")
        except Exception:
            b_vote = "NO"
            b_reason = "service_unavailable"

    # Вікно для імітації збою координатора або учасника
    decision_delay = int(os.getenv("DECISION_DELAY", "0"))
    if decision_delay > 0:
        print(f"Waiting DECISION_DELAY of {decision_delay}s...")
        await asyncio.sleep(decision_delay)

    # Прийняття рішення
    decision = "COMMIT" if (w_vote == "YES" and b_vote == "YES") else "ABORT"

    # Запис рішення в tx_log (строго перед повідомленням учасників за розділом 7 методички)
    order_final_status = "CONFIRMED" if decision == "COMMIT" else "FAILED"
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE tx_log SET decision = %s WHERE tx_id = %s;", (decision, tx_id))
        cur.execute("UPDATE orders SET status = %s WHERE order_id = %s;", (order_final_status, order_id))
    conn.close()

    # Фаза 2 (commit/abort)
    async with httpx.AsyncClient(timeout=3.0) as client:
        if decision == "COMMIT":
            # Якщо COMMIT - надсилаємо учасникам
            w_commited = False
            b_commited = False
            try:
                rw = await client.post(f"{WAREHOUSE_URL}/tx/{tx_id}/commit")
                if rw.status_code == 200:
                    w_commited = True
            except Exception:
                pass

            try:
                rb = await client.post(f"{BANK_URL}/tx/{tx_id}/commit")
                if rb.status_code == 200:
                    b_commited = True
            except Exception:
                pass

            # Якщо обидва відповіли успішно - ставимо RESOLVED, інакше воркер відновлення завершить
            if w_commited and b_commited:
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute("UPDATE tx_log SET status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))
                conn.close()

            # Зберігаємо чек у S3
            save_receipt_to_s3(order_id, req.user, req.product, req.qty, amount)

            response.status_code = status.HTTP_201_CREATED
            return {"order_id": order_id, "status": "CONFIRMED"}

        else:
            # Якщо ABORT - надсилаємо abort
            try:
                await client.post(f"{WAREHOUSE_URL}/tx/{tx_id}/abort")
            except Exception:
                pass

            try:
                await client.post(f"{BANK_URL}/tx/{tx_id}/abort")
            except Exception:
                pass

            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE tx_log SET status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))
            conn.close()

            # Формуємо код відповіді за контрактом
            if w_reason == "service_unavailable" or b_reason == "service_unavailable":
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"error": "service_unavailable"}
            elif w_vote == "NO":
                response.status_code = status.HTTP_409_CONFLICT
                return {"error": "out_of_stock"}
            elif b_vote == "NO":
                response.status_code = status.HTTP_402_PAYMENT_REQUIRED
                return {"error": "insufficient_funds"}
            else:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"error": "service_unavailable"}
