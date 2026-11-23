import os
import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "bank")

def get_connection(autocommit=True):
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=autocommit,
        cursorclass=DictCursor
    )

def init_db():
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True
    )
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME};")
    conn.close()

    conn = get_connection()
    with conn.cursor() as cur:
        # Таблиця рахунків користувачів
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                user_id VARCHAR(64) PRIMARY KEY,
                balance INT NOT NULL
            );
        """)
        # Таблиця резервування коштів (2PC)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tx_reserve (
                tx_id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                amount INT NOT NULL,
                state VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Заповнюємо u1-u20 по 1500 грн, якщо їх ще немає
        cur.execute("SELECT COUNT(*) AS cnt FROM accounts;")
        res = cur.fetchone()
        if res["cnt"] == 0:
            for i in range(1, 21):
                cur.execute("INSERT INTO accounts (user_id, balance) VALUES (%s, 1500);", (f"u{i}",))
    conn.close()
