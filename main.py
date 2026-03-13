import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.types import FSInputFile

from config import BOT_TOKEN, CHECK_INTERVAL_HOURS, AUTHORIZED_USER_IDS, DB_PATH
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
    raise RuntimeError("BOT_TOKEN topilmadi.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)


async def notify_new_licenses(unnotified):
    users = AUTHORIZED_USER_IDS
    if not users:
        logging.info("AUTHORIZED_USER_IDS bo'sh.")
        return

    caption = f"🔔 {len(unnotified)} ta yangi Oliy ta'lim litsenziyasi topildi"
    db_file = FSInputFile(DB_PATH, filename="registry.db")

    sent_doc_numbers = []
    all_delivered = True

    for user_id in users:
        try:
            await bot.send_document(
                user_id,
                document=db_file,
                caption=caption,
            )
            sent_doc_numbers = [row[0] for row in unnotified]
        except Exception as exc:
            logging.warning("Xabar yuborishda xato. user_id=%s error=%s", user_id, exc)
            all_delivered = False

    if sent_doc_numbers:
        mark_notified_bulk(sent_doc_numbers)


async def auto_check():
    logging.info("Auto-check boshlandi")
    set_scan_meta("last_scan_status", "running")
    set_scan_meta("last_scan_mode", "scheduled")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, run_scan)
        if result is None:
            logging.warning("Scan allaqachon ishlayapti — o'tkazildi")
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
        logging.info("Yangi litsenziyalar: %s", len(unnotified))
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