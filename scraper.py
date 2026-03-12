"""
scraper.py
==========
Barcha sahifalarni bitta doimiy brauzer sessiyasi orqali skanerlaydi.

Oqim:
  1. ensure_startup_navigation()
       - Avvalgi sikldan qolgan tablarni yopish
       - YouTube ochib "uzbekistan" qidirish (anti-detection isitish)
       - Yangi tabda registry page=1 ochish
  2. Sahifalar sonini joriy yuklanmadan o'qish
  3. Har sahifada (joriy tabda navigate):
       - Sahifa yuklanguncha kutish
           * activity_types allaqachon saqlangan bo'lsa o'tish
           * Qatorga siljib natural click → modal ochilguncha kutish
           * Modal ichidan faoliyat turlari + file token olish
           * Qatorga siljib natural click → modal ochilguncha kutish
           * save_edu_license() — filtersiz saqlash
           * Escape bilan modalni yopish
           * (Oliy ta'lim bo'lsa) save_edu_license()
       - Sahifalar orasida tabiiy pauza

Qo'shimcha tab OCHILMAYDI — hamma ish joriy tabda inline bajariladi.
"""

import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    BASE_URL,
    BROWSER_PROFILE_DIR,
    CHROME_VERSION,
    FILTER_PARAMS,
    HEADLESS,
    PAGE_LIMIT,
    SCRAPER_RETRY_COUNT,
    SCRAPER_WAIT_TIMEOUT,
)
from database import edu_license_has_details, save_document, save_edu_license

# ── CSS konstantalar ────────────────────────────────────────────────────────
TARGET_CSS   = "td.Table_cell__2s5cE"          # jadval hujayralari
ROW_CSS      = "tr.Table_row__pqKpz, tbody tr"  # jadval qatorlari
DEBUG_DIR    = Path("debug_artifacts")

# Modal selectorlar — real HTML dan olingan aniq selectorlar
# Artifact: Modal_container__3Wm3u-id, Modal_content__BZbGL
MODAL_SELECTORS = [
    "#Modal_container__3Wm3u-id",
    ".Modal_content__BZbGL",
    "[class*='Modal_container']",
    "[class*='Modal_content']",
]

# ── Yagona driver instance ───────────────────────────────────────────────────
_DRIVER = None


def is_driver_alive(driver):
    try:
        _ = driver.current_url
        _ = driver.window_handles
        return True
    except Exception:
        return False


def init_driver():
    print("[SCRAPER] init_driver start")
    # Profil va chromedriver keshi loyiha papkasida saqlanadi (Ubuntu uchun ham ishlaydi)
    profile_mode = "headless" if HEADLESS else "headed"
    profile_dir_name = f"{BROWSER_PROFILE_DIR}_{profile_mode}"
    profile_path = os.path.abspath(profile_dir_name)
    os.makedirs(profile_path, exist_ok=True)
    print(f"[SCRAPER] profile path: {profile_path}")

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Ubuntu server uchun zarur argumentlar
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    if HEADLESS:
        options.add_argument("--headless=new")

    # chromedriver binary loyiha papkasida saqlansin (server uchun qulay)
    # Windows: chromedriver.exe, Linux/Mac: chromedriver
    _cd_candidates = [
        os.path.abspath("chromedriver.exe"),
        os.path.abspath("chromedriver"),
    ]
    driver_executable_path = next((p for p in _cd_candidates if os.path.exists(p)), None)
    if driver_executable_path:
        print(f"[SCRAPER] local chromedriver ishlatilmoqda: {driver_executable_path}")
    print("[SCRAPER] starting uc.Chrome")
    driver = uc.Chrome(
        version_main=CHROME_VERSION,
        options=options,
        driver_executable_path=driver_executable_path,
    )
    driver.set_page_load_timeout(120)
    print("[SCRAPER] init_driver done")
    return driver


def get_or_create_driver():
    global _DRIVER
    if _DRIVER is not None and is_driver_alive(_DRIVER):
        print("[SCRAPER] reusing existing driver")
        return _DRIVER
    print("[SCRAPER] creating new driver")
    _DRIVER = init_driver()
    return _DRIVER


# ── Kutish yordamchilari ─────────────────────────────────────────────────────

