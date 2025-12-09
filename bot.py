import telebot
import datetime
import pytz
import subprocess
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import io
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# =======================
# НАСТРОЙКИ
# =======================
TOKEN = "8353686586:AAGP8rO1wKkLGv8pIzQwLsk5ziUH_BmsUD4"
TABLE_ID = "1R9RVzxYrR8ClcQpogUWAdnqpd_2UthwEcLgm2w8IL14"
ADMIN_IDS = [8136311010]
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# канал для уведомлений
REPORT_CHANNEL_ID = -1003227555928

bot = telebot.TeleBot(TOKEN)

# =======================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# =======================
engineers = []
locations = []
work_names = []
work_point = {}
user_data = {}


# =======================
# МЕНЮ
# =======================

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Старт"))
    kb.add(KeyboardButton("Посмотреть таблицу"))
    kb.add(KeyboardButton("Открыть таблицу"))
    kb.add(KeyboardButton("Настройки"))
    return kb


def restart_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Начать сначала", "Меню")
    return kb


@bot.message_handler(func=lambda m: m.text == "Меню")
def go_main_menu(message):
    user_data.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())


def is_admin(chat_id):
    return chat_id in ADMIN_IDS


# =======================
# GOOGLE SHEETS
# =======================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds_legacy = ServiceAccountCredentials.from_json_keyfile_name(
    "credentials.json", scope
)
client = gspread.authorize(creds_legacy)
book = client.open_by_key(TABLE_ID)

ops_sheet = book.worksheet("Список")
eng_sheet = book.worksheet("Engineers")
loc_sheet = book.worksheet("Locations")
works_sheet = book.worksheet("Works")


# =======================
# ПОДГРУЗКА СПРАВОЧНИКОВ
# =======================

def reload_data():
    global engineers, locations, work_names, work_point

    eng_values = eng_sheet.get_all_values()
    engineers = [r[0].strip() for r in eng_values[1:] if r and r[0].strip()]

    loc_values = loc_sheet.get_all_values()
    locations = [r[0].strip() for r in loc_values[1:] if r and r[0].strip()]

    work_values = works_sheet.get_all_values()
    work_names_local = []
    work_point_local = {}

    for r in work_values[1:]:
        if not r or not r[0].strip():
            continue
        name = r[0].strip()
        point = r[1].strip() if len(r) > 1 else ""
        work_names_local.append(name)
        work_point_local[name] = point

    work_names = work_names_local
    work_point = work_point_local


reload_data()


