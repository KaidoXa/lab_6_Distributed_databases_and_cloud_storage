import os
import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "warehouse")

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
    # Підключаємося спочатку без зазначення бази даних, щоб створити її якщо не існує
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
        # Таблиця товарів
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                stock INT NOT NULL,
                price INT NOT NULL
            );
        """)
        # Таблиця транзакцій резервування (2PC)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tx_reserve (
                tx_id VARCHAR(64) PRIMARY KEY,
                product_id VARCHAR(64) NOT NULL,
                qty INT NOT NULL,
                state VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Початковий стан: товар p1 - 10 шт., ціна 1000 грн
        cur.execute("SELECT COUNT(*) AS cnt FROM products WHERE id = 'p1';")
        res = cur.fetchone()
        if res["cnt"] == 0:
            cur.execute("INSERT INTO products (id, name, stock, price) VALUES ('p1', 'Зарядна станція', 10, 1000);")
    conn.close()