def human_delay(min_sec=0.6, max_sec=1.8):
    """Odamga o'xshash tasodifiy pauza — bot signalini kamaytiradi."""
    time.sleep(random.uniform(min_sec, max_sec))


def debug_artifact_path(prefix, suffix):
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return DEBUG_DIR / f"{stamp}_{prefix}{suffix}"


def save_debug_snapshot(driver, prefix):
    """Modal yoki page muammosida screenshot va HTML saqlaydi."""
    try:
        screenshot_path = debug_artifact_path(prefix, ".png")
        driver.save_screenshot(str(screenshot_path))
        print(f"  Debug screenshot saqlandi: {screenshot_path}")
    except Exception as exc:
        print(f"  Screenshot saqlanmadi: {exc}")

    try:
        html_path = debug_artifact_path(prefix, ".html")
        html_path.write_text(driver.page_source, encoding="utf-8")
        print(f"  Debug HTML saqlandi: {html_path}")
    except Exception as exc:
        print(f"  HTML saqlanmadi: {exc}")


def wait_for_data(driver, timeout=SCRAPER_WAIT_TIMEOUT):
    """Jadval hujayralari paydo bo'lguncha kutish."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, TARGET_CSS))
        )
        return True
    except Exception:
        return False


def wait_for_modal(driver, timeout=20):
    """Modal ko'ringuncha kutish; birinchi ko'rinadigan elementni qaytaradi."""
    for css in MODAL_SELECTORS:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, css))
            )
            if el and el.is_displayed():
                return el
        except Exception:
            continue
    return None


def _any_modal_visible(driver):
    """Hech bo'lmasa bitta modal ko'rinib turganligini tekshirish."""
    for css in MODAL_SELECTORS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, css)
            if any(el.is_displayed() for el in els):
                return True
        except Exception:
            pass
    return False


def _wait_modal_gone_quick(driver, timeout=12):
    """Barcha modallar ko'rinmas bo'lguncha kutish. True=yo'qoldi."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _any_modal_visible(driver):
            return True
        time.sleep(0.3)
    return False


def wait_for_modal_gone(driver, timeout=12):
    _wait_modal_gone_quick(driver, timeout)


# ── Harakat yordamchilari ────────────────────────────────────────────────────

def scroll_into_view(driver, element):
    """Elementni markazga siljitish — tabiiy scroll taqlidi."""
    driver.execute_script(
        "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
        element,
    )
    time.sleep(random.uniform(0.3, 0.7))


def close_modal(driver):
    """
    Modalni ishonchli yopish:
      1. Drawer/Modal ichidagi X (close) tugmasini topib bosish
      2. Overlay/backdrop bosish
      3. Escape tugmasi
    Har urinishdan keyin yopilganini tekshiradi.
    """
    # 1. Close div — real HTML: <div class="ModalNav_close__1lmq4">
    for css in [".ModalNav_close__1lmq4", "[class*='ModalNav_close']"]:
        try:
            close_el = WebDriverWait(driver, 3).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, css))
            )
            print(f"  Modal close selector ishlatildi: {css}")
            driver.execute_script("arguments[0].click();", close_el)  # JS click (div uchun ishonchli)
            if _wait_modal_gone_quick(driver, 6):
                human_delay(0.3, 0.6)
                return
            break
        except Exception:
            continue

    # 2. Backdrop bosish — real HTML: <div class="Modal_backdrop__1mf1y">
    for css in [".Modal_backdrop__1mf1y", "[class*='Modal_backdrop']", "[class*='backdrop']", "[class*='Overlay']"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, css)
            if el.is_displayed():
                print(f"  Modal overlay selector ishlatildi: {css}")
                el.click()
                if _wait_modal_gone_quick(driver, 6):
                    human_delay(0.3, 0.6)
                    return
        except Exception:
            continue

    # 3. Escape (oxirgi chora)
    try:
        print("  Modal ESC bilan yopishga urinish")
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        if _wait_modal_gone_quick(driver, 10):
            human_delay(0.4, 0.8)
            return
    except Exception:
        pass

    print("  Modal yopilmadi — debug snapshot olinmoqda")
    save_debug_snapshot(driver, "modal_not_closed")
    human_delay(0.4, 0.8)


