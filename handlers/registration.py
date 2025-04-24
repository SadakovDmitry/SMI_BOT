# handlers/registration.py
from aiogram import types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
import db
from config import ADMIN_USERNAMES

# Определяем состояния FSM для регистрации
class RegistrationState(StatesGroup):
    choosing_role = State()             # выбор роли (журналист/спикер)
    entering_email = State()            # ввод email
    choosing_specializations = State()  # выбор специализаций (для спикера)

# Обработчик команды /start – начало процесса регистрации
async def cmd_start(message: types.Message, state: FSMContext):
    user = await db.get_user_by_tg_id(message.from_user.id)
    if user:
        # Если пользователь уже есть в базе, завершаем (не повторяем регистрацию)
        await state.clear()
        await message.answer("Вы уже зарегистрированы. Используйте команды бота для дальнейшей работы.")
        return
    # Пользователь новый – начинаем регистрацию
    # Подготавливаем клавиатуру для выбора роли
    buttons = [
        [
            types.KeyboardButton(text="Журналист"),
            types.KeyboardButton(text="Спикер")
        ]
    ]
    if message.from_user.username in ADMIN_USERNAMES:
        buttons.append([types.KeyboardButton(text="Администратор")])

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Добро пожаловать! Пожалуйста, выберите вашу роль:", reply_markup=keyboard)
    # Устанавливаем состояние FSM для ожидания выбора роли
    # await RegistrationState.choosing_role.set()
    await state.set_state(RegistrationState.choosing_role)

# Обработчик выбора роли пользователем
async def process_role(message: types.Message, state: FSMContext):
    role_text = message.text.strip().lower()
    role = None
    if role_text == "журналист":
        role = "journalist"
    elif role_text == "спикер":
        role = "speaker"
    elif role_text == "администратор":
        # Проверяем, имеет ли пользователь право быть админом
        if message.from_user.username in ADMIN_USERNAMES:
            role = "admin"
        else:
            await message.answer("Вы не имеете права зарегистрироваться как администратор.")
            # Остаёмся в состоянии выбора роли, позволяем выбрать снова
            return
    else:
        # Неизвестный ввод
        await message.answer("Пожалуйста, выберите роль, используя предложенную клавиатуру.")
        return
    # Сохраняем выбранную роль во временные данные FSM
    await state.update_data(chosen_role=role)
    # Запрашиваем email
    await message.answer("Хорошо, теперь укажите ваш email для связи:")
    await state.set_state(RegistrationState.entering_email)  # переходим к состоянию entering_email

# Обработчик ввода email
async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    # Простейшая проверка формата email
    if "@" not in email or "." not in email:
        await message.answer("Пожалуйста, введите корректный email.")
        return
    # Сохраняем email во временном состоянии
    await state.update_data(email=email)
    data = await state.get_data()
    role = data.get('chosen_role')
    # Сохраняем пользователя в базе данных
    # Если у пользователя нет username, используем его имя (first_name + last_name) для идентификации
    user_name = message.from_user.username
    if not user_name:
        user_name = message.from_user.full_name or ""
    await db.add_user(message.from_user.id, user_name, role, email)
    user = await db.get_user_by_tg_id(message.from_user.id)
    # Если пользователь – спикер, переходим к выбору специализаций
    if role == "speaker":
        specs = await db.list_specializations()
        if specs:
            # Предоставляем список доступных специализаций
            spec_names = ", ".join([s[1] for s in specs])
            await message.answer(
                f"Укажите ваши специализации через запятую из списка: {spec_names}\nЕсли ничего не подходит, введите 'нет'."
            )
        else:
            await message.answer("Сейчас в системе нет доступных специализаций. Вы можете добавить их позже через администратора.")
            # Завершаем регистрацию, если нет ни одной специализации
            await state.clear()
            return
        await state.set_state(RegistrationState.choosing_specializations)  # состояние choosing_specializations
    else:
        # Если роль – журналист или админ, на этом регистрация заканчивается
        await message.answer("Регистрация завершена! Вы можете начинать работу с ботом.")
        await state.clear()

# Обработчик выбора специализаций для спикера
async def process_specializations(message: types.Message, state: FSMContext):
    spec_input = message.text.strip()
    data = await state.get_data()
    user = await db.get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Ошибка: пользователь не найден.")
        await state.clear()
        return
    if spec_input.lower() in ('нет', 'не знаю', 'нечего'):
        # Спикер указал, что специализаций нет или не подошли
        await message.answer("Спасибо! Вы зарегистрированы как спикер без указанных специализаций.")
        await state.clear()
        return
    # Разбираем введённые названия специализаций
    spec_names = [name.strip() for name in spec_input.split(',') if name.strip()]
    assigned_any = False
    for name in spec_names:
        spec = await db.get_specialization_by_name(name)
        if spec:
            # Привязываем специализацию к пользователю-спикеру
            await db.assign_specialization_to_user(user[0], spec[0])
            assigned_any = True
    if assigned_any:
        await message.answer("Ваши специализации сохранены. Регистрация завершена!")
    else:
        await message.answer("Не удалось сохранить специализации (возможно, указаны неверные названия). "
                              "При необходимости обратитесь к администратору для добавления новых специализаций.")
    await state.clear()

# Функция для регистрации обработчиков данного модуля в диспетчере
def register_handlers_registration(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(process_role, StateFilter(RegistrationState.choosing_role))
    dp.message.register(process_email, StateFilter(RegistrationState.entering_email))
    dp.message.register(process_specializations, StateFilter(RegistrationState.choosing_specializations))
