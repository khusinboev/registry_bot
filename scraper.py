"""
scraper.py — ishonchli, shoshmasdan ishlaydigan versiya
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

# ── CSS konstantalar ──────────────────────────────────────────────────────────
DESKTOP_ROW_CSS  = "tr.Table_row__329lz"
DESKTOP_CELL_CSS = "td.Table_cell__2s5cE"
MOBILE_ROW_CSS   = "div.RegistryPage_tableMobileWrapper__3oxDb"
DEBUG_DIR        = Path("debug_artifacts")

MODAL_SELECTORS = [
    "#Modal_container__3Wm3u-id",
    ".Modal_content__BZbGL",
    "[class*='Modal_container']",
    "[class*='Modal_content']",
]

_DRIVER = None


# ── Driver ────────────────────────────────────────────────────────────────────

def is_driver_alive(driver):
    try:
        _ = driver.current_url
        _ = driver.window_handles
        return True
    except Exception:
        return False


def init_driver():
    print("[SCRAPER] init_driver start")
    profile_mode     = "headless" if HEADLESS else "headed"
    profile_dir_name = f"{BROWSER_PROFILE_DIR}_{profile_mode}"
    profile_path     = os.path.abspath(profile_dir_name)
    os.makedirs(profile_path, exist_ok=True)
    print(f"[SCRAPER] profile path: {profile_path}")

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if HEADLESS:
        options.add_argument("--headless=new")

    _cd_candidates = [
        os.path.abspath("chromedriver.exe"),
        os.path.abspath("chromedriver"),
    ]
    driver_executable_path = next(
        (p for p in _cd_candidates if os.path.exists(p)), None
    )
    if driver_executable_path:
        print(f"[SCRAPER] local chromedriver: {driver_executable_path}")

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


# ── Yordamchilar ──────────────────────────────────────────────────────────────

def human_delay(min_sec=0.8, max_sec=2.0):
    time.sleep(random.uniform(min_sec, max_sec))


def debug_artifact_path(prefix, suffix):
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return DEBUG_DIR / f"{stamp}_{prefix}{suffix}"


def save_debug_snapshot(driver, prefix):
    try:
        path = debug_artifact_path(prefix, ".png")
        driver.save_screenshot(str(path))
        print(f"  Screenshot: {path}")
    except Exception as exc:
        print(f"  Screenshot xato: {exc}")
    try:
        path = debug_artifact_path(prefix, ".html")
        path.write_text(driver.page_source, encoding="utf-8")
        print(f"  HTML: {path}")
    except Exception as exc:
        print(f"  HTML xato: {exc}")


def scroll_into_view(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
        element,
    )
    time.sleep(random.uniform(0.4, 0.9))


# ── Kutish ────────────────────────────────────────────────────────────────────

def _page_has_rows(driver):
    if driver.find_elements(By.CSS_SELECTOR, DESKTOP_ROW_CSS):
        return True
    return bool(driver.find_elements(By.CSS_SELECTOR, MOBILE_ROW_CSS))


def wait_for_data(driver, timeout=SCRAPER_WAIT_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _page_has_rows(driver):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def wait_for_modal(driver, timeout=25):
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
    for css in MODAL_SELECTORS:
        try:
            if any(
                el.is_displayed()
                for el in driver.find_elements(By.CSS_SELECTOR, css)
            ):
                return True
        except Exception:
            pass
    return False


def _wait_modal_gone(driver, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _any_modal_visible(driver):
            return True
        time.sleep(0.3)
    return False


# ── Modal ─────────────────────────────────────────────────────────────────────

def close_modal(driver):
    for css in [".ModalNav_close__1lmq4", "[class*='ModalNav_close']"]:
        try:
            el = WebDriverWait(driver, 4).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, css))
            )
            driver.execute_script("arguments[0].click();", el)
            if _wait_modal_gone(driver, 8):
                human_delay(0.3, 0.6)
                return
        except Exception:
            continue

    for css in [
        ".Modal_backdrop__1mf1y",
        "[class*='Modal_backdrop']",
        "[class*='backdrop']",
        "[class*='Overlay']",
    ]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, css)
            if el.is_displayed():
                el.click()
                if _wait_modal_gone(driver, 8):
                    human_delay(0.3, 0.6)
                    return
        except Exception:
            continue

    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        if _wait_modal_gone(driver, 12):
            human_delay(0.4, 0.8)
            return
    except Exception:
        pass

    print("  Modal yopilmadi — snapshot")
    save_debug_snapshot(driver, "modal_not_closed")
    human_delay(0.5, 1.0)


def ensure_no_modal(driver):
    if _any_modal_visible(driver):
        print("  Ochiq modal — yopilmoqda...")
        close_modal(driver)
        human_delay(0.4, 0.8)


# ── Ma'lumot ajratish ─────────────────────────────────────────────────────────

def extract_file_token_from_modal(driver):
    try:
        tabs = driver.find_elements(
            By.CSS_SELECTOR, "[class*='RegistryView_tabItem']"
        )
        doc_tab = None
        for tab in tabs:
            cls = tab.get_attribute("class") or ""
            if "tabItemActive" not in cls:
                doc_tab = tab
                break
        if doc_tab is None and len(tabs) >= 2:
            doc_tab = tabs[1]
        if doc_tab is None:
            return None

        driver.execute_script("arguments[0].click();", doc_tab)
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a[href*='/certificate/uuid/']")
                )
            )
        except Exception:
            pass

        for link in driver.find_elements(
            By.CSS_SELECTOR, "a[href*='/certificate/uuid/']"
        ):
            href = link.get_attribute("href") or ""
            m = re.search(r"/certificate/uuid/([0-9a-f\-]{30,})", href)
            if m:
                return m.group(1)
    except Exception as exc:
        print(f"  file_token xato: {exc}")
    return None


def extract_activity_types_from_modal(driver, modal, timeout=15):
    section_titles = ["Фаолият турлари", "Faoliyat turlari"]

    def _read(_driver):
        try:
            wrappers = modal.find_elements(By.CSS_SELECTOR, "[class*='List_wrapper']")
        except Exception:
            return False
        for wrapper in wrappers:
            try:
                title_text = wrapper.find_element(
                    By.CSS_SELECTOR, "[class*='List_title']"
                ).text.strip()
            except Exception:
                continue
            if not any(s.lower() in title_text.lower() for s in section_titles):
                continue
            texts = []
            for css in [
                "[class*='List_itemDescription'] p",
                "[class*='List_itemDescription']",
                "[class*='List_itemContent']",
            ]:
                try:
                    for el in wrapper.find_elements(By.CSS_SELECTOR, css):
                        t = (el.text or "").strip()
                        if t and t not in texts:
                            texts.append(t)
                except Exception:
                    continue
            if texts:
                return "\n".join(texts)
        return False

    try:
        return WebDriverWait(driver, timeout).until(_read)
    except Exception:
        return ""


def extract_is_active_from_modal(modal):
    try:
        for wrapper in modal.find_elements(
            By.CSS_SELECTOR, "[class*='InfoBlock_wrapper']"
        ):
            try:
                title = wrapper.find_element(
                    By.CSS_SELECTOR, "[class*='InfoBlock_title']"
                ).text.strip()
            except Exception:
                continue
            if "олати" not in title and "holat" not in title.lower():
                continue
            try:
                desc = wrapper.find_element(
                    By.CSS_SELECTOR, "[class*='InfoBlock_description']"
                ).text.strip()
            except Exception:
                continue
            cls = wrapper.get_attribute("class") or ""
            if "green" in cls or "аол" in desc or desc.lower() == "faol":
                return 1
            return 0
    except Exception:
        pass
    return None


# ── Row parsing ───────────────────────────────────────────────────────────────

def _parse_desktop_rows(driver):
    results = []
    try:
        for row in driver.find_elements(By.CSS_SELECTOR, DESKTOP_ROW_CSS):
            try:
                cells = row.find_elements(By.CSS_SELECTOR, DESKTOP_CELL_CSS)
                if len(cells) < 6:
                    continue
                # doc_number — td[1] ichidagi <span>
                span_els   = cells[1].find_elements(By.TAG_NAME, "span")
                doc_number = span_els[0].text.strip() if span_els else cells[1].text.strip().split("\n")[0]
                org_name   = cells[1].text.strip().replace(doc_number, "").strip()
                # status — td[5] innerHTML dan
                cell5_html = cells[5].get_attribute("innerHTML") or ""
                is_active  = 0 if ("danger" in cell5_html or "inactive" in cell5_html.lower()) else 1
                if doc_number:
                    results.append((doc_number, org_name, is_active, row))
            except Exception:
                continue
    except Exception as exc:
        print(f"  Desktop parse xato: {exc}")
    return results


def _parse_mobile_rows(driver):
    results = []
    try:
        for wrapper in driver.find_elements(By.CSS_SELECTOR, MOBILE_ROW_CSS):
            try:
                num_el   = wrapper.find_element(By.CSS_SELECTOR, "[class*='tableMobileNumber']")
                span_els = num_el.find_elements(By.TAG_NAME, "span")
                raw      = span_els[0].text.strip() if span_els else num_el.text.strip()
                parts    = raw.split(" ", 1)
                doc_number = parts[0].strip()
                org_name   = parts[1].strip() if len(parts) > 1 else ""
                try:
                    status_el = wrapper.find_element(By.CSS_SELECTOR, "[class*='Status_wrapper']")
                    cls       = status_el.get_attribute("class") or ""
                    is_active = 0 if ("danger" in cls or "inactive" in status_el.text.lower()) else 1
                except Exception:
                    is_active = 1
                if doc_number:
                    results.append((doc_number, org_name, is_active, wrapper))
            except Exception:
                continue
    except Exception as exc:
        print(f"  Mobile parse xato: {exc}")
    return results


def parse_rows(driver):
    desktop = _parse_desktop_rows(driver)
    if desktop:
        print(f"  Layout: desktop ({len(desktop)} qator)")
        return desktop
    mobile = _parse_mobile_rows(driver)
    if mobile:
        print(f"  Layout: mobile ({len(mobile)} qator)")
        return mobile
    return []


# ── Pagination ────────────────────────────────────────────────────────────────

def get_total_pages_from_current(driver):
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='Pagination']"))
        )
        time.sleep(2.0)
    except Exception:
        pass

    try:
        btns = driver.find_elements(
            By.CSS_SELECTOR,
            "button.Pagination_page__YrHMb, [class*='Pagination'] button, "
            "[class*='pagination'] button",
        )
        nums = []
        for btn in btns:
            t = (btn.text or "").strip()
            a = (btn.get_attribute("aria-label") or "").strip()
            if t.isdigit():
                nums.append(int(t))
            else:
                m = re.search(r"Page\s+(\d+)", a, re.IGNORECASE)
                if m:
                    nums.append(int(m.group(1)))
        print(f"  Pagination: {sorted(set(nums))}")
        if nums:
            return max(nums)
    except Exception:
        pass

    try:
        html = driver.page_source
        candidates = []
        for pat in [
            r"pageCount['\"]?\s*[:=]\s*(\d+)",
            r"totalPages['\"]?\s*[:=]\s*(\d+)",
            r"lastPage['\"]?\s*[:=]\s*(\d+)",
        ]:
            candidates.extend(int(v) for v in re.findall(pat, html, re.IGNORECASE))
        if candidates:
            return max(candidates)
    except Exception:
        pass

    return 1


# ── Navigate ──────────────────────────────────────────────────────────────────

def navigate_and_wait(driver, url, retries=None):
    """URL ga o'tib, qatorlar paydo bo'lguncha kutadi. Muvaffaqiyatsiz bo'lsa retry."""
    if retries is None:
        retries = SCRAPER_RETRY_COUNT

    for attempt in range(retries + 1):
        try:
            driver.get(url)
        except Exception as exc:
            print(f"  driver.get xato (attempt {attempt+1}): {exc}")

        if wait_for_data(driver):
            time.sleep(2.0)  # JS lazy-load uchun
            return True

        print(f"  Sahifa bo'sh/yuklanmadi — {attempt+1}/{retries} urinish")
        if attempt < retries:
            wait_time = 10.0 + attempt * 5.0  # 10s, 15s, 20s...
            print(f"  {wait_time:.0f} soniya kutilmoqda...")
            time.sleep(wait_time)
            try:
                driver.refresh()
            except Exception:
                pass

    return False


