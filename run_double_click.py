import asyncio
import httpx
import sys

async def order(client, shop_url, req_id):
    r = await client.post(
        f"{shop_url}/orders",
        json={"user": "u1", "product": "p1", "qty": 1},
        timeout=10.0
    )
    print(f"Запит {req_id}: HTTP {r.status_code} -> {r.text}")
    return r.status_code

async def main():
    shop_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    print("=== Сценарій 1.3: Подвійне натискання від u1 ===")
    async with httpx.AsyncClient() as client:
        # Скидання перед тестом
        await client.post(f"{shop_url}/admin/reset")
        print("Бази скинуто до початкових. Надсилаємо 2 одночасні запити від u1...")
        res = await asyncio.gather(
            order(client, shop_url, 1),
            order(client, shop_url, 2)
        )
    print(f"\nПідсумок: статус-коди = {res}")

if __name__ == "__main__":
    asyncio.run(main())
