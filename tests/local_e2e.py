"""Локальний e2e-тест усіх сценаріїв 1.2-1.3 і 2.1-2.6 (без Docker і без AWS).

Потрібно: MySQL/MariaDB на localhost:3306 (root / пароль з DB_PASSWORD, за замовчуванням "password"),
наприклад `docker compose up -d mysql`, та `pip install -r requirements.txt`.
Тест сам запускає Склад, Банк і Магазин як окремі процеси (порти 18081/18082/18080), аварійно
завершує їх (SIGKILL) і перевіряє поведінку 2PC. Запуск:  python tests/local_e2e.py
"""
import os
import subprocess
import sys
import threading
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTS = {"shop": 18080, "warehouse": 18081, "bank": 18082}
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
SHOP = f"http://127.0.0.1:{PORTS['shop']}"
procs = {}
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{detail}]" if detail and not cond else ""), flush=True)


def start(name, extra=None):
    env = dict(os.environ, DB_HOST=DB_HOST, DB_PORT="3306", DB_USER="root", DB_PASSWORD=DB_PASSWORD,
               DB_NAME={"shop": "e2e_shop", "warehouse": "e2e_warehouse", "bank": "e2e_bank"}[name],
               WAREHOUSE_URL=f"http://127.0.0.1:{PORTS['warehouse']}", BANK_URL=f"http://127.0.0.1:{PORTS['bank']}",
               PYTHONUNBUFFERED="1")
    env.update(extra or {})
    log = open(os.path.join(ROOT, "tests", f"e2e_{name}.log"), "a")
    procs[name] = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORTS[name]), "--log-level", "warning"],
        cwd=os.path.join(ROOT, name), env=env, stdout=log, stderr=log)
    for _ in range(60):
        try:
            if httpx.get(f"http://127.0.0.1:{PORTS[name]}/openapi.json", timeout=1).status_code == 200:
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{name} did not start")


def kill(name):
    """Аварійне завершення без жодного прибирання (SIGKILL / TerminateProcess)."""
    procs[name].kill()
    procs[name].wait()


def order(user, timeout=60):
    r = httpx.post(f"{SHOP}/orders", json={"user": user, "product": "p1", "qty": 1}, timeout=timeout)
    return r.status_code, r.json()


def state():
    return httpx.get(f"{SHOP}/state", timeout=5).json()


def summary():
    return httpx.get(f"{SHOP}/admin/summary", timeout=5).json()


def last_tx(n=1):
    return httpx.get(f"{SHOP}/admin/tx?limit={n}", timeout=5).json()["tx"]


def reset():
    httpx.post(f"{SHOP}/admin/reset", timeout=10)


