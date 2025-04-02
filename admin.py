from dotenv import load_dotenv
load_dotenv()  # Загружаем переменные окружения

import os
import sys
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
import db

logger = logging.getLogger(__name__)

# Состояния диалога для админ-команд
BROADCAST, MAINTENANCE = range(2)

# Читаем список администраторских ID из переменной окружения
ADMIN_IDS = []
admin_ids_env = os.getenv("ADMIN_IDS", "")
if admin_ids_env:
    try:
        ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(",") if x.strip()]
    except Exception as e:
        logger.error("Ошибка при парсинге ADMIN_IDS: %s", e)
else:
    logger.warning("ADMIN_IDS не заданы. Админ-команды будут недоступны.")

def build_admin_keyboard() -> InlineKeyboardMarkup:
    """Строит inline‑клавиатуру для админ-панели."""
    keyboard = [
        [InlineKeyboardButton("Broadcast Message", callback_data="admin:broadcast")],
        [InlineKeyboardButton("Maintenance Message", callback_data="admin:maintenance")],
        [InlineKeyboardButton("Get DB Stats", callback_data="admin:dbstats")],
        [InlineKeyboardButton("Restart Bot", callback_data="admin:restart")],
        [InlineKeyboardButton("Shutdown Bot", callback_data="admin:shutdown")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin – открывает панель админа."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text("Admin Panel:", reply_markup=build_admin_keyboard())

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline‑кнопок админ-панели."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("Access denied.")
        return ConversationHandler.END

    if data == "admin:broadcast":
        await query.edit_message_text("Введите сообщение для рассылки:\n(Отправьте текст в ответ на это сообщение)")
        return BROADCAST
    elif data == "admin:maintenance":
        await query.edit_message_text("Введите сообщение о ремонте для рассылки всем пользователям:")
        return MAINTENANCE
    elif data == "admin:dbstats":
        # Получаем полную информацию из users
        cursor = db.conn.cursor()
        cursor.execute("SELECT * FROM users")
        users_data = cursor.fetchall()
        # Получаем последние 50 записей из requests
        cursor.execute("SELECT * FROM requests ORDER BY timestamp DESC LIMIT 50")
        requests_data = cursor.fetchall()
        text = "DB Statistics:\n\nUsers:\n"
        for row in users_data:
            text += f"{row}\n"
        text += "\nLast 50 Requests:\n"
        for row in requests_data:
            text += f"{row}\n"
        await query.edit_message_text(text=text, reply_markup=build_admin_keyboard())
        return ConversationHandler.END
    elif data == "admin:restart":
        await query.edit_message_text("Перезапуск бота...")
        asyncio.create_task(restart_bot())
        return ConversationHandler.END
    elif data == "admin:shutdown":
        await query.edit_message_text("Выключение бота...")
        asyncio.create_task(shutdown_bot(context))
        return ConversationHandler.END
    else:
        await query.edit_message_text("Неизвестная команда.")
        return ConversationHandler.END

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текст для массовой рассылки."""
    message_text = update.message.text
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END

    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]
    success = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {uid}: {e}")
            continue
    await update.message.reply_text(f"Сообщение отправлено {success} пользователям.", reply_markup=build_admin_keyboard())
    return ConversationHandler.END

async def maintenance_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текст для рассылки maintenance-сообщения."""
    message_text = update.message.text
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END

    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]
    success = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text="Бот на ремонте. " + message_text)
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки maintenance-сообщения пользователю {uid}: {e}")
            continue
    await update.message.reply_text(f"Maintenance сообщение отправлено {success} пользователям.", reply_markup=build_admin_keyboard())
    return ConversationHandler.END

async def restart_bot():
    """Перезапускает бота, заменяя текущий процесс."""
    logger.info("Перезапуск бота...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

async def shutdown_bot(context: ContextTypes.DEFAULT_TYPE):
    """Выключает бота."""
    logger.info("Выключение бота...")
    try:
        await context.bot.send_message(chat_id=ADMIN_IDS[0], text="Бот выключается по запросу админа.")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения администратору: {e}")
    os._exit(0)

def register_admin_handlers(application):
    """Регистрирует админ-обработчики в приложении."""
    application.add_handler(CommandHandler("admin", admin_panel))
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback_handler, pattern="^admin:")],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)],
            MAINTENANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, maintenance_message)]
        },
        fallbacks=[]
    )
    application.add_handler(conv_handler)
