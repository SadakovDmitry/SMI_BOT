from aiogram import types, Dispatcher
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.types import BufferedInputFile
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import db
import pandas as pd
from io import BytesIO

def get_role_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    # добавляем все кнопки в один список
    builder.button(text="/add_spec")
    builder.button(text="/broadcast_journalists")
    builder.button(text="/broadcast_speakers")
    builder.button(text="/broadcast_all")
    builder.button(text="/export")
    builder.button(text="/status_all")
    # раскладываем по 2 кнопки в ряд
    builder.adjust(2)
    # собираем разметку
    return builder.as_markup(resize_keyboard=True)

bot = None
send_email = None

async def cmd_add_spec(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Использование: /add_spec <название>")
    await db.add_specialization(parts[1].strip())
    await message.answer(f"Специализация '{parts[1].strip()}' добавлена.")

async def cmd_broadcast_journalists(message: types.Message):
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        return await message.answer("Использование: /broadcast_journalists <текст>")
    for tg in await db.get_all_user_ids_by_role('journalist'):
        await bot.send_message(tg, text[2])
    await message.answer("Разослано журналистам.")

async def cmd_broadcast_speakers(message: types.Message):
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        return await message.answer("Использование: /broadcast_speakers <текст>")
    for tg in await db.get_all_user_ids_by_role('speaker'):
        await bot.send_message(tg, text[2])
    await message.answer("Разослано спикерам.")

async def cmd_broadcast_all(message: types.Message):
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        return await message.answer("Использование: /broadcast_all <текст>")
    all_ids = set(await db.get_all_user_ids_by_role('journalist') + await db.get_all_user_ids_by_role('speaker'))
    for tg in all_ids:
        await bot.send_message(tg, text[2])
    await message.answer("Разослано всем.")

async def cmd_export(message: types.Message):
    # 1) Получаем данные из БД
    users = await db.get_all_users()
    requests = await db.get_all_requests()

    # 2) Пользуемся pandas, чтобы записать в настоящий xlsx
    df_users = pd.DataFrame(users, columns=['id','username','email','role'])
    buf1 = BytesIO()
    df_users.to_excel(buf1, index=False, engine='openpyxl')
    buf1.seek(0)
    # Берём именно bytes, а не сам объект BytesIO
    data1 = buf1.getvalue()
    file1 = BufferedInputFile(data1, filename='users.xlsx')

    df_reqs = pd.DataFrame(
        requests,
        columns=['id','journalist','spec','topic','deadline','format','content','status','chosen_speaker']
    )
    buf2 = BytesIO()
    df_reqs.to_excel(buf2, index=False, engine='openpyxl')
    buf2.seek(0)
    data2 = buf2.getvalue()
    file2 = BufferedInputFile(data2, filename='requests.xlsx')

    # 3) Отправляем пользователю
    await bot.send_document(chat_id=message.chat.id, document=file1)
    await bot.send_document(chat_id=message.chat.id, document=file2)
    await message.answer("📊 Экспорт готов!")

async def cmd_status_all(message: types.Message):
    text = "Все запросы:\n"
    for r in await db.get_all_requests():
        text += f"ID {r[0]}: {r[3]} — {r[7]}\n"
    await message.answer(text)

def register_handlers_admin(dp: Dispatcher, bot_obj, email_func):
    global bot, send_email
    bot = bot_obj
    send_email = email_func
    dp.message.register(cmd_add_spec, Command('add_spec'), StateFilter(None))
    dp.message.register(cmd_broadcast_journalists, Command('broadcast_journalists'), StateFilter(None))
    dp.message.register(cmd_broadcast_speakers, Command('broadcast_speakers'), StateFilter(None))
    dp.message.register(cmd_broadcast_all, Command('broadcast_all'), StateFilter(None))
    dp.message.register(cmd_export, Command('export'), StateFilter(None))
    dp.message.register(cmd_status_all, Command('status_all'), StateFilter(None))
