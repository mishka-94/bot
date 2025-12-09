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
TOKEN = "8353686586:AAGP8rO1wKkLGv8pIzQwLsk5ziUH_BmsUD4"  # <-- СЮДА ВСТАВЬ СВОЙ ТОКЕН
TABLE_ID = "1R9RVzxYrR8ClcQpogUWAdnqpd_2UthwEcLgm2w8IL14"
ADMIN_IDS = [8136311010]  # твой Telegram ID
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

bot = telebot.TeleBot(TOKEN)

# =======================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# =======================
engineers = []
locations = []
work_names = []
work_point = {}       # {название_работы: "работы по п.№"}
user_data = {}        # временные данные диалогов


# =======================
# НИЖНЕЕ МЕНЮ (главное)
# =======================
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Старт"))
    kb.add(KeyboardButton("Посмотреть таблицу"))
    kb.add(KeyboardButton("Открыть таблицу"))
    kb.add(KeyboardButton("Настройки"))
    return kb


# Меню, которое показывается во время заполнения
def restart_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Начать сначала"))
    return kb


def is_admin(chat_id: int) -> bool:
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

# Основной лист с записями
ops_sheet = book.worksheet("Список")
# Листы со справочниками
eng_sheet = book.worksheet("Engineers")
loc_sheet = book.worksheet("Locations")
works_sheet = book.worksheet("Works")


# =======================
# ДИНАМИЧЕСКИЕ СПИСКИ
# =======================
def reload_data():
    global engineers, locations, work_names, work_point

    # Инженеры
    eng_values = eng_sheet.get_all_values()
    engineers = []
    if len(eng_values) > 1:
        for row in eng_values[1:]:
            if row and row[0].strip():
                engineers.append(row[0].strip())

    # Локации
    loc_values = loc_sheet.get_all_values()
    locations = []
    if len(loc_values) > 1:
        for row in loc_values[1:]:
            if row and row[0].strip():
                locations.append(row[0].strip())

    # Виды работ + "работы по п.№"
    work_values = works_sheet.get_all_values()
    work_names_local = []
    work_point_local = {}

    if len(work_values) > 1:
        for row in work_values[1:]:
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            point = row[1].strip() if len(row) > 1 else ""
            work_names_local.append(name)
            work_point_local[name] = point

    globals()["work_names"] = work_names_local
    globals()["work_point"] = work_point_local


reload_data()


# =======================
# PDF ЭКСПОРТ GOOGLE SHEETS
# =======================
def download_sheet_pdf():
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
        creds = service_account.Credentials.from_service_account_file(
            "credentials.json",
            scopes=SCOPES
        )
        authed_session = AuthorizedSession(creds)

        url = f"https://docs.google.com/spreadsheets/d/{TABLE_ID}/export?format=pdf"

        response = authed_session.get(url)

        if response.status_code != 200:
            print("PDF ERROR:", response.text)
            return None

        pdf_bytes = io.BytesIO(response.content)
        pdf_bytes.seek(0)
        return pdf_bytes

    except Exception as e:
        print("PDF ERROR:", e)
        return None
# =======================
# ВСПОМОГАТЕЛЬНЫЕ
# =======================
def make_keyboard(options, prefix):
    kb = InlineKeyboardMarkup()
    for opt in options:
        kb.add(InlineKeyboardButton(opt, callback_data=f"{prefix}:{opt}"))
    return kb


# =======================
# ОБРАБОТЧИКИ МЕНЮ
# =======================

# --- СТАРТ РАБОТЫ ---
@bot.message_handler(commands=["start"])
@bot.message_handler(func=lambda m: m.text == "Старт")
def start(message):
    user = message.chat.id
    user_data[user] = {}

    if not engineers:
        bot.send_message(
            user,
            "Список инженеров пуст. Добавьте инженеров через 'Настройки' (доступно админу).",
            reply_markup=main_menu(),
        )
        return

    # Скрываем главное меню, показываем только кнопку "Начать сначала"
    bot.send_message(user, "Начинаем заполнение…", reply_markup=restart_keyboard())

    # Формируем inline-кнопки инженеров
    kb = InlineKeyboardMarkup()
    for eng in engineers:
        kb.add(InlineKeyboardButton(eng, callback_data=f"eng:{eng}"))

    bot.send_message(user, "Выберите инженера:", reply_markup=kb)


