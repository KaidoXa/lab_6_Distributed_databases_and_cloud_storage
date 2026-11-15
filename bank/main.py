import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pymysql
from db import init_db, get_connection

@asynccontextmanager
async def lifespan(app: FastAPI):
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

app = FastAPI(title="Bank Service", lifespan=lifespan)

class PrepareRequest(BaseModel):
    user: str
    amount: int

@app.post("/admin/reset")
def reset_data():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE tx_reserve;")
        cur.execute("TRUNCATE TABLE accounts;")
        for i in range(1, 21):
            cur.execute("INSERT INTO accounts (user_id, balance) VALUES (%s, 1500);", (f"u{i}",))
    conn.close()
    return {"status": "ok"}

@app.get("/balances")
def get_balances():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, balance FROM accounts;")
        rows = cur.fetchall()
    conn.close()
    return {row["user_id"]: row["balance"] for row in rows}

# Контракт 2PC (розділ 7 методички)
@app.post("/tx/{tx_id}/prepare")
def prepare_tx(tx_id: str, req: PrepareRequest):
    conn = get_connection()
    with conn.cursor() as cur:
        # Ідемпотентність
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            if existing["state"] in ("PREPARED", "COMMITTED"):
                return {"vote": "YES"}
            return {"vote": "NO", "reason": "insufficient_funds"}

        # Атомарне списання грошей: WHERE balance >= amount
        affected = cur.execute(
            "UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND balance >= %s;",
            (req.amount, req.user, req.amount)
        )
        if affected == 0:
            conn.close()
            return {"vote": "NO", "reason": "insufficient_funds"}

        cur.execute(
            "INSERT INTO tx_reserve (tx_id, user_id, amount, state) VALUES (%s, %s, %s, 'PREPARED');",
            (tx_id, req.user, req.amount)
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
        
        cur.execute("UPDATE tx_reserve SET state = 'COMMITTED' WHERE tx_id = %s;", (tx_id,))
    conn.close()
    return {"state": "COMMITTED"}

@app.post("/tx/{tx_id}/abort")
def abort_tx(tx_id: str):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, amount, state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"state": "ABORTED"}

        if row["state"] == "PREPARED":
            # Повертаємо утримані кошти користувачу
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE user_id = %s;", (row["amount"], row["user_id"]))
            cur.execute("UPDATE tx_reserve SET state = 'ABORTED' WHERE tx_id = %s;", (tx_id,))
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
