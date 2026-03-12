from threading import Lock

from scraper import full_scan

_scan_lock = Lock()


def run_scan(status_callback=None):
    """Jarayonda bir vaqtda faqat bitta scan ishlashini ta'minlaydi."""
    acquired = _scan_lock.acquire(blocking=False)
    if not acquired:
        return None

    try:
        return full_scan(status_callback)
    finally:
        _scan_lock.release()
