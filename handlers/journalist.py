from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import db

class ReplyForm(StatesGroup):
    waiting_request_id = State()
    waiting_question = State()

class NewRequestForm(StatesGroup):
    waiting_request_id = State()
    waiting_question = State()

# def get_role_kb() -> ReplyKeyboardMarkup:
#     builder = ReplyKeyboardBuilder()
#     # добавляем все кнопки в один список
#     builder.button(text="/new_request")
#     builder.button(text="/reply")
#     builder.button(text="/ask")
#     builder.button(text="/status")
#     # раскладываем по 2 кнопки в ряд
#     builder.adjust(2)
#     # собираем разметку
#     return builder.as_markup(resize_keyboard=True)

bot = None
send_email = None

class RequestForm(StatesGroup):
    choosing_spec = State()
    choosing_speakers = State()
    entering_title = State()
    entering_deadline = State()
    entering_format = State()
    entering_content = State()

class RevisionState(StatesGroup):
    waiting_comment = State()


# ================================================================================================================
#                                           NEW_REQUEST
# ================================================================================================================


async def cmd_new_request(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[4] != 'journalist':
        return await message.answer("Только журналистам.")
    specs = await db.list_specializations()
    if not specs:
        return await message.answer("Нет специализаций.")

    await state.set_state(RequestForm.choosing_spec)
    b = InlineKeyboardBuilder()
    for sid, name in specs:
        b.button(text=name, callback_data=f"pick_spec_{sid}")
    b.adjust(2)
    await message.answer("Выберите специализацию:", reply_markup=b.as_markup())


async def spec_chosen(callback: types.CallbackQuery, state: FSMContext):
    _, _, spec_id = callback.data.split('_')
    spec_id = int(spec_id)
    await state.update_data(spec_id=spec_id)

    # 1) fetch both specialized and unspecialized speakers
    spec_speakers   = await db.get_speakers_by_specialization(spec_id)
    unspec_speakers = await db.get_speakers_without_specialization()
    # merge, avoiding duplicates
    all_speakers = {s[0]: s for s in spec_speakers}
    for s in unspec_speakers:
        all_speakers.setdefault(s[0], s)
    sp_map = {str(uid): (tg, name or email)
              for uid, tg, name, email in all_speakers.values()}

    # 2) store for later
    await state.update_data(potential_speakers=sp_map, selected_speakers=[])

    # 3) build the keyboard
    kb = InlineKeyboardBuilder()
    kb.button(text="☐ Выбрать всех", callback_data="toggle_spk_all")
    for uid, (tg, nm) in sp_map.items():
        kb.button(text=f"☐ {nm}", callback_data=f"toggle_spk_{uid}")
    kb.button(text="✅ Готово", callback_data="done_select")
    kb.adjust(2)

    await callback.message.edit_text("Выберите спикеров для запроса:", reply_markup=kb.as_markup())
    await state.set_state(RequestForm.choosing_speakers)
    await callback.answer()


async def toggle_speaker(callback: types.CallbackQuery, state: FSMContext):
    _, _, uid = callback.data.split('_')
    data = await state.get_data()
    selected = set(data['selected_speakers'])
    sp_map   = data['potential_speakers']

    if uid == "all":
        # flip‐flop select all vs none
        if "all" in selected:
            selected.clear()
        else:
            selected = set(sp_map.keys()) | {"all"}
    else:
        if uid in selected:
            selected.remove(uid)
            selected.discard("all")
        else:
            selected.add(uid)
            # if every single speaker is now selected, mark "all" too
            if set(sp_map.keys()) <= selected:
                selected |= set(sp_map.keys()) | {"all"}

    await state.update_data(selected_speakers=list(selected))

    # rebuild KB to show checks
    kb = InlineKeyboardBuilder()
    kb.button(
      text=("☑️" if "all" in selected else "☐") + " Выбрать всех",
      callback_data="toggle_spk_all"
    )
    for sid, (tg, nm) in sp_map.items():
        mark = "✅" if sid in selected else "☐"
        kb.button(text=f"{mark} {nm}", callback_data=f"toggle_spk_{sid}")
    kb.button(text="✅ Готово", callback_data="done_select")
    kb.adjust(2)

    await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    await callback.answer()


async def done_selecting(callback: types.CallbackQuery, state: FSMContext):
    data     = await state.get_data()
    selected = data['selected_speakers']
    sp_map   = data['potential_speakers']

    if not selected:
        return await callback.answer("Выберите хотя бы одного спикера.", show_alert=True)

    # if they hit “all”, pick every real speaker
    if "all" in selected:
        chosen = [int(uid) for uid in sp_map.keys()]
    else:
        chosen = [int(uid) for uid in selected]

    await state.update_data(chosen_speaker_ids=chosen)
    await callback.message.edit_text("Спикеры выбраны.")
    await callback.message.answer("Введите тему запроса:")
    await state.set_state(RequestForm.entering_title)
    await callback.answer()


async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Укажите дедлайн (например, 2025-05-10):")
    await state.set_state(RequestForm.entering_deadline)


async def process_deadline(message: types.Message, state: FSMContext):
    await state.update_data(deadline=message.text.strip())
    await message.answer("Укажите формат запроса (комментарий, интервью и т.д.):")
    await state.set_state(RequestForm.entering_format)


async def process_format(message: types.Message, state: FSMContext):
    await state.update_data(format=message.text.strip())
    await message.answer("Опишите детали запроса:")
    await state.set_state(RequestForm.entering_content)


async def process_content(message: types.Message, state: FSMContext):
    content = message.text.strip()
    if not content:
        await message.answer("Текст запроса не может быть пустым.")
        return
    data = await state.get_data()
    spec_id = data['spec_id']
    title = data['title']
    deadline = data['deadline']
    fmt = data['format']
    speakers = data['chosen_speaker_ids']
    journalist = await db.get_user_by_tg_id(message.from_user.id)
    req_id = await db.create_request(journalist[0], spec_id, title, deadline, fmt, content, speakers)
    # Рассылаем спикерам
    spec = await db.get_specialization_by_id(spec_id)
    spec_name = spec[1]
    for sp_id in speakers:
        user = await db.get_user_by_id(sp_id)
        text = (
            f"🆕 Новый запрос ({spec_name})\n"
            f"Тема: {title}\n"
            f"Дедлайн: {deadline}\n"
            f"Формат: {fmt}\n"
            f"{content}\n\n"
            f"Принять /decline запрос"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Принять", callback_data=f"req_{req_id}_accept_{sp_id}")
        builder.button(text="❌ Отклонить", callback_data=f"req_{req_id}_decline_{sp_id}")
        keyboard = builder.as_markup()
        await bot.send_message(user[1], text, reply_markup=keyboard)
    await message.answer(f"Запрос отправлен (ID запроса {req_id}). ")
    await state.clear()


# ================================================================================================================
#                                           MARK COMPLETED
# ================================================================================================================



# async def handle_accept(callback: types.CallbackQuery):
#     _, req_id_str, _, sp_id_str = callback.data.split('_')
#     req_id, sp_id = int(req_id_str), int(sp_id_str)
#
#     # 1) обновляем статус этого приглашения
#     await db.update_invite_status(req_id, sp_id, 'accepted')
#     await db.mark_request_in_progress(req_id)
#     await db.set_chosen_speaker(req_id, sp_id)
#
#     # 2) удаляем клавиатуру у самого callback-сообщения
#     await callback.message.edit_reply_markup(reply_markup=None)
#
#     # 3) уведомляем других спикеров (pending -> cancelled)
#     invites = await db.get_invites_for_request(req_id)
#     for other_sp_id, status, *_ in invites:
#         if status == 'pending':
#             # помечаем у них cancelled
#             await db.update_invite_status(req_id, other_sp_id, 'cancelled')
#             usr = await db.get_user_by_id(other_sp_id)
#             await bot.send_message(
#                 usr[1],
#                 "К вашему запросу уже найден спикер, это приглашение закрыто."
#             )
#
#     # 4) уведомляем журналиста
#     req = await db.get_request_by_id(req_id)
#     journ = await db.get_user_by_id(req[1])
#     # создаём однокнопочную панель для ЖУРНАЛИСТА
#     kb = InlineKeyboardBuilder()
#     kb.button(text="Остановить запрос", callback_data=f"stop_{req_id}")
#     await bot.send_message(
#         journ[1],
#         f"Спикер принял ваш запрос (ID {req_id}).",
#         reply_markup=kb.as_markup()
#     )
#
#     await callback.answer("Вы приняли запрос.")

async def handle_decline(callback: types.CallbackQuery):
    _, req_id, _, sp_id = callback.data.split('_')
    req_id, sp_id = int(req_id), int(sp_id)

    # 1) Обновляем статус приглашения
    await db.update_invite_status(req_id, sp_id, 'declined')

    # 2) Удаляем сообщение с приглашением
    await callback.message.delete()

    # 3) Даем фидбэк спикеру
    await callback.answer("Вы отклонили запрос.")


async def handle_stop(callback: types.CallbackQuery):
    _, req_id = callback.data.split('_')
    req_id = int(req_id)
    invites = await db.get_invites_for_request(req_id)
    for sp_id, status, *_ in invites:
        if status == 'pending':
            await db.update_invite_status(req_id, sp_id, 'cancelled')
            user = await db.get_user_by_id(sp_id)
            await bot.send_message(user[1], "Спикеры по запросу уже найдены.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Запрос остановлен.")


# async def cmd_ask(message: types.Message):
#     """Спикер задает уточняющий вопрос журналисту: /ask <request_id> <текст>"""
#     parts = message.text.split(maxsplit=2)
#     if len(parts) < 3:
#         await message.answer("Использование: /ask <ID запроса> <текст вопроса>")
#         return
#     _, req_id_str, question = parts
#     try:
#         req_id = int(req_id_str)
#     except ValueError:
#         await message.answer("Неверный ID запроса.")
#         return
#     inv = await db.get_invite(req_id, (await db.get_user_by_tg_id(message.from_user.id))[0])
#     if not inv or inv[3] != 'accepted':
#         await message.answer("Вы не участвуете в этом запросе или не приняли его.")
#         return
#     req = await db.get_request_by_id(req_id)
#     journ = await db.get_user_by_id(req[1])
#     await bot.send_message(journ[1], f"Вопрос по запросу {req_id}: {question}")
#     await message.answer("Вопрос отправлен журналисту.")


# async def cmd_answer(message: types.Message):
#     """Спикер отправляет ответ журналисту: /answer <request_id> <текст>"""
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
#     # Отправляем журналисту сообщение с кнопками
#     req = await db.get_request_by_id(req_id)
#     journ = await db.get_user_by_id(req[1])
#     keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
#     builder = InlineKeyboardBuilder()
#     builder.button(text="✅ Принять ответ", callback_data=f"ans_{req_id}_{user[0]}")
#     builder.button(text="✏️ Запросить правки", callback_data=f"rev_{req_id}_{user[0]}")
#     keyboard = builder.as_markup()
#     await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
#     await message.answer("Ответ отправлен журналисту.")


async def handle_accept_answer(callback: types.CallbackQuery):
    _, req_id, sp_id = callback.data.split('_')
    req_id, sp_id = int(req_id), int(sp_id)
    await db.accept_answer(req_id, sp_id)
    # Уведомляем спикера
    sp = await db.get_user_by_id(sp_id)
    await bot.send_message(sp[1], "Ваш ответ принят. Ожидайте публикации.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Ответ принят.")


async def handle_request_revision(callback: types.CallbackQuery, state: FSMContext):
    _, req_id, sp_id = callback.data.split('_')
    await state.update_data(req_id=int(req_id), sp_id=int(sp_id))
    await state.set_state(RevisionState.waiting_comment)
    await callback.message.answer("Введите комментарий с доработками:")
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
#                                           REPLY
# ================================================================================================================


async def cmd_reply_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[4] != 'journalist':
        return await message.answer("Только журналисты.")
    await state.set_state(ReplyForm.waiting_request_id)
    await message.answer("Введите ID запроса, на который хотите ответить:", reply_markup=None)


async def process_reply_id(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("Неверный формат ID. Введите число.")

    me = await db.get_user_by_tg_id(message.from_user.id)
    req = await db.get_request_by_id(int(text))
    if not req or req[1] != me[0]:
        await message.answer("Это не ваш запрос.")
        return await state.clear()

    await state.update_data(request_id=int(text))
    await state.set_state(ReplyForm.waiting_question)
    await message.answer("Теперь введите текст вашего сообщения или прикрепите файл:")

async def process_reply_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    req_id = data['request_id']
    # answer = message.text.strip()
    req = await db.get_request_by_id(req_id)

    sp_id = req[8]
    if not sp_id:
        await message.answer("Спикер ещё не выбран.")
        return await state.clear()
    sp = await db.get_user_by_id(sp_id)

    if message.document:
        caption = f"✉️ Ответ журналиста на запрос {req_id}:\n"
        if message.caption:
            caption += message.caption
        await bot.send_document(
            sp[1],
            document=message.document.file_id,
            caption=caption
        )
    else:
        # send plain text answer
        text = message.text or ""
        await bot.send_message(
            sp[1],
            f"✉️ Ответ журналиста на запрос {req_id}:\n{text}"
        )
    # await bot.send_message(sp[1], f"Ответ журналиста на запрос {req_id}:\n{answer}")
    await message.answer("Отправлено спикеру.")
    await state.clear()


async def cmd_reply(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("Использование: /reply <ID запроса> <текст>")
    _, req_str, text = parts
    try:
        req_id = int(req_str)
    except:
        return await message.answer("Неверный ID.")
    me = await db.get_user_by_tg_id(message.from_user.id)
    req = await db.get_request_by_id(req_id)
    if not req or req[1] != me[0]:
        return await message.answer("Это не ваш запрос.")

    sp_id = req[8]
    if not sp_id:
        return await message.answer("Спикер ещё не выбран.")
    sp = await db.get_user_by_id(sp_id)
    await bot.send_message(sp[1], f"Ответ журналиста на запрос {req_id}:\n{text}")
    await message.answer("Отправлено спикеру.")


# ================================================================================================================
#                                           STATUS
# ================================================================================================================


async def cmd_status(message: types.Message):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user:
        return await message.answer("Вас нет в списке пользователей.")
    role = user[4]
    if role not in ('journalist', 'speaker'):
        return await message.answer("Только журналистам и спикерам.")

    lines = ["Ваши запросы:"]
    if role == 'journalist':
        # r = (id, spec_id, title, deadline, format, content, status, chosen_speaker_id)
        for r in await db.get_requests_by_journalist(user[0]):
            lines.append(f"ID {r[0]}: «{r[2]}» — статус {r[6]}\n")
    else:  # speaker
        # r = (id, title, deadline, request_status, invite_status, ...)
        for r in await db.get_requests_for_speaker(user[0]):
            lines.append(
                f"ID {r[0]}: «{r[1]}» — статус запроса: {r[3]}, дедлайн: {r[2]}\n"
            )

    await message.answer("\n".join(lines))


# ================================================================================================================
#                                           HANDLERS
# ================================================================================================================


def register_handlers_journalist(dp: Dispatcher, bot_obj, email_func):
    global bot, send_email
    bot = bot_obj
    send_email = email_func
    dp.message.register(cmd_new_request, Command('new_request'), StateFilter(None))
    dp.callback_query.register(spec_chosen, lambda c: c.data.startswith('pick_spec_'), StateFilter(RequestForm.choosing_spec))
    dp.callback_query.register(toggle_speaker, lambda c: c.data.startswith('toggle_spk_'), StateFilter(RequestForm.choosing_speakers))
    dp.callback_query.register(done_selecting, lambda c: c.data == 'done_select', StateFilter(RequestForm.choosing_speakers))
    dp.message.register(process_title, StateFilter(RequestForm.entering_title))
    dp.message.register(process_deadline, StateFilter(RequestForm.entering_deadline))
    dp.message.register(process_format, StateFilter(RequestForm.entering_format))
    dp.message.register(process_content, StateFilter(RequestForm.entering_content))
    # dp.callback_query.register(handle_accept, lambda c: c.data.startswith('req_') and '_accept_' in c.data)
    dp.callback_query.register(handle_decline, lambda c: c.data.startswith('req_') and '_decline_' in c.data)
    dp.callback_query.register(handle_stop, lambda c: c.data.startswith('stop_'))
    # dp.message.register(cmd_ask, Command('ask'), StateFilter(None))
    # dp.message.register(cmd_answer, Command('answer'), StateFilter(None))
    dp.callback_query.register(handle_accept_answer, lambda c: c.data.startswith('ans_'))
    dp.callback_query.register(handle_request_revision, lambda c: c.data.startswith('rev_'), StateFilter(None))
    dp.message.register(process_revision, StateFilter(RevisionState.waiting_comment))
    dp.message.register(cmd_reply, Command('reply'), StateFilter(None))
    dp.message.register(cmd_status, Command('status'), StateFilter(None))
    dp.message.register(cmd_status, lambda c: c.text == 'Статус запросов', StateFilter(None))
    dp.message.register(cmd_reply_start, lambda c: c.text == 'Ответить на вопрос по запросу', StateFilter(None))
    dp.message.register(process_reply_id, StateFilter(ReplyForm.waiting_request_id))
    dp.message.register(process_reply_text, StateFilter(ReplyForm.waiting_question))
    dp.message.register(cmd_new_request, lambda c: c.text == 'Новый запрос', StateFilter(None))
