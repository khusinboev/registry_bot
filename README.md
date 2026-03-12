# Registry Bot

Bu bot `license.gov.uz` registridan ma'lumot yig'adi, modal ichida `Oliy ta'lim xizmatlari` faoliyat turini tekshiradi, topilgan yangi yozuvlarni SQLite bazaga saqlaydi va har 4 soatda authorized userlarga xabar yuboradi.

## 1) O'rnatish

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) Konfiguratsiya

1. `.env.example` dan `.env` yarating.
2. `BOT_TOKEN` ni to'ldiring.

```powershell
Copy-Item .env.example .env
```

## 3) Ishga tushirish

```powershell
python main.py
```

## 4) Qanday ishlaydi

- Birinchi run: to'liq scan (`full_scan`) bajaradi.
- Har 4 soatda: scheduler yangi scan qiladi.
- Dedupe: `doc_number` primary key bo'yicha.
- Notify: `edu_licenses.notified=0` bo'lgan yozuvlar authorized userlarga yuboriladi.

## 5) Muhim ENV o'zgaruvchilar

- `BOT_TOKEN` — Telegram bot tokeni.
- `CHECK_INTERVAL_HOURS` — auto-check interval (default `4`).
- `CHROME_VERSION` — undetected-chromedriver uchun major version (default `145`).
- `TARGET_ACTIVITY` — modal filter (default `Oliy ta'lim xizmatlari`).
- `SCRAPER_WAIT_TIMEOUT` — sahifa kutish timeouti.
- `SCRAPER_RETRY_COUNT` — sahifa qayta urinish soni.