# --- КНОПКА "НАЧАТЬ СНАЧАЛА" ---
@bot.message_handler(func=lambda m: m.text == "Начать сначала")
def restart(message):
    user = message.chat.id
    user_data[user] = {}  # очищаем данные

    bot.send_message(user, "Сценарий начат заново", reply_markup=restart_keyboard())

    # снова выбор инженера
    kb = InlineKeyboardMarkup()
    for eng in engineers:
        kb.add(InlineKeyboardButton(eng, callback_data=f"eng:{eng}"))

    bot.send_message(user, "Выберите инженера:", reply_markup=kb)


# =======================
# ОСНОВНОЙ СЦЕНАРИЙ
# =======================

# === Выбор инженера ===
@bot.callback_query_handler(func=lambda call: call.data.startswith("eng:"))
def choose_engineer(call):
    user = call.message.chat.id
    eng = call.data.split(":", 1)[1]

    if user not in user_data:
        user_data[user] = {}

    user_data[user]["engineer"] = eng

    # удаляем сообщение с кнопками инженеров
    bot.delete_message(user, call.message.message_id)

    # создаём inline-кнопки локаций
    kb = InlineKeyboardMarkup()
    for loc in locations:
        kb.add(InlineKeyboardButton(loc, callback_data=f"loc:{loc}"))
    kb.add(InlineKeyboardButton("➕ Другая локация", callback_data="loc:custom"))

    bot.send_message(user, "Выберите локацию:", reply_markup=kb)


# === Выбор локации ===
@bot.callback_query_handler(func=lambda call: call.data.startswith("loc:"))
def choose_location(call):
    user = call.message.chat.id

    if user not in user_data:
        user_data[user] = {}

    # Удаляем сообщение с кнопками локаций
    bot.delete_message(user, call.message.message_id)

    loc_code = call.data.split(":", 1)[1]

    # "Другая локация"
    if loc_code == "custom":
        bot.send_message(user, "Введите название новой локации:")
        bot.register_next_step_handler(call.message, ask_add_location)
        return

    # Обычная локация
    user_data[user]["location"] = loc_code

    # Переход к выбору даты и времени начала
    ask_datetime(user)


def ask_add_location(message):
    """Пользователь вводит свою локацию, но она НЕ сохраняется в таблицу."""
    user = message.chat.id
    name = message.text.strip()

    if not name:
        bot.send_message(user, "Пустое название. Попробуйте ещё раз:")
        bot.register_next_step_handler(message, ask_add_location)
        return

    # Локация используется только один раз
    user_data[user]["location"] = name

    bot.send_message(user, f"Локация '{name}' установлена (одноразовое значение).")

    # Переход к дате и времени
    ask_datetime(user)


# === Выбор даты и времени НАЧАЛА ===
def ask_datetime(user):
    now = datetime.datetime.now(MOSCOW_TZ)
    default_dt = now.strftime("%d.%m.%Y %H:%M")

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("Использовать текущее", callback_data="datetime_now"),
        InlineKeyboardButton("Изменить", callback_data="datetime_change")
    )
    bot.send_message(
        user,
        f"Дата и время НАЧАЛА работ: {default_dt}\nВыберите вариант:",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data in ["datetime_now", "datetime_change"])
def process_datetime_choice(call):
    user = call.message.chat.id

    # Удаляем сообщение со старыми кнопками
    bot.delete_message(user, call.message.message_id)

    if call.data == "datetime_now":
        now = datetime.datetime.now(MOSCOW_TZ)
        user_data[user]["date_work"] = now.strftime("%d.%m.%Y")
        user_data[user]["time_work"] = now.strftime("%H:%M")
        ask_end_time(user)
        return

    if call.data == "datetime_change":
        bot.send_message(user, "Введите дату и время НАЧАЛА в формате:\nДД.ММ.ГГГГ ЧЧ:ММ")
        bot.register_next_step_handler(call.message, save_custom_datetime)
        return


def save_custom_datetime(message):
    user = message.chat.id
    text = message.text.strip()

    try:
        dt = datetime.datetime.strptime(text, "%d.%m.%Y %H:%M")
    except:
        bot.send_message(user, "Неверный формат! Введите так: 27.01.2025 09:30")
        bot.register_next_step_handler(message, save_custom_datetime)
        return

    user_data[user]["date_work"] = dt.strftime("%d.%m.%Y")
    user_data[user]["time_work"] = dt.strftime("%H:%M")

    ask_end_time(user)


