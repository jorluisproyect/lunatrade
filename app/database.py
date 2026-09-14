from __future__ import annotations

import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.getenv("LUNATRADE_DATA_DIR", str(_DEFAULT_DATA_DIR))).expanduser()
DB_PATH = DATA_DIR / "lunatrade.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                amount_usdt REAL NOT NULL,
                gross_pnl REAL NOT NULL,
                fees REAL NOT NULL,
                net_pnl REAL NOT NULL,
                reason TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                level TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                referral_code TEXT NOT NULL UNIQUE,
                referrer_code TEXT NOT NULL DEFAULT 'JORGE-LT',
                demo_balance REAL NOT NULL DEFAULT 100,
                demo_pnl REAL NOT NULL DEFAULT 0,
                selected_mode TEXT NOT NULL DEFAULT 'trading',
                demo_bot_running INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT
            );

            CREATE TABLE IF NOT EXISTS platform_fee_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                created_at TEXT NOT NULL,
                trade_notional REAL NOT NULL DEFAULT 0,
                fee_rate REAL NOT NULL DEFAULT 0.0001,
                fee_amount REAL NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'demo',
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES demo_users(id)
            );
            """
        )
        # Migraciones seguras para usuarios existentes de V12.
        _ensure_column(conn, "demo_users", "first_name", "TEXT")
        _ensure_column(conn, "demo_users", "last_name", "TEXT")
        _ensure_column(conn, "demo_users", "email", "TEXT")
        _ensure_column(conn, "demo_users", "signup_source", "TEXT NOT NULL DEFAULT 'admin'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_demo_users_email_unique ON demo_users(lower(email)) WHERE email IS NOT NULL AND email <> ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_users_referrer ON demo_users(referrer_code)")


def add_trade(trade: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO trades (
                opened_at, closed_at, symbol, side, entry_price, exit_price,
                amount_usdt, gross_pnl, fees, net_pnl, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade["opened_at"], trade["closed_at"], trade["symbol"], trade["side"],
                trade["entry_price"], trade["exit_price"], trade["amount_usdt"],
                trade["gross_pnl"], trade["fees"], trade["net_pnl"], trade["reason"],
            ),
        )


def recent_trades(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def add_event(level: str, title: str, message: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events (created_at, level, title, message) VALUES (?, ?, ?, ?)",
            (created_at, level, title, message),
        )


def recent_events(limit: int = 30) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def set_runtime_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO runtime_settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_runtime_setting(key: str, default: str | None = None) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM runtime_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def username_exists(username: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM demo_users WHERE lower(username)=lower(?)", (username,)).fetchone()
    return bool(row)


def email_exists(email: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM demo_users WHERE lower(email)=lower(?)", (email.strip(),)).fetchone()
    return bool(row)


def referral_exists(code: str) -> bool:
    if code.strip().upper() == "JORGE-LT":
        return True
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM demo_users WHERE upper(referral_code)=upper(?)", (code.strip(),)).fetchone()
    return bool(row)


def create_demo_user_record(*, display_name: str, username: str, password_salt: str, password_hash: str,
                            referral_code: str, referrer_code: str = "JORGE-LT", demo_balance: float = 100.0,
                            first_name: str | None = None, last_name: str | None = None,
                            email: str | None = None, signup_source: str = "admin") -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO demo_users (
                display_name, username, password_salt, password_hash, referral_code, referrer_code,
                demo_balance, demo_pnl, selected_mode, demo_bot_running, is_active, created_at,
                first_name, last_name, email, signup_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'trading', 0, 1, ?, ?, ?, ?, ?)
            """,
            (
                display_name, username, password_salt, password_hash, referral_code, referrer_code,
                demo_balance, created_at, first_name, last_name, email, signup_source,
            ),
        )
        row = conn.execute("SELECT * FROM demo_users WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_demo_user_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM demo_users WHERE lower(username)=lower(?)", (username.strip(),)).fetchone()
    return dict(row) if row else None


def get_demo_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM demo_users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_demo_user_by_referral(code: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM demo_users WHERE upper(referral_code)=upper(?)", (code.strip(),)).fetchone()
    return dict(row) if row else None


def list_demo_users(limit: int = 1000) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, display_name, first_name, last_name, email, username, referral_code, referrer_code,
                      demo_balance, demo_pnl, selected_mode, demo_bot_running, is_active, signup_source,
                      created_at, last_login
               FROM demo_users ORDER BY id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
    users = [dict(row) for row in rows]
    by_code = {str(u["referral_code"]).upper(): u for u in users}
    referral_counts = Counter(str(u.get("referrer_code") or "").upper() for u in users)

    def referral_level(user: dict[str, Any]) -> int:
        level = 1
        current = str(user.get("referrer_code") or "JORGE-LT").upper()
        seen: set[str] = set()
        while current and current != "JORGE-LT" and current not in seen and level < 50:
            seen.add(current)
            parent = by_code.get(current)
            if not parent:
                break
            level += 1
            current = str(parent.get("referrer_code") or "JORGE-LT").upper()
        return level

    enriched: list[dict[str, Any]] = []
    for user in reversed(users):
        parent_code = str(user.get("referrer_code") or "JORGE-LT").upper()
        parent = by_code.get(parent_code)
        item = dict(user)
        item["referrer_name"] = "Master · Jorge" if parent_code == "JORGE-LT" else (parent.get("display_name") if parent else "Código externo")
        item["referrer_username"] = "admin" if parent_code == "JORGE-LT" else (parent.get("username") if parent else "—")
        item["referral_level"] = referral_level(user)
        item["direct_referrals"] = int(referral_counts.get(str(user.get("referral_code") or "").upper(), 0))
        enriched.append(item)
    return enriched


def touch_demo_login(user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("UPDATE demo_users SET last_login=? WHERE id=?", (now, user_id))


def update_demo_mode(user_id: int, mode: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE demo_users SET selected_mode=? WHERE id=?", (mode, user_id))


def update_demo_bot(user_id: int, running: bool) -> None:
    with _connect() as conn:
        conn.execute("UPDATE demo_users SET demo_bot_running=? WHERE id=?", (1 if running else 0, user_id))


def update_demo_password(user_id: int, password_salt: str, password_hash: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE demo_users SET password_salt=?, password_hash=? WHERE id=?", (password_salt, password_hash, user_id))


def platform_fee_summary() -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(trade_notional),0) AS volume, COALESCE(SUM(fee_amount),0) AS fees, COUNT(*) AS rows FROM platform_fee_ledger"
        ).fetchone()
    return {"tracked_volume": float(row["volume"]), "tracked_fees": float(row["fees"]), "ledger_rows": int(row["rows"])}
