# handlers/speaker.py
from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import db

from handlers.registration import get_role_kb

class AskForm(StatesGroup):
    selecting_request = State()
    waiting_question = State()

class AnswerForm(StatesGroup):
    selecting_request = State()
    waiting_question = State()

# def get_role_kb() -> ReplyKeyboardMarkup:
#     builder = ReplyKeyboardBuilder()
#     # добавляем все кнопки в один список
#     builder.button(text="/answer")
#     builder.button(text="/ask")
#     builder.button(text="/status")
#     # раскладываем по 2 кнопки в ряд
#     builder.adjust(2)
#     # собираем разметку
#     return builder.as_markup(resize_keyboard=True)

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

# async def cmd_answer(message: types.Message):
#     parts = message.text.split(maxsplit=2)
#     if len(parts) < 3:
#         await message.answer("Использование: /answer <ID запроса> <текст ответа>")
#         return
#     _, req_id_str, answer = parts
#     try:
#         req_id = int(req_id_str)
#     except ValueError:
#         await message.answer("Неверный ID запроса.")
#         return
#     user = await db.get_user_by_tg_id(message.from_user.id)
#     await db.record_answer(req_id, user[0], answer)
#     req = await db.get_request_by_id(req_id)
#     journ = await db.get_user_by_id(req[1])
#     builder = InlineKeyboardBuilder()
#     builder.button(text="✅ Принять ответ", callback_data=f"ans_{req_id}_{user[0]}")
#     builder.button(text="✏️ Запросить правки", callback_data=f"rev_{req_id}_{user[0]}")
#     keyboard = builder.as_markup()
#     await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
#     await message.answer("Ответ отправлен журналисту.")

async def handle_request_revision(callback: types.CallbackQuery, state: FSMContext):
    _, req_id, sp_id = callback.data.split('_')
    await state.update_data(req_id=int(req_id), sp_id=int(sp_id))
    await state.set_state(RevisionState.waiting_comment)
    await callback.message.answer("Введите комментарий для доработки ответа:")
    await callback.answer()

async def handle_accept(callback: types.CallbackQuery):
    _, req_id_str, _, sp_id_str = callback.data.split('_')
    req_id = int(req_id_str)
    speaker_id = int(sp_id_str)

    # обновляем базу
    await db.update_invite_status(req_id, speaker_id, 'accepted')
    await db.mark_request_in_progress(req_id)
    await db.set_chosen_speaker(req_id, speaker_id)

    # подтверждение спикеру
    await callback.message.answer(f"Вы приняли запрос (ID {req_id}).")
    await callback.message.edit_reply_markup(None)

    # отменяем у остальных
    invites = await db.get_invites_for_request(req_id)
    for other_id, status, *_ in invites:
        if status == 'pending':
            await db.update_invite_status(req_id, other_id, 'cancelled')
            other_user = await db.get_user_by_id(other_id)
            await bot.send_message(other_user[1], "Извините, этот запрос уже занял другой спикер.")

    # уведомляем журналиста
    req = await db.get_request_by_id(req_id)
    journalist = await db.get_user_by_id(req[1])
    sp = await db.get_user_by_id(speaker_id)
    display = sp[3]  # display_name
    await bot.send_message(
        journalist[1],
        f"Спикер {display} принял ваш запрос (ID {req_id})."
    )

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

# ================================================================================================================
#                                           ANSWER
# ================================================================================================================


async def cmd_answer(message: types.Message):
    """Спикер отправляет ответ журналисту: /answer <request_id> <текст>"""
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
    # Отправляем журналисту сообщение с кнопками
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять ответ", callback_data=f"ans_{req_id}_{user[0]}")
    builder.button(text="✏️ Запросить правки", callback_data=f"rev_{req_id}_{user[0]}")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
    await message.answer("Ответ отправлен журналисту.")


