import asyncio

import httpx


async def main() -> None:
    base = "http://127.0.0.1:8000"
    async with httpx.AsyncClient(base_url=base) as client:
        for i in range(100):
            ping = await client.get("/ping")
            print(ping.status_code, ping.json())

            limited = await client.get("/limited")
            print(limited.status_code, limited.json())


if __name__ == "__main__":
    asyncio.run(main())
