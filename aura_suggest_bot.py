import asyncio
import os
import time
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= НАСТРОЙКИ ПРЕДЛОЖ-БОТА =================
BOT_TOKEN = "9165467259:AAEBWBELEwwHwaFUFTKkVpEcg-mDMDKpPYA"
ADMIN_ID =  1094406951                          # ТВОЙ ТЕЛЕГРАМ ID (сюда будут падать заявки + у тебя будет вечный доступ)
CLUB_CHAT_ID = -1004324447753                  # ID закрытой группы AURA (куда бот будет постить)

DB_NAME = "aura_club.db"                       # Имя базы (должно быть то же самое, что у бота оплаты)

# ID топиков в закрытой группе (включи темы в группе и скопируй ID из URL)
TOPICS = {
    "sos": 9,          # ID топика "🩸 Разбор ситуаций (SOS)"
    "challenge": 24,    # ID топика "⚔️ Челленджи и Режим"
    "network": 27,      # ID топика "🤝 Связи и Свои люди"
    "books": 8         # ID топика "📖 Книжный арсенал и Саммари"
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= МАШИНА СОСТОЯНИЙ =================
class SuggestionState(StatesGroup):
    waiting_for_content = State()
    waiting_for_admin_comment = State()

# ================= БАЗА ДАННЫХ =================
async def init_db():
    # Создаем таблицу заявок, если её еще нет.
    # Таблица users (со статусом подписки) уже должна быть создана и заполнена главным ботом.
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS suggestions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER, "
            "category TEXT, "
            "text_content TEXT, "
            "media_id TEXT, "
            "status TEXT DEFAULT 'pending', "
            "created_at INTEGER)"
        )
        await db.commit()

async def check_active_sub(user_id: int) -> bool:
    """Проверяет, есть ли активная подписка (через базу aura_club.db)"""
    # === БЕЗУСЛОВНЫЙ ПРОПУСК ДЛЯ АДМИНА ===
    if user_id == ADMIN_ID:
        return True

    now = int(time.time())
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT sub_end FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                # Жесткий режим: если основное время вышло (даже если идут 3 дня отсрочки), предложка закрыта.
                if row and row[0] > now:
                    return True
    except Exception as e:
        print(f"Ошибка проверки БД: {e}")
    return False

# ================= КЛАВИАТУРЫ =================
def suggest_category_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🩸 Разбор ситуаций (SOS)", callback_data="cat_sos")],
        [InlineKeyboardButton(text="⚔️ Отчет по челленджу", callback_data="cat_challenge")],
        [InlineKeyboardButton(text="🤝 Анкета: Связи и Свои люди", callback_data="cat_network")],
        [InlineKeyboardButton(text="📖 Книжный арсенал", callback_data="cat_books")],
    ])

def admin_review_kb(sugg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"adm_pub_{sugg_id}")],
        [InlineKeyboardButton(text="✏️ С моим комментом", callback_data=f"adm_com_{sugg_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_rej_{sugg_id}")]
    ])

# ================= ЛОГИКА ПОЛЬЗОВАТЕЛЯ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if not await check_active_sub(user_id):
        await message.answer("❌ <b>Твой доступ в клуб AURA не активен или истек.</b>\nОформи подписку в главном боте, чтобы отправлять кейсы на разбор.", parse_mode="HTML")
        return

    text = "\n".join([
        "📨 <b>ПРЕДЛОЖКА ОРДЕНА AURA</b>",
        "",
        "Здесь ты можешь анонимно отправить историю на разбор, скинуть отчет по челленджу или опубликовать анкету.",
        "",
        "Выбери нужную категорию ниже:"
    ])
    await message.answer(text, reply_markup=suggest_category_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("cat_"))
async def suggest_category_chosen(call: CallbackQuery, state: FSMContext):
    if not await check_active_sub(call.from_user.id):
        await call.answer("❌ Доступ закрыт. Продли подписку.", show_alert=True)
        return

    cat_id = call.data.split("_")[1]
    cat_names = {
        "sos": "🩸 Разбор ситуаций (SOS)", 
        "challenge": "⚔️ Челленджи и Режим", 
        "network": "🤝 Связи и Свои люди", 
        "books": "📖 Книжный арсенал и Саммари"
    }
    
    await state.update_data(category=cat_id, cat_name=cat_names[cat_id])
    
    text = "\n".join([
        f"📝 <b>Категория: {cat_names[cat_id]}</b>",
        "",
        "Отправь текст своего сообщения. Опиши ситуацию сухо и по фактам. Замажь чужие фамилии и лица, если отправляешь фото.",
        "<b>Важно:</b> Прикрепляй текст и ОДНО фото в одном сообщении."
    ])
    await call.message.edit_text(text, parse_mode="HTML")
    await state.set_state(SuggestionState.waiting_for_content)

