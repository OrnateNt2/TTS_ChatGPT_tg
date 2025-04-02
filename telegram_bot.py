import os
import tempfile
import logging
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
import openai

# Загрузка переменных окружения из .env
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Укажите TELEGRAM_BOT_TOKEN и OPENAI_API_KEY в файле .env")

# Настройка openai (используется только для ключа и base_url)
openai.api_key = OPENAI_API_KEY
openai.api_base = "https://api.proxyapi.ru/openai/v1"

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def generate_tts_audio(model: str, voice: str, input_text: str, instructions: str, audio_path: str):
    """
    Отправляет POST-запрос к TTS-endpoint и сохраняет полученное аудио в audio_path.
    """
    url = f"{openai.api_base}/audio/speech"
    headers = {
        "Authorization": f"Bearer {openai.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "voice": voice,
        "input": input_text,
    }
    if instructions:
        payload["instructions"] = instructions

    with requests.post(url, headers=headers, json=payload, stream=True) as r:
        r.raise_for_status()
        with open(audio_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Привет! Я TTS‑бот:\n\n"
        "• Отправь мне текст или текстовый файл (.txt), и я верну озвучку.\n"
        "• Отправь голосовое сообщение — транскрипция временно недоступна.\n\n"
        "Используй команду /model, чтобы выбрать модель TTS (tts-1 или tts-1-hd).\n\n"
        "Просто отправьте сообщение!"
    )
    await update.message.reply_text(welcome_text)

async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("tts-1", callback_data="model:tts-1"),
            InlineKeyboardButton("tts-1-hd", callback_data="model:tts-1-hd"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите модель для TTS:", reply_markup=reply_markup)

async def handle_model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # например, "model:tts-1-hd"
    if data.startswith("model:"):
        model_choice = data.split(":", 1)[1]
        context.user_data["tts_model"] = model_choice
        await query.edit_message_text(text=f"Вы выбрали модель: {model_choice}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        await update.message.reply_text("Пожалуйста, отправьте текст.")
        return

    await update.message.reply_text("Генерирую аудио...")
    # Получаем выбранную модель из данных пользователя, по умолчанию "tts-1-hd"
    tts_model = context.user_data.get("tts_model", "tts-1-hd")
    voice = "nova"  # зафиксированный голос (можно добавить выбор)
    instructions = ""  # можно добавить поле для инструкций

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        audio_path = tf.name

    try:
        generate_tts_audio(
            model=tts_model,
            voice=voice,
            input_text=text,
            instructions=instructions,
            audio_path=audio_path,
        )
        with open(audio_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file)
    except Exception as e:
        logger.error("Ошибка при генерации аудио: %s", e)
        await update.message.reply_text("Ошибка при генерации аудио: " + str(e))
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document:
        await update.message.reply_text("Документ не найден.")
        return

    file = await document.get_file()
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            file_path = tf.name
        await file.download_to_drive(custom_path=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        await update.message.reply_text("Генерирую аудио из файла...")
        tts_model = context.user_data.get("tts_model", "tts-1-hd")
        voice = "nova"
        instructions = ""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf_audio:
            audio_path = tf_audio.name

        generate_tts_audio(
            model=tts_model,
            voice=voice,
            input_text=text,
            instructions=instructions,
            audio_path=audio_path,
        )
        with open(audio_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file)
    except Exception as e:
        logger.error("Ошибка при обработке файла: %s", e)
        await update.message.reply_text("Ошибка при обработке файла: " + str(e))
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        if 'audio_path' in locals() and os.path.exists(audio_path):
            os.remove(audio_path)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Транскрипция голосовых сообщений временно недоступна
    await update.message.reply_text("Транскрипция голосовых сообщений временно недоступна.")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", set_model))
    application.add_handler(CallbackQueryHandler(handle_model_callback, pattern="^model:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    application.run_polling()

if __name__ == '__main__':
    main()
