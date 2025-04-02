import sqlite3
from datetime import datetime

# Подключаемся к базе данных activity.db.
# Используем check_same_thread=False, чтобы один объект соединения мог использоваться в разных потоках.
conn = sqlite3.connect("activity.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    # Создаём таблицу users, если её ещё нет.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        total_requests INTEGER DEFAULT 0,
        monthly_requests INTEGER DEFAULT 0
    )
    """)
    # Создаём таблицу requests для логирования каждого запроса, с дополнительными данными о настройках.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        request_type TEXT,
        model_used TEXT,
        voice_used TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)
    # Создаем таблицу metadata для хранения служебной информации (например, последний сброс месяца)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    # Инициализируем метаданные, если нет записи для last_reset_month
    cursor.execute("SELECT value FROM metadata WHERE key = 'last_reset_month'")
    row = cursor.fetchone()
    if row is None:
        current_month = datetime.now().month
        cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("last_reset_month", str(current_month)))
    conn.commit()

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def add_or_update_user(user_id, username, first_name, last_name):
    """
    Если пользователя с таким user_id нет, добавляет запись.
    Иначе обновляет данные (username, first_name, last_name).
    """
    user = get_user(user_id)
    if user is None:
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, total_requests, monthly_requests)
            VALUES (?, ?, ?, ?, 0, 0)
        """, (user_id, username, first_name, last_name))
    else:
        cursor.execute("""
            UPDATE users
            SET username = ?, first_name = ?, last_name = ?
            WHERE user_id = ?
        """, (username, first_name, last_name, user_id))
    conn.commit()

def check_and_reset_monthly_requests():
    """
    Проверяет, если текущий месяц отличается от сохранённого в metadata, сбрасывает monthly_requests для всех пользователей.
    """
    current_month = datetime.now().month
    cursor.execute("SELECT value FROM metadata WHERE key = 'last_reset_month'")
    row = cursor.fetchone()
    if row:
        last_reset = int(row[0])
        if current_month != last_reset:
            # Сбрасываем monthly_requests для всех пользователей
            cursor.execute("UPDATE users SET monthly_requests = 0")
            # Обновляем метаданные
            cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_reset_month'", (str(current_month),))
            conn.commit()

def log_request(user_id, request_type, model_used=None, voice_used=None):
    """
    Добавляет запись в таблицу requests и увеличивает счетчики в таблице users.
    Также проверяет и сбрасывает ежемесячную статистику, если наступил новый месяц.
    """
    check_and_reset_monthly_requests()
    cursor.execute("""
        INSERT INTO requests (user_id, request_type, model_used, voice_used)
        VALUES (?, ?, ?, ?)
    """, (user_id, request_type, model_used, voice_used))
    cursor.execute("""
        UPDATE users
        SET total_requests = total_requests + 1,
            monthly_requests = monthly_requests + 1
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()

def get_user_stats(user_id):
    """
    Возвращает (total_requests, monthly_requests) для данного пользователя.
    """
    cursor.execute("SELECT total_requests, monthly_requests FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

# Функция, которую можно запускать по расписанию (например, раз в месяц через cron)
def reset_monthly_requests():
    cursor.execute("UPDATE users SET monthly_requests = 0")
    # Обновляем метаданные с текущим месяцем
    current_month = datetime.now().month
    cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_reset_month'", (str(current_month),))
    conn.commit()

# Инициализируем базу при импорте модуля.
init_db()