# ── Startup ───────────────────────────────────────────────────────────────────

def _try_youtube_warmup(driver):
    try:
        driver.execute_script("window.location.href = arguments[0];", "https://www.youtube.com")
        human_delay(1.5, 2.5)
    except Exception:
        return
    try:
        driver.execute_script(
            "window.location.href = arguments[0];",
            "https://www.youtube.com/results?search_query=uzbekistan",
        )
        human_delay(1.5, 2.5)
    except Exception:
        pass


def ensure_startup_navigation(driver):
    print("[SCRAPER] startup navigation begin")
    try:
        handles = driver.window_handles
        for handle in handles[1:]:
            try:
                driver.switch_to.window(handle)
                driver.close()
            except Exception:
                pass
        driver.switch_to.window(driver.window_handles[0])
    except Exception:
        pass

    print("[SCRAPER] youtube warmup")
    _try_youtube_warmup(driver)

    registry_url = f"{BASE_URL}{FILTER_PARAMS}&page=1"
    print(f"[SCRAPER] registry url: {registry_url}")
    try:
        driver.get(registry_url)
    except Exception as exc:
        print(f"[SCRAPER] registry get xato: {exc}")

    wait_for_data(driver)
    time.sleep(2.0)
    human_delay(0.5, 1.2)
    print(f"[SCRAPER] startup done: {driver.current_url}")