# === ВЫБОР ВРЕМЕНИ ОКОНЧАНИЯ ===
def ask_end_time(user):
    start_date = user_data[user]["date_work"]

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("Ввести только время окончания", callback_data="end_time_only"),
        InlineKeyboardButton("Изменить дату и время", callback_data="end_change")
    )

    bot.send_message(
        user,
        f"Дата ОКОНЧАНИЯ работ (по умолчанию): {start_date}\n"
        f"Выберите, как ввести время окончания:",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda call: call.data in ["end_time_only", "end_change"])
def process_end_time_choice(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    if call.data == "end_time_only":
        bot.send_message(user, "Введите ВРЕМЯ окончания работ (например: 18:45):")
        bot.register_next_step_handler(call.message, save_end_time_only)
        return

    if call.data == "end_change":
        bot.send_message(user, "Введите дату и время ОКОНЧАНИЯ в формате:\nДД.ММ.ГГГГ ЧЧ:ММ")
        bot.register_next_step_handler(call.message, save_end_datetime)
        return


def save_end_time_only(message):
    user = message.chat.id
    time_text = message.text.strip()
    start_date = user_data[user]["date_work"]

    try:
        dt = datetime.datetime.strptime(time_text, "%H:%M")
        user_data[user]["end_date"] = start_date
        user_data[user]["end_time"] = dt.strftime("%H:%M")
    except:
        bot.send_message(user, "Неверный формат! Введите время как 18:30")
        bot.register_next_step_handler(message, save_end_time_only)
        return

    # Переход к выбору вида работы
    show_job_selection(message)


def save_end_datetime(message):
    user = message.chat.id
    text = message.text.strip()

    try:
        dt = datetime.datetime.strptime(text, "%d.%m.%Y %H:%M")
        user_data[user]["end_date"] = dt.strftime("%d.%m.%Y")
        user_data[user]["end_time"] = dt.strftime("%H:%M")
    except:
        bot.send_message(user, "Ошибка! Введите так: 27.01.2025 19:15")
        bot.register_next_step_handler(message, save_end_datetime)
        return

    # Переход к выбору вида работы
    show_job_selection(message)


# === Выбор вида работы ===
def show_job_selection(source):
    user = source.chat.id if hasattr(source, "chat") else source.message.chat.id

    kb = InlineKeyboardMarkup()
    for i, name in enumerate(work_names):
        kb.add(InlineKeyboardButton(name, callback_data=f"job:{i}"))
    kb.add(InlineKeyboardButton("➕ Другой вид работы", callback_data="job_custom"))

    bot.send_message(
        user,
        "Выберите вид работы:",
        reply_markup=kb
    )
@bot.callback_query_handler(func=lambda call: call.data.startswith("job:"))
def choose_job(call):
    global work_point, work_names

    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    index = int(call.data.split(":", 1)[1])
    job_name = work_names[index]
    job_point_value = work_point.get(job_name, "")

    user_data[user]["job_name"] = job_name
    user_data[user]["job_point"] = job_point_value

    bot.send_message(user, "Введите ответственного:")
    bot.register_next_step_handler(call.message, ask_order_number)


@bot.callback_query_handler(func=lambda call: call.data == "job_custom")
def choose_custom_job(call):
    user = call.message.chat.id
    bot.delete_message(user, call.message.message_id)

    bot.send_message(user, "Введите ВИД работы:")
    bot.register_next_step_handler(call.message, save_custom_job_name)


def save_custom_job_name(message):
    user = message.chat.id
    name = message.text.strip()
    if not name:
        bot.send_message(user, "Пустое название. Введите вид работы ещё раз:")
        bot.register_next_step_handler(message, save_custom_job_name)
        return

    user_data[user]["job_name"] = name

    bot.send_message(user, "Введите 'работы по п.№' для этого вида работы (или '-' если нет):")
    bot.register_next_step_handler(message, save_custom_job_point)


def save_custom_job_point(message):
    user = message.chat.id
    point = message.text.strip()
    user_data[user]["job_point"] = point

    bot.send_message(user, "Введите ответственного:")
    bot.register_next_step_handler(message, ask_order_number)


# === Ответственный + НОМЕР ЗАКАЗ-НАРЯДА ===
def ask_order_number(message):
    user = message.chat.id
    user_data[user]["master"] = message.text.strip()

    bot.send_message(user, "Введите номер заказ-наряда:")
    bot.register_next_step_handler(message, save_order_number)


def save_order_number(message):
    user = message.chat.id
    user_data[user]["order_number"] = message.text.strip()

    get_master(message)


# === Сохранение в таблицу ===
def get_master(message):
    user = message.chat.id

    row = [
        user_data[user].get("date_work", ""),     # Дата начала
        user_data[user].get("time_work", ""),     # Время начала
        user_data[user].get("end_date", ""),      # Дата окончания
        user_data[user].get("end_time", ""),      # Время окончания
        user_data[user].get("engineer", ""),
        user_data[user].get("location", ""),
        user_data[user].get("job_name", ""),
        user_data[user].get("job_point", ""),     # работы по п.№
        user_data[user].get("master", ""),        # ответственный
        user_data[user].get("order_number", ""),  # номер заказ-наряда
    ]

    ops_sheet.append_row(row)

    # Сообщение пользователю + возврат главного меню
    bot.send_message(
        user,
        "Запись сохранена! ✔️",
        reply_markup=main_menu()
    )

    # Подробное сообщение
    bot.send_message(
        user,
        f"""
Инженер: {user_data[user].get('engineer', '')}
Локация: {user_data[user].get('location', '')}
Вид работы: {user_data[user].get('job_name', '')}
Работы по п.№: {user_data[user].get('job_point', '')}
Начало: {user_data[user].get('date_work', '')} {user_data[user].get('time_work', '')}
Окончание: {user_data[user].get('end_date', '')} {user_data[user].get('end_time', '')}
Ответственный: {user_data[user].get('master', '')}
Заказ-наряд: {user_data[user].get('order_number', '')}
"""
    )


# =======================
# КНОПКИ МЕНЮ: ТАБЛИЦА / ССЫЛКА
# =======================
@bot.message_handler(func=lambda m: m.text == "Посмотреть таблицу")
def send_pdf(message):
    bot.send_message(message.chat.id, "⏳ Формирую PDF...")

    pdf = download_sheet_pdf()

    if not pdf:
        bot.send_message(
            message.chat.id,
            "❗ Ошибка создания PDF. Проверьте доступ сервисного аккаунта к таблице.",
        )
        return

    bot.send_document(
        message.chat.id,
        ("table.pdf", pdf, "application/pdf"),
    )
@bot.message_handler(func=lambda m: m.text == "Открыть таблицу")
def open_table(message):
    bot.send_message(
        message.chat.id,
        f"🔗 Таблица:\nhttps://docs.google.com/spreadsheets/d/{TABLE_ID}/edit",
    )


# =======================
# НАСТРОЙКИ (ТОЛЬКО ДЛЯ АДМИНА)
# =======================
@bot.message_handler(func=lambda m: m.text == "Настройки")
def settings_root(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "Доступ к настройкам только у администратора.")
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("👷 Инженеры", callback_data="set_eng"))
    kb.add(InlineKeyboardButton("📍 Локации", callback_data="set_loc"))
    kb.add(InlineKeyboardButton("🔧 Виды работ", callback_data="set_work"))
    bot.send_message(message.chat.id, "⚙ Что хотите настроить?", reply_markup=kb)