# =======================
# PDF GOOGLE SHEET
# =======================
def download_sheet_pdf():
    try:
        creds = service_account.Credentials.from_service_account_file(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        authed_session = AuthorizedSession(creds)
        url = f"https://docs.google.com/spreadsheets/d/{TABLE_ID}/export?format=pdf"
        response = authed_session.get(url)

        if response.status_code != 200:
            return None

        pdf_bytes = io.BytesIO(response.content)
        pdf_bytes.seek(0)
        return pdf_bytes
    except:
        return None

@bot.message_handler(commands=["start"])
@bot.message_handler(func=lambda m: m.text == "Старт")
def start(message):
    user = message.chat.id
    user_data[user] = {}

    if not engineers:
        bot.send_message(
            user,
            "Список инженеров пуст. Добавьте инженеров в настройках.",
            reply_markup=main_menu()
        )
        return

    bot.send_message(user, "Начинаем заполнение…", reply_markup=restart_keyboard())

    kb = InlineKeyboardMarkup()
    for eng in engineers:
        kb.add(InlineKeyboardButton(eng, callback_data=f"eng:{eng}"))

    bot.send_message(user, "Выберите инженера:", reply_markup=kb)


@bot.message_handler(func=lambda m: m.text == "Начать сначала")
def restart(message):
    user = message.chat.id
    user_data[user] = {}

    bot.send_message(user, "Начинаем заново", reply_markup=restart_keyboard())

    kb = InlineKeyboardMarkup()
    for eng in engineers:
        kb.add(InlineKeyboardButton(eng, callback_data=f"eng:{eng}"))

    bot.send_message(user, "Выберите инженера:", reply_markup=kb)
# =======================
# ВЫБОР ИНЖЕНЕРА
# =======================

@bot.callback_query_handler(func=lambda call: call.data.startswith("eng:"))
def choose_engineer(call):
    user = call.message.chat.id
    eng = call.data.split(":", 1)[1]
    user_data[user] = {"engineer": eng}

    bot.delete_message(user, call.message.message_id)

    kb = InlineKeyboardMarkup()
    for loc in locations:
        kb.add(InlineKeyboardButton(loc, callback_data=f"loc:{loc}"))
    kb.add(InlineKeyboardButton("➕ Другая локация", callback_data="loc:custom"))

    bot.send_message(user, "Выберите локацию:", reply_markup=kb)


# =======================
# ВЫБОР ЛОКАЦИИ
# =======================

@bot.callback_query_handler(func=lambda call: call.data.startswith("loc:"))
def choose_location(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    loc = call.data.split(":", 1)[1]

    if loc == "custom":
        bot.send_message(user, "Введите название локации:")
        bot.register_next_step_handler(call.message, save_custom_location)
        return

    user_data[user]["location"] = loc
    ask_time_start(user)


def save_custom_location(message):
    user = message.chat.id
    loc = message.text.strip()

    user_data[user]["location"] = loc
    ask_time_start(user)


# =======================
# НОВАЯ ЛОГИКА ВВОДА ДАТЫ И ВРЕМЕНИ
# =======================

def ask_time_start(user):
    today = datetime.datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y")
    user_data[user]["date_work"] = today

    bot.send_message(user, f"Дата начала работ: *{today}*\nВведите ВРЕМЯ начала (ЧЧ:ММ):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(user, save_time_start)


def save_time_start(message):
    user = message.chat.id
    t = message.text.strip()

    try:
        datetime.datetime.strptime(t, "%H:%M")
    except:
        bot.send_message(user, "Неверный формат! Введите время как ЧЧ:ММ")
        return bot.register_next_step_handler(message, save_time_start)

    user_data[user]["time_work"] = t

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("Да", callback_data="change_start_date"),
        InlineKeyboardButton("Нет", callback_data="keep_start_date")
    )

    bot.send_message(user, "Хотите изменить дату начала?", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data in ["change_start_date", "keep_start_date"])
def process_start_date_change(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    if call.data == "keep_start_date":
        return ask_time_end(user)

    bot.send_message(user, "Введите новую дату начала (ДД.ММ.ГГГГ):")
    bot.register_next_step_handler(call.message, save_new_start_date)


def save_new_start_date(message):
    user = message.chat.id
    date_text = message.text.strip()

    try:
        dt = datetime.datetime.strptime(date_text, "%d.%m.%Y")
        user_data[user]["date_work"] = dt.strftime("%d.%m.%Y")
    except:
        bot.send_message(user, "Неверный формат! Введите дату как ДД.ММ.ГГГГ")
        return bot.register_next_step_handler(message, save_new_start_date)

    ask_time_end(user)


# =======================
# ВРЕМЯ ОКОНЧАНИЯ
# =======================

def ask_time_end(user):
    bot.send_message(user, "Введите ВРЕМЯ окончания работ (ЧЧ:ММ):")
    bot.register_next_step_handler_by_chat_id(user, save_time_end)
def save_time_end(message):
    user = message.chat.id
    t = message.text.strip()

    try:
        datetime.datetime.strptime(t, "%H:%M")
    except:
        bot.send_message(user, "Неверный формат! Введите время как ЧЧ:ММ")
        return bot.register_next_step_handler(message, save_time_end)

    user_data[user]["end_time"] = t
    user_data[user]["end_date"] = user_data[user]["date_work"]

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("Да", callback_data="change_end_date"),
        InlineKeyboardButton("Нет", callback_data="keep_end_date"),
    )

    bot.send_message(user, "Хотите изменить дату окончания?", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data in ["change_end_date", "keep_end_date"])
def process_end_date_change(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    if call.data == "keep_end_date":
        return show_job_selection(user)

    bot.send_message(user, "Введите новую дату окончания (ДД.ММ.ГГГГ):")
    bot.register_next_step_handler(call.message, save_new_end_date)


def save_new_end_date(message):
    user = message.chat.id
    date_text = message.text.strip()

    try:
        dt = datetime.datetime.strptime(date_text, "%d.%m.%Y")
        user_data[user]["end_date"] = dt.strftime("%d.%m.%Y")
    except:
        bot.send_message(user, "Неверный формат! Введите как ДД.ММ.ГГГГ")
        return bot.register_next_step_handler(message, save_new_end_date)

    show_job_selection(user)


# =======================
# ВЫБОР ВИДА РАБОТЫ
# =======================

def show_job_selection(user):
    kb = InlineKeyboardMarkup()
    for i, name in enumerate(work_names):
        kb.add(InlineKeyboardButton(name, callback_data=f"job:{i}"))
    kb.add(InlineKeyboardButton("➕ Другой вид работы", callback_data="job_custom"))

    bot.send_message(user, "Выберите вид работы:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("job:"))
def choose_job(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    index = int(call.data.split(":", 1)[1])
    name = work_names[index]

    user_data[user]["job_name"] = name
    user_data[user]["job_point"] = work_point.get(name, "")

    bot.send_message(user, "Введите ответственного:")
    bot.register_next_step_handler(call.message, ask_order_number)


@bot.callback_query_handler(func=lambda c: c.data == "job_custom")
def custom_job(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)
    bot.send_message(user, "Введите название вида работы:")
    bot.register_next_step_handler(call.message, save_custom_job_name)


def save_custom_job_name(message):
    user = message.chat.id
    name = message.text.strip()

    user_data[user]["job_name"] = name

    bot.send_message(user, "Введите работы по п.№ (или '-' если нет):")
    bot.register_next_step_handler(message, save_custom_job_point)


def save_custom_job_point(message):
    user = message.chat.id
    user_data[user]["job_point"] = message.text.strip()

    bot.send_message(user, "Введите ответственного:")
    bot.register_next_step_handler(message, ask_order_number)


# =======================
# ОТВЕТСТВЕННЫЙ + ЗАКАЗ-НАРЯД
# =======================

def ask_order_number(message):
    user = message.chat.id
    user_data[user]["master"] = message.text.strip()

    bot.send_message(user, "Введите номер заказ-наряда:")
    bot.register_next_step_handler(message, save_order_number)


def save_order_number(message):
    user = message.chat.id
    user_data[user]["order_number"] = message.text.strip()

    save_to_sheet(user)


# =======================
# СОХРАНЕНИЕ + ОТПРАВКА В КАНАЛ
# =======================

def save_to_sheet(user):
    row = [
        user_data[user].get("date_work"),
        user_data[user].get("time_work"),
        user_data[user].get("end_date"),
        user_data[user].get("end_time"),
        user_data[user].get("engineer"),
        user_data[user].get("location"),
        user_data[user].get("job_name"),
        user_data[user].get("job_point"),
        user_data[user].get("master"),
        user_data[user].get("order_number"),
    ]

    ops_sheet.append_row(row)

    # сообщение пользователю
    bot.send_message(user, "Запись сохранена ✔️", reply_markup=main_menu())

    text = (
        "✔ *Новая запись добавлена*\n\n"
        f"Инженер: {row[4]}\n"
        f"Локация: {row[5]}\n"
        f"Вид работы: {row[6]}\n"
        f"Работы по п.№: {row[7]}\n"
        f"Начало: {row[0]} {row[1]}\n"
        f"Окончание: {row[2]} {row[3]}\n"
        f"Ответственный: {row[8]}\n"
        f"Заказ-наряд: {row[9]}"
    )

    # отправка в канал
    try:
        bot.send_message(REPORT_CHANNEL_ID, text, parse_mode="Markdown")
    except:
        bot.send_message(user, "⚠ Не удалось отправить сообщение в канал.")

    # отправка пользователю
    bot.send_message(user, text, parse_mode="Markdown")


# =======================
# ПРОСМОТР ТАБЛИЦЫ
# =======================

@bot.message_handler(func=lambda m: m.text == "Посмотреть таблицу")
def send_pdf(message):
    bot.send_message(message.chat.id, "⏳ Формирую PDF...")

    pdf = download_sheet_pdf()
    if not pdf:
        return bot.send_message(message.chat.id, "Ошибка PDF.")

    bot.send_document(message.chat.id, ("table.pdf", pdf, "application/pdf"))


@bot.message_handler(func=lambda m: m.text == "Открыть таблицу")
def open_table(message):
    bot.send_message(message.chat.id, f"https://docs.google.com/spreadsheets/d/{TABLE_ID}/edit")


# =======================
# НАСТРОЙКИ (АДМИН)
# =======================

@bot.message_handler(func=lambda m: m.text == "Настройки")
def settings(message):
    if not is_admin(message.chat.id):
        return bot.send_message(message.chat.id, "Нет прав.")

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Инженеры", callback_data="set_eng"))
    kb.add(InlineKeyboardButton("Локации", callback_data="set_loc"))
    kb.add(InlineKeyboardButton("Виды работ", callback_data="set_work"))
    bot.send_message(message.chat.id, "Настройки:", reply_markup=kb)

# (ADMIN блоки остаются без изменений — чтобы не раздувать общий файл)

# =======================
# ЗАПУСК
# =======================

bot.polling(none_stop=True)





