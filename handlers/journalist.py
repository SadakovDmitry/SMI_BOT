from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
import db

# Будут установлены при регистрации хендлеров
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


async def cmd_new_request(message: types.Message, state: FSMContext):
    """Начало создания нового запроса (для журналистов)"""
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user or user[4] != 'journalist':
        await message.answer("Эта команда доступна только журналистам.")
        return
    specs = await db.list_specializations()
    if not specs:
        await message.answer("Нет доступных специализаций. Обратитесь к администратору.")
        return
    await state.set_state(RequestForm.choosing_spec)
    builder = InlineKeyboardBuilder()
    for spec in specs:
        builder.button(text=spec[1], callback_data=f"pick_spec_{spec[0]}")
    builder.adjust(2)  # по 2 кнопки в ряд
    keyboard = builder.as_markup()
    await message.answer("Выберите специализацию запроса:", reply_markup=keyboard)


async def spec_chosen(callback: types.CallbackQuery, state: FSMContext):
    _, _, spec_id = callback.data.split('_')
    spec_id = int(spec_id)
    await state.update_data(spec_id=spec_id)
    speakers = await db.get_speakers_by_specialization(spec_id)
    if not speakers:
        await callback.answer("Нет спикеров с этой специализацией.", show_alert=True)
        return
    # Формируем словарь спикеров {id: (tg_id, name)}
    sp_map = {str(s[0]): (s[1], s[2] or s[3]) for s in speakers}
    await state.update_data(potential_speakers=sp_map, selected_speakers=[])
    # Строим клавиатуру для выбора спикеров
    # keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    builder = InlineKeyboardBuilder()
    for uid, (tg, name) in sp_map.items():
        builder.button(text=f"☐ {name}", callback_data=f"toggle_spk_{uid}")
    builder.button(text="✅ Готово", callback_data="done_select")
    keyboard = builder.as_markup()
    await callback.message.edit_text("Выберите спикеров для запроса:", reply_markup=keyboard)
    await state.set_state(RequestForm.choosing_speakers)
    await callback.answer()


async def toggle_speaker(callback: types.CallbackQuery, state: FSMContext):
    _, _, uid = callback.data.split('_')
    data = await state.get_data()
    selected = data['selected_speakers']
    sp_map = data['potential_speakers']
    if uid in selected:
        selected.remove(uid)
    else:
        selected.append(uid)
    await state.update_data(selected_speakers=selected)
    # Обновляем кнопки
    builder = InlineKeyboardBuilder()
    for id_, (tg, name) in sp_map.items():
        mark = '✅' if id_ in selected else '☐'
        builder.button(text=f"{mark} {name}", callback_data=f"toggle_spk_{id_}")
    builder.button(text="✅ Готово", callback_data="done_select")
    keyboard = builder.as_markup()
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()


async def done_selecting(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data['selected_speakers']
    if not selected:
        await callback.answer("Выберите хотя бы одного спикера.", show_alert=True)
        return
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
    await message.answer(f"Запрос отправлен {len(speakers)} спикерам.")
    await state.clear()


async def handle_accept(callback: types.CallbackQuery):
    _, req_id_str, _, sp_id_str = callback.data.split('_')
    req_id, sp_id = int(req_id_str), int(sp_id_str)

    # 1) обновляем статус этого приглашения
    await db.update_invite_status(req_id, sp_id, 'accepted')
    await db.mark_request_in_progress(req_id)
    await db.set_chosen_speaker(req_id, sp_id)  # если вы уже добавили эту функцию

    # 2) удаляем клавиатуру у самого callback-сообщения
    await callback.message.edit_reply_markup(reply_markup=None)

    # 3) уведомляем других спикеров (pending -> cancelled)
    invites = await db.get_invites_for_request(req_id)
    for other_sp_id, status, *_ in invites:
        if status == 'pending':
            # помечаем у них cancelled
            await db.update_invite_status(req_id, other_sp_id, 'cancelled')
            usr = await db.get_user_by_id(other_sp_id)
            await bot.send_message(
                usr[1],
                "К вашему запросу уже найден спикер, это приглашение закрыто."
            )

    # 4) уведомляем журналиста
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    # создаём однокнопочную панель для ЖУРНАЛИСТА
    kb = InlineKeyboardBuilder()
    kb.button(text="Остановить запрос", callback_data=f"stop_{req_id}")
    await bot.send_message(
        journ[1],
        f"Спикер принял ваш запрос (ID {req_id}).",
        reply_markup=kb.as_markup()
    )

    await callback.answer("Вы приняли запрос.")



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


async def cmd_ask(message: types.Message):
    """Спикер задает уточняющий вопрос журналисту: /ask <request_id> <текст>"""
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
        await message.answer("Вы не участвуете в этом запросе или не приняли его.")
        return
    req = await db.get_request_by_id(req_id)
    journ = await db.get_user_by_id(req[1])
    await bot.send_message(journ[1], f"Вопрос по запросу {req_id}: {question}")
    await message.answer("Вопрос отправлен журналисту.")


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
    keyboard = builder.as_markup()
    await bot.send_message(journ[1], f"Ответ по запросу {req_id}:\n{answer}", reply_markup=keyboard)
    await message.answer("Ответ отправлен журналисту.")
#
#
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


async def cmd_status(message: types.Message):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Вы не зарегистрированы.")
        return
    role = user[4]
    text = "Статусы ваших запросов:\n"
    if role == 'journalist':
        reqs = await db.get_requests_by_journalist(user[0])
        for r in reqs:
            text += f"ID {r[0]}: {r[2]} - {r[7]}\n"
    elif role == 'speaker':
        invs = await db.get_requests_for_speaker(user[0])
        for inv in invs:
            text += f"Запрос ID {inv[0]} - приглашение: {inv[4]}, статус запроса: {inv[3]}\n"
    else:
        text = "Команда /status не поддерживается для вашей роли."
    await message.answer(text)


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
    dp.callback_query.register(handle_accept, lambda c: c.data.startswith('req_') and '_accept_' in c.data)
    dp.callback_query.register(handle_decline, lambda c: c.data.startswith('req_') and '_decline_' in c.data)
    dp.callback_query.register(handle_stop, lambda c: c.data.startswith('stop_'))
    dp.message.register(cmd_ask, Command('ask'), StateFilter(None))
    dp.message.register(cmd_answer, Command('answer'), StateFilter(None))
    dp.callback_query.register(handle_accept_answer, lambda c: c.data.startswith('ans_'))
    dp.callback_query.register(handle_request_revision, lambda c: c.data.startswith('rev_'), StateFilter(None))
    dp.message.register(process_revision, StateFilter(RevisionState.waiting_comment))
    dp.message.register(cmd_status, Command('status'), StateFilter(None))