# ---- НАСТРОЙКИ ИНЖЕНЕРОВ ----
@bot.callback_query_handler(func=lambda c: c.data == "set_eng")
def settings_engineers(call):
    if not is_admin(call.message.chat.id):
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Добавить инженера", callback_data="add_eng"))
    bot.edit_message_text(
        "Настройки инженеров:", call.message.chat.id, call.message.message_id, reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data == "add_eng")
def add_engineer_prompt(call):
    if not is_admin(call.message.chat.id):
        return
    bot.send_message(call.message.chat.id, "Введите ФИО нового инженера:")
    bot.register_next_step_handler(call.message, add_engineer_save)


def add_engineer_save(message):
    if not is_admin(message.chat.id):
        return
    name = message.text.strip()
    if not name:
        bot.send_message(message.chat.id, "Пустое имя. Отмена.")
        return
    eng_sheet.append_row([name])
    reload_data()
    bot.send_message(message.chat.id, f"Инженер '{name}' добавлен.")


# ---- НАСТРОЙКИ ЛОКАЦИЙ ----
@bot.callback_query_handler(func=lambda c: c.data == "set_loc")
def settings_locations(call):
    if not is_admin(call.message.chat.id):
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Добавить локацию", callback_data="add_loc"))
    bot.edit_message_text(
        "Настройки локаций:", call.message.chat.id, call.message.message_id, reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data == "add_loc")
