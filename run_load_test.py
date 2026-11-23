import sys
import asyncio
import httpx
import time

async def buy(client: httpx.AsyncClient, shop_url: str, user_id: str):
    try:
        r = await client.post(
            f"{shop_url}/orders",
            json={"user": user_id, "product": "p1", "qty": 1},
            timeout=15.0
        )
        return r.status_code, r.text
    except Exception as e:
        return 500, str(e)

async def main():
    shop_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    print(f"=== Запуск навантажувального тесту: 20 одночасних покупців u1-u20 ===")
    print(f"Цільовий сервіс: {shop_url}")

    start_time = time.time()
    async with httpx.AsyncClient() as client:
        tasks = [buy(client, shop_url, f"u{i}") for i in range(1, 21)]
        results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time

    status_codes = [code for code, _ in results]
    c_201 = status_codes.count(201)
    c_409 = status_codes.count(409)
    c_402 = status_codes.count(402)
    c_other = [code for code in status_codes if code not in (201, 409, 402)]

    print(f"\nЧас виконання: {total_time:.2f} с")
    print(f"Відповідей 201 (CONFIRMED): {c_201}")
    print(f"Відповідей 409 (OUT_OF_STOCK): {c_409}")
    print(f"Відповідей 402 (INSUFFICIENT_FUNDS): {c_402}")
    if c_other:
        print(f"Інші коди відповідей: {c_other}")

if __name__ == "__main__":
    asyncio.run(main())
