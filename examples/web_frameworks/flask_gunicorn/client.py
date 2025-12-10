import httpx


def main() -> None:
    base = "http://127.0.0.1:5000"
    with httpx.Client(base_url=base) as client:
        for _ in range(100):
            ping = client.get("/ping")
            print(ping.status_code, ping.json())

            limited = client.get("/limited")
            print(limited.status_code, limited.json())


if __name__ == "__main__":
    main()