# async def cmd_answer_start(message: types.Message, state: FSMContext):
#     # Проверяем, что спикер
#     user = await db.get_user_by_tg_id(message.from_user.id)
#     if not user or user[5] != 'speaker':
#         return await message.answer("Только спикерам.")
#     await state.set_state(AnswerForm.selecting_request)
#     await message.answer("Введите ID запроса, на который вы хотите ответить:", reply_markup=None)


async def cmd_answer_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[5] != 'speaker':
        return await message.answer("Только спикерам.")
    invs = await db.get_requests_for_speaker(user[0])
    if not invs:
        return await message.answer("Нет активных запросов.")
    builder = InlineKeyboardBuilder()
    for req_id, title, *_ in invs:
        builder.button(text=title, callback_data=f"answer_req_{req_id}")
    builder.adjust(2)
    await message.answer("Выберите запрос, на который хотите ответить:", reply_markup=builder.as_markup())
    await state.set_state(AnswerForm.selecting_request)


async def on_answer_request_selected(callback: types.CallbackQuery, state: FSMContext):
    _, _, req_id_str = callback.data.split('_')
    req_id = int(req_id_str)
    await state.update_data(request_id=req_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Введите текст ответа и/или прикрепите файл:")
    await state.set_state(AnswerForm.waiting_question)
    await callback.answer()


# async def process_answer_id(message: types.Message, state: FSMContext):
#     text = message.text.strip()
#     if not text.isdigit():
#         return await message.answer("Неверный формат ID. Введите число.")
#
#     me = await db.get_user_by_tg_id(message.from_user.id)
#     req = await db.get_request_by_id(int(text))
#     if not req or req[8] != me[0]:
#         await message.answer("Это не ваш запрос.")
#         return await state.clear()
#
#     await state.update_data(request_id=int(text))
#     await state.set_state(AnswerForm.waiting_question)
#     await message.answer("Теперь введите текст ответа и/или прикрепите файл:")


async def process_answer_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    req_id = data['request_id']
    # answer = message.text.strip()
    user = await db.get_user_by_tg_id(message.from_user.id)
    if message.text:
        await db.record_answer(req_id, user[0], message.text)
    # Отправляем журналисту сообщение с кнопками
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять ответ", callback_data=f"ans_{req_id}_{user[0]}")
    builder.button(text="✏️ Запросить правки", callback_data=f"rev_{req_id}_{user[0]}")
    keyboard = builder.as_markup(resize_keyboard=True)
    # await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
    title = await db.get_request_title(req_id)
    if message.document:
        caption = f"✉️ Ответ по запросу «{title}»:\n"
        await db.record_answer(req_id, user[0], message.caption)
        if message.caption:
            caption += message.caption
        await bot.send_document(
            journ[1],
            document=message.document.file_id,
            caption=caption,
            reply_markup=keyboard
        )
    else:
        # send plain text answer
        text = message.text or ""
        await bot.send_message(
            journ[1],
            f"✉️ Ответ по запросу «{title}»:\n{text}",
            reply_markup=keyboard
        )
    await message.answer("Ответ отправлен журналисту.")
    await state.clear()


# ================================================================================================================
#                                           ASK
# ================================================================================================================


# async def cmd_ask_start(message: types.Message, state: FSMContext):
#     # Проверяем, что спикер
#     user = await db.get_user_by_tg_id(message.from_user.id)
#     if not user or user[5] != 'speaker':
#         return await message.answer("Только спикерам.")
#     await state.set_state(AskForm.selecting_request)
#     await message.answer("Введите ID запроса, на который хотите задать вопрос:", reply_markup=None)

async def cmd_ask_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[5] != 'speaker':
        return await message.answer("Только спикерам.")
    # Получаем список “в работе” запросов
    invs = await db.get_requests_for_speaker(user[0])
    if not invs:
        return await message.answer("У вас нет активных запросов.")
    # Строим клавиатуру
    builder = InlineKeyboardBuilder()
    for req_id, title, *_ in invs:
        builder.button(text=title, callback_data=f"ask_req_{req_id}")
    builder.adjust(2)
    await message.answer("Выберите запрос, по которому хотите задать вопрос:", reply_markup=builder.as_markup())
    await state.set_state(AskForm.selecting_request)

async def on_ask_request_selected(callback: types.CallbackQuery, state: FSMContext):
    _, _, req_id_str = callback.data.split('_')
    req_id = int(req_id_str)
    # Сохраняем в FSM
    await state.update_data(request_id=req_id)
    # Убираем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    # Запрашиваем текст вопроса
    await callback.message.answer("Теперь введите текст вашего вопроса и/или прикрепите файл:", reply_markup=get_role_kb("speaker"))
    await state.set_state(AskForm.waiting_question)
    await callback.answer()

# async def process_ask_id(message: types.Message, state: FSMContext):
#     text = message.text.strip()
#     if not text.isdigit():
#         return await message.answer("Неверный формат ID. Введите число.")
#
#     me = await db.get_user_by_tg_id(message.from_user.id)
#     req = await db.get_request_by_id(int(text))
#     if not req or req[8] != me[0]:
#         await message.answer("Это не ваш запрос.")
#         return await state.clear()
#
#     await state.update_data(request_id=int(text))
#     await state.set_state(AskForm.waiting_question)
#     await message.answer("Теперь введите текст вашего вопроса и/или прикрепите файл:")

async def process_ask_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    req_id = data['request_id']
    # question = message.text.strip()
    # достаём журналиста и шлём ему
    req = await db.get_request_by_id(req_id)
    if not req:
        await message.answer("Запрос с таким ID не найден.")
        return await state.clear()
    journ = await db.get_user_by_id(req[1])
    # await bot.send_message(journ[1], f"❓ Вопрос по запросу {req_id}:\n{question}")
    title = await db.get_request_title(req_id)
    if message.document:
        caption = f"❓ Вопрос по запросу «{title}»:\n"
        if message.caption:
            caption += message.caption
        await bot.send_document(
            journ[1],
            document=message.document.file_id,
            caption=caption
        )
    else:
        # plain text question
        text = message.text or ""
        await bot.send_message(
            journ[1],
            f"❓ Вопрос по запросу «{title}»:\n{text}"
        )
    await message.answer("Вопрос отправлен журналисту.")
    await state.clear()


# ================================================================================================================
#                                           HANDLERS
# ================================================================================================================


def register_handlers_speaker(dp: Dispatcher, bot_obj):
    global bot
    bot = bot_obj
    dp.message.register(cmd_ask, Command('ask'), StateFilter(None))
    dp.message.register(cmd_answer, Command('answer'), StateFilter(None))
    dp.callback_query.register(handle_request_revision, lambda c: c.data.startswith('rev_'), StateFilter(None))
    dp.callback_query.register(handle_accept, lambda c: c.data.startswith('req_') and '_accept_' in c.data)
    dp.message.register(process_revision, StateFilter(RevisionState.waiting_comment))
    dp.message.register(cmd_ask_start, lambda c: c.text == 'Задать вопрос по запросу', StateFilter(None))
    dp.callback_query.register(on_ask_request_selected, lambda c: c.data.startswith('ask_req_'), StateFilter(AskForm.selecting_request))
    # dp.message.register(process_ask_id, StateFilter(AskForm.selecting_request))
    dp.message.register(process_ask_text, StateFilter(AskForm.waiting_question))
    dp.message.register(cmd_answer_start, lambda c: c.text == 'Ответить на запрос', StateFilter(None))
    # dp.message.register(process_answer_id, StateFilter(AnswerForm.selecting_request))
    dp.message.register(process_answer_text, StateFilter(AnswerForm.waiting_question))
    dp.callback_query.register(on_answer_request_selected, lambda c: c.data.startswith("answer_req_"), StateFilter(AnswerForm.selecting_request))
    # dp.message.register(cmd_status, Text("Статус запросов"), StateFilter(None))

