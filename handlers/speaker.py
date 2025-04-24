# handlers/speaker.py
from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
import db

bot = None

class RevisionState(StatesGroup):
    waiting_comment = State()

async def cmd_ask(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /ask <ID запроса> <текст вопроса>")
        return
    _, req_id_str, question = parts
    try:
        req_id = int(req_id_str)
    except ValueError:
        await message.answer("Неверный ID запроса.")
        return
    inv = await db.get_invite(req_id, (await db.get_user_by_tg_id(message.from_user.id))[0])
    if not inv or inv[3] != 'accepted':
        await message.answer("Вы не участвуете или не приняли запрос.")
        return
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    await bot.send_message(journ[1], f"Вопрос по запросу {req_id}: {question}")
    await message.answer("Вопрос отправлен журналисту.")

async def cmd_answer(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /answer <ID запроса> <текст ответа>")
        return
    _, req_id_str, answer = parts
    try:
        req_id = int(req_id_str)
    except ValueError:
        await message.answer("Неверный ID запроса.")
        return
    user = await db.get_user_by_tg_id(message.from_user.id)
    await db.record_answer(req_id, user[0], answer)
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять ответ", callback_data=f"ans_{req_id}_{user[0]}")
    builder.button(text="✏️ Запросить правки", callback_data=f"rev_{req_id}_{user[0]}")
    keyboard = builder.as_markup()
    await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
    await message.answer("Ответ отправлен журналисту.")

async def handle_request_revision(callback: types.CallbackQuery, state: FSMContext):
    _, req_id, sp_id = callback.data.split('_')
    await state.update_data(req_id=int(req_id), sp_id=int(sp_id))
    await state.set_state(RevisionState.waiting_comment)
    await callback.message.answer("Введите комментарий для доработки ответа:")
    await callback.answer()

async def process_revision(message: types.Message, state: FSMContext):
    data = await state.get_data()
    req_id = data['req_id']
    sp_id = data['sp_id']
    comment = message.text.strip()
    await db.mark_revision_requested(req_id, sp_id)
    sp = await db.get_user_by_id(sp_id)
    await bot.send_message(sp[1], f"Журналист просит доработать ответ по запросу {req_id}: {comment}")
    await message.answer("Комментарий отправлен спикеру.")
    await state.clear()

async def cmd_status(message: types.Message):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Вы не зарегистрированы.")
        return
    invs = await db.get_requests_for_speaker(user[0])
    text = "Статусы ваших запросов (спикер):\n"
    for inv in invs:
        text += f"ID {inv[0]} - статус приглашения: {inv[4]}\n"
    await message.answer(text)

def register_handlers_speaker(dp: Dispatcher, bot_obj):
    global bot
    bot = bot_obj
    dp.message.register(cmd_ask, Command('ask'), StateFilter(None))
    dp.message.register(cmd_answer, Command('answer'), StateFilter(None))
    dp.callback_query.register(handle_request_revision, lambda c: c.data.startswith('rev_'), StateFilter(None))
    dp.message.register(process_revision, StateFilter(RevisionState.waiting_comment))
    dp.message.register(cmd_status, Command('status'), StateFilter(None))

