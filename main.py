import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, CHECK_INTERVAL_HOURS, AUTHORIZED_USER_IDS
from database import (
    get_unnotified,
    init_db,
    mark_notified_bulk,
    set_scan_meta,
)
from handlers import router
from scan_runtime import run_scan

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Muhit o'zgaruvchisi orqali sozlang.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)


async def notify_new_licenses(unnotified):
    users = AUTHORIZED_USER_IDS
    if not users:
        logging.info("AUTHORIZED_USER_IDS bo'sh. Xabar yuborilmadi")
        return

    for user_id in users:
        try:
            await bot.send_message(
                user_id,
                f"🔔 {len(unnotified)} ta yangi Oliy ta'lim litsenziyasi topildi"
            )
        except Exception as exc:
            logging.warning("Sarlavha xabarini yuborishda xato. user_id=%s error=%s", user_id, exc)

    sent_doc_numbers = []
    for doc_number, file_token, org_name in unnotified:
        status = "✅ Faol"
        token_info = f"\n📎 Token: `{file_token}`" if file_token else ""
        text = f"🏫 *{org_name}*\n📄 `{doc_number}`\n{status}{token_info}"

        delivered_to_all = True
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode="Markdown")
            except Exception as exc:
                logging.warning("Xabar yuborishda xato. user_id=%s error=%s", user_id, exc)
                delivered_to_all = False

        if delivered_to_all:
            sent_doc_numbers.append(doc_number)

    mark_notified_bulk(sent_doc_numbers)


async def auto_check():
    logging.info("Auto-check boshlandi")
    set_scan_meta("last_scan_status", "running")
    set_scan_meta("last_scan_mode", "scheduled")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, run_scan)
        if result is None:
            logging.warning("Scan allaqachon ishlayapti. Auto-check sikli o'tkazib yuborildi")
            set_scan_meta("last_scan_status", "skipped_locked")
            return
        set_scan_meta("last_scan_status", "success")
    except Exception as exc:
        set_scan_meta("last_scan_status", f"failed: {exc}")
        logging.exception("Auto-check xatolik bilan tugadi")
        return
    finally:
        set_scan_meta("last_scan_at", datetime.now(timezone.utc).isoformat())

    unnotified = get_unnotified()
    if unnotified:
        await notify_new_licenses(unnotified)
        logging.info("Yuborilgan yangi litsenziyalar soni: %s", len(unnotified))
    else:
        logging.info("Yangi litsenziya topilmadi")


async def main():
    init_db()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(auto_check, "interval", hours=CHECK_INTERVAL_HOURS)
    scheduler.start()

    logging.info("Bot ishga tushdi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
