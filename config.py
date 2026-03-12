import os

from dotenv import load_dotenv

if load_dotenv is not None:
	load_dotenv()


def parse_authorized_user_ids(raw_value):
	if not raw_value:
		return []

	user_ids = []
	for chunk in raw_value.split(","):
		item = chunk.strip()
		if not item:
			continue
		try:
			user_ids.append(int(item))
		except ValueError:
			continue
	return user_ids

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "registry.db")
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "4"))
BASE_URL = "https://license.gov.uz/registry"
FILTER_PARAMS = "?filter%5Bdocument_id%5D=4409&filter%5Bdocument_type%5D=LICENSE"
CHROME_VERSION = int(os.getenv("CHROME_VERSION", "145"))
TARGET_ACTIVITY = os.getenv("TARGET_ACTIVITY", "Oliy ta'lim xizmatlari")
SCRAPER_WAIT_TIMEOUT = int(os.getenv("SCRAPER_WAIT_TIMEOUT", "30"))
SCRAPER_RETRY_COUNT = int(os.getenv("SCRAPER_RETRY_COUNT", "2"))
AUTHORIZED_USER_IDS = parse_authorized_user_ids(os.getenv("AUTHORIZED_USER_IDS", ""))
BROWSER_PROFILE_DIR = os.getenv("BROWSER_PROFILE_DIR", "browser_profile")
# Sinov uchun 3, ishlab chiqarish uchun 0 (cheklovsiz)
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "3"))
# Ubuntu server: ekransiz muhitda True qiling
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