def wait_for(cond, timeout, step=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                return time.time() - t0
        except Exception:
            pass
        time.sleep(step)
    return None


def async_order(user, out, key):
    def work():
        try:
            out[key] = order(user)
        except Exception:
            pass  # з'єднання обірвано (наприклад, SIGKILL координатора) - покупець відповіді не отримав
    t = threading.Thread(target=work)
    t.start()
    return t


def restart_shop(delay=0):
    kill("shop") if procs["shop"].poll() is None else None
    start("shop", {"DECISION_DELAY": str(delay)})


def drop_dbs():
    import pymysql
    c = pymysql.connect(host=DB_HOST, user="root", password=DB_PASSWORD, autocommit=True)
    with c.cursor() as cur:
        for d in ("e2e_shop", "e2e_warehouse", "e2e_bank"):
            cur.execute(f"DROP DATABASE IF EXISTS {d}")
    c.close()


def burst(users):
    out = {}
    ths = [async_order(u, out, u) for u in users]
    for t in ths:
        t.join()
    codes = [v[0] for v in out.values()]
    return codes.count(201), codes.count(409), codes.count(402), codes.count(503)


def main():
    for f in os.listdir(os.path.join(ROOT, "tests")):
        if f.startswith("e2e_") and f.endswith(".log"):
            os.remove(os.path.join(ROOT, "tests", f))
    drop_dbs()
    start("warehouse"); start("bank"); start("shop")
    try:
        print("\n== 2.1 Успішна транзакція і голос NO ==")
        reset()
        c, _ = order("u1"); check("перша покупка u1 -> 201", c == 201)
        tx1 = last_tx()[0]
        check("tx 1: Склад і Банк COMMITTED, tx_log COMMIT/RESOLVED",
              (tx1["warehouse"], tx1["bank"], tx1["decision"], tx1["status"]) == ("COMMITTED", "COMMITTED", "COMMIT", "RESOLVED"), tx1)
        c, b = order("u1"); check("друга покупка u1 -> 402 (Банк NO)", c == 402 and b["error"] == "insufficient_funds", (c, b))
        tx2 = last_tx()[0]
        check("tx 2: ABORT, Склад і Банк ABORTED, RESOLVED",
              (tx2["warehouse"], tx2["bank"], tx2["decision"], tx2["status"]) == ("ABORTED", "ABORTED", "ABORT", "RESOLVED"), tx2)
        s = state(); check("stock=9, u1=500, CONFIRMED=1, FAILED=1",
                           s["stock"]["p1"] == 9 and s["balances"]["u1"] == 500 and s["orders"]["CONFIRMED"] == 1 and s["orders"]["FAILED"] == 1, s)

        print("\n== 2.2 Учасник (Банк) недоступний ==")
        kill("bank")
        c, b = order("u3"); check("замовлення при зупиненому Банку -> 503", c == 503, (c, b))
        tx = last_tx()[0]
        check("Склад ABORTED, Банк unavailable, tx_log ABORT/IN_PROGRESS (abort ще не доставлено Банку)",
              (tx["warehouse"], tx["bank"], tx["decision"], tx["status"]) == ("ABORTED", "unavailable", "ABORT", "IN_PROGRESS"), tx)
        start("bank")
        t = wait_for(lambda: last_tx()[0]["status"] == "RESOLVED", 20)
        check("після запуску Банку recovery доставляє abort (RESOLVED)", t is not None)
        s = state(); check("stock=9, u3=1500 (гроші не списано)", s["stock"]["p1"] == 9 and s["balances"]["u3"] == 1500, s)

        print("\n== 2.3 Збій координатора (SIGKILL під час затримки) ==")
        restart_shop(delay=8)
        reset()
        out = {}; th = async_order("u1", out, "u1")
        time.sleep(3)
        tx = last_tx()[0]
        check("до збою: Склад і Банк PREPARED, tx_log STARTED/IN_PROGRESS",
              (tx["warehouse"], tx["bank"], tx["decision"], tx["status"]) == ("PREPARED", "PREPARED", "STARTED", "IN_PROGRESS"), tx)
        s = state(); check("до збою: stock=9, u1=500 (ресурси утримано)", s["stock"]["p1"] == 9 and s["balances"]["u1"] == 500, s)
        kill("shop"); th.join(timeout=20)
        check("покупець не отримав відповіді (з'єднання обірвано)", "u1" not in out)
        time.sleep(3)  # RestartSec=3 у systemd
        t0 = time.time(); start("shop", {"DECISION_DELAY": "0"})
        t = wait_for(lambda: last_tx()[0]["status"] == "RESOLVED", 20, 0.5)
        tx = last_tx()[0]
        check(f"після перезапуску: tx_log ABORT/RESOLVED, обидва ABORTED (за {time.time()-t0:.1f} с)",
              t is not None and (tx["warehouse"], tx["bank"], tx["decision"]) == ("ABORTED", "ABORTED", "ABORT"), tx)
        s = state(); check("stock=10, u1=1500, FAILED=1, CONFIRMED=0",
                           s["stock"]["p1"] == 10 and s["balances"]["u1"] == 1500 and s["orders"]["FAILED"] == 1 and s["orders"]["CONFIRMED"] == 0, s)

        print("\n== 2.4 Збій учасника (Банк) після голосування ==")
        restart_shop(delay=8)
        reset()
        out = {}; th = async_order("u1", out, "u1")
        time.sleep(3)
        kill("bank")
        th.join(timeout=30)
        check("покупець отримав 201 (рішення COMMIT записано)", out.get("u1", (0,))[0] == 201, out)
        tx = last_tx()[0]
        check("Склад COMMITTED, Банк unavailable, tx_log COMMIT/IN_PROGRESS",
              (tx["warehouse"], tx["bank"], tx["decision"], tx["status"]) == ("COMMITTED", "unavailable", "COMMIT", "IN_PROGRESS"), tx)
        time.sleep(6)
        tx = last_tx()[0]; check("координатор НЕ скасував транзакцію, поки Банк недоступний", tx["decision"] == "COMMIT" and tx["status"] == "IN_PROGRESS", tx)
        start("bank")
        t = wait_for(lambda: last_tx()[0]["status"] == "RESOLVED", 20)
        tx = last_tx()[0]
        check("Банк запущено: PREPARED збережено в БД, рішення доставлено -> COMMITTED/COMMITTED, RESOLVED",
              t is not None and (tx["warehouse"], tx["bank"]) == ("COMMITTED", "COMMITTED"), tx)
        s = state(); check("stock=9, u1=500, CONFIRMED=1", s["stock"]["p1"] == 9 and s["balances"]["u1"] == 500 and s["orders"]["CONFIRMED"] == 1, s)

        print("\n== 2.5 Блокування ==")
        restart_shop(delay=0)
        reset()
        for i in range(1, 10):
            order(f"u{i}")
        check("після 9 покупок на складі 1 станція", state()["stock"]["p1"] == 1)
        restart_shop(delay=8)
        out = {}
        t10 = async_order("u10", out, "u10"); time.sleep(2)
        t11 = async_order("u11", out, "u11"); time.sleep(1)
        tx = [x for x in last_tx(2) if x["user_id"] == "u10"][0]
        check("під час затримки tx u10: Склад і Банк PREPARED", (tx["warehouse"], tx["bank"]) == ("PREPARED", "PREPARED"), tx)
        check("під час затримки stock=0 (останню станцію утримано)", state()["stock"]["p1"] == 0)
        t10.join(); t11.join()
        check("u10 -> 201", out["u10"][0] == 201, out)
        check("u11 -> 409, хоча станцію ще не продано на момент запиту", out["u11"][0] == 409, out)
        s = state(); check("підсумок: stock=0, CONFIRMED=10, FAILED=1", s["stock"]["p1"] == 0 and s["orders"]["CONFIRMED"] == 10 and s["orders"]["FAILED"] == 1, s)

        print("\n== 2.6 Розпродаж через 2PC (20 одночасних покупок) ==")
        restart_shop(delay=0)
        reset()
        n201, n409, n402, n503 = burst([f"u{i}" for i in range(1, 21)])
        check("10x201 і 10x409", (n201, n409) == (10, 10), (n201, n409, n402, n503))
        s = state(); spent = sum(1500 - v for v in s["balances"].values())
        check("stock=0, списано 10000, PENDING=0", s["stock"]["p1"] == 0 and spent == 10000 and s["orders"]["PENDING"] == 0, (s["stock"], spent, s["orders"]))
        sm = summary()
        check("немає PREPARED у Складі й Банку і IN_PROGRESS у tx_log",
              "PREPARED" not in sm["warehouse"] and "PREPARED" not in sm["bank"] and "IN_PROGRESS" not in sm["tx_log"], sm)

        print("\n== 1.3 Подвійне натискання ==")
        reset()
        out = {}
        ths = [async_order("u1", out, "a"), async_order("u1", out, "b")]
        for t in ths: t.join()
        codes = sorted(v[0] for v in out.values())
        s = state()
        check("одне 201 і одне 402", codes == [201, 402], codes)
        check("u1=500, stock=9, CONFIRMED=1", s["balances"]["u1"] == 500 and s["stock"]["p1"] == 9 and s["orders"]["CONFIRMED"] == 1, s)

        print("\n== 1.2 Наївна версія Складу (демонстрація перепродажу) ==")
        kill("warehouse"); start("warehouse", {"NAIVE_MODE": "true"})
        reset()
        n201, n409, n402, n503 = burst([f"u{i}" for i in range(1, 21)])
        s = state(); spent = sum(1500 - v for v in s["balances"].values())
        check(f"наївна: перепродаж (201={n201}, stock={s['stock']['p1']}, списано={spent})", n201 > 10 and s["stock"]["p1"] < 0, s)
        kill("warehouse"); start("warehouse")
        reset()
        n201, n409, n402, n503 = burst([f"u{i}" for i in range(1, 21)])
        s = state(); check("атомарна після повернення режиму: 10x201, stock=0", (n201, n409) == (10, 10) and s["stock"]["p1"] == 0, (n201, n409, s["stock"]))
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.kill()
    ok = all(results)
    print(f"\n{'ВСІ ПЕРЕВІРКИ ПРОЙДЕНО' if ok else 'Є ПРОВАЛИ'}: {sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
