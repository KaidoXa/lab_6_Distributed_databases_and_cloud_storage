import os
import json
import uuid
import time
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field
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
        "timestamp": datetime.now(timezone.utc).isoformat()
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

def log(msg: str):
    print(f"[shop] {msg}", flush=True)


# tx_id транзакцій, які ПРЯМО ЗАРАЗ виконує цей процес. Після аварійного завершення (SIGKILL) множина
# порожня, тому всі незавершені записи tx_log вважаються «осиротілими» і опрацьовуються відновленням.
IN_FLIGHT = set()


def db_run(statements):
    """Виконує список (sql, params) в ОДНІЙ транзакції БД."""
    conn = get_connection(autocommit=False)
    try:
        with conn.cursor() as cur:
            for sql, params in statements:
                cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_query(sql, params=()):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


async def send_decision(tx_id: str, decision: str) -> bool:
    """Фаза 2: надсилає commit/abort ОБОМ учасникам. True, лише якщо обидва відповіли 200.
    commit/abort ідемпотентні, тому повторне надсилання безпечне."""
    path = "commit" if decision == "COMMIT" else "abort"
    ok = True
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in (("warehouse", WAREHOUSE_URL), ("bank", BANK_URL)):
            try:
                r = await client.post(f"{url}/tx/{tx_id}/{path}")
                if r.status_code == 200:
                    log(f"tx={tx_id} {path} -> {name}: {r.json().get('state')}")
                else:
                    log(f"tx={tx_id} {path} -> {name}: HTTP {r.status_code}")
                    ok = False
            except Exception as e:
                log(f"tx={tx_id} {path} -> {name}: unavailable ({type(e).__name__})")
                ok = False
    return ok