def ensure_no_modal(driver):
    """Har click oldidan: modal ochiq bo'lsa majburan yopish."""
    if _any_modal_visible(driver):
        print("  Ochiq modal topildi — yopilmoqda...")
        close_modal(driver)
        human_delay(0.3, 0.6)


def close_details_view(driver, row_index=None):
    """
    Batafsil ko'rinishni yopish.
    Modal ustidagi aniq close/backdrop logikasi bilan yopiladi.
    Row reclick bu sahifada ishonchli emas, chunki click ko'pincha modal elementlari bilan intercept qilinadi.
    """
    close_modal(driver)


def navigate_and_wait(driver, url):
    """
    Berilgan URL ga o'tib, jadval yuklanguncha kutish.
    SCRAPER_RETRY_COUNT marta qayta urinib ko'radi.
    """
    for attempt in range(SCRAPER_RETRY_COUNT + 1):
        try:
            driver.get(url)
        except Exception:
            pass

        if wait_for_data(driver):
            human_delay(0.5, 1.2)
            return True

        if attempt < SCRAPER_RETRY_COUNT:
            print(f"  Sahifa yuklanmadi — qayta urinish {attempt + 1}/{SCRAPER_RETRY_COUNT}...")
            human_delay(3.0, 6.0)
            try:
                driver.refresh()
            except Exception:
                pass

    return False


# ── Ajratib olish yordamchilari ──────────────────────────────────────────────

def extract_file_token_from_modal(driver):
    """
    Modal ichida "Ҳужжат" tabini bosib, hujjat havolasidan UUID tokenini oladi.
    URL ko'rinishi: https://doc.licenses.uz/v1/certificate/uuid/UUID_SHUYER/pdf?...
    """
    try:
        # "Ҳужжат" tab — ikkinchi tab (faol emas)
        tabs = driver.find_elements(By.CSS_SELECTOR, "[class*='RegistryView_tabItem']")
        doc_tab = None
        for tab in tabs:
            if tab.get_attribute("class") and "tabItemActive" not in tab.get_attribute("class"):
                doc_tab = tab
                break
        if doc_tab is None and len(tabs) >= 2:
            doc_tab = tabs[1]
        if doc_tab is None:
            return None

        driver.execute_script("arguments[0].click();", doc_tab)

        # DocumentGenerator yuklanguncha kutish
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[class*='DocumentGenerator_wrapper'] a[href*='/certificate/uuid/']")
                )
            )
        except Exception:
            pass

        links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='/certificate/uuid/']"
        )
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r'/certificate/uuid/([0-9a-f\-]{30,})', href)
            if m:
                return m.group(1)
    except Exception as exc:
        print(f"  file_token olishda xato: {exc}")
    return None


def extract_activity_types_from_modal(driver, modal, timeout=10):
    """"Faoliyat turlari" blokini kutib, barcha matnlarni yig'adi."""
    section_titles = ["Фаолият турлари", "Faoliyat turlari"]

    def _read_activity_types(_driver):
        try:
            wrappers = modal.find_elements(By.CSS_SELECTOR, "[class*='List_wrapper']")
        except Exception:
            return False

        for wrapper in wrappers:
            try:
                title_el = wrapper.find_element(By.CSS_SELECTOR, "[class*='List_title']")
                title_text = (title_el.text or "").strip()
            except Exception:
                continue

            if not any(section_title.lower() in title_text.lower() for section_title in section_titles):
                continue

            texts = []
            for css in [
                "[class*='List_itemDescription'] p",
                "[class*='List_itemDescription']",
                "[class*='List_itemContent']",
            ]:
                try:
                    for element in wrapper.find_elements(By.CSS_SELECTOR, css):
                        text_value = (element.text or "").strip()
                        if text_value and text_value not in texts:
                            texts.append(text_value)
                except Exception:
                    continue

            if texts:
                return "\n".join(texts)
        return False

    try:
        return WebDriverWait(driver, timeout).until(_read_activity_types)
    except Exception:
        return ""