# ── Modal ochish va ma'lumot olish (retry bilan) ──────────────────────────────

def _open_modal_and_extract(driver, rows_data, idx, doc_number, page_num):
    """
    Modalni ochib activity_types, file_token, is_active oladi.
    3 marta urinadi. Muvaffaqiyatsiz bo'lsa (None, None, None) qaytaradi.
    """
    MAX_MODAL_RETRIES = 3

    for attempt in range(MAX_MODAL_RETRIES):
        ensure_no_modal(driver)

        # DOM dan qatorni qayta fetch
        try:
            live_rows = parse_rows(driver)
            if idx >= len(live_rows):
                print(f"  Indeks {idx} topilmadi (attempt {attempt+1})")
                return None, None, None
            target_el = live_rows[idx][3]
        except Exception as exc:
            print(f"  DOM refetch xato (attempt {attempt+1}): {exc}")
            human_delay(2.0, 4.0)
            continue

        # Click
        try:
            scroll_into_view(driver, target_el)
            human_delay(0.6, 1.2)
            target_el.click()
        except Exception as exc:
            print(f"  Click xato (attempt {attempt+1}): {exc}")
            human_delay(2.0, 4.0)
            continue

        # Modal kutish
        modal = wait_for_modal(driver, timeout=25)
        if modal is None:
            print(f"  Modal ochilmadi (attempt {attempt+1}/{MAX_MODAL_RETRIES}): {doc_number}")
            save_debug_snapshot(driver, f"modal_not_opened_p{page_num}_{idx+1}_try{attempt+1}")
            ensure_no_modal(driver)
            human_delay(3.0, 6.0)
            continue

        # Modal ichidan ma'lumot
        human_delay(1.2, 2.0)
        activity_types  = extract_activity_types_from_modal(driver, modal, timeout=15)
        modal_is_active = extract_is_active_from_modal(modal)
        file_token      = extract_file_token_from_modal(driver)

        close_modal(driver)
        human_delay(0.8, 1.5)

        # activity_types bo'sh bo'lsa — retry
        if not activity_types:
            print(f"  activity_types bo'sh (attempt {attempt+1}/{MAX_MODAL_RETRIES}): {doc_number}")
            if attempt < MAX_MODAL_RETRIES - 1:
                human_delay(3.0, 5.0)
                continue

        return activity_types, file_token, modal_is_active

    # 3 urinishdan keyin ham bo'sh — None qaytaramiz
    # Bu holda edu_license_has_details False bo'lib qoladi,
    # keyingi scan da qaytadan urinadi
    print(f"  {MAX_MODAL_RETRIES} urinishdan keyin ham olinmadi: {doc_number}")
    return None, None, None