async def recover_once():
    """Один прохід відновлення за журналом tx_log (розділ 7 методички):
    - рішення не прийнято (STARTED) -> ABORT і надсилання abort учасникам;
    - рішення прийнято (COMMIT/ABORT), але хтось не підтвердив -> повторне надсилання, доки обоє не підтвердять.
    Запис позначається RESOLVED лише після підтвердження ОБОХ учасників."""
    rows = db_query("SELECT * FROM tx_log WHERE status = 'IN_PROGRESS' ORDER BY created_at;")
    for tx in rows:
        tx_id = tx["tx_id"]
        if tx_id in IN_FLIGHT:
            continue  # цю транзакцію ще веде живий обробник запиту
        decision = tx["decision"]
        if decision == "STARTED":
            log(f"[recovery] tx={tx_id} has no decision in tx_log -> ABORT")
            db_run([
                ("UPDATE tx_log SET decision = 'ABORT' WHERE tx_id = %s;", (tx_id,)),
                ("UPDATE orders SET status = 'FAILED' WHERE order_id = %s;", (tx["order_id"],)),
            ])
            decision = "ABORT"
        else:
            log(f"[recovery] tx={tx_id} decision={decision} not confirmed by all -> resending")
        if await send_decision(tx_id, decision):
            db_run([("UPDATE tx_log SET status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))])
            log(f"[recovery] tx={tx_id} {decision} delivered to both participants -> RESOLVED")
            if decision == "COMMIT":
                await asyncio.to_thread(save_receipt_to_s3, tx["order_id"], tx["user_id"], tx["product_id"], tx["qty"], tx["amount"])


async def recovery_worker():
    """Фоновий цикл: кожні 5 секунд повторює спроби доставити рішення."""
    while True:
        await asyncio.sleep(5)
        try:
            await recover_once()
        except Exception as e:
            log(f"[recovery] error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    retry_count = 10
    while retry_count > 0:
        try:
            init_db()
            break
        except Exception as e:
            print(f"Waiting for DB... error: {e}", flush=True)
            time.sleep(2)
            retry_count -= 1

    # Відновлення одразу після старту (розділ 7 методички): перегляд журналу tx_log
    log(f"started, DECISION_DELAY={os.getenv('DECISION_DELAY', '0')}; recovery scan of tx_log...")
    try:
        await recover_once()
    except Exception as e:
        log(f"[recovery] startup scan error: {e}")
    recovery_task = asyncio.create_task(recovery_worker())
    yield
    recovery_task.cancel()


app = FastAPI(title="Shop Coordinator Service", lifespan=lifespan)

class OrderRequest(BaseModel):
    user: str
    product: str
    qty: int = Field(ge=1)

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
    IN_FLIGHT.add(tx_id)
    try:
        return await run_order(req, response, order_id, tx_id, amount)
    finally:
        IN_FLIGHT.discard(tx_id)


async def vote(client, url, tx_id, body, default_reason):
    """Надсилає prepare. Помилка з'єднання/тайм-аут/не-200 трактуються як голос NO (service_unavailable)."""
    try:
        r = await client.post(f"{url}/tx/{tx_id}/prepare", json=body)
        if r.status_code == 200:
            data = r.json()
            return data.get("vote", "NO"), data.get("reason", default_reason)
    except Exception:
        pass
    return "NO", "service_unavailable"


async def run_order(req, response, order_id, tx_id, amount):
    # Запис замовлення (PENDING) і транзакції (STARTED) в tx_log — ОДНІЄЮ транзакцією БД
    db_run([
        ("INSERT INTO orders (order_id, user_id, product_id, qty, status) VALUES (%s, %s, %s, %s, 'PENDING');",
         (order_id, req.user, req.product, req.qty)),
        ("INSERT INTO tx_log (tx_id, order_id, user_id, product_id, qty, amount, decision, status) "
         "VALUES (%s, %s, %s, %s, %s, %s, 'STARTED', 'IN_PROGRESS');",
         (tx_id, order_id, req.user, req.product, req.qty, amount)),
    ])
    log(f"tx={tx_id} STARTED order={order_id} user={req.user} qty={req.qty}")

    # Фаза 1 (prepare)
    async with httpx.AsyncClient(timeout=3.0) as client:
        w_vote, w_reason = await vote(client, WAREHOUSE_URL, tx_id, {"product": req.product, "qty": req.qty}, "out_of_stock")
        b_vote, b_reason = await vote(client, BANK_URL, tx_id, {"user": req.user, "amount": amount}, "insufficient_funds")
    log(f"tx={tx_id} votes: warehouse={w_vote}({w_reason}) bank={b_vote}({b_reason})")

    # Вікно для імітації збою координатора або учасника (обидва учасники зараз у стані PREPARED)
    decision_delay = int(os.getenv("DECISION_DELAY", "0"))
    if decision_delay > 0:
        log(f"tx={tx_id} waiting DECISION_DELAY={decision_delay}s before decision")
        await asyncio.sleep(decision_delay)

    decision = "COMMIT" if (w_vote == "YES" and b_vote == "YES") else "ABORT"

    # Рішення СПЕРШУ записується в tx_log (разом зі станом замовлення, однією транзакцією)
    order_final = "CONFIRMED" if decision == "COMMIT" else "FAILED"
    db_run([
        ("UPDATE tx_log SET decision = %s WHERE tx_id = %s;", (decision, tx_id)),
        ("UPDATE orders SET status = %s WHERE order_id = %s;", (order_final, order_id)),
    ])
    log(f"tx={tx_id} DECISION={decision} written to tx_log")

    if decision == "COMMIT":
        # чек підтвердженого замовлення (якщо процес впаде зараз, чек допише відновлення)
        await asyncio.to_thread(save_receipt_to_s3, order_id, req.user, req.product, req.qty, amount)

    # Фаза 2: рішення надсилається учасникам. RESOLVED лише якщо ОБОЄ підтвердили, інакше воркер повторить
    if await send_decision(tx_id, decision):
        db_run([("UPDATE tx_log SET status = 'RESOLVED' WHERE tx_id = %s;", (tx_id,))])
        log(f"tx={tx_id} RESOLVED")
    else:
        log(f"tx={tx_id} decision not delivered to everyone -> stays IN_PROGRESS, recovery will retry")

    # Відповідь покупцю — після запису рішення (транзакція вважається завершеною)
    if decision == "COMMIT":
        response.status_code = status.HTTP_201_CREATED
        return {"order_id": order_id, "status": "CONFIRMED"}
    if "service_unavailable" in (w_reason, b_reason):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"error": "service_unavailable"}
    if w_vote == "NO":
        response.status_code = status.HTTP_409_CONFLICT
        return {"error": "out_of_stock"}
    response.status_code = status.HTTP_402_PAYMENT_REQUIRED
    return {"error": "insufficient_funds"}


# ---------------------------------------------------------------- допоміжні ендпоінти для спостереження
async def participant_state(client, url, tx_id):
    try:
        r = await client.get(f"{url}/tx/{tx_id}")
        if r.status_code == 200:
            return r.json().get("state")
        return f"HTTP {r.status_code}"
    except Exception:
        return "unavailable"


@app.get("/admin/tx")
async def admin_tx(limit: int = 5):
    """Останні транзакції з tx_log і їхній стан у Складі та Банку (для звіту/демонстрації)."""
    rows = db_query(
        "SELECT tx_id, order_id, user_id, decision, status, created_at FROM tx_log ORDER BY created_at DESC LIMIT %s;",
        (limit,),
    )
    async with httpx.AsyncClient(timeout=3.0) as client:
        for row in rows:
            row["created_at"] = str(row["created_at"])
            row["warehouse"] = await participant_state(client, WAREHOUSE_URL, row["tx_id"])
            row["bank"] = await participant_state(client, BANK_URL, row["tx_id"])
    return {"tx": rows}


@app.get("/admin/summary")
async def admin_summary():
    """Кількість транзакцій за станами: tx_log, Склад, Банк. Для перевірки «немає PREPARED / IN_PROGRESS»."""
    rows = db_query("SELECT status, COUNT(*) AS cnt FROM tx_log GROUP BY status;")
    result = {"tx_log": {r["status"]: r["cnt"] for r in rows}}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in (("warehouse", WAREHOUSE_URL), ("bank", BANK_URL)):
            try:
                r = await client.get(f"{url}/admin/summary")
                result[name] = r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception:
                result[name] = "unavailable"
    return result