def extract_is_active_from_modal(modal):
    """
    Modal tepasidagi InfoBlock dan hujjat holatini o'qiydi.
    HTML: <div class="InfoBlock_wrapper--green..."><div>Ҳолати</div><div>Фаол</div></div>
    Faol=1, boshqa holat=0. Aniqlab bo'lmasa None qaytaradi.
    """
    try:
        wrappers = modal.find_elements(By.CSS_SELECTOR, "[class*='InfoBlock_wrapper']")
        for wrapper in wrappers:
            try:
                title = wrapper.find_element(By.CSS_SELECTOR, "[class*='InfoBlock_title']").text.strip()
            except Exception:
                continue
            if "олати" not in title and "holat" not in title.lower():
                continue
            try:
                desc = wrapper.find_element(By.CSS_SELECTOR, "[class*='InfoBlock_description']").text.strip()
            except Exception:
                continue
            cls = wrapper.get_attribute("class") or ""
            # green class = faol; yoki matn "Фаол" / "Faol"
            if "green" in cls or "аол" in desc or desc.lower() == "faol":
                return 1
            return 0
    except Exception:
        pass
    return None  # aniqlab bo'lmadi — jadval qatoridan kelgan qiymat saqlanadi


# ── Pagination ───────────────────────────────────────────────────────────────

def get_total_pages_from_current(driver):
    """
    Joriy yuklanmadan sahifalar sonini aniqlash.
    Pagination to'liq render bo'lishini kutib, barcha raqamli tugmalardan max ni oladi.
    """
    # Pagination elementini kutish
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='Pagination']"))
        )
        time.sleep(1.5)
    except Exception:
        pass
    try:
        btns = driver.find_elements(
            By.CSS_SELECTOR,
            "button.Pagination_page__YrHMb, [class*='Pagination'] button, [class*='pagination'] button, [class*='Pagination'] a[aria-label^='Page '], [class*='pagination'] a[aria-label^='Page ']",
        )
        nums = []
        for btn in btns:
            text_value = (btn.text or "").strip()
            aria_label = (btn.get_attribute("aria-label") or "").strip()
            if text_value.isdigit():
                nums.append(int(text_value))
                continue
            match = re.search(r"Page\s+(\d+)", aria_label, flags=re.IGNORECASE)
            if match:
                nums.append(int(match.group(1)))
        print(f"  Pagination raqamlari topildi: {sorted(set(nums))}")
        if nums:
            return max(nums)
    except Exception:
        pass

    try:
        html = driver.page_source
        patterns = [
            r"pageCount['\"]?\s*[:=]\s*(\d+)",
            r"totalPages['\"]?\s*[:=]\s*(\d+)",
            r"lastPage['\"]?\s*[:=]\s*(\d+)",
        ]
        candidates = []
        for pattern in patterns:
            candidates.extend(int(value) for value in re.findall(pattern, html, flags=re.IGNORECASE))
        if candidates:
            print(f"  HTML page candidates: {sorted(set(candidates))[:10]} ... max={max(candidates)}")
            return max(candidates)
    except Exception:
        pass

    return 1


# ── Startup oqimi ────────────────────────────────────────────────────────────

def _try_youtube_warmup(driver):
    """
    YouTube ochib qidiruv qilish — anti-detection uchun.
    Har qanday xatoda (cookie banner, consent, timeout) darhol qaytadi,
    asosiy scan jarayonini BLOKLAMAYDI.
    """
    try:
        driver.execute_script("window.location.href = arguments[0];", "https://www.youtube.com")
        human_delay(1.0, 2.0)
        print("[SCRAPER] youtube navigation triggered")
    except Exception as exc:
        print(f"[SCRAPER] youtube warmup timeout/xato: {exc}")
        return

    # Search input yoki consent DOM'ini kutib turmasdan, bevosita qidiruv natijasiga o'tish
    try:
        driver.execute_script(
            "window.location.href = arguments[0];",
            "https://www.youtube.com/results?search_query=uzbekistan",
        )
        human_delay(1.2, 2.5)
        print("[SCRAPER] youtube search triggered")
    except Exception:
        pass  # Topilmasa ham davom etamiz


