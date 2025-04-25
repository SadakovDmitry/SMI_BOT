# handlers/admin.py

from aiogram import types, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.state import StateFilter
from aiogram.types import BufferedInputFile
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import db
import pandas as pd
from io import BytesIO

bot = None
send_email = None

# ================================================================================================================
#  FSM для «Добавить специализацию»
# ================================================================================================================
class AddSpecState(StatesGroup):
    waiting_name = State()

async def cmd_add_spec_start(message: types.Message, state: FSMContext):
    """Запуск FSM по кнопке 'Добавить специализацию'"""
    await state.set_state(AddSpecState.waiting_name)
    await message.answer("✏️ Введите название новой специализации:")

async def process_add_spec(message: types.Message, state: FSMContext):
    """Обработка ввода названия специализации"""
    name = message.text.strip()
    if not name:
        return await message.answer("Название не может быть пустым, введите ещё раз:")
    await db.add_specialization(name)
    await message.answer(f"✅ Специализация «{name}» добавлена.")
    await state.clear()

# ================================================================================================================
#  Broadcast FSM
# ================================================================================================================
class BroadcastState(StatesGroup):
    waiting_comment = State()

async def cmd_broadcast_journalists_start(message: types.Message, state: FSMContext):
    """Начало FSM для рассылки журналистам по кнопке"""
    await state.update_data(broadcast_type='journalist')
    await message.answer("✉️ Напишите, что вы хотите разослать журналистам:")
    await state.set_state(BroadcastState.waiting_comment)

async def cmd_broadcast_speakers_start(message: types.Message, state: FSMContext):
    """Начало FSM для рассылки спикерам по кнопке"""
    await state.update_data(broadcast_type='speaker')
    await message.answer("✉️ Напишите, что вы хотите разослать спикерам:")
    await state.set_state(BroadcastState.waiting_comment)

async def cmd_broadcast_all_start(message: types.Message, state: FSMContext):
    """Начало FSM для рассылки всем по кнопке"""
    await state.update_data(broadcast_type='all')
    await message.answer("✉️ Напишите, что вы хотите разослать всем пользователям:")
    await state.set_state(BroadcastState.waiting_comment)

async def process_broadcast(message: types.Message, state: FSMContext):
    """Обрабатывает следующий текст и запускает рассылку"""
    data = await state.get_data()
    text = message.text
    btype = data.get('broadcast_type')

    if btype == 'journalist':
        ids = await db.get_all_user_ids_by_role('journalist')
    elif btype == 'speaker':
        ids = await db.get_all_user_ids_by_role('speaker')
    else:
        # все вместе, без дубликатов
        ids = (await db.get_all_user_ids_by_role('journalist')) + \
              (await db.get_all_user_ids_by_role('speaker'))

    for tg in set(ids):
        await bot.send_message(tg, text)
    await message.answer("✅ Рассылка выполнена.")
    await state.clear()

# ================================================================================================================
#  Специализации
# ================================================================================================================

async def cmd_add_spec(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Использование: /add_spec <название>")
    await db.add_specialization(parts[1].strip())
    await message.answer(f"Специализация '{parts[1].strip()}' добавлена.")

async def cmd_broadcast_journalists(message: types.Message):
    """Старая версия: /broadcast_journalists текст"""
    text = message.text.partition(' ')[2]
    if not text:
        return await message.answer("Использование: /broadcast_journalists <текст>")
    for tg in await db.get_all_user_ids_by_role('journalist'):
        await bot.send_message(tg, text)
    await message.answer("✅ Разослано журналистам.")

async def cmd_broadcast_speakers(message: types.Message):
    text = message.text.partition(' ')[2]
    if not text:
        return await message.answer("Использование: /broadcast_speakers <текст>")
    for tg in await db.get_all_user_ids_by_role('speaker'):
        await bot.send_message(tg, text)
    await message.answer("✅ Разослано спикерам.")

async def cmd_broadcast_all(message: types.Message):
    text = message.text.partition(' ')[2]
    if not text:
        return await message.answer("Использование: /broadcast_all <текст>")
    all_ids = set(
        await db.get_all_user_ids_by_role('journalist') +
        await db.get_all_user_ids_by_role('speaker')
    )
    for tg in all_ids:
        await bot.send_message(tg, text)
    await message.answer("✅ Разослано всем.")

async def cmd_export(message: types.Message):
    # экспорт в настоящий xlsx
    users = await db.get_all_users()
    requests = await db.get_all_requests()

    df_u = pd.DataFrame(users, columns=['id','username','email','role'])
    buf1 = BytesIO()
    df_u.to_excel(buf1, index=False, engine='openpyxl'); buf1.seek(0)
    file1 = BufferedInputFile(buf1.getvalue(), filename='users.xlsx')

    df_r = pd.DataFrame(
        requests,
        columns=['id','journalist','spec','topic','deadline','format','content','status','chosen_speaker']
    )
    buf2 = BytesIO()
    df_r.to_excel(buf2, index=False, engine='openpyxl'); buf2.seek(0)
    file2 = BufferedInputFile(buf2.getvalue(), filename='requests.xlsx')

    await bot.send_document(message.chat.id, file1)
    await bot.send_document(message.chat.id, file2)
    await message.answer("📊 Экспорт готов!")

async def cmd_status_all(message: types.Message):
    text = "Все запросы:\n"
    for r in await db.get_all_requests():
        text += f"ID {r[0]}: {r[3]} — {r[7]}\n"
    await message.answer(text)

# ================================================================================================================
#  Регистрация
# ================================================================================================================

def register_handlers_admin(dp: Dispatcher, bot_obj, email_func):
    global bot, send_email
    bot = bot_obj
    send_email = email_func

    # — slash-commands —
    dp.message.register(cmd_add_spec,               Command('add_spec'), StateFilter(None))
    dp.message.register(cmd_broadcast_journalists,  Command('broadcast_journalists'), StateFilter(None))
    dp.message.register(cmd_broadcast_speakers,     Command('broadcast_speakers'), StateFilter(None))
    dp.message.register(cmd_broadcast_all,          Command('broadcast_all'), StateFilter(None))
    dp.message.register(cmd_export,                 Command('export'), StateFilter(None))
    dp.message.register(cmd_status_all,             Command('status_all'), StateFilter(None))

    # — кнопки обычной клавиатуры —
    dp.message.register(cmd_add_spec_start,              lambda c: c.text == 'Добавить специализацию', StateFilter(None))
    dp.message.register(cmd_broadcast_journalists_start, lambda c: c.text == 'Рассылка журналистам', StateFilter(None))
    dp.message.register(cmd_broadcast_speakers_start,    lambda c: c.text == 'Рассылка спикерам',   StateFilter(None))
    dp.message.register(cmd_broadcast_all_start,         lambda c: c.text == 'Рассылка всем',       StateFilter(None))
    dp.message.register(cmd_export,                      lambda c: c.text == 'Показать BD',         StateFilter(None))
    dp.message.register(cmd_status_all,                  lambda c: c.text == 'Статусы всех запросов', StateFilter(None))

    # — FSM для ввода текста —
    dp.message.register(process_add_spec,  StateFilter(AddSpecState.waiting_name))
    dp.message.register(process_broadcast, StateFilter(BroadcastState.waiting_comment))
