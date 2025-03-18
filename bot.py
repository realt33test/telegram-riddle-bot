import telebot
import os
from telebot import types
import sqlite3
from datetime import datetime, timedelta
import logging
import threading
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# Подключение к базе данных SQLite
conn = sqlite3.connect('riddle_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    members_count INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS riddles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    riddle_text TEXT,
                    answer TEXT,
                    prize TEXT,
                    time_limit INTEGER,
                    message_id INTEGER,
                    active INTEGER DEFAULT 1,
                    end_time INTEGER,
                    hint TEXT,
                    hint_delay INTEGER,
                    start_time INTEGER,
                    photo_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS scores (
                    user_id INTEGER,
                    chat_id INTEGER,
                    points INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id))''')

# Добавление столбцов, если они отсутствуют
try:
    cursor.execute("ALTER TABLE riddles ADD COLUMN end_time INTEGER")
    logger.info("Столбец end_time добавлен в таблицу riddles")
except sqlite3.OperationalError:
    logger.info("Столбец end_time уже существует")
try:
    cursor.execute("ALTER TABLE riddles ADD COLUMN hint TEXT")
    logger.info("Столбец hint добавлен в таблицу riddles")
except sqlite3.OperationalError:
    logger.info("Столбец hint уже существует")
try:
    cursor.execute("ALTER TABLE riddles ADD COLUMN hint_delay INTEGER")
    logger.info("Столбец hint_delay добавлен в таблицу riddles")
except sqlite3.OperationalError:
    logger.info("Столбец hint_delay уже существует")
try:
    cursor.execute("ALTER TABLE riddles ADD COLUMN start_time INTEGER")
    logger.info("Столбец start_time добавлен в таблицу riddles")
except sqlite3.OperationalError:
    logger.info("Столбец start_time уже существует")
try:
    cursor.execute("ALTER TABLE riddles ADD COLUMN photo_id TEXT")
    logger.info("Столбец photo_id добавлен в таблицу riddles")
except sqlite3.OperationalError:
    logger.info("Столбец photo_id уже существует")

conn.commit()

# Обновление данных о чатах
def update_data():
    logger.info("Обновление данных о чатах")
    cursor.execute("SELECT chat_id FROM chats")
    chats = cursor.fetchall()
    for (chat_id,) in chats:
        try:
            chat = bot.get_chat(chat_id)
            members_count = bot.get_chat_member_count(chat_id)
            cursor.execute("UPDATE chats SET title = ?, members_count = ? WHERE chat_id = ?",
                           (chat.title, members_count, chat_id))
            logger.info(f"Обновлены данные чата {chat_id}: {chat.title}, {members_count} участников, тип: {chat.type}")
        except Exception as e:
            logger.error(f"Чат {chat_id} недоступен: {e}. Удаляем из базы.")
            cursor.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            cursor.execute("DELETE FROM riddles WHERE chat_id = ?", (chat_id,))
        conn.commit()

# Главное меню
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("➕ Добавить в чат", "📜 Список чатов")
    markup.add("📊 Статистика бота", "ℹ️ Как пользоваться")
    bot.send_message(user_id, "✨ *Добро пожаловать!* ✨\n\nВыбери действие ниже 👇", reply_markup=markup)

# Проверка администратора
def is_admin(user_id, chat_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки админа для user_id {user_id} в чате {chat_id}: {e}")
        return False

# Проверка, состоит ли пользователь в чате
def is_member(user_id, chat_id):
    try:
        bot.get_chat_member(chat_id, user_id)
        return True
    except Exception as e:
        logger.info(f"Пользователь {user_id} не состоит в чате {chat_id}: {e}")
        return False

# Таймер для загадки с автоматической подсказкой
def riddle_timer(riddle_id, chat_id, message_id, time_limit, riddle_text, prize, hint, hint_delay):
    MAX_TIME_LIMIT = 1440
    time_limit = int(time_limit) if time_limit is not None else None
    if time_limit and time_limit > MAX_TIME_LIMIT:
        time_limit = MAX_TIME_LIMIT
        logger.info(f"Таймер для загадки {riddle_id} ограничен {MAX_TIME_LIMIT} минутами")

    start_time = int(time.time())
    end_time = start_time + time_limit * 60 if time_limit else None
    cursor.execute("UPDATE riddles SET end_time = ? WHERE id = ?", (end_time, riddle_id))
    conn.commit()

    hint_sent = False
    hint_time = None
    if hint:
        if time_limit:
            hint_time = start_time + int(time_limit * 60 * 0.8)  # 80% времени в секундах
        elif hint_delay is not None:
            hint_time = start_time + hint_delay * 60  # Задержка в секундах

    while True:
        cursor.execute("SELECT active FROM riddles WHERE id = ?", (riddle_id,))
        active = cursor.fetchone()
        if not active or active[0] == 0:
            logger.info(f"Таймер для загадки {riddle_id} остановлен: загадка уже неактивна")
            break

        current_time = int(time.time())

        # Отправка подсказки
        if hint and not hint_sent and hint_time and current_time >= hint_time:
            try:
                bot.send_message(chat_id, f"💡 *ПОДСКАЗКА!!* 💡\n\n{hint}")
                logger.info(f"Подсказка для загадки {riddle_id} отправлена в чат {chat_id}")
                hint_sent = True
            except Exception as e:
                logger.error(f"Ошибка отправки подсказки для загадки {riddle_id}: {e}")

        # Проверка окончания времени
        if time_limit:
            remaining = end_time - current_time
            if remaining <= 0:
                try:
                    cursor.execute("UPDATE riddles SET active = 0 WHERE id = ?", (riddle_id,))
                    conn.commit()
                    bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                                        text=f"⏰ *Время вышло!* ⏰\n\n{riddle_text}\n\n*К сожалению, никто не угадал...* 😔\nЗагадка завершена.", 
                                        parse_mode="Markdown")
                    logger.info(f"Загадка {riddle_id} в чате {chat_id} завершена по таймеру")
                    threading.Timer(1800, lambda: bot.delete_message(chat_id, message_id)).start()
                except Exception as e:
                    logger.error(f"Ошибка завершения загадки {riddle_id}: {e}")
                break
            else:
                minutes, seconds = divmod(remaining, 60)
                try:
                    bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                                        text=f"🚨 *ЗАГАДКА!* 🚨\n\n{riddle_text}\n\n🎁 *ПРИЗ:*\n{prize}\n\n⏰ *Осталось:* {minutes} мин {seconds} сек\n\n💬 *Как ответить?* Реплай на это сообщение своим ответом!",
                                        parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Ошибка обновления таймера для загадки {riddle_id}: {e}")
                    if "message to edit not found" in str(e):
                        logger.info(f"Сообщение {message_id} не найдено, остановка таймера для загадки {riddle_id}")
                        break
                sleep_time = 60 if minutes > 60 else 5
                time.sleep(sleep_time)
        else:
            time.sleep(5)  # Если нет таймера, проверяем каждые 5 секунд для подсказки

# Обработчики команд
@bot.message_handler(commands=['start'], chat_types=['private'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    logger.info(f"Новый пользователь: {user_id} (@{username})")
    bot.send_message(user_id, "👋 *Привет!* 👋\n\nЯ бот-загадочник! 🎉\nДобавь меня в чат, и давай играть! 🚀\n\n*P.S.* Дай мне права администратора, чтобы всё работало! 😉")
    main_menu(user_id)

@bot.message_handler(commands=['zagadka'], chat_types=['group', 'supergroup'])
def zagadka_command(message):
    user_id = message.from_user.id
    bot.send_message(message.chat.id, "✨ *Хочешь загадку?* ✨\n\nПерейди в ЛС бота, чтобы её создать! 👇")
    bot.send_message(user_id, "👋 *Привет!* 👋\n\nДавай создадим крутую загадку! 🎲\nВыбери действие ниже 👇", reply_markup=main_menu(user_id))

@bot.message_handler(commands=['top_all'], chat_types=['private'])
def top_all(message):
    user_id = message.from_user.id
    cursor.execute("SELECT user_id, SUM(points) as total_points FROM scores GROUP BY user_id ORDER BY total_points DESC LIMIT 10")
    top_users = cursor.fetchall()
    if not top_users:
        bot.send_message(user_id, "🏆 *Общий топ отгадчиков* 🏆\n\nПока никто не отгадал ни одной загадки! 😅\nБудь первым! 🚀")
        return
    text = "🏆 *Общий топ отгадчиков* 🏆\n\n"
    for i, (user_id, points) in enumerate(top_users, 1):
        username = cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
        text += f"{i}. @{username} — {points} очков 🌟\n"
    bot.send_message(user_id, text, parse_mode="Markdown")

@bot.message_handler(commands=['riddlekings'], chat_types=['group', 'supergroup'])
def top_chat(message):
    chat_id = message.chat.id
    cursor.execute("SELECT user_id, points FROM scores WHERE chat_id = ? ORDER BY points DESC LIMIT 10", (chat_id,))
    top_users = cursor.fetchall()
    if not top_users:
        bot.send_message(chat_id, f"🏆 *Топ отгадчиков в {bot.get_chat(chat_id).title}* 🏆\n\nПока здесь нет мастеров загадок! 😮\nСтань первым! 💪")
        return
    text = f"🏆 *Топ отгадчиков в {bot.get_chat(chat_id).title}* 🏆\n\n"
    for i, (user_id, points) in enumerate(top_users, 1):
        username = cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
        text += f"{i}. @{username} — {points} очков 🌟\n"
    bot.send_message(chat_id, text, parse_mode="Markdown")

# Обработчик текстовых сообщений в ЛС
@bot.message_handler(content_types=['text'], chat_types=['private'])
def handle_text_private(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    update_data()

    if bot.get_state(user_id, chat_id) is not None:
        if message.text in ["➕ Добавить в чат", "📜 Список чатов", "📊 Статистика бота", "ℹ️ Как пользоваться"]:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Отменить создание", callback_data="cancel"))
            bot.send_message(user_id, "⛔ *Ой-ой!* ⛔\n\nТы сейчас создаёшь загадку! Заверши её или нажми 'Отменить' 👇", reply_markup=markup)
            return

    if message.text == "➕ Добавить в чат":
        logger.info(f"Пользователь {user_id} нажал 'Добавить в чат'")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✨ Добавить в группу", url=f"https://t.me/{bot.get_me().username}?startgroup=true"))
        bot.send_message(user_id, "🎉 *Добавь меня в чат!* 🎉\n\nНажми кнопку ниже и выбери группу! 👇\n*P.S.* Не забудь дать мне права админа! 😉", reply_markup=markup)
    
    elif message.text == "📜 Список чатов":
        logger.info(f"Пользователь {user_id} запросил список> список чатов")
        cursor.execute("SELECT chat_id, title, members_count FROM chats")
        chats = cursor.fetchall()
        if not chats:
            bot.send_message(user_id, "😔 *Пусто!* 😔\n\nБот ещё не добавлен ни в один чат. Добавь меня в группу через '➕ Добавить в чат'! 👇")
        else:
            markup = types.InlineKeyboardMarkup()
            for chat in chats:
                chat_id, title, members_count = chat
                if is_admin(user_id, chat_id):
                    cursor.execute("SELECT COUNT(*) FROM riddles WHERE chat_id = ? AND active = 1", (chat_id,))
                    active_riddles = cursor.fetchone()[0]
                    markup.add(types.InlineKeyboardButton(f"💬 {title}\n👥 {members_count} чел. | 🧩 {active_riddles}", callback_data=f"chat_{chat_id}"))
                else:
                    logger.info(f"Пользователь {user_id} не админ в чате {chat_id}")
            if not markup.keyboard:
                bot.send_message(user_id, "😔 *Упс!* 😔\n\nТы не админ ни в одном чате, где я есть. Добавь меня и дай права! 😉")
            else:
                bot.send_message(user_id, "🌟 *Твои чаты (где ты админ):* 🌟\n\nВыбери чат для загадки 👇", reply_markup=markup)
    
    elif message.text == "📊 Статистика бота":
        logger.info(f"Пользователь {user_id} запросил статистику")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📈 Общая статистика", callback_data="stats_global"))
        markup.add(types.InlineKeyboardButton("👥 Чаты и участники", callback_data="stats_chats_users"))
        bot.send_message(user_id, "📊 *Статистика бота* 📊\n\nВыбери, что посмотреть 👇", reply_markup=markup)
    
    elif message.text == "ℹ️ Как пользоваться":
        logger.info(f"Пользователь {user_id} запросил инструкцию")
        instruction = (
            "✨ *Как пользоваться ботом-загадочником?* ✨\n\n"
            "👇 *Простая инструкция:*\n"
            "  1. *Добавь меня в чат* ➕ Нажми 'Добавить в чат', выбери группу и дай мне права админа.\n"
            "  2. *Создай загадку* 🧩 В ЛС выбери 'Список чатов', затем чат, введи текст, ответ и приз.\n"
            "  3. *Настрой время и подсказку* ⏳ Укажи таймер (или пропусти) и добавь подсказку (по желанию).\n"
            "  4. *Жди отгадок* 🎉 Участники будут отвечать, а ты узнаешь, кто победил!\n\n"
            "🎯 *Команды в чате:*\n"
            "  - `/riddlekings` — топ отгадчиков здесь\n\n"
            "🏆 *Рейтинг и статистика:*\n"
            "  - В ЛС: `/top_all` — общий топ\n"
            "  - '📊 Статистика бота' — все успехи!\n\n"
            "💡 *Подсказки:* появляются через 80% времени (если таймер есть) или через заданную задержку (если таймера нет).\n\n"
            "🎉 Готово! Загадывай и отгадывай! Если что-то неясно, пиши мне в ЛС! 🚀"
        )
        bot.send_message(user_id, instruction, parse_mode="Markdown")

# Новый участник
@bot.message_handler(content_types=['new_chat_members'])
def new_chat_member(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            chat_id = message.chat.id
            title = message.chat.title
            members_count = bot.get_chat_member_count(chat_id)
            cursor.execute("INSERT OR IGNORE INTO chats (chat_id, title, members_count) VALUES (?, ?, ?)",
                           (chat_id, title, members_count))
            conn.commit()
            logger.info(f"Бот добавлен в чат {chat_id}, тип: {message.chat.type}")
            bot.send_message(chat_id, "🎉 *Ура! Я здесь!* 🎉\n\nДайте мне права администратора, чтобы я мог творить магию загадок! ✨")

# Выбор чата и создание загадки
@bot.callback_query_handler(func=lambda call: call.data.startswith("chat_"))
def select_chat(call):
    chat_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    if not is_admin(user_id, chat_id):
        bot.send_message(user_id, "⛔ *Ой!* ⛔\n\nТолько админы могут создавать загадки! Попроси права у админа чата! 😊")
        logger.warning(f"Пользователь {user_id} пытался создать загадку в чате {chat_id}, но не админ")
        return
    logger.info(f"Пользователь {user_id} выбрал чат {chat_id} для загадки")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(user_id, "🧩 *Создаём загадку!* 🧩\n\nНапиши текст загадки в ЛС 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(user_id, get_riddle, chat_id, user_id)

def get_riddle(message, chat_id, user_id):
    if message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши загадку в ЛС, а не в чате! 😉")
        return
    riddle_text = message.text
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data=f"photo_skip_{chat_id}_{user_id}|{riddle_text}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(user_id, "📸 *Добавь фото!* 📸\n\nПрикрепи картинку к загадке или нажми 'Пропустить' 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(user_id, get_photo, chat_id, user_id, riddle_text)

@bot.callback_query_handler(func=lambda call: call.data.startswith("photo_skip_"))
def photo_skip(call):
    try:
        data = call.data[len("photo_skip_"):].split("|", 1)
        ids, riddle_text = data[0].split("_"), data[1]
        chat_id, user_id = int(ids[0]), int(ids[1])
        get_photo(None, chat_id, user_id, riddle_text)
    except (IndexError, ValueError) as e:
        logger.error(f"Ошибка разбора callback_data в photo_skip: {e}, data: {call.data}")
        bot.send_message(call.from_user.id, "⛔ *Упс!* ⛔\n\nОшибка при пропуске фото. Начни заново! 😅")
        main_menu(call.from_user.id)

def get_photo(message, chat_id, user_id, riddle_text):
    if message and message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nОтправляй фото в ЛС, а не в чат! 😉")
        return
    photo_id = message.photo[-1].file_id if message and message.photo else None
    if message and message.text == "пропустить":
        photo_id = None
    elif message and not photo_id:
        bot.send_message(user_id, "⛔ *Ой!* ⛔\n\nПрикрепи фото или нажми 'Пропустить'! 👇")
        return
    
    bot.clear_step_handler_by_chat_id(user_id)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(user_id, "🔑 *Какой ответ?* 🔑\n\nНапиши правильный ответ в ЛС 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(user_id, get_answer, chat_id, user_id, riddle_text, photo_id)

def get_answer(message, chat_id, user_id, riddle_text, photo_id):
    if message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши ответ в ЛС, а не в чате! 😉")
        return
    answer = message.text
    
    bot.clear_step_handler_by_chat_id(user_id)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(user_id, "🎁 *Какой приз?* 🎁\n\nУкажи приз для победителя 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(user_id, get_prize, chat_id, user_id, riddle_text, photo_id, answer)

def get_prize(message, chat_id, user_id, riddle_text, photo_id, answer):
    if message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши приз в ЛС, а не в чате! 😉")
        return
    prize = message.text
    cursor.execute("INSERT INTO riddles (chat_id, user_id, riddle_text, answer, prize, photo_id, active) VALUES (?, ?, ?, ?, ?, ?, 0)",
                   (chat_id, user_id, riddle_text, answer, prize, photo_id))
    conn.commit()
    riddle_id = cursor.lastrowid
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏳ Задать время", callback_data=f"time_set_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("⏰ Без таймера", callback_data=f"time_none_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(user_id, "⏳ *Нужен таймер?* ⏳\n\nУстановить время или оставить без ограничений? 👇", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("time_set_"))
def get_time_set(call):
    riddle_id = int(call.data.split("_")[2])
    cursor.execute("SELECT chat_id, user_id, riddle_text, photo_id, answer, prize FROM riddles WHERE id = ?", (riddle_id,))
    chat_id, user_id, riddle_text, photo_id, answer, prize = cursor.fetchone()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(call.from_user.id, "⏳ *Сколько минут?* ⏳\n\nВведи время (максимум 1440) 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.from_user.id, get_time, chat_id, call.from_user.id, riddle_text, photo_id, answer, prize, riddle_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("time_none_"))
def get_time_none(call):
    riddle_id = int(call.data.split("_")[2])
    cursor.execute("SELECT chat_id, user_id, riddle_text, photo_id, answer, prize FROM riddles WHERE id = ?", (riddle_id,))
    chat_id, user_id, riddle_text, photo_id, answer, prize = cursor.fetchone()
    cursor.execute("UPDATE riddles SET time_limit = NULL WHERE id = ?", (riddle_id,))
    conn.commit()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💡 Добавить подсказку", callback_data=f"hint_add_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data=f"hint_skip_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(call.from_user.id, "💡 *Нужна подсказка?* 💡\n\nХочешь добавить подсказку? 👇", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("hint_add_"))
def get_hint_add(call):
    riddle_id = int(call.data.split("_")[2])
    cursor.execute("SELECT chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit FROM riddles WHERE id = ?", (riddle_id,))
    chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit = cursor.fetchone()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    bot.send_message(call.from_user.id, "💡 *Текст подсказки* 💡\n\nНапиши подсказку для участников 👇", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.from_user.id, get_hint, chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, riddle_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("hint_skip_"))
def get_hint_skip(call):
    riddle_id = int(call.data.split("_")[2])
    cursor.execute("SELECT chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit FROM riddles WHERE id = ?", (riddle_id,))
    chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit = cursor.fetchone()
    get_hint(None, chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, riddle_id)

def get_time(message, chat_id, user_id, riddle_text, photo_id, answer, prize, riddle_id):
    if message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши время в ЛС, а не в чате! 😉")
        return
    time_limit = message.text
    if not time_limit.isdigit():
        bot.send_message(user_id, "⛔ *Ой!* ⛔\n\nВведи число в минутах (например, 10)! 👇")
        return
    time_limit = int(time_limit)
    if time_limit > 1440:
        time_limit = 1440
        bot.send_message(user_id, "⚠️ *Максимум!* ⚠️\n\nТаймер ограничен 1440 минутами (24 часа).")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💡 Добавить подсказку", callback_data=f"hint_add_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data=f"hint_skip_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    cursor.execute("UPDATE riddles SET time_limit = ? WHERE id = ?", (time_limit, riddle_id))
    conn.commit()
    bot.send_message(user_id, "💡 *Нужна подсказка?* 💡\n\nХочешь добавить подсказку? 👇", reply_markup=markup)

def get_hint(message, chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, riddle_id):
    if message and message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши подсказку в ЛС, а не в чате! 😉")
        return
    hint = message.text if message else None
    cursor.execute("UPDATE riddles SET hint = ?, time_limit = ? WHERE id = ?", (hint, time_limit, riddle_id))
    conn.commit()
    if hint and not time_limit:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
        bot.send_message(user_id, "⏳ *Когда показать подсказку?* ⏳\n\nЧерез сколько минут (или '0' для сразу)? 👇", reply_markup=markup)
        bot.register_next_step_handler_by_chat_id(user_id, get_hint_delay, chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint, riddle_id)
    else:
        show_riddle_preview(chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, None, riddle_id)

def get_hint_delay(message, chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint, riddle_id):
    if message.chat.id != user_id:
        bot.send_message(user_id, "⛔ *Эй!* ⛔\n\nПиши время в ЛС, а не в чате! 😉")
        return
    hint_delay = message.text
    if not hint_delay.isdigit():
        bot.send_message(user_id, "⛔ *Ой!* ⛔\n\nВведи число в минутах или '0'! 👇")
        return
    hint_delay = int(hint_delay)
    cursor.execute("UPDATE riddles SET hint_delay = ? WHERE id = ?", (hint_delay, riddle_id))
    conn.commit()
    show_riddle_preview(chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint_delay, riddle_id)

def show_riddle_preview(chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint_delay, riddle_id):
    time_limit = int(time_limit) if time_limit is not None else None
    preview = (
        f"🚨 *ЗАГАДКА!* 🚨\n\n"
        f"{riddle_text}\n\n"
        f"🎁 *ПРИЗ:*\n{prize}\n\n"
        f"⏰ *Время:* {time_limit if time_limit is not None else 'не ограничено'} мин"
    )
    cursor.execute("SELECT hint FROM riddles WHERE id = ?", (riddle_id,))
    hint = cursor.fetchone()[0]
    if hint:
        if time_limit is not None:
            hint_time = int((time_limit * 60) * 0.8)
            preview += f"\n\n💡 *Подсказка через:* {hint_time} сек"
        elif hint_delay is not None:
            preview += f"\n\n💡 *Подсказка через:* {hint_delay} мин"
        else:
            preview += f"\n\n💡 *Подсказка сразу!*"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Отправить в чат", callback_data=f"send_{riddle_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    if photo_id:
        bot.send_photo(user_id, photo_id, caption=preview, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(user_id, preview, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_"))
def send_riddle(call):
    riddle_id = int(call.data.split("_")[1])
    cursor.execute("SELECT chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint, hint_delay FROM riddles WHERE id = ?", (riddle_id,))
    chat_id, user_id, riddle_text, photo_id, answer, prize, time_limit, hint, hint_delay = cursor.fetchone()
    time_limit = int(time_limit) if time_limit is not None else None
    
    text = (
        f"🚨 *ЗАГАДКА!* 🚨\n\n"
        f"{riddle_text}\n\n"
        f"🎁 *ПРИЗ:*\n{prize}\n\n"
        f"💬 *Как ответить?* Реплай на это сообщение своим ответом!"
    )
    if time_limit:
        text += f"\n\n⏰ *Время:* {time_limit} мин"
    if photo_id:
        msg = bot.send_photo(chat_id, photo_id, caption=text, parse_mode="Markdown")
    else:
        msg = bot.send_message(chat_id, text, parse_mode="Markdown")
    
    start_time = int(time.time())
    cursor.execute("UPDATE riddles SET message_id = ?, start_time = ?, active = 1 WHERE id = ?",
                   (msg.message_id, start_time, riddle_id))
    conn.commit()
    logger.info(f"Загадка отправлена в чат {chat_id} пользователем {user_id} с message_id {msg.message_id}")
    bot.send_message(call.from_user.id, "✨ *Готово!* ✨\n\nЗагадка отправлена в чат! 🎉")
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        logger.info(f"Удалено превью загадки в ЛС для пользователя {call.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка удаления превью в ЛС: {e}")
    
    threading.Thread(target=riddle_timer, args=(riddle_id, chat_id, msg.message_id, time_limit, riddle_text, prize, hint, hint_delay), daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_riddle(call):
    user_id = call.from_user.id
    cursor.execute("DELETE FROM riddles WHERE user_id = ? AND active = 0", (user_id,))
    conn.commit()
    bot.send_message(user_id, "❌ *Отменено!* ❌\n\nСоздание загадки остановлено! 😊")
    logger.info(f"Пользователь {user_id} отменил создание загадки")
    bot.clear_step_handler_by_chat_id(user_id)
    main_menu(user_id)

@bot.callback_query_handler(func=lambda call: call.data in ["stats_global", "stats_chats_users"])
def show_stats(call):
    user_id = call.from_user.id
    if call.data == "stats_global":
        cursor.execute("SELECT COUNT(*) FROM riddles")
        total_riddles = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM riddles WHERE active = 0")
        solved_riddles = cursor.fetchone()[0]
        cursor.execute("SELECT AVG(end_time - start_time) / 60 FROM riddles WHERE active = 0 AND end_time IS NOT NULL")
        avg_time = cursor.fetchone()[0] or 0
        text = (
            f"📈 *Общая статистика* 📈\n\n"
            f"✨ Создано загадок: {total_riddles}\n"
            f"✅ Отгадано: {solved_riddles} ({solved_riddles/total_riddles*100:.1f}%)\n"
            f"⏱ Среднее время отгадки: {avg_time:.1f} мин"
        )
        bot.send_message(user_id, text, parse_mode="Markdown")
    elif call.data == "stats_chats_users":
        cursor.execute("SELECT COUNT(*) FROM chats")
        total_chats = cursor.fetchone()[0]
        cursor.execute("SELECT chat_id, members_count FROM chats")
        chats = cursor.fetchall()
        total_members = sum(members_count for _, members_count in chats)
        text = (
            f"👥 *Чаты и участники* 👥\n\n"
            f"💬 Чатов с ботом: {total_chats}\n"
            f"👤 Всего участников: {total_members}"
        )
        bot.send_message(user_id, text, parse_mode="Markdown")

# Обработка ответов
incorrect_messages = {}

@bot.message_handler(content_types=['text'], chat_types=['group', 'supergroup'])
def check_answer(message):
    global incorrect_messages
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not message.reply_to_message:
        logger.info(f"Сообщение в чате {chat_id} от {user_id}: '{message.text}' - не ответ")
        return
    
    reply_to_id = message.reply_to_message.message_id
    logger.info(f"Получен ответ в чате {chat_id} на сообщение {reply_to_id} от пользователя {user_id}: '{message.text}'")

    cursor.execute("SELECT id, answer, prize, user_id, message_id FROM riddles WHERE chat_id = ? AND message_id = ? AND active = 1",
                   (chat_id, reply_to_id))
    riddle = cursor.fetchone()
    
    if riddle:
        riddle_id, correct_answer, prize, creator_id, riddle_message_id = riddle
        user_answer = message.text.lower().strip()
        correct_answer = correct_answer.lower().strip()
        logger.info(f"Проверка ответа на загадку {riddle_id}: '{user_answer}' vs '{correct_answer}'")
        
        if user_answer == correct_answer:
            winner_message = bot.reply_to(message, f"🎉 *Ура! Загадка разгадана!* 🎉\n\nПоздравляем, @{message.from_user.username}! 🏆")
            cursor.execute("UPDATE riddles SET active = 0, end_time = ? WHERE id = ?", (int(time.time()), riddle_id))
            cursor.execute("INSERT OR IGNORE INTO scores (user_id, chat_id, points) VALUES (?, ?, 0)", (user_id, chat_id))
            cursor.execute("UPDATE scores SET points = points + 1 WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
            conn.commit()
            logger.info(f"Загадка {riddle_id} разгадана пользователем {user_id}")
            
            try:
                bot.delete_message(chat_id, riddle_message_id)
                logger.info(f"Удалено сообщение загадки {riddle_message_id} в чате {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка удаления сообщения {riddle_message_id}: {e}")
            
            if chat_id not in incorrect_messages:
                incorrect_messages[chat_id] = []
            for msg_id in incorrect_messages[chat_id]:
                try:
                    bot.delete_message(chat_id, msg_id)
                    logger.info(f"Удалено сообщение с неправильным ответом {msg_id} в чате {chat_id}")
                except Exception as e:
                    logger.error(f"Ошибка удаления сообщения {msg_id}: {e}")
            incorrect_messages[chat_id] = []
            
            if prize:
                bot.send_message(user_id, f"🥳 *Победа!* 🥳\n\nТы отгадал загадку! 🎉\nТвой приз: *{prize}*")
            else:
                creator = cursor.execute("SELECT username FROM users WHERE user_id = ?", (creator_id,)).fetchone()[0]
                bot.send_message(user_id, f"🥳 *Победа!* 🥳\n\nТы отгадал загадку! 🎉\nСвяжитесь с @{creator} за призом!")
        else:
            incorrect_msg = bot.reply_to(message, "❌ *Не угадал!* ❌\n\nПопробуй ещё раз! 😉")
            if chat_id not in incorrect_messages:
                incorrect_messages[chat_id] = []
            incorrect_messages[chat_id].append(incorrect_msg.message_id)
            logger.info(f"Неправильный ответ '{user_answer}' на загадку {riddle_id}, message_id {incorrect_msg.message_id}")
    else:
        logger.info(f"Сообщение {reply_to_id} в чате {chat_id} не связано с активной загадкой")

# Запуск бота
if __name__ == "__main__":
    logger.info("Бот запущен")
    bot.polling(none_stop=True)