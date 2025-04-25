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

class AskForm(StatesGroup):
    waiting_request_id = State()
    waiting_question = State()

class AnswerForm(StatesGroup):
    waiting_request_id = State()
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

async def handle_accept(callback: types.CallbackQuery):
    # 1) Извлекаем из callback.data ID запроса и спикера
    _, req_id_str, _, sp_id_str = callback.data.split('_')
    req_id = int(req_id_str)
    speaker_id = int(sp_id_str)

    # 2) Обновляем базу: помечаем приглашение как 'accepted',
    #    переводим запрос в in_progress и сохраняем выбранного спикера
    await db.update_invite_status(req_id, speaker_id, 'accepted')
    await db.mark_request_in_progress(req_id)
    await db.set_chosen_speaker(req_id, speaker_id)

    # 3) Уведомляем самого спикера, что он принял запрос (и показываем ID)
    await callback.message.answer(
        f"Вы приняли запрос (ID {req_id})."
    )

    # 4) Убираем inline-кнопки из оригинального сообщения
    await callback.message.edit_reply_markup(reply_markup=None)

    # 5) «Отменяем» все остальные открытые приглашения и уведомляем других спикеров
    invites = await db.get_invites_for_request(req_id)
    for other_id, status, *_ in invites:
        if status == 'pending':
            # помечаем как cancelled
            await db.update_invite_status(req_id, other_id, 'cancelled')
            other_user = await db.get_user_by_id(other_id)
            await bot.send_message(
                other_user[1],
                "Извините, этот запрос уже занял другой спикер."
            )

    # 6) Уведомляем журналиста, что запрос принят
    req = await db.get_request_by_id(req_id)
    journalist = await db.get_user_by_id(req[1])
    # можно использовать свою клавиатуру для журналиста, здесь — та же простая
    # kb = ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("/new_request"), KeyboardButton("/status"))
    # builder = InlineKeyboardBuilder()
    # builder.button(text="✅ Принять ответ", callback_data="/new_reques")
    # builder.button(text="✏️ Запросить правки", callback_data="/status")
    # kb = builder.as_markup()

    await bot.send_message(
        journalist[1],
        f"Спикер @{(await db.get_user_by_id(speaker_id))[2]} принял ваш запрос (ID {req_id})."
    )

    # 7) Завершаем callback, чтобы у кнопки пропало «часика» ожидания
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


async def cmd_answer_start(message: types.Message, state: FSMContext):
    # Проверяем, что спикер
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[4] != 'speaker':
        return await message.answer("Только спикерам.")
    await state.set_state(AnswerForm.waiting_request_id)
    await message.answer("Введите ID запроса, на который вы хотите ответить:", reply_markup=None)


async def process_answer_id(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("Неверный формат ID. Введите число.")

    me = await db.get_user_by_tg_id(message.from_user.id)
    req = await db.get_request_by_id(int(text))
    if not req or req[8] != me[0]:
        await message.answer("Это не ваш запрос.")
        return await state.clear()

    await state.update_data(request_id=int(text))
    await state.set_state(AnswerForm.waiting_question)
    await message.answer("Теперь введите текст ответа и/или прикрепите файл:")


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
    if message.document:
        caption = f"✉️ Ответ по запросу {req_id}:\n"
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
            f"✉️ Ответ по запросу {req_id}:\n{text}",
            reply_markup=keyboard
        )
    await message.answer("Ответ отправлен журналисту.")
    await state.clear()


# ================================================================================================================
#                                           ASK
# ================================================================================================================


async def cmd_ask_start(message: types.Message, state: FSMContext):
    # Проверяем, что спикер
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[4] != 'speaker':
        return await message.answer("Только спикерам.")
    await state.set_state(AskForm.waiting_request_id)
    await message.answer("Введите ID запроса, на который хотите задать вопрос:", reply_markup=None)

async def process_ask_id(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("Неверный формат ID. Введите число.")

    me = await db.get_user_by_tg_id(message.from_user.id)
    req = await db.get_request_by_id(int(text))
    if not req or req[8] != me[0]:
        await message.answer("Это не ваш запрос.")
        return await state.clear()

    await state.update_data(request_id=int(text))
    await state.set_state(AskForm.waiting_question)
    await message.answer("Теперь введите текст вашего вопроса и/или прикрепите файл:")

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
    if message.document:
        caption = f"❓ Вопрос по запросу {req_id}:\n"
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
            f"❓ Вопрос по запросу {req_id}:\n{text}"
        )
    await message.answer("Вопрос отправлен журналисту.")
    await state.clear()

# async def cmd_status(message: types.Message):
#     user = await db.get_user_by_tg_id(message.from_user.id)
#     if not user:
#         return await message.answer("Не зарегистрированы.")
#     text = "Ваши запросы:\n"
#     for r in await db.get_requests_for_speaker(user[0]):
#         text += f"ID {r[0]}: {r[1]} — {r[3]}\n"
#     await message.answer(text)


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
    dp.message.register(process_ask_id, StateFilter(AskForm.waiting_request_id))
    dp.message.register(process_ask_text, StateFilter(AskForm.waiting_question))
    dp.message.register(cmd_answer_start, lambda c: c.text == 'Ответить на запрос', StateFilter(None))
    dp.message.register(process_answer_id, StateFilter(AnswerForm.waiting_request_id))
    dp.message.register(process_answer_text, StateFilter(AnswerForm.waiting_question))
    # dp.message.register(cmd_status, Text("Статус запросов"), StateFilter(None))

