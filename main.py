# main.py
import logging
import smtplib
from email.mime.text import MIMEText
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
import db

from handlers.registration import register_handlers_registration
from handlers.journalist import register_handlers_journalist
from handlers.speaker import register_handlers_speaker
from handlers.admin import register_handlers_admin

logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера (aiogram v3.x)
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


async def send_email(to_email: str, subject: str, body: str):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = config.FROM_EMAIL
    msg['To'] = to_email

    server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
    server.starttls()
    server.login(config.SMTP_USER, config.SMTP_PASS)
    server.send_message(msg)
    server.quit()


async def on_startup():
    # Создаем таблицы в SQLite
    await bot.delete_webhook(drop_pending_updates=True)
    await db.create_tables()

    # Регистрируем хендлеры в новом API aiogram 3.x
    register_handlers_registration(dp)
    register_handlers_journalist(dp, bot, send_email)
    register_handlers_speaker(dp, bot)
    register_handlers_admin(dp, bot, send_email)

    logging.info("Бот запущен")


if __name__ == '__main__':
    async def _main():
        await on_startup()
        # Запуск поллинга
        await dp.start_polling(bot)
    asyncio.run(_main())