@dp.message(SuggestionState.waiting_for_content)
async def receive_suggestion(message: Message, state: FSMContext):
    data = await state.get_data()
    cat_id = data.get("category")
    cat_name = data.get("cat_name")
    
    if not cat_id:
        await message.answer("Категория не выбрана. Напиши /start")
        return

    text_content = message.html_text or ""
    media_id = None
    
    if message.photo:
        media_id = message.photo[-1].file_id
    elif not text_content:
        await message.answer("⚠️ Пожалуйста, отправь текст (с фото или без). Пустое фото не принимается.")
        return

    now = int(time.time())
    user_id = message.from_user.id
    
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "INSERT INTO suggestions (user_id, category, text_content, media_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, cat_id, text_content, media_id, now)
            )
            sugg_id = cursor.lastrowid
            await db.commit()

        await message.answer("✅ <b>Принято.</b> Твой материал передан в штаб Ордена. Ожидай публикации в группе.", parse_mode="HTML")
        await state.clear()

        # Пересылка админу
        admin_msg = f"📨 <b>Новая заявка (#{sugg_id})</b>\nКатегория: {cat_name}\nОт: <code>{user_id}</code>\n\n{text_content}"
        if media_id:
            await bot.send_photo(chat_id=ADMIN_ID, photo=media_id, caption=admin_msg[:1024], reply_markup=admin_review_kb(sugg_id), parse_mode="HTML")
        else:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=admin_review_kb(sugg_id), parse_mode="HTML")

    except Exception as e:
        await message.answer("⚠️ Произошла ошибка при сохранении. Попробуй позже.")
        print(f"Ошибка сохранения предложки: {e}")

# ================= ЛОГИКА АДМИНА =================
@dp.callback_query(F.data.startswith("adm_rej_"))
async def admin_reject(call: CallbackQuery):
    sugg_id = int(call.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE suggestions SET status = 'rejected' WHERE id = ?", (sugg_id,))
        await db.commit()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("❌ Заявка отклонена")

@dp.callback_query(F.data.startswith("adm_pub_"))
async def admin_publish(call: CallbackQuery):
    sugg_id = int(call.data.split("_")[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT category, text_content, media_id FROM suggestions WHERE id = ?", (sugg_id,)) as cursor:
            row = await cursor.fetchone()
            
    if not row:
        return await call.answer("Заявка не найдена в базе")
        
    cat_id, text, media_id = row
    topic_id = TOPICS.get(cat_id)
    
    header = "🩸 <b>АНОНИМНЫЙ РАЗБОР (SOS)</b>\n\n" if cat_id == "sos" else ""
    full_text = f"{header}{text}"

    try:
        if media_id:
            await bot.send_photo(chat_id=CLUB_CHAT_ID, photo=media_id, caption=full_text[:1024], message_thread_id=topic_id, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=CLUB_CHAT_ID, text=full_text, message_thread_id=topic_id, parse_mode="HTML")
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE suggestions SET status = 'published' WHERE id = ?", (sugg_id,))
            await db.commit()
            
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("✅ Успешно опубликовано в группу!")
    except Exception as e:
        await call.answer(f"Ошибка публикации: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("adm_com_"))
async def admin_comment_start(call: CallbackQuery, state: FSMContext):
    sugg_id = int(call.data.split("_")[2])
    await state.update_data(sugg_id=sugg_id)
    await call.message.answer(f"✏️ Отправь текст разбора для заявки #{sugg_id}. Он будет прикреплен снизу к посту.")
    await state.set_state(SuggestionState.waiting_for_admin_comment)
    await call.answer()

@dp.message(SuggestionState.waiting_for_admin_comment)
async def admin_comment_receive(message: Message, state: FSMContext):
    data = await state.get_data()
    sugg_id = data.get("sugg_id")
    
    if not sugg_id:
        return await message.answer("Ошибка: ID заявки не найден.")

    admin_comment = message.html_text
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT category, text_content, media_id FROM suggestions WHERE id = ?", (sugg_id,)) as cursor:
            row = await cursor.fetchone()
            
    if not row:
        return await message.answer("Заявка не найдена в базе")
        
    cat_id, text, media_id = row
    topic_id = TOPICS.get(cat_id)
    
    header = "🩸 <b>АНОНИМНЫЙ РАЗБОР (SOS)</b>\n\n" if cat_id == "sos" else ""
    full_text = f"{header}{text}\n\n— — — — — — —\n🦅 <b>Разбор от AURA:</b>\n{admin_comment}"

    try:
        if media_id:
            await bot.send_photo(chat_id=CLUB_CHAT_ID, photo=media_id, caption=full_text[:1024], message_thread_id=topic_id, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=CLUB_CHAT_ID, text=full_text, message_thread_id=topic_id, parse_mode="HTML")
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE suggestions SET status = 'published' WHERE id = ?", (sugg_id,))
            await db.commit()
            
        await message.answer("✅ Опубликовано с твоим разбором!")
    except Exception as e:
        await message.answer(f"Ошибка публикации: {e}")
        
    await state.clear()

async def main():
    await init_db()
    print("✅ Бот-предложка AURA запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
