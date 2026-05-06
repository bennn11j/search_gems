import asyncio

from app.config import settings
from app.notifier import TelegramNotifier


async def main():
    notifier = TelegramNotifier(settings.tg_bot_token, settings.tg_chat_id)
    ok = await notifier.send("✅ Test message from dota2_gem_finder")
    print("sent:", ok)


if __name__ == "__main__":
    asyncio.run(main())