
import asyncio
import os
import hmac

from datetime import datetime, date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from database import (
    init_db,
    add_available_slot,
    get_available_slots,
    delete_available_slot,
    book_available_slot,
    get_client_bookings,
    cancel_client_booking as cancel_booking_in_db
)


# Загружаем настройки из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MASTER_PASSWORD = os.getenv("MASTER_PASSWORD")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в файле .env")

if not MASTER_PASSWORD:
    raise ValueError("Не найден MASTER_PASSWORD в файле .env")


# Создаём бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Аккаунты, вошедшие в кабинет мастера
authorized_masters = set()


# Состояние входа
class MasterLogin(StatesGroup):
    waiting_for_password = State()


# Состояния добавления окошка
class MasterAddSlot(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()

# Состояния записи клиента
class ClientBooking(StatesGroup):
    choosing_service = State()
    choosing_master = State()
    choosing_slot = State()
    confirming = State()

# Главное меню

# Главное меню клиента
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Записаться"),
            KeyboardButton(text="Услуги и цены")
        ],
        [
            KeyboardButton(text="Наши мастера"),
            KeyboardButton(text="Мои записи")
        ],
        [
            KeyboardButton(text="Мой профиль"),
            KeyboardButton(text="Войти как мастер")
        ],
        [
            KeyboardButton(text="Помощь")
        ]
    ],
    resize_keyboard=True
)


# Меню мастера
master_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Добавить окошко")],
        [KeyboardButton(text="Моё расписание")],
        [KeyboardButton(text="Удалить окошко")],
        [KeyboardButton(text="Выйти из кабинета")]
    ],
    resize_keyboard=True
)


# Список услуг
services = [
    {
        "name": "Маникюр без покрытия",
        "price": 3000,
        "description": "Гигиенический маникюр, обработка кутикулы"
    },
    {
        "name": "Маникюр с гель-лаком",
        "price": 4000,
        "description": "Покрытие ногтевой пластины гель-лаком без наращивания длины"
    },
    {
        "name": "Наращивание ногтей",
        "price": 5000,
        "description": "Создание желаемой длины и формы ногтей"
    },
    {
        "name": "Снятие покрытия",
        "price": 1000,
        "description": "Аккуратное снятие старого покрытия"
    },
    {
        "name": "Дизайн",
        "price": 1000,
        "description": "Дополнительное оформление ногтей"
    },
    {
        "name": "Ремонт 1 ногтя",
        "price": 1000,
        "description": "Восстановление повреждённого ногтя"
    }
]


# Список мастеров
masters = [
    {
        "name": "Анна",
        "specialization": "Мастер маникюра",
        "experience": "2 года",
        "phone": "+7 702 154 79 01",
        "inst": "@maria.nails.krg"
    }
]


# Проверка авторизации
def is_authorized_master(user_id: int):
    return user_id in authorized_masters


# Форматирование даты
def selected_date_for_display(booking_date: str):
    parsed_date = datetime.strptime(booking_date, "%Y-%m-%d")
    return parsed_date.strftime("%d.%m.%Y")


