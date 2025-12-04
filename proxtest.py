import asyncio

from telethon import TelegramClient
from telethon.network.connection import ConnectionTcpAbridged

# اگر از همون API عمومی استفاده می‌کنی همین رو بذار
api_id = 2040
api_hash = "fe0dddfc8abcbfbb6"

session_name = "test_proxy_session"

# بر اساس اسکرین‌شات تو: Local [mixed:10808]
proxy = ("socks5", "127.0.0.1", 10808)


async def main():
    client = TelegramClient(
        session_name,
        api_id,
        api_hash,
        connection=ConnectionTcpAbridged,
        proxy=proxy,
    )

    async with client:
        me = await client.get_me()
        print("CONNECTED OK, USER ID:", me.id)


if __name__ == "__main__":
    asyncio.run(main())
