import asyncio

from aiogram import Bot


BOT_TOKEN = "8202374178:AAHjYzQg1WjUNZUJG-j3umdkQ-8yJA_UVsw"


async def main():
    async with Bot(token=BOT_TOKEN) as bot:
        await bot.delete_webhook(drop_pending_updates=True)

        print("Теперь отправь новое сообщение в канал и нажми Enter...")
        input()

        updates = await bot.get_updates(timeout=10)

        if not updates:
            print("Апдейтов нет")
            return

        found = False

        for update in updates:
            if update.channel_post:
                chat = update.channel_post.chat
                print(f"TITLE: {chat.title}")
                print(f"CHAT ID: {chat.id}")
                print("-" * 40)
                found = True

        if not found:
            print("channel_post не найден")


if __name__ == "__main__":
    asyncio.run(main())