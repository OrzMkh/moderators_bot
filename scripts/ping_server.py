"""Cron-скрипт: Keep-alive ping для Render free tier."""
import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx


async def ping() -> None:
    render_url = os.environ.get("RENDER_APP_URL", "").rstrip("/")
    if not render_url:
        print("Error: RENDER_APP_URL environment variable is not set.")
        sys.exit(1)

    url = f"{render_url}/health"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url)
            ts = datetime.now(timezone.utc).isoformat()
            print(f"[{ts}] Ping {url} → Status: {response.status_code}")
            sys.exit(0 if response.status_code == 200 else 1)
        except Exception as e:
            print(f"Ping failed: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(ping())
