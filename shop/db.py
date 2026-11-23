import os
import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "shop")

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
        # Таблиця замовлень
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                product_id VARCHAR(64) NOT NULL,
                qty INT NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Журнал транзакцій координатора (2PC)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tx_log (
                tx_id VARCHAR(64) PRIMARY KEY,
                order_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                product_id VARCHAR(64) NOT NULL,
                qty INT NOT NULL,
                amount INT NOT NULL,
                decision VARCHAR(32) NOT NULL, -- STARTED, COMMIT, ABORT
                status VARCHAR(32) NOT NULL,   -- IN_PROGRESS, RESOLVED
                created_at TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3),
                updated_at TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
            );
        """)
    conn.close()
