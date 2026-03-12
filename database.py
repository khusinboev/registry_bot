import sqlite3
from config import DB_PATH

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Table 1: barcha ro'yxatdagi hujjatlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_number TEXT PRIMARY KEY,
            is_active   INTEGER DEFAULT 1,
            checked_at  TEXT
        )
    """)

    # Table 2: filterlangan (Oliy ta'lim) hujjatlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS edu_licenses (
            doc_number  TEXT PRIMARY KEY,
            file_token  TEXT,
            org_name    TEXT,
            activity_types TEXT,
            is_active   INTEGER DEFAULT 1,
            notified    INTEGER DEFAULT 0,
            saved_at    TEXT
        )
    """)

    c.execute("PRAGMA table_info(edu_licenses)")
    edu_license_columns = {row[1] for row in c.fetchall()}
    if "activity_types" not in edu_license_columns:
        c.execute("ALTER TABLE edu_licenses ADD COLUMN activity_types TEXT")

    # Table 3: ruxsat berilgan foydalanuvchilar
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            added_at    TEXT
        )
    """)

    # Table 4: scan holati va metadata
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_meta (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT
        )
    """)

    conn.commit()
    conn.close()

def doc_exists(doc_number):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM documents WHERE doc_number=?", (doc_number,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_document(doc_number, is_active):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO documents (doc_number, is_active, checked_at)
        VALUES (?, ?, datetime('now'))
    """, (doc_number, is_active))
    conn.commit()
    conn.close()

def edu_license_exists(doc_number):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM edu_licenses WHERE doc_number=?", (doc_number,))
    result = c.fetchone()
    conn.close()
    return result is not None

def edu_license_has_details(doc_number):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM edu_licenses WHERE doc_number=? AND COALESCE(TRIM(activity_types), '') <> ''",
        (doc_number,)
    )
    result = c.fetchone()
    conn.close()
    return result is not None

def save_edu_license(doc_number, file_token, org_name, activity_types, is_active):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO edu_licenses 
        (doc_number, file_token, org_name, activity_types, is_active, notified, saved_at)
        VALUES (?, ?, ?, ?, ?, 0, datetime('now'))
        ON CONFLICT(doc_number) DO UPDATE SET
            file_token=excluded.file_token,
            org_name=excluded.org_name,
            activity_types=excluded.activity_types,
            is_active=excluded.is_active
    """, (doc_number, file_token, org_name, activity_types, is_active))
    conn.commit()
    conn.close()

def get_unnotified():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT doc_number, file_token, org_name FROM edu_licenses WHERE notified=0")
    rows = c.fetchall()
    conn.close()
    return rows

def mark_notified(doc_number):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE edu_licenses SET notified=1 WHERE doc_number=?", (doc_number,))
    conn.commit()
    conn.close()

def mark_notified_bulk(doc_numbers):
    if not doc_numbers:
        return
    conn = get_conn()
    c = conn.cursor()
    c.executemany(
        "UPDATE edu_licenses SET notified=1 WHERE doc_number=?",
        [(doc_number,) for doc_number in doc_numbers]
    )
    conn.commit()
    conn.close()

def save_user(user_id, username=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO users (user_id, username, added_at)
        VALUES (?, ?, datetime('now'))
        """,
        (user_id, username)
    )
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users ORDER BY added_at ASC")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def set_scan_meta(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO scan_meta (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=datetime('now')
        """,
        (key, value)
    )
    conn.commit()
    conn.close()

def get_scan_meta(key, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM scan_meta WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row is None:
        return default
    return row[0]

def get_all_edu_licenses():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT doc_number, file_token, org_name, is_active, saved_at FROM edu_licenses ORDER BY saved_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_edu_licenses_by_doc_numbers(doc_numbers):
    if not doc_numbers:
        return []
    placeholders = ",".join(["?"] * len(doc_numbers))
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        f"""
        SELECT doc_number, file_token, org_name, is_active, saved_at
        FROM edu_licenses
        WHERE doc_number IN ({placeholders})
        ORDER BY saved_at DESC
        """,
        tuple(doc_numbers)
    )
    rows = c.fetchall()
    conn.close()
    return rows