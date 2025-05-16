from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardRemove
import db
from config import ADMIN_USERNAMES

def get_role_kb(role: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    if role == "journalist":
        builder.button(text="Новый запрос")
        builder.button(text="Ответить на вопрос по запросу")
        builder.button(text="Статус запросов")
    elif role == "speaker":
        builder.button(text="Ответить на запрос")       # speaker: answer
        builder.button(text="Задать вопрос по запросу") # speaker: ask
        builder.button(text="Статус запросов")          # speaker: status
    elif role == "admin":
        builder.button(text="Добавить специализацию")
        builder.button(text="Рассылка журналистам")
        builder.button(text="Рассылка спикерам")
        builder.button(text="Рассылка всем")
        builder.button(text="Показать BD")
        builder.button(text="Статусы всех запросов")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

class RegistrationState(StatesGroup):
    choosing_role = State()
    entering_email = State()
    entering_display_name = State()
    choosing_specializations = State()
    choosing_tariff = State()

async def cmd_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    # user = (id, tg_id, username, display_name, email, role, tariff, is_active)
    if user:
        # если ещё не подтверждён админом
        if user[7] == 0:
            await message.answer("Ваша регистрация ещё не подтверждена администратором. Пожалуйста, ожидайте.")
            return
        # уже зарегистрирован и активен
        await state.clear()
        await message.answer(
            "Вы уже зарегистрированы. Используйте команды бота.",
            reply_markup=get_role_kb(user[5])  # роль — на позиции 5
        )
        return

    # дальше — обычная логика начала регистрации для новых пользователей
    builder = ReplyKeyboardBuilder()
    builder.button(text="Журналист")
    builder.button(text="Спикер")
    builder.adjust(2)
    if message.from_user.username in ADMIN_USERNAMES:
        builder.button(text="Администратор")
    kb = builder.as_markup(resize_keyboard=True)
    await message.answer("Добро пожаловать! Выберите роль:", reply_markup=kb)
    await state.set_state(RegistrationState.choosing_role)

async def process_role(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    role = None
    if text == "журналист":
        role = "journalist"
    elif text == "спикер":
        role = "speaker"
    elif text == "администратор" and message.from_user.username in ADMIN_USERNAMES:
        role = "admin"
    if not role:
        await message.answer("Нужно выбрать из клавиатуры.")
        return
    await state.update_data(chosen_role=role)
    await message.answer("Укажите ваш email:")
    await state.set_state(RegistrationState.entering_email)

async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer("Неверный email, попробуйте ещё раз.")
        return
    await state.update_data(email=email)
    await message.answer("Введите ваше полное имя или название компании:")
    await state.set_state(RegistrationState.entering_display_name)


async def process_display_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    role = data['chosen_role']
    email = data['email']
    display_name = message.text.strip()
    tg = message.from_user

    # Сохраняем в БД (пока неактивного)
    await db.add_user(
        tg_id=tg.id,
        username=(tg.username or tg.full_name),
        display_name=display_name,
        email=email,
        role=role,
        tariff=None,
        is_active=0
    )

    # Если админ — сразу активируем и даём доступ без модерации
    if role == "admin":
        # сохраняем в users сразу с is_active=1
        await db.add_user(
            tg_id=message.from_user.id,
            username=message.from_user.username or message.from_user.full_name,
            display_name=display_name,
            email=email,
            role='admin',
            tariff=None,
            is_active=1
        )
        await message.answer(
            "Вы успешно зарегистрированы как администратор!",
            reply_markup=get_role_kb('admin')
        )
        await state.clear()
        return

    # Если спикер — сначала специализации, потом тариф
    if role == "speaker":
        specs = await db.list_specializations()
        if specs:
            names = ", ".join(s[1] for s in specs)
            await message.answer(
                f"Укажите ваши специализации через запятую из списка:\n{names}\nИли напишите 'нет'.",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.set_state(RegistrationState.choosing_specializations)
            return
        else:
            # если специализаций нет — сразу к тарифу
            await _ask_tariff(message, state)
            return

    # Иначе (журналист) — уведомляем админов и просим ждать
    await _notify_admins_new_user(message.bot, tg.id, data, None)
    await message.answer("Спасибо! Ожидайте подтверждения администратора.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

async def process_specializations(message: types.Message, state: FSMContext):
    """Обработка специализаций для спикера, затем — тариф."""
    user = await db.get_user_by_tg_id(message.from_user.id)
    specs = [n.strip() for n in message.text.split(",") if n.strip().lower()!='нет']
    for nm in specs:
        spec = await db.get_specialization_by_name(nm)
        if spec:
            await db.assign_specialization_to_user(user[0], spec[0])
    # теперь спрашиваем тариф
    await _ask_tariff(message, state)

async def _ask_tariff(message: types.Message, state: FSMContext):
    """Inline-кнопки с тарифами для спикера."""
    builder = InlineKeyboardBuilder()
    for t in ("Базовый","Профи","Премиум"):
        builder.button(text=t, callback_data=f"tariff_{t}")
    builder.adjust(2)
    await message.answer("Выберите тариф:", reply_markup=builder.as_markup())
    await state.set_state(RegistrationState.choosing_tariff)

async def on_tariff_selected(callback: types.CallbackQuery, state: FSMContext):
    tariff = callback.data.split("_",1)[1]
    data = await state.get_data()
    tg_id = callback.from_user.id

    # Сохраняем тариф
    await db.update_user_tariff(tg_id, tariff)

    # Уведомляем админов о готовности к подтверждению
    await _notify_admins_new_user(callback.bot, tg_id, data, tariff)

    await callback.message.answer("Спасибо! Ожидайте подтверждения администратора.", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await callback.answer()

async def _notify_admins_new_user(bot, tg_id, data, tariff):
    """Шлём всем админам на подтверждение новый аккаунт."""
    admins = await db.get_all_user_ids_by_role('admin')
    # display = data.get('display_name', '—')
    user = await db.get_user_by_tg_id(tg_id)
    text = (
        f"Новый пользователь:\n"
        f"Telegram ID: {tg_id}\n"
        f"Username: {user[2]}\n"
        f"Имя/компания: {user[3]}\n"
        f"Email: {data.get('email','—')}\n"
        f"Роль: {data.get('chosen_role','—')}"
    )
    if tariff:
        text += f"\nТариф: {tariff}\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"reg_confirm_{tg_id}")
    builder.button(text="❌ Отклонить",  callback_data=f"reg_reject_{tg_id}")
    builder.adjust(2)
    for adm in admins:
        await bot.send_message(adm, text, reply_markup=builder.as_markup())

def register_handlers_registration(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(process_role, StateFilter(RegistrationState.choosing_role))
    dp.message.register(process_email, StateFilter(RegistrationState.entering_email))
    dp.message.register(process_display_name, StateFilter(RegistrationState.entering_display_name))
    dp.message.register(process_specializations, StateFilter(RegistrationState.choosing_specializations))
    dp.callback_query.register(on_tariff_selected, lambda c: c.data.startswith("tariff_"), StateFilter(RegistrationState.choosing_tariff))
