"""Склад: учасник 2PC.

Метод «запис-резерв»: prepare в ОДНІЙ транзакції БД зменшує залишок і створює рядок
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
    print(f"[warehouse] {msg}", flush=True)


def naive_mode() -> bool:
    # NAIVE_MODE=true вмикає «наївне» резервування SELECT -> sleep(0.2) -> UPDATE (сценарій 1.2)
    return os.getenv("NAIVE_MODE", "false").lower() in ("true", "1", "yes")


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
    log(f"started, NAIVE_MODE={naive_mode()}")
    yield


app = FastAPI(title="Warehouse Service", lifespan=lifespan)


class PrepareRequest(BaseModel):
    product: str
    qty: int


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
def prepare_naive(tx_id: str, req: PrepareRequest):
    """Навмисно НЕПРАВИЛЬНА версія (check-then-act) лише для демонстрації в сценарії 1.2."""
    conn = get_connection()  # autocommit
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT stock FROM products WHERE id = %s;", (req.product,))
            prod = cur.fetchone()
            if not prod or prod["stock"] < req.qty:
                return {"vote": "NO", "reason": "out_of_stock"}
            time.sleep(0.2)  # вікно, в яке встигають інші покупці
            cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s;", (req.qty, req.product))
            cur.execute(
                "INSERT INTO tx_reserve (tx_id, product_id, qty, state) VALUES (%s, %s, %s, 'PREPARED');",
                (tx_id, req.product, req.qty),
            )
        return {"vote": "YES"}
    finally:
        conn.close()


@app.post("/tx/{tx_id}/prepare")
def prepare_tx(tx_id: str, req: PrepareRequest):
    if naive_mode():
        log(f"tx={tx_id} prepare (NAIVE)")
        return prepare_naive(tx_id, req)
    if req.qty <= 0:
        return {"vote": "NO", "reason": "out_of_stock"}

    def work(cur):
        # Атомарна перевірка і зміна: один UPDATE з умовою. InnoDB блокує рядок товару,
        # тому паралельні запити виконуються по черзі й залишок не може піти нижче нуля.
        affected = cur.execute(
            "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s;",
            (req.qty, req.product, req.qty),
        )
        if affected == 0:
            return ("NO", "out_of_stock")
        # Той самий транзакційний контекст: або зміна залишку + рядок PREPARED, або нічого.
        try:
            cur.execute(
                "INSERT INTO tx_reserve (tx_id, product_id, qty, state) VALUES (%s, %s, %s, 'PREPARED');",
                (tx_id, req.product, req.qty),
            )
        except pymysql.err.IntegrityError:
            return ("DUP", None)  # повторний prepare: транзакція вже відома -> відкотимо зміну залишку
        return ("YES", None)

    kind, reason = run_tx(lambda cur: _with_rollback_on_dup(cur, work))
    if kind == "DUP":
        # транзакція вже існує -> відповідаємо за її поточним станом (ідемпотентність)
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
    log(f"tx={tx_id} PREPARED (qty={req.qty} reserved) -> vote YES")
    return {"vote": "YES"}


def _with_rollback_on_dup(cur, work):
    res = work(cur)
    if res[0] == "DUP":
        cur.connection.rollback()  # скасовуємо UPDATE залишку в цій транзакції
    return res


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
        # Якщо транзакція невідома (prepare не дійшов), лишаємо запис ABORTED: запізнілий prepare отримає NO.
        cur.execute(
            "INSERT IGNORE INTO tx_reserve (tx_id, product_id, qty, state) VALUES (%s, '', 0, 'ABORTED');",
            (tx_id,),
        )
        cur.execute("SELECT product_id, qty, state FROM tx_reserve WHERE tx_id = %s FOR UPDATE;", (tx_id,))
        row = cur.fetchone()
        if row["state"] == "PREPARED":
            # повертаємо утриманий товар і змінюємо стан в одній транзакції
            cur.execute("UPDATE products SET stock = stock + %s WHERE id = %s;", (row["qty"], row["product_id"]))
            cur.execute("UPDATE tx_reserve SET state = 'ABORTED' WHERE tx_id = %s;", (tx_id,))
            return ("ABORTED", True)
        return (row["state"], False)  # вже завершена: повертаємо поточний стан

    state, changed = run_tx(work)
    log(f"tx={tx_id} abort -> {state}" + (" (stock returned)" if changed else " (no change)"))
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
