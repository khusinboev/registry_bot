from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
from config import AUTHORIZED_USER_IDS
from database import get_all_edu_licenses, get_edu_licenses_by_doc_numbers
from scan_runtime import run_scan

router = Router()


def is_authorized(user_id):
    return user_id in AUTHORIZED_USER_IDS

def format_license(row):
    doc_number, file_token, org_name, is_active, saved_at = row
    status = "✅ Faol" if is_active else "❌ Nofaol"
    token_info = f"\n📎 Token: `{file_token}`" if file_token else ""
    return (
        f"🏫 *{org_name}*\n"
        f"📄 Hujjat: `{doc_number}`\n"
        f"📌 Holat: {status}"
        f"{token_info}\n"
        f"🕐 Saqlangan: {saved_at}"
    )

@router.message(CommandStart())
async def start(message: Message):
    if not is_authorized(message.from_user.id):
        await message.answer("Sizga ruxsat berilmagan.")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Mavjudlar", callback_data="show_all")
    kb.button(text="🔍 Tekshirish", callback_data="check_new")
    kb.adjust(2)
    await message.answer(
        "Oliy ta'lim litsenziyalari boti\n\n"
        "📋 *Mavjudlar* — bazadagi litsenziyalar\n"
        "🔍 *Tekshirish* — yangilarini qidirish",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "show_all")
async def show_all(callback: CallbackQuery):
    if not is_authorized(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    rows = get_all_edu_licenses()
    if not rows:
        await callback.message.answer("Bazada hozircha yozuv yo'q.")
        await callback.answer()
        return

    await callback.message.answer(f"Jami {len(rows)} ta litsenziya:")
    for row in rows:
        await callback.message.answer(format_license(row), parse_mode="Markdown")

    await callback.answer()

@router.callback_query(F.data == "check_new")
async def check_new(callback: CallbackQuery):
    if not is_authorized(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await callback.message.answer("🔄 Skanerlash boshlandi, kuting...")
    await callback.answer()

    loop = asyncio.get_event_loop()
    status_msg = await callback.message.answer("⏳ Ishlanmoqda...")

    async def update_status(text):
        try:
            await status_msg.edit_text(f"⏳ {text}")
        except Exception:
            # Status yangilashdagi xato scan jarayonini to'xtatmasin
            pass

    def status_cb(text):
        asyncio.run_coroutine_threadsafe(update_status(text), loop)

    new_items = await loop.run_in_executor(None, lambda: run_scan(status_cb))

    if new_items is None:
        await status_msg.edit_text("⏳ Hozir boshqa scan ishlayapti. Keyinroq qayta urinib ko'ring.")
        await callback.answer()
        return

    if new_items:
        await status_msg.edit_text(f"✅ {len(new_items)} ta yangi litsenziya topildi!")
        doc_numbers = [item["doc_number"] for item in new_items]
        rows = get_edu_licenses_by_doc_numbers(doc_numbers)
        for row in rows:
            await callback.message.answer(format_license(row), parse_mode="Markdown")
    else:
        await status_msg.edit_text("✅ Yangi litsenziya topilmadi.")