def ensure_startup_navigation(driver):
    """
    Har scan oldidan:
      1. Eski qo'shimcha tablarni yopish
      2. 1-tabda YouTube isitish (xato bo'lsa o'tkaziladi)
      3. Yangi (2-) tabda registry page=1 ochish va yuklanguncha kutish
    """
    print("[SCRAPER] startup navigation begin")
    # 1. Avvalgi sikldan qolgan tablarni tozalash
    try:
        handles = driver.window_handles
        if len(handles) > 1:
            for handle in handles[1:]:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    pass
        driver.switch_to.window(driver.window_handles[0])
    except Exception:
        pass

    # 2. YouTube isitish (non-blocking)
    print("[SCRAPER] youtube warmup")
    _try_youtube_warmup(driver)

    # 3. Xuddi shu tabda registry ga o'tish (window.open bloklanshligi mumkin)
    registry_url = f"{BASE_URL}{FILTER_PARAMS}&page=1"
    print(f"[SCRAPER] opening registry url: {registry_url}")
    try:
        driver.get(registry_url)
    except Exception as exc:
        print(f"[SCRAPER] registry get xato: {exc}")

    wait_for_data(driver)
    human_delay(0.5, 1.2)
    print(f"[SCRAPER] startup navigation done, current url: {driver.current_url}")


# ── Sahifa protsessori ───────────────────────────────────────────────────────