# ── Sahifa protsessori ────────────────────────────────────────────────────────

def process_current_page(driver, page_num, new_edu_licenses, status_callback=None):
    """
    Sahifadagi barcha qatorlarni ishlab chiqadi.
    Har qator uchun modal retry bilan ochiladi.
    activity_types bo'sh bo'lsa saqlanmaydi — keyingi scan da qaytadan uriniladi.
    """
    # Sahifada qatorlar bo'lguncha kut (bo'sh kelsa 3 marta refresh)
    for page_retry in range(3):
        rows_data = parse_rows(driver)
        if rows_data:
            break
        print(f"  Sahifa {page_num} bo'sh — refresh {page_retry+1}/3")
        save_debug_snapshot(driver, f"empty_page_{page_num}_try{page_retry+1}")
        time.sleep(8.0)
        try:
            driver.refresh()
        except Exception:
            pass
        wait_for_data(driver)
        time.sleep(2.0)

    if not rows_data:
        print(f"  Sahifa {page_num}: 3 urinishdan keyin ham bo'sh — o'tkazildi")
        return

    print(f"  Sahifa {page_num}: {len(rows_data)} ta qator")

    for idx, (doc_number, org_name, is_active, _el) in enumerate(rows_data):
        save_document(doc_number, is_active)

        if edu_license_has_details(doc_number):
            print(f"  [{idx+1}/{len(rows_data)}] Skip: {doc_number}")
            continue

        if status_callback:
            status_callback(f"Sahifa {page_num}, {idx+1}/{len(rows_data)}: {doc_number}")

        print(f"  [{idx+1}/{len(rows_data)}] Modal: {doc_number} | {org_name}")

        activity_types, file_token, modal_is_active = _open_modal_and_extract(
            driver, rows_data, idx, doc_number, page_num
        )

        # Modal ochilmadi yoki activity_types olinmadi — keyingisiga o'tish
        # (edu_license_has_details False qoladi → keyingi scan da qaytadan urinadi)
        if activity_types is None:
            continue

        if modal_is_active is not None and modal_is_active != is_active:
            print(f"  Holat: {is_active} → {modal_is_active} ({doc_number})")
            is_active = modal_is_active

        save_edu_license(doc_number, file_token, org_name, activity_types, is_active)
        new_edu_licenses.append({
            "doc_number":     doc_number,
            "org_name":       org_name,
            "is_active":      is_active,
            "activity_types": activity_types,
        })
        print(f"  [+] Saqlandi: {doc_number} | {org_name}")

        if status_callback:
            status_callback(f"{doc_number} saqlandi ({idx+1}/{len(rows_data)})")