def add_location_prompt(call):
    if not is_admin(call.message.chat.id):
        return
    bot.send_message(call.message.chat.id, "Введите название новой локации:")
    bot.register_next_step_handler(call.message, add_location_save)


def add_location_save(message):
    if not is_admin(message.chat.id):
        return
    name = message.text.strip()
    if not name:
        bot.send_message(message.chat.id, "Пустое название. Отмена.")
        return
    loc_sheet.append_row([name])
    reload_data()
    bot.send_message(message.chat.id, f"Локация '{name}' добавлена.")


# ---- НАСТРОЙКИ ВИДОВ РАБОТ ----
@bot.callback_query_handler(func=lambda c: c.data == "set_work")
def settings_works(call):
    if not is_admin(call.message.chat.id):
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Добавить вид работы", callback_data="add_work"))
    bot.edit_message_text(
        "Настройки видов работ:", call.message.chat.id, call.message.message_id, reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data == "add_work")
def add_work_prompt(call):
    if not is_admin(call.message.chat.id):
        return
    bot.send_message(call.message.chat.id, "Введите название вида работы:")
    bot.register_next_step_handler(call.message, add_work_name_save)


def add_work_name_save(message):
    if not is_admin(message.chat.id):
     return
    user = message.chat.id
    name = message.text.strip()
    if not name:
        bot.send_message(user, "Пустое название. Отмена.")
        return
    if user not in user_data:
        user_data[user] = {}
    user_data[user]["new_work_name"] = name
    bot.send_message(user, "Введите 'работы по п.№' для этого вида работы:")
    bot.register_next_step_handler(message, add_work_grade_save)


def add_work_grade_save(message):
    if not is_admin(message.chat.id):
        return
    user = message.chat.id
    point = message.text.strip()
    name = user_data.get(user, {}).get("new_work_name")
    if not name:
        bot.send_message(user, "Не удалось найти название работы. Начните заново.")
        return
    works_sheet.append_row([name, point])
    reload_data()
    bot.send_message(
        user,
        f"Вид работы '{name}' с работами по п.№ '{point}' добавлен.",
    )
    user_data[user].pop("new_work_name", None)


# =======================
# СЛУЖЕБНО: /id
# =======================
@bot.message_handler(commands=["id"])
def get_id(message):
    bot.send_message(message.chat.id, f"Ваш Telegram ID: {message.chat.id}")


# =======================
# апдате
# =======================
@bot.message_handler(commands=["update"])
def update_bot(message):
    if message.chat.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ У вас нет прав.")
        return
    
    bot.send_message(message.chat.id, "🔄 Обновляю бота с GitHub...")

    try:
        # Пуллим изменения
        pull_output = subprocess.check_output(
            ["git", "-C", "/opt/bot", "pull"],
            stderr=subprocess.STDOUT
        ).decode()

        bot.send_message(message.chat.id, f"📥 Git Pull:\n```\n{pull_output}\n```", parse_mode="Markdown")

        # Перезапуск systemd
        subprocess.call(["systemctl", "restart", "bot"])

        bot.send_message(message.chat.id, "✅ Бот обновлён и перезапущен.")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка обновления:\n{e}")


@bot.message_handler(commands=["status"])
def bot_status(message):
    if message.chat.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ У вас нет прав.")
        return

    try:
        # uptime
        uptime = subprocess.check_output("uptime -p", shell=True).decode()

        # systemd service status
        service = subprocess.check_output(
            ["systemctl", "is-active", "bot"]
        ).decode().strip()

        # git commit
        commit = subprocess.check_output(
            ["git", "-C", "/opt/bot", "rev-parse", "--short", "HEAD"]
        ).decode().strip()

        bot.send_message(
            message.chat.id,
            f"📊 *Статус сервера:*\n"
            f"• Uptime: `{uptime}`\n"
            f"• Сервис: `{service}`\n"
            f"• Git commit: `{commit}`\n",
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка статуса:\n{e}")


# =======================
# ЗАПУСК
# =======================

bot.polling(none_stop=True)



