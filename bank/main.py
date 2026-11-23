"""Банк: учасник 2PC.

Метод «запис-резерв»: prepare в ОДНІЙ транзакції БД зменшує баланс і створює рядок
tx_reserve зі станом PREPARED. Стан зберігається в базі, тому переживає перезапуск процесу.
"""
import os
import time
from contextlib import asynccontextmanager

import pymysql
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import init_db, get_connection


def log(msg: str):
    print(f"[bank] {msg}", flush=True)


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
    log("started")
    yield


app = FastAPI(title="Bank Service", lifespan=lifespan)


class PrepareRequest(BaseModel):
    user: str
    amount: int


def run_tx(fn, attempts: int = 4):
    """Виконує fn(conn, cur) в одній транзакції БД; повторює при deadlock (1213) / lock timeout (1205)."""
    for attempt in range(attempts):
        conn = get_connection(autocommit=False)
        try:
            with conn.cursor() as cur:
                result = fn(cur)
            conn.commit()
            return result
        except pymysql.err.OperationalError as e:
            conn.rollback()
            if e.args and e.args[0] in (1213, 1205) and attempt < attempts - 1:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


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


@app.get("/admin/summary")
def summary():
    """Кількість транзакцій за станами (для перевірки «немає PREPARED»)."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT state, COUNT(*) AS cnt FROM tx_reserve GROUP BY state;")
        rows = cur.fetchall()
    conn.close()
    return {r["state"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------- 2PC: prepare
@app.post("/tx/{tx_id}/prepare")
def prepare_tx(tx_id: str, req: PrepareRequest):
    if req.amount <= 0:
        return {"vote": "NO", "reason": "insufficient_funds"}

    def work(cur):
        # Атомарна перевірка і списання: один UPDATE з умовою balance >= amount.
        # InnoDB блокує рядок рахунку, тому два одночасні запити одного покупця виконуються по черзі,
        # і другий бачить уже зменшений баланс (захист від подвійного списання).
        affected = cur.execute(
            "UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND balance >= %s;",
            (req.amount, req.user, req.amount),
        )
        if affected == 0:
            return ("NO", "insufficient_funds")
        try:
            cur.execute(
                "INSERT INTO tx_reserve (tx_id, user_id, amount, state) VALUES (%s, %s, %s, 'PREPARED');",
                (tx_id, req.user, req.amount),
            )
        except pymysql.err.IntegrityError:
            cur.connection.rollback()
            return ("DUP", None)
        return ("YES", None)

    kind, reason = run_tx(work)
    if kind == "DUP":
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
            row = cur.fetchone()
        conn.close()
        if row and row["state"] in ("PREPARED", "COMMITTED"):
            log(f"tx={tx_id} prepare repeated -> YES ({row['state']})")
            return {"vote": "YES"}
        return {"vote": "NO", "reason": "aborted"}
    if kind == "NO":
        log(f"tx={tx_id} prepare -> vote NO ({reason})")
        return {"vote": "NO", "reason": reason}
    log(f"tx={tx_id} PREPARED ({req.amount} reserved from {req.user}) -> vote YES")
    return {"vote": "YES"}


# ---------------------------------------------------------------- 2PC: commit / abort
@app.post("/tx/{tx_id}/commit")
def commit_tx(tx_id: str):
    def work(cur):
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s FOR UPDATE;", (tx_id,))
        row = cur.fetchone()
        if not row:
            return None
        if row["state"] == "PREPARED":
            cur.execute("UPDATE tx_reserve SET state = 'COMMITTED' WHERE tx_id = %s;", (tx_id,))
            return ("COMMITTED", True)
        return (row["state"], False)  # повторний commit: нічого не міняємо

    res = run_tx(work)
    if res is None:
        raise HTTPException(status_code=404, detail="unknown_tx")
    state, changed = res
    log(f"tx={tx_id} commit -> {state}" + ("" if changed else " (repeat, no change)"))
    return {"state": state}


@app.post("/tx/{tx_id}/abort")
def abort_tx(tx_id: str):
    def work(cur):
        # Якщо транзакція невідома (prepare не дійшов або Банк проголосував NO), лишаємо запис ABORTED: запізнілий prepare отримає NO.
        cur.execute(
            "INSERT IGNORE INTO tx_reserve (tx_id, user_id, amount, state) VALUES (%s, '', 0, 'ABORTED');",
            (tx_id,),
        )
        cur.execute("SELECT user_id, amount, state FROM tx_reserve WHERE tx_id = %s FOR UPDATE;", (tx_id,))
        row = cur.fetchone()
        if row["state"] == "PREPARED":
            # повертаємо утримані гроші і змінюємо стан в одній транзакції
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE user_id = %s;", (row["amount"], row["user_id"]))
            cur.execute("UPDATE tx_reserve SET state = 'ABORTED' WHERE tx_id = %s;", (tx_id,))
            return ("ABORTED", True)
        return (row["state"], False)  # вже завершена: повертаємо поточний стан

    state, changed = run_tx(work)
    log(f"tx={tx_id} abort -> {state}" + (" (money returned)" if changed else " (no change)"))
    return {"state": state}


@app.get("/tx/{tx_id}")
def get_tx(tx_id: str):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM tx_reserve WHERE tx_id = %s;", (tx_id,))
        row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="unknown_tx")
    return {"state": row["state"]}