# ── Asosiy kirish nuqtasi ─────────────────────────────────────────────────────

def full_scan(status_callback=None, page_limit=PAGE_LIMIT, row_limit=None):
    driver = get_or_create_driver()
    new_edu_licenses = []

    try:
        print("[SCRAPER] full_scan start")
        if status_callback:
            status_callback("Brauzer tayyorlanmoqda...")

        ensure_startup_navigation(driver)

        total_pages = get_total_pages_from_current(driver)
        print(f"Jami {total_pages} ta sahifa")
        if status_callback:
            status_callback(f"Jami {total_pages} sahifa. Boshlandi...")

        last_page = (
            min(total_pages, page_limit)
            if page_limit and page_limit > 0
            else total_pages
        )

        # Sahifa 1 allaqachon ochiq
        if status_callback:
            status_callback(f"Sahifa 1/{last_page}...")
        process_current_page(driver, 1, new_edu_licenses, status_callback)

        for page in range(2, last_page + 1):
            if status_callback:
                status_callback(f"Sahifa {page}/{last_page} yuklanmoqda...")

            url = f"{BASE_URL}{FILTER_PARAMS}&page={page}"
            if not navigate_and_wait(driver, url, retries=3):
                print(f"  Sahifa {page} yuklanmadi — o'tkazildi")
                save_debug_snapshot(driver, f"page_not_loaded_{page}")
                continue

            process_current_page(driver, page, new_edu_licenses, status_callback)

            # Sahifalar orasida pauza
            human_delay(2.5, 5.0)

        print(f"[SCRAPER] Tugadi. Yangi: {len(new_edu_licenses)}")

    except Exception:
        global _DRIVER
        _DRIVER = None
        raise

    return new_edu_licenses