def process_current_page(driver, page_num, new_edu_licenses, status_callback=None, row_limit=None):
    """
    Joriy sahifadagi qatorlarni ikki bosqichda ko'rib chiqadi:
      1. Avval barcha qatorlarning ma'lumotlarini yig'ish (click qilmasdan)
      2. Har bir yangi hujjat uchun DOM'ni qayta fetch qilib, aniq qatorni bosish
         → Modal ochilguncha kutish → Ma'lumot o'qish → Modalni ishonchli yopish
    Stale element xatosining oldini oladi.
    """
    # ── BOSQICH 1: barcha qatorlarning statik ma'lumotlarini yig'ish ───────
    rows_data = []
    try:
        raw_rows = driver.find_elements(By.CSS_SELECTOR, ROW_CSS)
        for raw_row in raw_rows:
            try:
                cells = raw_row.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE, td")
                if len(cells) < 6:
                    continue
                doc_number = cells[2].text.strip()
                org_name   = cells[1].text.strip()
                # cells[5] ishonchli emas — modal ochilganda aniq qiymat bilan overwrite qilinadi
                # Boshlang'ich qiymat: "nofaol"/"inactive" bo'lmasa faol deb hisoblaymiz
                cell5_text = cells[5].text.strip()
                is_active  = 0 if ("nofaol" in cell5_text.lower() or
                                    "inactive" in cell5_text.lower() or
                                    "нофаол" in cell5_text.lower()) else 1
                if doc_number:
                    rows_data.append((doc_number, org_name, is_active))
            except Exception:
                continue
    except Exception as exc:
        print(f"  Sahifa {page_num} qatorlarini o'qishda xato: {exc}")
        return

    if not rows_data:
        print(f"  Sahifa {page_num}: hech qanday qator topilmadi")
        return

    print(f"  Sahifa {page_num}: {len(rows_data)} ta qator topildi")

    # ── BOSQICH 2: har qator uchun modal ───────────────────────────────────
    if row_limit is not None:
        rows_data = rows_data[:row_limit]

    for data_idx, (doc_number, org_name, is_active) in enumerate(rows_data):
        # Asosiy jadvalga doim saqlash
        save_document(doc_number, is_active)

        # Batafsil ma'lumotlari allaqachon bazada bo'lsa — modal kerak emas
        if edu_license_has_details(doc_number):
            continue

        if status_callback:
            status_callback(
                f"Sahifa {page_num}, {data_idx + 1}/{len(rows_data)}: {doc_number}"
            )
        print(f"  Tekshirilmoqda: {doc_number} ({org_name})")
        if status_callback:
            status_callback(f"{doc_number} uchun batafsil ma'lumot ochilmoqda...")

        # Click oldidan ochiq modal bo'lsa yopish
        ensure_no_modal(driver)

        # DOM'ni qayta fetch — stale element xatosini oldini olish
        try:
            live_rows = driver.find_elements(By.CSS_SELECTOR, ROW_CSS)
            data_rows = [
                r for r in live_rows
                if len(r.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE, td")) >= 6
            ]
            if data_idx >= len(data_rows):
                print(f"  Qator indeksi {data_idx} topilmadi — o'tkazildi")
                continue
            target_row = data_rows[data_idx]
        except Exception as exc:
            print(f"  DOM qayta fetch xatosi: {exc}")
            continue

        # Qatorga siljib natural click
        try:
            scroll_into_view(driver, target_row)
            human_delay(0.5, 1.1)
            target_row.click()
        except Exception as exc:
            print(f"  Click xatosi ({doc_number}): {exc}")
            ensure_no_modal(driver)
            continue

        # Modal ochilib, ichki ma'lumotlar yuklanguncha kutish
        modal = wait_for_modal(driver)
        if modal is None:
            print(f"  Modal ochilmadi: {doc_number} — o'tkazildi")
            save_debug_snapshot(driver, f"modal_not_opened_page{page_num}_{data_idx+1}")
            ensure_no_modal(driver)
            continue

        human_delay(1.0, 1.8)
        activity_types = extract_activity_types_from_modal(driver, modal, timeout=12)
        # Holatni modal InfoBlock dan o'qish — jadval qatoridan ishonchliroq
        modal_is_active = extract_is_active_from_modal(modal)
        if modal_is_active is not None:
            if modal_is_active != is_active:
                print(f"  Holat to'g'irlandi: jadval={is_active} → modal={modal_is_active} ({doc_number})")
            is_active = modal_is_active
        file_token = extract_file_token_from_modal(driver)
        if status_callback:
            status_callback(f"{doc_number} uchun batafsil ma'lumot o'qildi, yopilmoqda...")
        if activity_types:
            print(f"  Faoliyat turlari olindi: {activity_types[:160]}")
        else:
            print(f"  Faoliyat turlari topilmadi: {doc_number}")

        # Modalni yopish va yo'qolishini tasdiqlash
        close_details_view(driver, row_index=data_idx)
        if _any_modal_visible(driver):
            print(f"  Modal hali ham ochiq: {doc_number}")
            save_debug_snapshot(driver, f"modal_still_open_page{page_num}_{data_idx+1}")
        elif status_callback:
            status_callback(f"{doc_number} yopildi, keyingi yozuvga o'tilmoqda...")
        human_delay(0.7, 1.5)

        save_edu_license(doc_number, file_token, org_name, activity_types, is_active)
        new_edu_licenses.append(
            {
                "doc_number": doc_number,
                "org_name": org_name,
                "is_active": is_active,
                "activity_types": activity_types,
            }
        )
        print(f"  [+] Saqlandi: {doc_number} | {org_name}")


# ── Asosiy kirish nuqtasi ────────────────────────────────────────────────────

def full_scan(status_callback=None, page_limit=PAGE_LIMIT, row_limit=None):
    """
    Barcha sahifalarni skanerlaydi.
    Har sahifadagi qatorlar inline (shu sahifada) ko'rib chiqiladi.
    """
    driver = get_or_create_driver()
    new_edu_licenses = []

    try:
        print("[SCRAPER] full_scan start")
        if status_callback:
            status_callback("Brauzer tayyorlanmoqda...")

        ensure_startup_navigation(driver)

        # Sahifalar soni hozir ochiq yuklanmadan o'qiladi
        total_pages = get_total_pages_from_current(driver)
        print(f"Jami {total_pages} ta sahifa")

        if status_callback:
            status_callback(f"Jami {total_pages} sahifa. Skanerlash boshlandi...")

        # Sahifa 1 allaqachon ochiq — to'g'ri ishlatamiz
        if status_callback:
            status_callback(f"Sahifa 1/{total_pages} ishlanmoqda...")
        process_current_page(driver, 1, new_edu_licenses, status_callback, row_limit=row_limit)

        # Sahifalar 2..N: joriy tabda navigate
        last_page = min(total_pages, page_limit) if page_limit and page_limit > 0 else total_pages
        for page in range(2, last_page + 1):
            if status_callback:
                status_callback(f"Sahifa {page}/{last_page} yuklanmoqda...")

            url = f"{BASE_URL}{FILTER_PARAMS}&page={page}"
            if not navigate_and_wait(driver, url):
                print(f"  Sahifa {page} yuklanmadi — o'tkazildi")
                save_debug_snapshot(driver, f"page_not_loaded_{page}")
                continue

            process_current_page(driver, page, new_edu_licenses, status_callback, row_limit=row_limit)

            # Sahifalar orasida tabiiy pauza
            human_delay(1.2, 3.0)

        print(f"Yangi oliy ta'lim litsenziyalari: {len(new_edu_licenses)}")

    except Exception:
        global _DRIVER
        _DRIVER = None
        raise

    return new_edu_licenses