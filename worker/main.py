import asyncio
import os

async def main():
    interval = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
    while True:
        print("worker: heartbeat")
        await asyncio.sleep(interval)

if __name__ == "__main__":
    asyncio.run(main())
