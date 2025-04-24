# handlers/admin.py
from aiogram import types, Dispatcher
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.types import BufferedInputFile
import db, csv, io

bot = None
send_email = None

async def cmd_add_spec(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /add_spec <название>")
        return
    name = parts[1].strip()
    await db.add_specialization(name)
    await message.answer(f"Специализация '{name}' добавлена.")

async def cmd_broadcast_journalists(message: types.Message):
    text = message.text.partition(' ')[2]
    ids = await db.get_all_user_ids_by_role('journalist')
    for tg_id in ids:
        await bot.send_message(tg_id, text)
    await message.answer("Сообщение отправлено журналистам.")

async def cmd_broadcast_speakers(message: types.Message):
    text = message.text.partition(' ')[2]
    ids = await db.get_all_user_ids_by_role('speaker')
    for tg_id in ids:
        await bot.send_message(tg_id, text)
    await message.answer("Сообщение отправлено спикерам.")

async def cmd_broadcast_all(message: types.Message):
    text = message.text.partition(' ')[2]
    all_ids = set((await db.get_all_user_ids_by_role('journalist')) + (await db.get_all_user_ids_by_role('speaker')))
    for tg_id in all_ids:
        await bot.send_message(tg_id, text)
    await message.answer("Сообщение отправлено всем.")


async def cmd_export(message: types.Message):
    users = await db.get_all_users()
    requests = await db.get_all_requests()

    # CSV для пользователей
    buf1 = io.StringIO()
    w1 = csv.writer(buf1)
    w1.writerow(['id','username','email','role'])
    w1.writerows(users)
    data1 = buf1.getvalue().encode('utf-8')
    file1 = BufferedInputFile(data1, filename='users.csv')

    # CSV для запросов
    buf2 = io.StringIO()
    w2 = csv.writer(buf2)
    w2.writerow(['id','journalist','spec','topic','deadline','format','content','status','chosen_speaker'])
    w2.writerows(requests)
    data2 = buf2.getvalue().encode('utf-8')
    file2 = BufferedInputFile(data2, filename='requests.csv')

    # Отправляем
    await bot.send_document(chat_id=message.chat.id, document=file1)
    await bot.send_document(chat_id=message.chat.id, document=file2)

async def cmd_status_all(message: types.Message):
    # Статус всех запросов для администратора
    reqs = await db.get_all_requests()
    text = "Все запросы:\n"
    for r in reqs:
        text += f"ID {r[0]}: {r[1]} → {r[2]} [{r[7]}]\n"
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
