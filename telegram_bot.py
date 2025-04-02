import os
import tempfile
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
import db

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Укажите TELEGRAM_BOT_TOKEN и OPENAI_API_KEY в файле .env")

openai.api_key = OPENAI_API_KEY
openai.api_base = "https://api.proxyapi.ru/openai/v1"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

persistent_keyboard = ReplyKeyboardMarkup(
    [["Сменить настройки"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

def generate_tts_audio(model: str, voice: str, input_text: str, instructions: str, audio_path: str):
    url = f"{openai.api_base}/audio/speech"
    headers = {
        "Authorization": f"Bearer {openai.api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "voice": voice, "input": input_text}
    if instructions:
        payload["instructions"] = instructions
    with requests.post(url, headers=headers, json=payload, stream=True) as r:
        r.raise_for_status()
        with open(audio_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def transcribe_voice_file(audio_path: str) -> dict:
    url = f"{openai.api_base}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {openai.api_key}"}
    data = {"model": "whisper-1"}
    with open(audio_path, "rb") as audio_file:
        files = {"file": audio_file}
        response = requests.post(url, headers=headers, data=data, files=files)
        response.raise_for_status()
        return response.json()

def build_settings_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    current_model = context.user_data.get("tts_model", "tts-1-hd")
    current_voice = context.user_data.get("tts_voice", "nova")
    model_buttons = [
        InlineKeyboardButton(f"tts-1{' ✅' if current_model == 'tts-1' else ''}", callback_data="model:tts-1"),
        InlineKeyboardButton(f"tts-1-hd{' ✅' if current_model == 'tts-1-hd' else ''}", callback_data="model:tts-1-hd")
    ]
    voice_buttons = [
        InlineKeyboardButton(f"alloy{' ✅' if current_voice == 'alloy' else ''}", callback_data="voice:alloy"),
        InlineKeyboardButton(f"echo{' ✅' if current_voice == 'echo' else ''}", callback_data="voice:echo"),
        InlineKeyboardButton(f"fable{' ✅' if current_voice == 'fable' else ''}", callback_data="voice:fable"),
        InlineKeyboardButton(f"onyx{' ✅' if current_voice == 'onyx' else ''}", callback_data="voice:onyx"),
        InlineKeyboardButton(f"nova{' ✅' if current_voice == 'nova' else ''}", callback_data="voice:nova"),
        InlineKeyboardButton(f"shimmer{' ✅' if current_voice == 'shimmer' else ''}", callback_data="voice:shimmer")
    ]
    voice_rows = [voice_buttons[i:i+3] for i in range(0, len(voice_buttons), 3)]
    keyboard = [model_buttons] + voice_rows
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Привет! Я TTS‑бот:\n\n"
        "• Отправь текст или текстовый файл (.txt) – я верну озвучку.\n"
        "• Отправь голосовое сообщение – я выполню транскрипцию через Whisper.\n\n"
        "Нажми «Сменить настройки», чтобы выбрать модель и голос."
    )
    user = update.message.from_user
    db.add_or_update_user(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(welcome_text, reply_markup=persistent_keyboard)

async def set_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = build_settings_keyboard(context)
    await update.message.reply_text("Выберите настройки TTS:", reply_markup=reply_markup)

async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("model:"):
        context.user_data["tts_model"] = data.split(":", 1)[1]
    elif data.startswith("voice:"):
        context.user_data["tts_voice"] = data.split(":", 1)[1]
    reply_markup = build_settings_keyboard(context)
    await query.edit_message_text(text="Настройки обновлены:", reply_markup=reply_markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    db.add_or_update_user(user.id, user.username, user.first_name, user.last_name)
    text = update.message.text
    if not text or text.strip() == "":
        await update.message.reply_text("Пожалуйста, отправьте текст.", reply_markup=persistent_keyboard)
        return
    if text.strip().lower() == "сменить настройки":
        await set_settings(update, context)
        return
    await update.message.reply_text("Генерирую аудио...", reply_markup=persistent_keyboard)
    tts_model = context.user_data.get("tts_model", "tts-1-hd")
    tts_voice = context.user_data.get("tts_voice", "nova")
    instructions = ""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        audio_path = tf.name
    try:
        generate_tts_audio(
            model=tts_model,
            voice=tts_voice,
            input_text=text,
            instructions=instructions,
            audio_path=audio_path,
        )
        with open(audio_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file, reply_markup=persistent_keyboard)
        db.log_request(user.id, "TTS", model_used=tts_model, voice_used=tts_voice)
    except Exception as e:
        logger.error("Ошибка при генерации аудио: %s", e)
        await update.message.reply_text("Ошибка при генерации аудио: " + str(e), reply_markup=persistent_keyboard)
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    db.add_or_update_user(user.id, user.username, user.first_name, user.last_name)
    document = update.message.document
    if not document:
        await update.message.reply_text("Документ не найден.", reply_markup=persistent_keyboard)
        return
    file = await document.get_file()
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            file_path = tf.name
        await file.download_to_drive(custom_path=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        await update.message.reply_text("Генерирую аудио из файла...", reply_markup=persistent_keyboard)
        tts_model = context.user_data.get("tts_model", "tts-1-hd")
        tts_voice = context.user_data.get("tts_voice", "nova")
        instructions = ""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf_audio:
            audio_path = tf_audio.name
        generate_tts_audio(
            model=tts_model,
            voice=tts_voice,
            input_text=text,
            instructions=instructions,
            audio_path=audio_path,
        )
        with open(audio_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file, reply_markup=persistent_keyboard)
        db.log_request(user.id, "File", model_used=tts_model, voice_used=tts_voice)
    except Exception as e:
        logger.error("Ошибка при обработке файла: %s", e)
        await update.message.reply_text("Ошибка при обработке файла: " + str(e), reply_markup=persistent_keyboard)
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        if 'audio_path' in locals() and os.path.exists(audio_path):
            os.remove(audio_path)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    db.add_or_update_user(user.id, user.username, user.first_name, user.last_name)
    voice = update.message.voice
    if not voice:
        await update.message.reply_text("Голосовое сообщение не найдено.", reply_markup=persistent_keyboard)
        return
    file = await voice.get_file()
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tf:
            voice_path = tf.name
        await file.download_to_drive(custom_path=voice_path)
        transcript = transcribe_voice_file(voice_path)
        await update.message.reply_text(transcript.get("text", "Нет текста"), reply_markup=persistent_keyboard)
        # Для голосовых запросов можно логировать, передав настройки, если нужно.
        db.log_request(user.id, "Voice", model_used=context.user_data.get("tts_model"), voice_used=context.user_data.get("tts_voice"))
    except Exception as e:
        logger.error("Ошибка при транскрипции голосового сообщения: %s", e)
        await update.message.reply_text("Ошибка при транскрипции голосового сообщения: " + str(e), reply_markup=persistent_keyboard)
    finally:
        if os.path.exists(voice_path):
            os.remove(voice_path)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", set_settings))
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^(model:|voice:)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^сменить настройки$"), set_settings))
    application.run_polling()

if __name__ == '__main__':
    main()