# Клавиатура услуг
def get_services_keyboard():
    buttons = []

    for index, service in enumerate(services):
        buttons.append([
            InlineKeyboardButton(
                text=f"{service['name']} — {service['price']} ₸",
                callback_data=f"service_{index}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатура выбора услуги для записи
def get_booking_services_keyboard():
    buttons = []

    for index, service in enumerate(services):
        buttons.append([
            InlineKeyboardButton(
                text=f"{service['name']} — {service['price']} ₸",
                callback_data=f"book_service_{index}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатура выбора мастера
def get_booking_masters_keyboard():
    buttons = []

    for index, master in enumerate(masters):
        buttons.append([
            InlineKeyboardButton(
                text=master["name"],
                callback_data=f"book_master_{index}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатура свободных окошек
def get_booking_slots_keyboard(slots):
    buttons = []

    for slot in slots:
        slot_id, booking_date, booking_time, is_booked = slot

        if is_booked:
            continue

        formatted_date = selected_date_for_display(booking_date)

        buttons.append([
            InlineKeyboardButton(
                text=f"{formatted_date} — {booking_time}",
                callback_data=f"book_slot_{slot_id}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатура подтверждения
def get_booking_confirmation_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить запись",
                    callback_data="confirm_booking"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data="cancel_booking"
                )
            ]
        ]
    )


# Вход в кабинет мастера
@dp.message(F.text == "Войти как мастер")
async def master_login(message: Message, state: FSMContext):
    if is_authorized_master(message.from_user.id):
        await message.answer(
            "Ты уже вошёл в кабинет мастера.",
            reply_markup=master_keyboard
        )
        return

    await state.set_state(MasterLogin.waiting_for_password)

    await message.answer(
        "Вход в кабинет мастера.\n\n"
        "Введите пароль.\n"
        "Для отмены отправьте /cancel."
    )


# Проверка пароля
@dp.message(MasterLogin.waiting_for_password)
async def check_master_password(message: Message, state: FSMContext):
    if not message.text or not hmac.compare_digest(
        message.text,
        MASTER_PASSWORD
    ):
        await message.answer(
            "Неверный пароль. Попробуй ещё раз или отправь /cancel."
        )
        return

    authorized_masters.add(message.from_user.id)
    await state.clear()

    await message.answer(
        "Вход выполнен успешно!\n\n"
        "Добро пожаловать в кабинет мастера.",
        reply_markup=master_keyboard
    )


# Отмена входа
@dp.message(Command("cancel"), MasterLogin.waiting_for_password)
async def cancel_master_login(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Вход отменён.",
        reply_markup=main_keyboard
    )


# Выход из кабинета
@dp.message(F.text == "Выйти из кабинета")
async def master_logout(message: Message, state: FSMContext):
    authorized_masters.discard(message.from_user.id)
    await state.clear()

    await message.answer(
        "Ты вышел из кабинета мастера.",
        reply_markup=main_keyboard
    )


# Начало добавления свободного окошка
@dp.message(F.text == "Добавить окошко")
async def start_add_slot(message: Message, state: FSMContext):
    if not is_authorized_master(message.from_user.id):
        await message.answer("Сначала войди в кабинет мастера.")
        return

    await state.set_state(MasterAddSlot.waiting_for_date)

    await message.answer(
        "Добавление свободного окошка.\n\n"
        "Введи дату в формате ДД.ММ.ГГГГ.\n"
        "Например: 15.11.2026\n\n"
        "Для отмены отправь /cancel."
    )


# Получение даты
@dp.message(MasterAddSlot.waiting_for_date)
async def get_slot_date(message: Message, state: FSMContext):
    if not is_authorized_master(message.from_user.id):
        await state.clear()
        await message.answer("Нет доступа к кабинету мастера.")
        return

    try:
        selected_date = datetime.strptime(
            message.text,
            "%d.%m.%Y"
        ).date()

        if selected_date < date.today():
            await message.answer(
                "Нельзя добавить окошко на прошедшую дату. "
                "Введи другую дату."
            )
            return

    except (ValueError, TypeError):
        await message.answer(
            "Неверный формат даты. Введи дату так: 15.11.2026"
        )
        return

    await state.update_data(
        booking_date=selected_date.strftime("%Y-%m-%d")
    )

    await state.set_state(MasterAddSlot.waiting_for_time)

    await message.answer(
        "Теперь введи время в формате ЧЧ:ММ.\n"
        "Например: 14:30"
    )


# Получение времени и сохранение окошка
@dp.message(MasterAddSlot.waiting_for_time)
async def get_slot_time(message: Message, state: FSMContext):
    if not is_authorized_master(message.from_user.id):
        await state.clear()
        await message.answer("Нет доступа к кабинету мастера.")
        return

    try:
        selected_time = datetime.strptime(
            message.text,
            "%H:%M"
        ).time()

    except (ValueError, TypeError):
        await message.answer(
            "Неверный формат времени. Введи время так: 14:30"
        )
        return

    data = await state.get_data()
    booking_date = data["booking_date"]

    master_name = masters[0]["name"]

    added = add_available_slot(
        master_name,
        booking_date,
        selected_time.strftime("%H:%M")
    )

    await state.clear()

    if added:
        await message.answer(
            "Свободное окошко успешно добавлено!\n\n"
            f"Мастер: {master_name}\n"
            f"Дата: {selected_date_for_display(booking_date)}\n"
            f"Время: {selected_time.strftime('%H:%M')}",
            reply_markup=master_keyboard
        )
    else:
        await message.answer(
            "На эту дату и время окошко уже существует.",
            reply_markup=master_keyboard
        )


# Отмена добавления окошка
@dp.message(Command("cancel"), MasterAddSlot.waiting_for_date)
@dp.message(Command("cancel"), MasterAddSlot.waiting_for_time)
async def cancel_add_slot(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Добавление окошка отменено.",
        reply_markup=master_keyboard
    )


# Главное меню
@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Привет!\n\n"
        "Добро пожаловать в Beauty Booking!\n"
        "Выбери действие в меню ниже.",
        reply_markup=main_keyboard
    )


# Услуги и цены
@dp.message(F.text == "Услуги и цены")
async def services_handler(message: Message):
    await message.answer(
        "Наши услуги и цены.\n\n"
        "Выбери интересующую тебя процедуру:",
        reply_markup=get_services_keyboard()
    )


# Подробная информация об услуге
@dp.callback_query(F.data.startswith("service_"))
async def service_detail_handler(callback: CallbackQuery):
    service_index = int(callback.data.split("_")[1])

    if not 0 <= service_index < len(services):
        await callback.answer("Услуга не найдена.", show_alert=True)
        return

    service = services[service_index]

    await callback.message.answer(
        f"{service['name']}\n\n"
        f"{service['description']}\n\n"
        f"Стоимость: {service['price']} ₸"
    )

    await callback.answer()


# Наши мастера
@dp.message(F.text == "Наши мастера")
async def masters_handler(message: Message):
    for master in masters:
        text = (
            f"Мастер: {master['name']}\n\n"
            f"Специализация: {master['specialization']}\n"
            f"Опыт работы: {master['experience']}\n\n"
            f"Телефон: {master['phone']}\n"
            f"Instagram: {master['inst']}"
        )

        await message.answer(text)


# Запись

# Начало записи клиента
@dp.message(F.text == "Записаться")
async def booking_handler(message: Message, state: FSMContext):
    await state.set_state(ClientBooking.choosing_service)

    await message.answer(
        "Давай запишемся!\n\n"
        "Сначала выбери услугу:",
        reply_markup=get_booking_services_keyboard()
    )


# Просмотр активных записей клиента
@dp.message(F.text == "Мои записи")
async def my_bookings_handler(message: Message):
    bookings = get_client_bookings(message.from_user.id)

    # Оставляем только записи на сегодня и будущие даты
    today = date.today()

    active_bookings = []

    for booking in bookings:
        booking_date = datetime.strptime(
            booking[3], "%Y-%m-%d"
        ).date()

        if booking_date >= today:
            active_bookings.append(booking)

    if not active_bookings:
        await message.answer(
            "У тебя пока нет активных записей.\n\n"
            "Нажми «Записаться», чтобы выбрать удобное время.",
            reply_markup=main_keyboard
        )
        return

    await message.answer(
        f"Твои активные записи: {len(active_bookings)}"
    )

    for booking in active_bookings:
        (
            booking_id,
            service_name,
            master_name,
            booking_date,
            booking_time,
            status,
            slot_id
        ) = booking

        formatted_date = selected_date_for_display(booking_date)

        service = next(
            (item for item in services if item["name"] == service_name),
            None
        )

        price_text = (
            f"{service['price']} ₸"
            if service else "Не указана"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отменить запись",
                        callback_data=f"cancel_my_booking_{booking_id}"
                    )
                ]
            ]
        )

        await message.answer(
            "Твоя запись\n\n"
            f"Услуга: {service_name}\n"
            f"Стоимость: {price_text}\n"
            f"Мастер: {master_name}\n"
            f"Дата: {formatted_date}\n"
            f"Время: {booking_time}\n"
            "Статус: Подтверждена",
            reply_markup=keyboard
        )


# Отмена активной записи клиентом
@dp.callback_query(F.data.startswith("cancel_my_booking_"))
async def cancel_my_booking_handler(callback: CallbackQuery):
    try:
        booking_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(
            "Не удалось определить запись.",
            show_alert=True
        )
        return

    cancelled = cancel_booking_in_db(
        booking_id,
        callback.from_user.id
        )

    if cancelled:
        await callback.message.edit_text(
            "Твоя запись отменена.\n\n"
            "Это время снова доступно для записи."
        )

        await callback.answer("Запись отменена!")
    else:
        await callback.answer(
            "Запись уже отменена или не найдена.",
            show_alert=True
        )


# Клиент выбирает услугу
@dp.callback_query(F.data.startswith("book_service_"))
async def choose_booking_service(callback: CallbackQuery, state: FSMContext):
    try:
        service_index = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора услуги.", show_alert=True)
        return

    if not 0 <= service_index < len(services):
        await callback.answer("Услуга не найдена.", show_alert=True)
        return

    service = services[service_index]

    await state.update_data(
        service_index=service_index,
        service_name=service["name"],
        service_price=service["price"]
    )

    await state.set_state(ClientBooking.choosing_master)

    await callback.message.edit_text(
        f"Ты выбрал(а): {service['name']}\n"
        f"Стоимость: {service['price']} ₸\n\n"
        "Теперь выбери мастера:",
        reply_markup=get_booking_masters_keyboard()
    )

    await callback.answer()


# Клиент выбирает мастера
@dp.callback_query(F.data.startswith("book_master_"))
async def choose_booking_master(callback: CallbackQuery, state: FSMContext):
    try:
        master_index = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора мастера.", show_alert=True)
        return

    if not 0 <= master_index < len(masters):
        await callback.answer("Мастер не найден.", show_alert=True)
        return

    master = masters[master_index]

    await state.update_data(
        master_name=master["name"]
    )

    slots = get_available_slots(master["name"])

    free_slots = [
        slot for slot in slots if slot[3] == 0
    ]

    if not free_slots:
        await callback.message.edit_text(
            f"У мастера {master['name']} пока нет свободных окошек.\n\n"
            "Попробуй выбрать другого мастера."
        )

        await callback.answer()
        return

    await state.set_state(ClientBooking.choosing_slot)

    await callback.message.edit_text(
        f"Мастер: {master['name']}\n\n"
        "Выбери удобную дату и время:",
        reply_markup=get_booking_slots_keyboard(free_slots)
    )

    await callback.answer()


# Клиент выбирает свободное окошко
@dp.callback_query(F.data.startswith("book_slot_"))
async def choose_booking_slot(callback: CallbackQuery, state: FSMContext):
    try:
        slot_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора времени.", show_alert=True)
        return

    data = await state.get_data()

    if not data.get("service_name") or not data.get("master_name"):
        await callback.answer(
            "Начни запись заново.",
            show_alert=True
        )
        await state.clear()
        return

    master_name = data["master_name"]
    slots = get_available_slots(master_name)

    selected_slot = next(
        (
            slot for slot in slots
            if slot[0] == slot_id and slot[3] == 0
        ),
        None
    )

    if selected_slot is None:
        await callback.answer(
            "Это окошко уже занято. Выбери другое.",
            show_alert=True
        )
        return

    slot_id, booking_date, booking_time, is_booked = selected_slot

    await state.update_data(
        slot_id=slot_id,
        booking_date=booking_date,
        booking_time=booking_time
    )

    await state.set_state(ClientBooking.confirming)

    formatted_date = selected_date_for_display(booking_date)

    await callback.message.edit_text(
        "Проверь свою запись:\n\n"
        f"Услуга: {data['service_name']}\n"
        f"Стоимость: {data['service_price']} ₸\n"
        f"Мастер: {master_name}\n"
        f"Дата: {formatted_date}\n"
        f"Время: {booking_time}\n\n"
        "Всё верно?",
        reply_markup=get_booking_confirmation_keyboard()
    )

    await callback.answer()


# Клиент подтверждает запись
@dp.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    required_fields = [
        "slot_id",
        "service_name",
        "master_name",
        "booking_date",
        "booking_time"
    ]

    if not all(field in data for field in required_fields):
        await state.clear()
        await callback.answer(
            "Данные записи потерялись. Начни заново.",
            show_alert=True
        )
        return

    username = callback.from_user.username or ""

    result = book_available_slot(
        slot_id=data["slot_id"],
        telegram_id=callback.from_user.id,
        username=username,
        service_name=data["service_name"],
        master_name=data["master_name"]
    )

    await state.clear()

    if result is None:
        await callback.message.edit_text(
            "К сожалению, это окошко уже занято.\n\n"
            "Попробуй записаться на другое время."
        )
        await callback.answer("Время недоступно.")
        return

    booking_date, booking_time, master_name = result

    await callback.message.edit_text(
        "Запись успешно подтверждена!\n\n"
        f"Услуга: {data['service_name']}\n"
        f"Стоимость: {data['service_price']} ₸\n"
        f"Мастер: {master_name}\n"
        f"Дата: {selected_date_for_display(booking_date)}\n"
        f"Время: {booking_time}\n\n"
        "Спасибо за запись в Beauty Booking!"
    )

    await callback.answer("Запись подтверждена!")


# Отмена записи
@dp.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    await callback.message.edit_text(
        "Запись отменена. Ты можешь начать заново через кнопку «Записаться»."
    )

    await callback.answer()


# Отмена записи через команду
@dp.message(Command("cancel"), ClientBooking.choosing_service)
@dp.message(Command("cancel"), ClientBooking.choosing_master)
@dp.message(Command("cancel"), ClientBooking.choosing_slot)
@dp.message(Command("cancel"), ClientBooking.confirming)
async def cancel_client_booking(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Запись отменена.",
        reply_markup=main_keyboard
    )



# Профиль
@dp.message(F.text == "Мой профиль")
async def profile_handler(message: Message):
    await message.answer(
        "Твой профиль.\n\n"
        f"Имя: {message.from_user.full_name}"
    )


# Помощь
@dp.message(F.text == "Помощь")
async def help_handler(message: Message):
    await message.answer(
        "Раздел помощи.\n\n"
        "Если у тебя возникли вопросы по записи или услугам, "
        "обратись к администратору."
    )


# Моё расписание
@dp.message(F.text == "Моё расписание")
async def my_schedule_handler(message: Message):
    if not is_authorized_master(message.from_user.id):
        await message.answer(
            "Сначала войди в кабинет мастера.",
            reply_markup=main_keyboard
        )
        return

    master_name = masters[0]["name"]
    slots = get_available_slots(master_name)

    if not slots:
        await message.answer(
            "В расписании пока нет окошек.",
            reply_markup=master_keyboard
        )
        return

    text = f"Расписание мастера {master_name}\n\n"

    for slot in slots:
        slot_id, booking_date, booking_time, is_booked = slot

        formatted_date = selected_date_for_display(booking_date)

        status = "Занято" if is_booked else "Свободно"

        text += (
            f"Дата: {formatted_date}\n"
            f"Время: {booking_time}\n"
            f"Статус: {status}\n"
            f"--------------------\n"
        )

    await message.answer(
        text,
        reply_markup=master_keyboard
    )


# Удаление окошка
@dp.message(F.text == "Удалить окошко")
async def start_delete_slot(message: Message):
    if not is_authorized_master(message.from_user.id):
        await message.answer(
            "Сначала войди в кабинет мастера.",
            reply_markup=main_keyboard
        )
        return

    master_name = masters[0]["name"]
    slots = get_available_slots(master_name)

    free_slots = [
        slot for slot in slots if slot[3] == 0
    ]

    if not free_slots:
        await message.answer(
            "Нет свободных окошек для удаления.",
            reply_markup=master_keyboard
        )
        return

    buttons = []

    for slot in free_slots:
        slot_id, booking_date, booking_time, is_booked = slot

        formatted_date = selected_date_for_display(booking_date)

        buttons.append([
            InlineKeyboardButton(
                text=f"{formatted_date} — {booking_time}",
                callback_data=f"delete_slot_{slot_id}"
            )
        ])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await message.answer(
        "Выбери свободное окошко, которое хочешь удалить:",
        reply_markup=keyboard
    )


# Обработка удаления окошка
@dp.callback_query(F.data.startswith("delete_slot_"))
async def delete_slot_handler(callback: CallbackQuery):
    if not is_authorized_master(callback.from_user.id):
        await callback.answer(
            "Сначала войди в кабинет мастера.",
            show_alert=True
        )
        return

    try:
        slot_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер окошка.",
            show_alert=True
        )
        return

    master_name = masters[0]["name"]

    deleted = delete_available_slot(
        slot_id,
        master_name
    )

    if deleted:
        await callback.message.edit_text(
            "Свободное окошко успешно удалено."
        )
        await callback.answer("Удалено!")
    else:
        await callback.answer(
            "Не удалось удалить окошко. Возможно, оно уже занято.",
            show_alert=True
        )


# Неизвестные сообщения
@dp.message()
async def unknown_handler(message: Message):
    await message.answer(
        "Я пока не понимаю эту команду. "
        "Пожалуйста, воспользуйся кнопками меню."
    )


# Запуск бота
async def main():
    init_db()

    print("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())




