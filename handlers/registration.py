from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
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
    choosing_specializations = State()

async def cmd_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if user:
        await state.clear()
        await message.answer(
            "Вы уже зарегистрированы. Используйте команды бота.",
            reply_markup=get_role_kb(user[4])
        )
        return

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

    data = await state.get_data()
    role = data['chosen_role']
    username = message.from_user.username or message.from_user.full_name or ""
    await db.add_user(message.from_user.id, username, role, email)
    if role == "speaker":
        specs = await db.list_specializations()
        if specs:
            names = ", ".join([s[1] for s in specs])
            await message.answer(
                f"Выберите специализации через запятую из списка: {names}\n"
                "Или напишите 'нет'."
            )
            await state.set_state(RegistrationState.choosing_specializations)
            return
    await message.answer(
        "Регистрация завершена!",
        reply_markup=get_role_kb(role)
    )
    await state.clear()

async def process_specializations(message: types.Message, state: FSMContext):
    spec_input = message.text.strip().lower()
    user = await db.get_user_by_tg_id(message.from_user.id)
    if spec_input in ('нет', 'не знаю', 'нечего'):
        await message.answer("Регистрация завершена!", reply_markup=get_role_kb("speaker"))
        await state.clear()
        return

    names = [n.strip() for n in message.text.split(",")]
    assigned = False
    for nm in names:
        spec = await db.get_specialization_by_name(nm)
        if spec:
            await db.assign_specialization_to_user(user[0], spec[0])
            assigned = True

    msg = "Специализации сохранены." if assigned else "Ничего не сохранено."
    await message.answer(msg, reply_markup=get_role_kb("speaker"))
    await state.clear()

def register_handlers_registration(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(process_role, StateFilter(RegistrationState.choosing_role))
    dp.message.register(process_email, StateFilter(RegistrationState.entering_email))
    dp.message.register(process_specializations, StateFilter(RegistrationState.choosing_specializations))
