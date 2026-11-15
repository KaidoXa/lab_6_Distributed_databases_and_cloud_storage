import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pymysql
from db import init_db, get_connection

# Флаг для імітації "наївного" резервування у Сценарії 1.2
# NAIVE_MODE=true вмикає SELECT -> sleep(0.2) -> UPDATE
NAIVE_MODE = os.getenv("NAIVE_MODE", "false").lower() in ("true", "1", "yes")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ініціалізація таблиць при старті (CREATE TABLE IF NOT EXISTS)
    # Згідно з вимогами розділу 4 методички
    retry_count = 10
    while retry_count > 0:
        try:
            init_db()
            break
        except Exception as e:
            print(f"Waiting for DB... error: {e}")
            time.sleep(2)
            retry_count -= 1
    yield

app = FastAPI(title="Warehouse Service", lifespan=lifespan)

class PrepareRequest(BaseModel):
    product: str
    qty: int

@app.post("/admin/reset")
def reset_data():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE tx_reserve;")
        cur.execute("UPDATE products SET stock = 10 WHERE id = 'p1';")
    conn.close()
    return {"status": "ok"}

@app.get("/stock")
def get_stock():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id, stock FROM products;")
        rows = cur.fetchall()
    conn.close()
    return {row["id"]: row["stock"] for row in rows}

# Контракт 2PC (розділ 7 методички)
@app.post("/tx/{tx_id}/prepare")
def prepare_tx(tx_id: str, req: PrepareRequest):
    conn = get_connection()
    with conn.cursor() as cur:
        # Перевірка на ідемпотентність: чи не існує вже транзакція
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            if existing["state"] in ("PREPARED", "COMMITTED"):
                return {"vote": "YES"}
            return {"vote": "NO", "reason": "out_of_stock"}

        # Перевірка наївного режиму для Сценарію 1.2
        is_naive = os.getenv("NAIVE_MODE", "false").lower() in ("true", "1", "yes")
        if is_naive:
            # Наївний підхід: SELECT -> sleep(0.2) -> UPDATE
            cur.execute("SELECT stock FROM products WHERE id = %s;", (req.product,))
            prod = cur.fetchone()
            if not prod or prod["stock"] < req.qty:
                conn.close()
                return {"vote": "NO", "reason": "out_of_stock"}
            
            time.sleep(0.2) # Імітація паузи за методичкою Сценарій 1.2

            cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s;", (req.qty, req.product))
            cur.execute(
                "INSERT INTO tx_reserve (tx_id, product_id, qty, state) VALUES (%s, %s, %s, 'PREPARED');",
                (tx_id, req.product, req.qty)
            )
            conn.close()
            return {"vote": "YES"}

        # Правильний атомарний підхід:
        # Атомарне зменшення залишку в межах умови WHERE stock >= qty
        affected = cur.execute(
            "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s;",
            (req.qty, req.product, req.qty)
        )
        if affected == 0:
            conn.close()
            return {"vote": "NO", "reason": "out_of_stock"}

        cur.execute(
            "INSERT INTO tx_reserve (tx_id, product_id, qty, state) VALUES (%s, %s, %s, 'PREPARED');",
            (tx_id, req.product, req.qty)
        )
    conn.close()
    return {"vote": "YES"}

@app.post("/tx/{tx_id}/commit")
def commit_tx(tx_id: str):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="tx_not_found")
        
        # Ідемпотентна фіксація
        cur.execute("UPDATE tx_reserve SET state = 'COMMITTED' WHERE tx_id = %s;", (tx_id,))
    conn.close()
    return {"state": "COMMITTED"}

@app.post("/tx/{tx_id}/abort")
def abort_tx(tx_id: str):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT product_id, qty, state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            # Якщо транзакція невідома або не була зарезервована - повертаємо ABORTED ідемпотентно
            return {"state": "ABORTED"}

        if row["state"] == "PREPARED":
            # Повертаємо утриманий товар назад на склад
            cur.execute("UPDATE products SET stock = stock + %s WHERE id = %s;", (row["qty"], row["product_id"]))
            cur.execute("UPDATE tx_reserve SET state = 'ABORTED' WHERE tx_id = %s;", (tx_id,))
        # Якщо вже була ABORTED або COMMITTED, нічого не змінюємо
    conn.close()
    return {"state": "ABORTED"}

@app.get("/tx/{tx_id}")
def get_tx_state(tx_id: str):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"state": row["state"]}
