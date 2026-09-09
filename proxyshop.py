import logging
import sqlite3
import re
import os
import time
import hashlib
import hmac
import json
import asyncio
import threading
from contextvars import ContextVar
from collections import defaultdict
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime
from flask import Flask, jsonify
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import gspread
from gspread.exceptions import WorksheetNotFound
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ContextTypes, filters
)

# ==================== Configuration ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0") or 0)

# Binance verification uses the same Binance Pay transaction-history flow as
# the hosting project. Keep credentials in Replit Secrets, never in source.
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "").strip()
BINANCE_PAY_API_ENDPOINT = os.getenv(
    "BINANCE_PAY_API_ENDPOINT",
    "https://api.binance.com/sapi/v1/pay/transactions",
).strip()

# MongoDB is the persistent source of truth. SQLite is only a small runtime
# compatibility cache for the original bot's existing query-based features.
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "rr_shop_bot").strip()
RUNTIME_DB_PATH = os.getenv("RUNTIME_DB_PATH", "/tmp/rr_shop_runtime.db")

# Google Sheets backup settings. Keep the service-account JSON in Render
# environment variables, never in GitHub.
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
_google_interval_seconds = os.getenv("GOOGLE_BACKUP_INTERVAL_SECONDS")
if _google_interval_seconds:
    GOOGLE_BACKUP_INTERVAL_SECONDS = max(1.0, float(_google_interval_seconds))
else:
    # Keep the old variable working for existing deployments, but use a
    # seconds-based setting so changes can reach Sheets within 1-3 seconds.
    GOOGLE_BACKUP_INTERVAL_SECONDS = max(
        1.0,
        float(os.getenv("GOOGLE_BACKUP_INTERVAL_MINUTES", "0.0167") or 0.0167) * 60,
    )

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================== Premium Emoji & Button Color ====================
PREMIUM_ICONS = {
    "back": "5267490665117275176",
    "close": "5420130255174145507",     # ❌
    "done": "5352694861990501856",      # ✅
    "refresh": "5375338737028841420",   # 🔄
    "warn": "5336944168944047463",      # ⚠️
    "stop": "5420118804791336929",      # 🛑
    "gear": "5420155432272438703",      # ⚙️
    "user": "5352861489541714456",      # 👤
    "group": "5420145051336485498",     # 🫂
    "king": "5217822164362739968",      # 👑
    "dashboard": "5352877703043258544", # 📊
    "fire": "5337267511261960341",      # 🔥
    "new": "5382357040008021292",       # 🆕
    "add": "5420323438508155202",       # ➕
    "delete": "5422557736330106570",    # 🗑
    "search": "5463352748751753567",    # 🔍
    "note": "5395444784611480792",      # ✏️
    "world": "5336972142066047577",     # 🌐
    "link": "5420517437885943844",      # 🔗
    "gem": "5352838545826420397",       # 💎
    "gift": "5420396762189831222",      # 🎁
    "wait": "5337172996211648018",      # ⌛
    "bkash": "5348469219761626211",     # 💸 bKash
    "nagad": "5352985330628730418",     # Nagad
    "rocket": "5346042941196507141",    # Rocket
    "upay": "6205972007482300169",      # Upay
    "binance": "6253780203282113440",   # Binance
    "card": "5190899075968441286",      # 💳
    "money": "5190576863226933563",     # 💰
    "chat": "5192704641564974847",      # 💬
    "support": "6052964261418769099",   # Support custom emoji
    "transaction": "6089234491434341490", # Transaction ID
    "deposit": "6073556477824472025",     # Deposit
    "balance": "6073556477824472025",     # Balance
    "profile": "6312024679984929396",     # My Profile
    "buy": "6071402452941279514",         # Buy
    "shield": "5190447043545438788",    # 🛡
    "folder": "5352721946054268944",    # 📁
    "rocket_icon": "5352597830089347330", # 🚀
    "bag": "5229064374403998351",       # 🛍
    "megaphone": "5424818078833715060", # 📣
    "send": "5353001161878182134",      # 📤
    "handshake": "5192805934073685937", # 🤝
    "calendar": "5352585194295564660",  # 📅
    "lock": "5353022963132174959",      # 🔐
    "pin": "5352922460897452503",       # 📍
    "number": "5352862640592949843",    # 🔢
    "balance_main": "6206096153511990389", # 💎 Balance Control Main Icon
    "balance_add": "6206375377925839184",  # ➕ Add Balance Icon
    "balance_cut": "5445267414562389170",  # ➖ Cut Balance Icon
    # Custom Emoji Map
    "owl_proxy": "5280812193380605697",
    "north_vpn": "5345970940364770589",
    "proton_vpn": "5348390922507817684",
    "express_vpn": "5346335574498251610",
    "gmail": "5348494358205207761",
    "proxy": "5796407074346767851",
    "vpn_icon": "5794362687093740845"
}

FALLBACK_ICONS = {
    "back": "◀️", "close": "❌", "done": "✅", "refresh": "🔄",
    "warn": "⚠️", "stop": "🛑", "gear": "⚙️", "user": "👤",
    "group": "👥", "king": "👑", "dashboard": "📊", "fire": "🔥",
    "new": "🆕", "add": "➕", "delete": "🗑️", "search": "🔍",
    "note": "✏️", "world": "🌐", "link": "🔗", "gem": "💎",
    "gift": "🎁", "wait": "⌛", "bkash": "💸", "nagad": "💸",
    "rocket": "🚀", "upay": "💸", "binance": "💠", "card": "💳",
    "money": "💰", "chat": "💬", "support": "🗣️",
    "transaction": "🧾", "deposit": "💠", "balance": "💠",
    "profile": "👤", "buy": "🛍️", "shield": "🛡️", "folder": "📁",
    "rocket_icon": "🚀", "bag": "🛍️", "megaphone": "📣",
    "send": "📤", "handshake": "🤝", "calendar": "📅", "lock": "🔐",
    "pin": "📍", "number": "🔢", "balance_main": "💠",
    "balance_add": "➕", "balance_cut": "➖",
}


def set_current_user(user):
    """Render premium custom emoji only for premium viewers."""
    _current_user_is_premium.set(bool(getattr(user, "is_premium", False)))


def _button_text_with_fallback(text, icon):
    if _current_user_is_premium.get() or not icon:
        return text
    fallback = FALLBACK_ICONS.get(icon)
    if fallback and not str(text).lstrip().startswith(fallback):
        return f"{fallback} {text}"
    return text


def normalize_button_text(text):
    """Remove a normal-emoji fallback before matching reply-keyboard actions."""
    normalized = str(text or "").strip()
    for fallback in sorted(set(FALLBACK_ICONS.values()), key=len, reverse=True):
        if normalized.startswith(fallback):
            return normalized[len(fallback):].strip()
    return normalized


def pbtn(text, icon=None, style="primary", callback_data=None, url=None):
    kwargs = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    emoji_id = PREMIUM_ICONS.get(icon) if icon else None
    if emoji_id and _current_user_is_premium.get():
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(_button_text_with_fallback(text, icon), **kwargs)

def rkbtn(text, icon=None, style="primary"):
    kwargs = {}
    emoji_id = PREMIUM_ICONS.get(icon) if icon else None
    if emoji_id and _current_user_is_premium.get():
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style:
        kwargs["style"] = style
    return KeyboardButton(_button_text_with_fallback(text, icon), **kwargs)

TEXT_EMOJI = {
    "❌": "5420130255174145507", "✅": "5352694861990501856", "💰": "5190576863226933563",
    "👤": "5352861489541714456", "💎": "5352838545826420397", "💳": "5190899075968441286",
    "🎁": "5420396762189831222", "🛍": "5229064374403998351", "🛍️": "5229064374403998351",
    "📅": "5352585194295564660", "🏷": "5222444124698853913", "🏷️": "5222444124698853913",
    "⚠": "5336944168944047463", "⚠️": "5336944168944047463", "🔗": "5420517437885943844",
    "📁": "5352721946054268944", "🔢": "5352862640592949843", "📢": "5424818078833715060",
    "🎉": "5461151367559141950", "⚙": "5420155432272438703", "⚙️": "5420155432272438703",
    "🟢": "5416081784641168838", "🔴": "5411225014148014586", "👑": "5217822164362739968",
    "📊": "5352877703043258544", "💬": "5192704641564974847", "🚀": "5352597830089347330",
    "👥": "5420145051336485498", "🚫": "5334807341109908955", "👋": "5353027129250453493",
    "🤑": "6237742262822901946", "💡": "5422439311196834318", "🏆": "5217822164362739968",
    "🧾": "6089234491434341490",
    "💠": "6073556477824472025",
    "🌸": "5348469219761626211", "🟠": "6205988689135277308", "🔄": "5375338737028841420",
    "🛑": "5420118804791336929", "🫂": "5420145051336485498", "🔥": "5337267511261960341",
    "➕": "5420323438508155202", "🗑": "5422557736330106570", "🔍": "5463352748751753567",
    "✏": "5395444784611480792", "✏️": "5395444784611480792", "🌐": "5336972142066047577",
    "💸": "5348469219761626211", "🛡": "5190447043545438788", "📣": "5352980533150259581",
    "📤": "5353001161878182134", "🤝": "5192805934073685937", "🔐": "5353022963132174959",
    "📍": "5352922460897452503", "📱": "5355208818017999139", "⚡": "5456140674028019486",
    "🗣": "6052964261418769099", "🗣️": "6052964261418769099", "🥇": "5440539497383087970",
    "🥈": "5447203607294265305", "🥉": "5453902265922376865", "🔹": "5352638632278660622",
    "🔑": "6316670168151893216", "📦": "5352721946054268944",
}

def pe(text):
    if not _current_user_is_premium.get():
        return text
    result = text
    for ch, eid in TEXT_EMOJI.items():
        if ch in result:
            result = result.replace(ch, f'<tg-emoji emoji-id="{eid}">{ch}</tg-emoji>')
    return result

def get_product_icon_key(title):
    t_lower = title.lower()
    if 'owl' in t_lower:
        return 'owl_proxy'
    elif 'proton' in t_lower:
        return 'proton_vpn'
    elif 'express' in t_lower:
        return 'express_vpn'
    elif 'north' in t_lower or 'nord' in t_lower:
        return 'north_vpn'
    elif 'gmail' in t_lower:
        return 'gmail'
    elif 'proxy' in t_lower:
        return 'proxy'
    elif 'vpn' in t_lower:
        return 'vpn_icon'
    return 'fire'

# ==================== Database Setup ====================
_mongo_client = None
_mongo_db_handle = None
_db_sync_lock = threading.RLock()
_db_initializing = False
_backup_lock = threading.Lock()
_backup_dirty = False
_backup_event = threading.Event()
_db_sync_event = threading.Event()
_db_sync_worker_lock = threading.Lock()
_db_sync_worker_started = False
_current_user_is_premium = ContextVar("current_user_is_premium", default=False)
_force_join_cache = {}
_force_join_cache_lock = threading.Lock()


def get_mongo_db():
    """Return the configured Mongo database, or None for local development."""
    global _mongo_client, _mongo_db_handle
    if not MONGODB_URI:
        return None
    with _db_sync_lock:
        if _mongo_db_handle is None:
            _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            _mongo_client.admin.command("ping")
            _mongo_db_handle = _mongo_client[MONGODB_DATABASE]
        return _mongo_db_handle


class SyncedSQLiteConnection:
    """Keep the original SQL code working while MongoDB persists the data."""

    def __init__(self, raw_connection):
        self.raw = raw_connection

    def cursor(self):
        return self.raw.cursor()

    def commit(self):
        self.raw.commit()
        if not _db_initializing:
            # Mongo/Google network work must not block Telegram button
            # handlers. The worker coalesces several quick database writes.
            schedule_runtime_db_sync()

    def rollback(self):
        return self.raw.rollback()

    def close(self):
        return self.raw.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


def get_db():
    conn = sqlite3.connect(RUNTIME_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return SyncedSQLiteConnection(conn)


def _table_rows(raw_conn, table_name):
    cursor = raw_conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    return [dict(row) for row in cursor.fetchall()]


def _replace_mongo_collection(mongo_db, name, documents):
    collection = mongo_db[name]
    collection.delete_many({})
    if documents:
        collection.insert_many(documents)


def schedule_runtime_db_sync():
    """Queue persistence work without making a button wait for the network."""
    global _db_sync_worker_started
    _db_sync_event.set()
    with _db_sync_worker_lock:
        if not _db_sync_worker_started:
            _db_sync_worker_started = True
            threading.Thread(
                target=run_runtime_db_sync_worker,
                daemon=True,
                name="runtime-db-sync",
            ).start()


def run_runtime_db_sync_worker():
    while True:
        _db_sync_event.wait()
        _db_sync_event.clear()
        try:
            sync_runtime_db_to_mongo()
        except Exception as error:
            logging.error("Background runtime DB sync failed: %s", error)


def sync_runtime_db_to_mongo():
    """Persist only bot-operational data; credentials are never stored here."""
    global _backup_dirty
    if not MONGODB_URI:
        if GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON:
            _backup_dirty = True
            _backup_event.set()
        return
    try:
        mongo_db = get_mongo_db()
        if mongo_db is None:
            return

        raw = sqlite3.connect(RUNTIME_DB_PATH, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        table_map = {
            "users": "users",
            "admins": "admins",
            "settings": "settings",
            "channels": "channels",
            "categories": "categories",
            "payment_methods": "payment_methods",
            "products": "products",
            "purchases": "orders",
            "deposits": "deposits",
        }
        all_rows = {
            table: _table_rows(raw, table)
            for table in table_map
        }

        pending_balances = defaultdict(float)
        for deposit in all_rows["deposits"]:
            if deposit.get("status") == "pending":
                pending_balances[deposit.get("user_id")] += float(deposit.get("amount") or 0)

        users = []
        for user in all_rows["users"]:
            user["pending_balance"] = round(pending_balances[user.get("user_id")], 2)
            users.append(user)

        for table, collection_name in table_map.items():
            documents = users if table == "users" else all_rows[table]
            _replace_mongo_collection(mongo_db, collection_name, documents)
        raw.close()
        _backup_dirty = True
        _backup_event.set()
    except (PyMongoError, OSError, sqlite3.Error) as error:
        logging.error("MongoDB sync failed: %s", error)


def restore_mongo_data_to_runtime_db(conn):
    """Restore persisted collections into the compatibility cache on startup."""
    if not MONGODB_URI:
        return
    mongo_db = get_mongo_db()
    if mongo_db is None:
        return

    collection_to_table = {
        "users": "users",
        "admins": "admins",
        "settings": "settings",
        "channels": "channels",
        "categories": "categories",
        "payment_methods": "payment_methods",
        "products": "products",
        "orders": "purchases",
        "deposits": "deposits",
    }
    cursor = conn.cursor()
    for collection_name, table_name in collection_to_table.items():
        documents = list(mongo_db[collection_name].find({}, {"_id": 0}))
        if not documents:
            continue

        cursor.execute(f"DELETE FROM {table_name}")
        if table_name == "users":
            for document in documents:
                document.pop("pending_balance", None)

        columns = [column for column in documents[0].keys()]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        for document in documents:
            values = [document.get(column) for column in columns]
            cursor.execute(
                f"INSERT OR REPLACE INTO {table_name} ({column_sql}) VALUES ({placeholders})",
                values,
            )


def init_db():
    global _db_initializing
    _db_initializing = True
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            ref_earnings REAL DEFAULT 0.0,
            referred_by INTEGER DEFAULT 0,
            joined_date TEXT,
            is_banned INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS channels (username TEXT PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_methods (
            name TEXT PRIMARY KEY,
            number_or_address TEXT,
            min_deposit REAL DEFAULT 10.0,
            icon_key TEXT DEFAULT 'card'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            price REAL,
            item_data TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            price REAL,
            date TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            method TEXT,
            trx_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            approved_by INTEGER,
            approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_commission', '10')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('support_link', 'https://t.me/your_support_username')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_join_status', 'ON')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_group_id', '')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('deposit_notify_enabled', 'OFF')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('deposit_notify_chat_id', '')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('deposit_notify_type', '')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('usdt_rate', '120')")

    default_methods = [
        ('bKash', '01700000000', 10.0, 'bkash'),
        ('Nagad', '01700000000', 10.0, 'nagad'),
        ('Rocket', '01700000000', 10.0, 'rocket'),
        ('Upay', '01700000000', 10.0, 'upay'),
        ('Binance', '1261150963', 0.1, 'binance')
    ]
    for m_name, m_num, m_min, m_icon in default_methods:
        cursor.execute(
            "INSERT OR IGNORE INTO payment_methods "
            "(name, number_or_address, min_deposit, icon_key) VALUES (?, ?, ?, ?)",
            (m_name, m_num, m_min, m_icon),
        )

    cursor.execute(
        "UPDATE payment_methods SET number_or_address = ? "
        "WHERE name = 'Binance' AND number_or_address = 'binance_pay_id_here'",
        ("1261150963",)
    )
    cursor.execute(
        "DELETE FROM payment_methods WHERE name IN "
        "('Gmail', 'North VPN', 'Proton VPN', 'Express VPN', 'OWL Proxy')"
    )

    conn.commit()
    restore_mongo_data_to_runtime_db(conn)
    conn.commit()
    conn.close()
    _db_initializing = False
    sync_runtime_db_to_mongo()

# ==================== Helper Functions ====================
def is_admin(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def is_user_banned(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return (res['is_banned'] == 1) if res else False

def get_all_admin_ids():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    rows = cursor.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

def get_total_users_count():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM users")
    res = cursor.fetchone()
    conn.close()
    return res['total'] if res else 0

def get_or_create_user(user_id, name, ref_id=0):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("INSERT INTO users (user_id, first_name, balance, ref_earnings, referred_by, joined_date, is_banned) VALUES (?, ?, 0.0, 0.0, ?, ?, 0)", 
                       (user_id, name, ref_id, today))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    conn.close()
    return user

def get_setting(key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res['value'] if res else ""

def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def get_pending_deposit(user_id):
    """Return the user's oldest pending deposit, if one exists."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, amount, method, trx_id, created_at FROM deposits "
        "WHERE user_id = ? AND status = 'pending' ORDER BY id ASC LIMIT 1",
        (user_id,),
    )
    pending = cursor.fetchone()
    conn.close()
    return pending


def deposit_notifications_enabled():
    return (
        get_setting("deposit_notify_enabled") == "ON"
        and bool(get_setting("deposit_notify_chat_id").strip())
    )


async def send_deposit_notification(context, text, reply_markup=None):
    """Send deposit alerts to the configured group/channel only."""
    if not deposit_notifications_enabled():
        return False

    target = get_setting("deposit_notify_chat_id").strip()
    try:
        await context.bot.send_message(
            chat_id=target,
            text=pe(text),
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return True
    except Exception as error:
        logging.error("Deposit notification target failed: %s", error)
        return False

def add_ref_earnings(user_id, amount):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ?, ref_earnings = ref_earnings + ? WHERE user_id = ?", (amount, amount, user_id))
    conn.commit()
    conn.close()

def format_item_to_code(text):
    formatted_lines = []
    for line in text.strip().split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            formatted_lines.append(f"{key.strip()}: <code>{val.strip()}</code>")
        else:
            formatted_lines.append(f"<code>{line.strip()}</code>")
    return "\n".join(formatted_lines)


def _get_backup_rows():
    """Build the four intentionally limited backup datasets."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, first_name, balance, joined_date, is_banned "
        "FROM users ORDER BY user_id"
    )
    users = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT user_id, title, price, date FROM purchases "
        "ORDER BY id DESC"
    )
    orders = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT user_id, amount, method, trx_id, created_at FROM deposits "
        "WHERE status = 'pending' ORDER BY id DESC"
    )
    pending_deposits = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT user_id, amount, method, trx_id, approved_at FROM deposits "
        "WHERE status = 'approved' ORDER BY id DESC"
    )
    successful_deposits = [dict(row) for row in cursor.fetchall()]
    conn.close()

    pending_by_user = defaultdict(float)
    for deposit in pending_deposits:
        pending_by_user[deposit["user_id"]] += float(deposit.get("amount") or 0)

    user_rows = [
        [
            user["user_id"],
            user.get("first_name") or "",
            round(float(user.get("balance") or 0), 2),
            round(pending_by_user[user["user_id"]], 2),
            user.get("joined_date") or "",
            "Banned" if user.get("is_banned") else "Active",
        ]
        for user in users
    ]

    return {
        "Users": [
            ["User ID", "Name", "Current Balance (BDT)",
             "Pending Balance (BDT)", "Joined", "Status"],
            *user_rows,
        ],
        "Orders": [
            ["User ID", "Product", "Price (BDT)", "Date"],
            *[
                [
                    row["user_id"],
                    row.get("title") or "",
                    round(float(row.get("price") or 0), 2),
                    row.get("date") or "",
                ]
                for row in orders
            ],
        ],
        "Pending Deposits": [
            ["User ID", "Amount (BDT)", "Method", "TrxID", "Created At"],
            *[
                [
                    row["user_id"],
                    round(float(row.get("amount") or 0), 2),
                    row.get("method") or "",
                    row.get("trx_id") or "",
                    row.get("created_at") or "",
                ]
                for row in pending_deposits
            ],
        ],
        "Successful Deposits": [
            ["User ID", "Amount (BDT)", "Method", "TrxID", "Approved At"],
            *[
                [
                    row["user_id"],
                    round(float(row.get("amount") or 0), 2),
                    row.get("method") or "",
                    row.get("trx_id") or "",
                    row.get("approved_at") or "",
                ]
                for row in successful_deposits
            ],
        ],
    }


def export_backup_to_google_sheet():
    """Overwrite the configured Google Sheet with the latest four backup tabs."""
    global _backup_dirty
    with _backup_lock:
        if not GOOGLE_SERVICE_ACCOUNT_JSON:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env variable সেট করা নেই।")
        if not GOOGLE_SHEET_ID:
            raise RuntimeError("GOOGLE_SHEET_ID env variable সেট করা নেই।")

        try:
            service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError as error:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON valid JSON নয়।") from error

        client = gspread.service_account_from_dict(service_account_info)
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

        for title, values in _get_backup_rows().items():
            try:
                worksheet = spreadsheet.worksheet(title)
            except WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(
                    title=title,
                    rows=max(len(values) + 10, 100),
                    cols=max(len(values[0]) + 2, 8),
                )
            worksheet.clear()
            worksheet.update(range_name="A1", values=values, raw=True)

        _backup_dirty = False
        return spreadsheet.url


def run_auto_backup_worker():
    """Refresh Google Sheets shortly after every database change."""
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        logging.info(
            "Automatic Google Sheet backup disabled: Google env variables are missing."
        )
        return

    interval_seconds = GOOGLE_BACKUP_INTERVAL_SECONDS
    while True:
        # Coalesce bursts of writes. One full export per second can still hit
        # Google's quota, so this is the fastest supported cadence, not a
        # promise that every API call completes in one second.
        _backup_event.wait(timeout=interval_seconds)
        _backup_event.clear()
        if not _backup_dirty:
            continue
        try:
            export_backup_to_google_sheet()
            logging.info("Automatic Google Sheet backup completed.")
        except Exception as error:
            logging.error("Automatic Google Sheet backup failed: %s", error)


def check_binance_payment(transaction_id):
    """Verify a Binance Pay transaction against the admin's Binance account."""
    if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
        return False, 0.0, "Binance API credentials configured নেই।"

    timestamp = int(time.time() * 1000)
    # The history endpoint defaults are too narrow for a delayed user
    # submission. Asking for the recent 30-day window also keeps the response
    # bounded and makes the signed request deterministic.
    params = {
        "limit": 100,
        "startTime": timestamp - (30 * 24 * 60 * 60 * 1000),
        "endTime": timestamp,
        "recvWindow": 5000,
        "timestamp": timestamp,
    }
    query_string = urlencode(params)
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    separator = "&" if "?" in BINANCE_PAY_API_ENDPOINT else "?"
    request_url = (
        f"{BINANCE_PAY_API_ENDPOINT}{separator}{query_string}"
        f"&signature={signature}"
    )
    request = Request(
        request_url,
        headers={"X-MBX-APIKEY": BINANCE_API_KEY},
        method="GET"
    )

    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if isinstance(payload, dict):
            api_code = str(payload.get("code", "000000"))
            if api_code not in {"000000", "0"}:
                return False, 0.0, (
                    f"Binance API {api_code}: "
                    f"{payload.get('msg', 'unknown error')}"
                )
            transactions = payload.get("data", [])
            if isinstance(transactions, dict):
                transactions = transactions.get("data", [])
        else:
            transactions = payload
        for item in transactions or []:
            if not isinstance(item, dict):
                continue
            submitted_id = str(transaction_id).strip()
            transaction_ids = {
                str(item.get(field, "")).strip()
                for field in ("transactionId", "orderId", "id")
                if item.get(field) not in (None, "")
            }
            # Binance Pay C2C history commonly exposes the user's value as
            # orderId while transactionId is a different internal value.
            if submitted_id not in transaction_ids:
                continue

            status = str(item.get("status", "")).upper()
            if status and status not in {"SUCCESS", "COMPLETED", "PAID"}:
                return False, 0.0, f"Binance transaction status {status} গ্রহণযোগ্য নয়।"

            try:
                paid_amount = float(item.get("amount", 0))
            except (TypeError, ValueError):
                paid_amount = 0.0

            currency = str(item.get("currency", "USDT")).upper()
            if currency != "USDT":
                return False, paid_amount, f"Currency {currency} গ্রহণযোগ্য নয়।"
            return True, paid_amount, f"{paid_amount:g} {currency}"

        return False, 0.0, "এই 🧾 Transaction ID Binance Pay history-তে পাওয়া যায়নি।"
    except HTTPError as error:
        response_text = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(response_text)
            api_code = error_payload.get("code", error.code)
            api_message = error_payload.get("msg", "unknown error")
        except (TypeError, ValueError, json.JSONDecodeError):
            api_code = error.code
            api_message = "non-JSON response"
        logging.error("Binance API HTTP error %s: %s", api_code, api_message)
        return False, 0.0, f"Binance API {api_code}: {api_message}"
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        logging.error("Binance verification error: %s", error)
        return False, 0.0, "Binance server response পাওয়া যায়নি।"
    except Exception as error:
        logging.error("Unexpected Binance verification error: %s", error)
        return False, 0.0, "Binance verification ব্যর্থ হয়েছে।"

def credit_binance_deposit(user_id, amount_bdt, amount_usdt, trx_id):
    """Atomically approve one verified Binance deposit and credit the user."""
    try:
        commission_percent = float(get_setting('referral_commission') or 10)
    except (TypeError, ValueError):
        commission_percent = 10.0

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT id FROM deposits WHERE user_id = ? AND status = 'pending' LIMIT 1",
            (user_id,),
        )
        if cursor.fetchone():
            conn.rollback()
            return False, -1, 0.0
        cursor.execute(
            "INSERT INTO deposits (user_id, amount, method, trx_id, status, approved_by, approved_at) "
            "VALUES (?, ?, 'Binance', ?, 'approved', ?, ?)",
            (user_id, amount_bdt, trx_id, SUPER_ADMIN_ID, datetime.now())
        )
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount_bdt, user_id)
        )

        cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
        user_info = cursor.fetchone()
        referrer_id = user_info['referred_by'] if user_info else 0
        commission_amount = 0.0
        if referrer_id:
            commission_amount = (amount_bdt * commission_percent) / 100.0
            cursor.execute(
                "UPDATE users SET balance = balance + ?, ref_earnings = ref_earnings + ? "
                "WHERE user_id = ?",
                (commission_amount, commission_amount, referrer_id)
            )

        conn.commit()
        return True, referrer_id, commission_amount
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, 0, 0.0
    except Exception as error:
        conn.rollback()
        logging.error("Binance deposit credit failed: %s", error)
        return False, 0, 0.0
    finally:
        conn.close()

async def safe_delete_msg(context, chat_id, message_id):
    try:
        if message_id:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

async def check_force_join(user_id, context: ContextTypes.DEFAULT_TYPE):
    if get_setting('force_join_status') != 'ON':
        return True, []

    # Membership checks are Telegram API calls. Cache only a successful check
    # briefly so every reply-keyboard click does not wait on the network.
    with _force_join_cache_lock:
        cached_at = _force_join_cache.get(user_id)
    if cached_at and time.monotonic() - cached_at < 30:
        return True, []
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM channels")
    channels = [row['username'] for row in cursor.fetchall()]
    conn.close()

    not_joined = []
    for ch in channels:
        ch_clean = ch if (ch.startswith('@') or ch.startswith('http')) else f"@{ch}"
        try:
            member = await context.bot.get_chat_member(chat_id=ch_clean, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch_clean)
        except Exception:
            not_joined.append(ch_clean)
            
    if not not_joined:
        with _force_join_cache_lock:
            _force_join_cache[user_id] = time.monotonic()
    return (len(not_joined) == 0), not_joined

# ==================== Keyboards & UI Renderers ====================
def get_main_keyboard(user_id):
    keyboard = [
        [rkbtn("Buy Products", icon="buy", style="danger")],
        [rkbtn("My Profile", icon="profile"), rkbtn("Deposit", icon="deposit", style="success")],
        [rkbtn("Referral", icon="gift"), rkbtn("Support", icon="support")]
    ]
    if is_admin(user_id):
        keyboard.append([rkbtn("Admin Panel", icon="gear", style="danger")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def build_quantity_keyboard(quantity):
    return InlineKeyboardMarkup([
        [
            pbtn("➖", icon="warn", style="danger", callback_data="qty_minus"),
            pbtn(f"{quantity}", icon="number", style="primary", callback_data="qty_noop"),
            pbtn("➕", icon="fire", style="success", callback_data="qty_plus")
        ],
        [pbtn("Custom Quantity", icon="note", style="primary", callback_data="qty_custom")],
        [
            pbtn("কনফার্ম", icon="done", style="success", callback_data="qty_confirm"),
            pbtn("Cancel", icon="close", style="danger", callback_data="qty_cancel")
        ]
    ])

async def send_admin_panel(update: Update):
    usdt_rate = get_setting('usdt_rate') or "120"
    log_group = get_setting('log_group_id') or "Not Set"
    total_users = get_total_users_count()
    
    keyboard = [
        [
            pbtn("User Mgmt", icon="user", callback_data='admin_user_mgmt'),
            pbtn("Group Log", icon="link", callback_data='admin_group_log')
        ],
        [
            pbtn("Deposit Alerts", icon="megaphone", callback_data="admin_deposit_notify")
        ],
        [
            pbtn("Broadcast", icon="megaphone", callback_data='admin_broadcast'),
            pbtn("Leaderboard", icon="king", callback_data='view_leaderboard')
        ],
        [
            pbtn("Admins", icon="shield", callback_data='admin_mgmt'),
            pbtn("Force Join", icon="group", callback_data='admin_fj_sys')
        ],
        [
            pbtn("Categories", icon="folder", callback_data='admin_cat_mgmt'),
            pbtn("Add Product", icon="new", style="success", callback_data='admin_add_prod')
        ],
        [
            pbtn("RR Control", icon="gear", style="danger", callback_data='admin_rr_control')
        ],
        [
            pbtn("Backup Data to Google Sheet", icon="folder", style="success", callback_data="admin_backup")
        ],
        [
            pbtn("Close", icon="close", style="danger", callback_data='close_msg')
        ]
    ]
    
    text = (
        f"⚙️ <b>SYSTEM SETTINGS</b>\n"
        f"Manage advanced bot configurations below:\n\n"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
        f"💲 <b>USDT Rate:</b> <code>1$ = {usdt_rate} BDT</code>\n"
        f"📢 <b>Activity Log ID:</b> <code>{log_group}</code>\n"
        f"💠 <b>Deposit Alerts:</b> "
        f"<code>{get_setting('deposit_notify_chat_id') if deposit_notifications_enabled() else 'OFF'}</code>"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.message.reply_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def render_categories_menu(update_or_query):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM categories")
    cats = cursor.fetchall()
    conn.close()

    if not cats:
        text = "❌ <b>কোনো ক্যাটাগরি যোগ করা নেই!</b>"
        keyboard = InlineKeyboardMarkup([[pbtn("Close", icon="close", style="danger", callback_data="close_msg")]])
        if hasattr(update_or_query, 'edit_message_text'):
            await update_or_query.edit_message_text(pe(text), reply_markup=keyboard, parse_mode="HTML")
        elif hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(pe(text), reply_markup=keyboard, parse_mode="HTML")
        else:
            await update_or_query.reply_text(pe(text), reply_markup=keyboard, parse_mode="HTML")
        return

    keyboard = []
    row = []
    for c in cats:
        cat_name = c['name']
        cat_icon = get_product_icon_key(cat_name)
        row.append(pbtn(cat_name, icon=cat_icon, callback_data=f"buycat_{cat_name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([pbtn("Close", icon="close", style="danger", callback_data="close_msg")])

    text = "🎯 <b>ক্যাটাগরি সিলেক্ট করুন:</b>"
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    elif hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update_or_query.reply_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# ==================== Handlers ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    set_current_user(user)
    context.user_data.clear()

    if is_user_banned(user.id):
        await update.message.reply_text(pe("🚫 <b>আপনি এই বট থেকে ব্যান হয়ে গেছেন!</b>"), parse_mode="HTML")
        return

    ref_id = 0
    if context.args:
        try:
            possible_id = int(context.args[0])
            if possible_id != user.id:
                ref_id = possible_id
        except ValueError:
            pass

    is_joined, missing_channels = await check_force_join(user.id, context)
    if not is_joined:
        buttons = []
        for ch in missing_channels:
            url = ch if ch.startswith('http') else f"https://t.me/{ch.replace('@', '')}"
            buttons.append([pbtn("JOIN CHANNEL", icon="link", style="primary", url=url)])
        buttons.append([pbtn("Verify / Check Again", icon="refresh", style="success", callback_data="check_join")])
        
        await update.message.reply_text(
            pe("⚠️ <b>বট ব্যবহার করতে নিচের চ্যানেলে জয়েন করুন:</b>"),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return

    get_or_create_user(user.id, user.first_name, ref_id)
    welcome_msg = f"👋 <b>RR SHOP</b> এ আপনাকে স্বাগতম, {user.first_name}!\n\nনিচের মেনু থেকে আপনার সেবাটি বাছুন:"
    await update.message.reply_text(pe(welcome_msg), reply_markup=get_main_keyboard(user.id), parse_mode="HTML")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    action_text = normalize_button_text(text)
    user = update.effective_user
    set_current_user(user)
    state = context.user_data.get('state')

    if is_user_banned(user.id):
        await update.message.reply_text(pe("🚫 <b>আপনি এই বট থেকে ব্যান হয়ে গেছেন!</b>"), parse_mode="HTML")
        return

    if not is_admin(user.id):
        is_joined, _ = await check_force_join(user.id, context)
        if not is_joined:
            await start(update, context)
            return

    db_user = get_or_create_user(user.id, user.first_name)

    # Balance Control States (Admin)
    if is_admin(user.id) and state in ['admin_add_balance', 'admin_cut_balance']:
        try:
            user_id_str, amount_str = text.strip().split()
            target_user_id = int(user_id_str)
            amount = float(amount_str)
        except ValueError:
            await update.message.reply_text(
                pe("❌ ভুল ফরম্যাট! দয়া করে সঠিক ফরম্যাটে লিখুন: `User_ID Amount` (যেমন: `123456789 100`)"), 
                parse_mode="HTML"
            )
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_user_id,))
        target_user = cursor.fetchone()

        if not target_user:
            await update.message.reply_text(pe("❌ এই ইউজার আইডিটি ডাটাবেজে পাওয়া যায়নি!"), parse_mode="HTML")
            conn.close()
            return

        if state == 'admin_add_balance':
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_user_id))
            conn.commit()
            msg = f"✅ সফলভাবে ইউজার `<code>{target_user_id}</code>` এর অ্যাকাউন্টে **{amount} BDT** যোগ করা হয়েছে।"
            try:
                await context.bot.send_message(chat_id=target_user_id, text=pe(f"🎉 আপনার অ্যাকাউন্টে অ্যাডমিন দ্বারা **{amount} BDT** যোগ করা হয়েছে!"), parse_mode="HTML")
            except Exception:
                pass
        elif state == 'admin_cut_balance':
            if target_user['balance'] < amount:
                await update.message.reply_text(pe("❌ ওই ইউজারের অ্যাকাউন্টে পর্যাপ্ত ব্যালেন্স নেই!"), parse_mode="HTML")
                conn.close()
                return
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, target_user_id))
            conn.commit()
            msg = f"✅ সফলভাবে ইউজার `<code>{target_user_id}</code>` এর অ্যাকাউন্ট থেকে **{amount} BDT** কেটে নেওয়া হয়েছে।"
            try:
                await context.bot.send_message(chat_id=target_user_id, text=pe(f"⚠️ আপনার অ্যাকাউন্ট থেকে অ্যাডমিন দ্বারা **{amount} BDT** কেটে নেওয়া হয়েছে!"), parse_mode="HTML")
            except Exception:
                pass

        conn.close()
        context.user_data.pop('state', None)
        await update.message.reply_text(pe(msg), reply_markup=InlineKeyboardMarkup([[pbtn("Back to RR Control", icon="back", callback_data="admin_rr_control")]]), parse_mode="HTML")
        return

    # Deposit Amount State
    if state == 'awaiting_deposit_amount':
        await safe_delete_msg(context, user.id, update.message.message_id)
        last_bot_msg_id = context.user_data.get('last_msg_id')
        await safe_delete_msg(context, user.id, last_bot_msg_id)

        try:
            val_input = float(text.strip())
            method_name = context.user_data.get('dep_method')

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT number_or_address, min_deposit FROM payment_methods WHERE name = ?", (method_name,))
            m_data = cursor.fetchone()
            conn.close()

            min_limit = m_data['min_deposit'] if m_data else 10.0
            num = m_data['number_or_address'] if m_data else "Not Set"

            if val_input < min_limit:
                unit = "USDT" if method_name.lower() == 'binance' else "BDT"
                m = await context.bot.send_message(chat_id=user.id, text=pe(f"❌ {method_name} এ সর্বনিম্ন ডিপোজিট {min_limit} {unit}!"), parse_mode="HTML")
                context.user_data['last_msg_id'] = m.message_id
                return
            
            if method_name.lower() == 'binance':
                try:
                    usdt_rate = float(get_setting('usdt_rate'))
                except ValueError:
                    usdt_rate = 120.0
                
                calculated_bdt = val_input * usdt_rate
                context.user_data['dep_amount'] = calculated_bdt
                context.user_data['dep_usdt'] = val_input
                context.user_data['state'] = 'awaiting_trxid'
                
                msg = (
                    f"💠 <b>{method_name} Pay Instructions:</b>\n\n"
                    f"📱 Pay ID: <code>{num}</code>\n"
                    f"💲 Amount: <b>{val_input} USDT</b>\n"
                    f"💠 Balance Added: <b>{calculated_bdt:.2f} BDT</b> (Rate: 1$ = {usdt_rate:.2f} BDT)\n\n"
                    f"👉 ওপরের আইডিতে <b>{val_input} USDT</b> পাঠানোর পর <b>🧾 Transaction ID (TrxID)</b> টাইপ করে পাঠান:"
                )
            else:
                context.user_data['dep_amount'] = val_input
                context.user_data['dep_usdt'] = 0
                context.user_data['state'] = 'awaiting_trxid'
                
                msg = (
                    f"💠 <b>{method_name} Cash Out / Send Money Instructions:</b>\n\n"
                    f"📱 Number / ID: <code>{num}</code>\n"
                    f"💰 Amount: <b>{val_input:.2f} BDT</b>\n\n"
                    f"👉 ওপরের নম্বরে/আইডিতে টাকা পাঠানোর পর <b>🧾 Transaction ID (TrxID)</b> টাইপ করে পাঠান:"
                )

            m = await context.bot.send_message(chat_id=user.id, text=pe(msg), parse_mode="HTML")
            context.user_data['last_msg_id'] = m.message_id
            return
        except ValueError:
            m = await context.bot.send_message(chat_id=user.id, text=pe("❌ পরিমাণ অবশ্যই সংখ্যায় টাইপ করুন!"), parse_mode="HTML")
            context.user_data['last_msg_id'] = m.message_id
            return

    # Add Payment Method States (Admin)
    if is_admin(user.id):
        if state == 'awaiting_usdt_rate':
            try:
                rate_val = float(text.strip())
                set_setting('usdt_rate', str(rate_val))
                context.user_data.clear()
                await update.message.reply_text(pe(f"✅ Binance USDT Rate <b>1$ = {rate_val:.2f} BDT</b> সেভ করা হয়েছে!"), parse_mode="HTML")
            except ValueError:
                await update.message.reply_text(pe("❌ ডলারের রেট অবশ্যই সংখ্যায় টাইপ করুন!"), parse_mode="HTML")
            return

        if state == 'add_pay_step1_name':
            context.user_data['new_pay_name'] = text.strip()
            context.user_data['state'] = 'add_pay_step2_num'
            await update.message.reply_text(pe(f"📱 <b>{text.strip()}</b> এর একাউন্ট নম্বর / Binance Pay ID দিন:"), parse_mode="HTML")
            return

        elif state == 'add_pay_step2_num':
            context.user_data['new_pay_num'] = text.strip()
            context.user_data['state'] = 'add_pay_step3_min'
            p_name = context.user_data.get('new_pay_name', '')
            unit_txt = "USDT (যেমন: 0.1)" if 'binance' in p_name.lower() else "টাকা (যেমন: 10)"
            await update.message.reply_text(pe(f"💠 এই মেথডের জন্য <b>Minimum Deposit Limit</b> কত দিতে চান? ({unit_txt}):"), parse_mode="HTML")
            return

        elif state == 'add_pay_step3_min':
            try:
                min_dep = float(text.strip())
                name = context.user_data.get('new_pay_name')
                num = context.user_data.get('new_pay_num')

                name_lower = name.lower()
                icon_key = 'card'
                if 'bkash' in name_lower: icon_key = 'bkash'
                elif 'nagad' in name_lower: icon_key = 'nagad'
                elif 'rocket' in name_lower: icon_key = 'rocket'
                elif 'upay' in name_lower: icon_key = 'upay'
                elif 'binance' in name_lower: icon_key = 'binance'

                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO payment_methods (name, number_or_address, min_deposit, icon_key) VALUES (?, ?, ?, ?)",
                    (name, num, min_dep, icon_key)
                )
                conn.commit()
                conn.close()

                unit_txt = "USDT" if 'binance' in name_lower else "BDT"
                context.user_data.clear()
                await update.message.reply_text(
                    pe(f"✅ <b>পেমেন্ট মেথড সফলভাবে যোগ/আপডেট হয়েছে!</b>\n\n"
                       f"💳 <b>Name:</b> {name}\n"
                       f"📱 <b>Number/ID:</b> <code>{num}</code>\n"
                       f"💠 <b>Min Deposit:</b> {min_dep} {unit_txt}"),
                    parse_mode="HTML"
                )
                return
            except ValueError:
                await update.message.reply_text(pe("❌ Minimum Deposit অবশ্যই সংখ্যায় দিন!"), parse_mode="HTML")
                return

    # Broadcast State (Admin)
    if is_admin(user.id) and state == 'awaiting_broadcast_msg':
        context.user_data.clear()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
        all_users = cursor.fetchall()
        conn.close()

        await update.message.reply_text(pe("⏳ <b>ব্রডকাস্ট পাঠানো শুরু হয়েছে...</b>"), parse_mode="HTML")
        
        success = 0
        failed = 0
        
        for u in all_users:
            try:
                await context.bot.copy_message(
                    chat_id=u['user_id'],
                    from_chat_id=user.id,
                    message_id=update.message.message_id
                )
                success += 1
            except Exception:
                failed += 1

        await update.message.reply_text(
            pe(f"✅ <b>Broadcast Complete!</b>\n\n"
            f"🟢 <b>সফল:</b> {success} জন\n"
            f"🔴 <b>ব্যর্থ (Blocked):</b> {failed} জন"),
            parse_mode="HTML"
        )
        return

    # Custom Quantity State
    if state == 'awaiting_custom_qty':
        await safe_delete_msg(context, user.id, update.message.message_id)
        last_bot_msg_id = context.user_data.get('last_msg_id')
        await safe_delete_msg(context, user.id, last_bot_msg_id)

        try:
            qty = int(text)
            if qty <= 0:
                m = await context.bot.send_message(chat_id=user.id, text=pe("❌ সর্বনিম্ন পরিমাণ ১ হতে হবে!"), parse_mode="HTML")
                context.user_data['last_msg_id'] = m.message_id
                return
            
            p_id = context.user_data.get('buy_pid')
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT title, category, price FROM products WHERE id = ?", (p_id,))
            res = cursor.fetchone()

            if not res:
                m = await context.bot.send_message(chat_id=user.id, text=pe("❌ প্রোডাক্টটি পাওয়া যায়নি!"), parse_mode="HTML")
                conn.close()
                context.user_data['last_msg_id'] = m.message_id
                return

            title = res['title']
            cat_name = res['category']
            price = res['price']

            cursor.execute("SELECT COUNT(*) as stock FROM products WHERE title = ? AND category = ?", (title, cat_name))
            stock_res = cursor.fetchone()
            stock = stock_res['stock'] if stock_res else 0
            conn.close()

            if stock == 0:
                m = await context.bot.send_message(chat_id=user.id, text=pe("❌ এই প্রোডাক্টটি আউট অফ স্টক!"), parse_mode="HTML")
                context.user_data['last_msg_id'] = m.message_id
                return

            if qty > stock:
                m = await context.bot.send_message(chat_id=user.id, text=pe(f"❌ স্টকে এতগুলো নেই! সর্বোচ্চ আছে: {stock} টি।"), parse_mode="HTML")
                context.user_data['last_msg_id'] = m.message_id
                return

            context.user_data['buy_qty'] = qty
            total = price * qty

            msg = (
                f"🏷️ <b>{title}</b>\n"
                f"💎 প্রাইস: {price:.2f} BDT\n"
                f"📦 স্টক: {stock}\n\n"
                f"<b>পরিমাণ:</b> {qty}\n"
                f"<b>মোট:</b> 💎 {total:.2f} BDT"
            )
            context.user_data['state'] = None
            m = await context.bot.send_message(chat_id=user.id, text=pe(msg), reply_markup=build_quantity_keyboard(qty), parse_mode="HTML")
            context.user_data['last_msg_id'] = m.message_id
            return
        except ValueError:
            m = await context.bot.send_message(chat_id=user.id, text=pe("❌ পরিমাণ অবশ্যই সংখ্যায় টাইপ করুন!"), parse_mode="HTML")
            context.user_data['last_msg_id'] = m.message_id
            return

    # Admin States
    if is_admin(user.id):
        if state == 'awaiting_search_user_id':
            try:
                target_id = int(text.strip())
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
                u_info = cursor.fetchone()

                if not u_info:
                    await update.message.reply_text(pe("❌ এই আইডি-র কোনো ইউজার ডাটাবেজে পাওয়া যায়নি!"), parse_mode="HTML")
                    conn.close()
                    return

                cursor.execute("SELECT COUNT(*) as total_buy FROM purchases WHERE user_id = ?", (target_id,))
                total_buy = cursor.fetchone()['total_buy']
                conn.close()

                status_txt = "🔴 Banned" if u_info['is_banned'] == 1 else "🟢 Active"
                ban_btn_txt = "🟢 Unban User" if u_info['is_banned'] == 1 else "🔴 Ban User"

                ban_style = "success" if u_info['is_banned'] == 1 else "danger"
                ban_icon = "done" if u_info['is_banned'] == 1 else "stop"
                keyboard = [
                    [pbtn(ban_btn_txt.split(" ", 1)[1] if " " in ban_btn_txt else ban_btn_txt, icon=ban_icon, style=ban_style, callback_data=f"toggle_ban_{target_id}")],
                    [pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")]
                ]

                u_msg = (
                    f"👤 <b>USER DETAILS</b>\n\n"
                    f"🆔 <b>User ID:</b> <code>{u_info['user_id']}</code>\n"
                    f"👤 <b>Name:</b> {u_info['first_name']}\n"
                    f"💠 <b>Balance:</b> {u_info['balance']:.2f} BDT\n"
                    f"🛍️ <b>Total Orders:</b> {total_buy} Pcs\n"
                    f"📅 <b>Joined:</b> {u_info['joined_date']}\n"
                    f"⚡ <b>Status:</b> {status_txt}"
                )
                context.user_data.clear()
                await update.message.reply_text(pe(u_msg), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
                return
            except ValueError:
                await update.message.reply_text(pe("❌ Telegram User ID অবশ্যই সংখ্যায় হতে হবে!"), parse_mode="HTML")
                return

        elif state == 'awaiting_deposit_notify_target':
            raw_target = text.strip()
            requested_type = context.user_data.get("deposit_notify_type", "group")
            try:
                chat = await context.bot.get_chat(raw_target)
                expected_types = {"group", "supergroup"} if requested_type == "group" else {"channel"}
                if chat.type not in expected_types:
                    expected_label = "group/supergroup" if requested_type == "group" else "channel"
                    raise ValueError(f"Targetটি Telegram {expected_label} নয়।")

                bot_user = await context.bot.get_me()
                bot_member = await context.bot.get_chat_member(chat.id, bot_user.id)
                if bot_member.status not in {"administrator", "creator"}:
                    raise ValueError("এই target-এ bot administrator নয়।")

                set_setting("deposit_notify_chat_id", str(chat.id))
                set_setting("deposit_notify_type", chat.type)
                set_setting("deposit_notify_enabled", "ON")
                context.user_data.clear()
                await update.message.reply_text(
                    pe(
                        f"✅ Deposit alerts <b>{chat.type}</b>-এ চালু হয়েছে!\n"
                        f"Chat ID: <code>{chat.id}</code>\n\n"
                        "এখন pending deposit এবং Binance auto-success notification "
                        "এখানেই যাবে।"
                    ),
                    parse_mode="HTML",
                )
            except Exception as error:
                logging.error("Deposit notification target validation failed: %s", error)
                await update.message.reply_text(
                    pe(
                        "❌ Target সেভ করা যায়নি। Bot-কে target group/channel-এ "
                        "administrator করুন এবং আবার সঠিক Chat ID বা @username পাঠান।"
                    ),
                    parse_mode="HTML",
                )
            return

        elif state == 'awaiting_group_id':
            grp_id = text.strip()
            set_setting('log_group_id', grp_id)
            context.user_data.clear()
            await update.message.reply_text(pe(f"✅ Log Group ID সফলভাবে সেভ হয়েছে: <code>{grp_id}</code>"), parse_mode="HTML")
            return

        elif state == 'add_prod_step1_name':
            context.user_data['add_title'] = text.strip()
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM categories")
            cats = [r['name'] for r in cursor.fetchall()]
            conn.close()

            if not cats:
                await update.message.reply_text(pe("❌ আগে অ্যাডমিন প্যানেল থেকে একটি ক্যাটাগরি তৈরি করে নিন!"), parse_mode="HTML")
                context.user_data.clear()
                return

            keyboard = [[pbtn(c, icon=get_product_icon_key(c), style="danger", callback_data=f"seladdcat_{c}")] for c in cats]
            await update.message.reply_text(pe("🏷️ প্রোডাক্টের জন্য <b>Category</b> সিলেক্ট করুন:"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

        elif state == 'add_prod_step3_price':
            try:
                context.user_data['add_price'] = float(text.strip())
                context.user_data['state'] = 'add_prod_step4_stock'
                await update.message.reply_text(pe("📦 এবার <b>All Products / Stock Data</b> একসাথে পাঠিয়ে দিন:"), parse_mode="HTML")
            except ValueError:
                await update.message.reply_text(pe("❌ Price অবশ্যই সংখ্যায় দিন!"), parse_mode="HTML")
            return

        elif state == 'add_prod_step4_stock':
            title = context.user_data.get('add_title')
            category = context.user_data.get('add_category')
            price = context.user_data.get('add_price')

            raw_blocks = re.split(r'\n\s*\n|\n(?=\d+\.\s*Host:|\n?Host:)', text.strip())
            items_to_add = [b.strip() for b in raw_blocks if b.strip()]

            if not items_to_add:
                items_to_add = [line.strip() for line in text.strip().split('\n') if line.strip()]

            conn = get_db()
            cursor = conn.cursor()
            for item_data in items_to_add:
                cursor.execute(
                    "INSERT INTO products (category, title, price, item_data) VALUES (?, ?, ?, ?)",
                    (category, title, price, item_data)
                )
            conn.commit()

            # Product count check after insert
            cursor.execute("SELECT COUNT(*) as current_stock FROM products WHERE title = ? AND category = ?", (title, category))
            total_stock_now = cursor.fetchone()['current_stock']

            # Get all non-banned users for Auto Broadcast
            cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
            all_users = cursor.fetchall()
            conn.close()

            context.user_data.clear()
            
            # Admin confirmation message
            await update.message.reply_text(
                pe(f"🎉 <b>সফলভাবে {len(items_to_add)} টি স্টক যোগ হয়েছে!</b>\n\n"
                f"📦 <b>Name:</b> {title}\n"
                f"🏷️ <b>Category:</b> {category}\n"
                f"💰 <b>Price:</b> {price:.2f} BDT\n\n"
                f"📢 <i>মেম্বারদের কাছে অটো ব্রডকাস্ট পাঠানো হচ্ছে...</i>"),
                parse_mode="HTML"
            )

            # ==================== AUTO BROADCAST FEATURE ====================
            broadcast_text = (
                f"🔥 <b>NEW PRODUCT AVAILABLE!</b> 🔥\n\n"
                f"🏷️ <b>Product:</b> {title}\n"
                f"📁 <b>Category:</b> {category}\n"
                f"💰 <b>Price:</b> {price:.2f} BDT\n"
                f"📦 <b>Total Stock:</b> {total_stock_now} Pcs\n\n"
                f"👉 এখনই কিনতে বট থেকে <b>Buy Products</b> এ চাপ দিন!"
            )
            
            buy_keyboard = InlineKeyboardMarkup([
                [pbtn("Buy Now", icon="buy", style="danger", callback_data=f"buycat_{category}")]
            ])

            for u in all_users:
                try:
                    await context.bot.send_message(
                        chat_id=u['user_id'],
                        text=pe(broadcast_text),
                        reply_markup=buy_keyboard,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return

        elif state == 'awaiting_new_category':
            cat_name = text.strip().upper()
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(pe(f"✅ নতুন ক্যাটাগরি <b>{cat_name}</b> যোগ হয়েছে!"), parse_mode="HTML")
            return

        elif state == 'awaiting_new_admin_id':
            try:
                new_id = int(text)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
                conn.commit()
                conn.close()
                context.user_data.clear()
                await update.message.reply_text(pe(f"✅ User <code>{new_id}</code> নতুন অ্যাডমিন হিসেবে যুক্ত হয়েছে!"), parse_mode="HTML")
            except ValueError:
                await update.message.reply_text(pe("❌ আইডি অবশ্যই সংখ্যায় দিন!"), parse_mode="HTML")
            return

        elif state == 'awaiting_add_channel':
            ch_username = text.strip()
            if not ch_username.startswith('@') and not ch_username.startswith('http'):
                ch_username = f"@{ch_username}"
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO channels (username) VALUES (?)", (ch_username,))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(pe(f"✅ চ্যানেল <code>{ch_username}</code> যুক্ত হয়েছে!"), parse_mode="HTML")
            return

        elif state == 'awaiting_support_link':
            set_setting('support_link', text.strip())
            context.user_data.clear()
            await update.message.reply_text(pe(f"✅ নতুন সাপোর্ট লিংক সেভ হয়েছে: {text.strip()}"), parse_mode="HTML")
            return

        elif state == 'awaiting_ref_bonus':
            try:
                bonus_val = float(text.strip())
                set_setting('referral_commission', str(bonus_val))
                context.user_data.clear()
                await update.message.reply_text(pe(f"✅ রেফারেল কমিশন <b>{bonus_val}%</b> সেভ করা হয়েছে!"), parse_mode="HTML")
            except ValueError:
                await update.message.reply_text(pe("❌ পার্সেন্টেজ অবশ্যই সংখ্যায় টাইপ করুন!"), parse_mode="HTML")
            return

    # Deposit TrxID Input State
    if state == 'awaiting_trxid':
        await safe_delete_msg(context, user.id, update.message.message_id)
        last_bot_msg_id = context.user_data.get('last_msg_id')
        await safe_delete_msg(context, user.id, last_bot_msg_id)

        method = context.user_data.get('dep_method', 'Payment')
        amount = float(context.user_data.get('dep_amount', 0))
        dep_usdt = float(context.user_data.get('dep_usdt', 0))
        trx_id = text.strip()

        # ==================== Duplicate TrxID Check ====================
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM deposits WHERE trx_id = ? AND status IN ('pending', 'approved')", (trx_id,))
        existing_trx = cursor.fetchone()

        if existing_trx:
            conn.close()
            m = await context.bot.send_message(
                chat_id=user.id, 
                text=pe("❌ <b>এই 🧾 Transaction ID (TrxID) টি আগেই ব্যবহার করা হয়েছে!</b>\nদয়া করে সঠিক এবং নতুন TrxID টাইপ করে পাঠান:"), 
                parse_mode="HTML"
            )
            context.user_data['last_msg_id'] = m.message_id
            return

        cursor.execute(
            "SELECT amount, method, trx_id FROM deposits "
            "WHERE user_id = ? AND status = 'pending' LIMIT 1",
            (user.id,),
        )
        if cursor.fetchone():
            conn.close()
            context.user_data.clear()
            await context.bot.send_message(
                chat_id=user.id,
                text=pe(
                    "⏳ আপনার একটি ডিপোজিট রিকোয়েস্ট আগেই pending আছে। "
                    "সেটি approve বা reject না হওয়া পর্যন্ত আরেকটি deposit করা যাবে না।"
                ),
                parse_mode="HTML",
            )
            return

        # Binance is verified directly against the admin's Binance account.
        # Other payment methods continue through the normal admin approval flow.
        if method.lower() == 'binance':
            conn.close()
            verifying_message = await context.bot.send_message(
                chat_id=user.id,
                text=pe("⏳ <b>Binance payment verify করা হচ্ছে...</b>"),
                parse_mode="HTML"
            )

            is_valid, paid_amount, verify_message = check_binance_payment(trx_id)
            if not is_valid or paid_amount < dep_usdt:
                context.user_data.clear()
                await context.bot.edit_message_text(
                    chat_id=user.id,
                    message_id=verifying_message.message_id,
                    text=pe(
                        f"❌ <b>Binance payment rejected!</b>\n\n"
                        f"🧾 TrxID: <code>{trx_id}</code>\n"
                        f"💲 প্রয়োজন ছিল: <b>{dep_usdt:g} USDT</b>\n"
                        f"⚠️ কারণ: {verify_message}"
                    ),
                    parse_mode="HTML"
                )
                return

            credited, referrer_id, commission_amount = credit_binance_deposit(
                user.id, amount, dep_usdt, trx_id
            )
            if not credited:
                context.user_data.clear()
                if referrer_id == -1:
                    await context.bot.edit_message_text(
                        chat_id=user.id,
                        message_id=verifying_message.message_id,
                        text=pe(
                            "⏳ আপনার আগের ডিপোজিট রিকোয়েস্ট এখনও pending আছে। "
                            "সেটি approve বা reject না হওয়া পর্যন্ত নতুন deposit করা যাবে না।"
                        ),
                        parse_mode="HTML",
                    )
                    return
                await context.bot.edit_message_text(
                    chat_id=user.id,
                    message_id=verifying_message.message_id,
                    text=pe("❌ এই 🧾 Transaction ID ইতিমধ্যে ব্যবহার করা হয়েছে বা balance update ব্যর্থ হয়েছে।"),
                    parse_mode="HTML"
                )
                return

            context.user_data.clear()
            await context.bot.edit_message_text(
                chat_id=user.id,
                message_id=verifying_message.message_id,
                text=pe(
                    f"✅ <b>Binance payment auto-approved!</b>\n\n"
                    f"💲 Payment: <b>{dep_usdt:g} USDT</b>\n"
                    f"💠 Balance added: <b>{amount:.2f} BDT</b>\n"
                    f"🧾 TrxID: <code>{trx_id}</code>"
                ),
                parse_mode="HTML"
            )

            if referrer_id and commission_amount > 0:
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=pe(
                            f"🎉 <b>রেফার কমিশন পেয়েছেন!</b>\n\n"
                            f"আপনার রেফারে ইউজার <code>{user.id}</code> Binance deposit করায় "
                            f"<b>{commission_amount:.2f} BDT</b> কমিশন পেয়েছেন!"
                        ),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            binance_log = (
                f"✅ <b>Binance Auto-Approved!</b>\n\n"
                f"👤 User: <code>{user.id}</code>\n"
                f"💲 Amount: <b>{dep_usdt:g} USDT</b>\n"
                f"💠 Credited: <b>{amount:.2f} BDT</b>\n"
                f"🧾 TrxID: <code>{trx_id}</code>"
            )
            if not await send_deposit_notification(context, binance_log):
                log_group_id = get_setting('log_group_id')
                if log_group_id:
                    try:
                        await context.bot.send_message(
                            chat_id=log_group_id,
                            text=pe(binance_log),
                            parse_mode="HTML",
                        )
                    except Exception as error:
                        logging.error("Failed to send Binance log: %s", error)
            return

        try:
            # Serialize the check and insert so two quick submissions cannot
            # create two pending requests for the same user.
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "SELECT id FROM deposits WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user.id,),
            )
            if cursor.fetchone():
                conn.rollback()
                conn.close()
                context.user_data.clear()
                await context.bot.send_message(
                    chat_id=user.id,
                    text=pe(
                        "⏳ আপনার আগের ডিপোজিট রিকোয়েস্ট pending আছে। "
                        "এটি process না হওয়া পর্যন্ত নতুন request করা যাবে না।"
                    ),
                    parse_mode="HTML",
                )
                return
            cursor.execute(
                "INSERT INTO deposits (user_id, amount, method, trx_id, status) VALUES (?, ?, ?, ?, 'pending')",
                (user.id, amount, method, trx_id)
            )
            deposit_id = cursor.lastrowid
            conn.commit()
            conn.close()
        except sqlite3.IntegrityError:
            conn.close()
            m = await context.bot.send_message(
                chat_id=user.id, 
                text=pe("❌ <b>এই 🧾 Transaction ID (TrxID) টি ডাটাবেজে আগে থেকেই আছে!</b>\nদয়া করে সঠিক TrxID টাইপ করুন:"), 
                parse_mode="HTML"
            )
            context.user_data['last_msg_id'] = m.message_id
            return

        context.user_data.clear()
        
        await context.bot.send_message(
            chat_id=user.id, 
            text=pe("⏳ <b>আপনার ডিপোজিট রিকোয়েস্ট জমা হয়েছে!</b>\nঅ্যাডমিন ভেরিফাই করে অ্যাপ্রুভ করবেন।"), 
            parse_mode="HTML"
        )
        
        keyboard = [
            [pbtn(f"Approve {amount:.2f} BDT", icon="done", style="success", callback_data=f"appdep_{deposit_id}")],
            [pbtn("Reject", icon="close", style="danger", callback_data=f"rejdep_{deposit_id}")]
        ]
        
        usdt_info = f"\n💲 USDT Amount: <b>{dep_usdt} USDT</b>" if dep_usdt > 0 else ""
        
        admin_msg = (
            f"💠 <b>নতুন ডিপোজিট রিকোয়েস্ট!</b>\n\n"
            f"👤 ইউজার: {user.first_name} (<code>{user.id}</code>)\n"
            f"💠 মাধ্যম: <b>{method}</b>{usdt_info}\n"
            f"💠 ব্যালেন্স পাবে: <b>{amount:.2f} BDT</b>\n"
            f"🧾 TrxID: <code>{trx_id}</code>"
        )
        notification_sent = await send_deposit_notification(
            context,
            admin_msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        if not notification_sent:
            for admin_id in get_all_admin_ids():
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=pe(admin_msg),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        return

    # Main Keyboard Actions
    if action_text == "Buy Products":
        await render_categories_menu(update)

    elif action_text == "My Profile":
        ref_income = db_user['ref_earnings'] if db_user['ref_earnings'] else 0.0
        
        profile_text = (
            f"👤 <b>আপনার প্রোফাইল:</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"💠 <b>ব্যালেন্স:</b> {db_user['balance']:.2f} BDT\n"
            f"🎁 <b>রেফার থেকে আয়:</b> {ref_income:.2f} BDT"
        )
        keyboard = [
            [
                pbtn("হিস্ট্রি", icon="bag", callback_data='purchases'),
                pbtn("Leaderboard", icon="king", callback_data='view_leaderboard')
            ],
            [pbtn("Close", icon="close", style="danger", callback_data="close_msg")]
        ]
        await update.message.reply_text(pe(profile_text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif action_text == "Referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as ref_count FROM users WHERE referred_by = ?", (user.id,))
        ref_count = cursor.fetchone()['ref_count']
        conn.close()

        ref_bonus = get_setting('referral_commission')
        ref_income = db_user['ref_earnings'] if db_user['ref_earnings'] else 0.0

        ref_text = (
            f"👥 <b>রেফারেল প্রোগ্রাম</b>\n\n"
            f"🔗 <b>আপনার লিঙ্ক:</b>\n<code>{ref_link}</code>\n\n"
            f"📊 <b>মোট রেফার করেছেন:</b> {ref_count} জন\n"
            f"💰 <b>রেফার থেকে মোট আয়:</b> {ref_income:.2f} BDT\n"
            f"🎁 <b>রেফার কমিশন:</b> {ref_bonus}%\n\n"
            f"💡 আপনার রেফারে কেউ জয়েন করে ডিপোজিট করলে তার জমা করা টাকার <b>{ref_bonus}%</b> কমিশন সরাসরি আপনার একাউন্ট ব্যালেন্সে যোগ হয়ে যাবে!"
        )
        await update.message.reply_text(pe(ref_text), parse_mode="HTML")

    elif action_text == "Deposit":
        pending = get_pending_deposit(user.id)
        if pending:
            await update.message.reply_text(
                pe(
                    "⏳ <b>আপনার একটি ডিপোজিট রিকোয়েস্ট এখনও অপেক্ষমাণ আছে।</b>\n\n"
                    f"💰 Amount: <b>{pending['amount']:.2f} BDT</b>\n"
                    f"💳 Method: <b>{pending['method']}</b>\n"
                    f"🧾 TrxID: <code>{pending['trx_id']}</code>\n\n"
                    "অ্যাডমিন approve বা reject না করা পর্যন্ত নতুন ডিপোজিট করা যাবে না।"
                ),
                parse_mode="HTML",
            )
            return
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, min_deposit, icon_key FROM payment_methods")
        methods = cursor.fetchall()
        conn.close()

        if not methods:
            await update.message.reply_text(pe("❌ বর্তমানে কোনো পেমেন্ট মেথড খালি/উপলব্ধ নেই!"), parse_mode="HTML")
            return

        keyboard = []
        row = []
        for m in methods:
            m_name = m['name']
            m_min = m['min_deposit']
            m_icon = m['icon_key']
            
            unit = "USDT" if m_name.lower() == 'binance' else "BDT"
            btn_txt = f"{m_name} (Min {m_min} {unit})" if m_name.lower() == 'binance' else f"{m_name} (Min {m_min:.0f} BDT)"
            
            row.append(pbtn(btn_txt, icon=m_icon, callback_data=f'depmethod_{m_name}'))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([pbtn("Close", icon="close", style="danger", callback_data="close_msg")])

        await update.message.reply_text(pe("💠 <b>ডিপোজিট পেমেন্ট মাধ্যম বেছে নিন:</b>"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif action_text == "Support":
        supp_link = get_setting('support_link')
        keyboard = [
            [pbtn("Contact Support", icon="support", style="primary", url=supp_link)],
            [pbtn("Close", icon="close", style="danger", callback_data="close_msg")]
        ]
        await update.message.reply_text(pe("🗣️ <b>Contact us for any help:</b>"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif action_text == "Admin Panel" and is_admin(user.id):
        await send_admin_panel(update)

# ==================== Callback Queries ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    set_current_user(user)

    if data == "close_msg":
        await query.message.delete()
        return

    # Admin: export the requested user/order/deposit backup to Google Sheets.
    if is_admin(user.id) and data == "admin_backup":
        await query.edit_message_text(
            pe("⏳ <b>Backup তৈরি হচ্ছে...</b>\nGoogle Sheet আপডেট করা হচ্ছে।"),
            parse_mode="HTML",
        )
        try:
            sheet_url = await asyncio.to_thread(export_backup_to_google_sheet)
            keyboard = InlineKeyboardMarkup([
                [pbtn("Open Google Sheet", icon="link", style="success", url=sheet_url)],
                [pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")],
            ])
            await query.edit_message_text(
                pe(
                    "✅ <b>Backup সফলভাবে আপডেট হয়েছে!</b>\n\n"
                    "Users, current balance, pending balance, orders, "
                    "pending deposits এবং successful deposits আলাদা tab-এ রাখা হয়েছে।"
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as error:
            error_type = type(error).__name__
            logging.exception("Google Sheet backup failed (%s)", error_type)
            await query.edit_message_text(
                pe(
                    "❌ <b>Backup করা যায়নি।</b>\n\n"
                    f"কারণ: <code>{error_type}</code>\n\n"
                    "Render env, JSON format এবং Service Account-এর "
                    "Sheet Editor permission যাচাই করুন।"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")]
                ]),
                parse_mode="HTML",
            )
        return

    # Admin: Delete Product Categories Menu
    if is_admin(user.id) and data == "admin_del_prod_prompt":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories")
        cats = cursor.fetchall()
        conn.close()

        if not cats:
            await query.edit_message_text(pe("❌ <b>কোনো ক্যাটাগরি নেই!</b>"), reply_markup=InlineKeyboardMarkup([[pbtn("Back", icon="back", callback_data="admin_rr_control")]]), parse_mode="HTML")
            return

        keyboard = []
        row = []
        for c in cats:
            c_name = c['name']
            row.append(pbtn(c_name, icon=get_product_icon_key(c_name), style="danger", callback_data=f"delcat_sel_{c_name}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([pbtn("Back", icon="back", callback_data="admin_rr_control")])
        await query.edit_message_text(pe("🗑️ <b>প্রোডাক্ট ডিলিট করতে ক্যাটাগরি সিলেক্ট করুন:</b>"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Admin: Delete Product Items List by Category
    if is_admin(user.id) and data.startswith("delcat_sel_"):
        cat_name = data.replace("delcat_sel_", "")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, price FROM products WHERE category = ? GROUP BY title", (cat_name,))
        items = cursor.fetchall()
        conn.close()

        if not items:
            await query.edit_message_text(pe(f"❌ <b>{cat_name}</b> ক্যাটাগরিতে কোনো প্রোডাক্ট নেই!"), reply_markup=InlineKeyboardMarkup([[pbtn("Back", icon="back", callback_data="admin_del_prod_prompt")]]), parse_mode="HTML")
            return

        keyboard = []
        for i in items:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as stock FROM products WHERE title = ? AND category = ?", (i['title'], cat_name))
            stock_count = cursor.fetchone()['stock']
            conn.close()

            icon_key = get_product_icon_key(i['title'])
            keyboard.append([
                pbtn(
                    f"🗑 {i['title']} ({stock_count} Stock)",
                    icon=icon_key,
                    style="danger",
                    callback_data=f"delitem_prompt_{i['title']}"
                )
            ])

        keyboard.append([pbtn("Back", icon="back", callback_data="admin_del_prod_prompt")])
        await query.edit_message_text(pe(f"🗑️ <b>{cat_name}</b> ক্যাটাগরির প্রোডাক্টসমূহ:\nযেটি ডিলিট করতে চান তাতে ক্লিক করুন:"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Admin: Delete Product Confirmation Prompt
    if is_admin(user.id) and data.startswith("delitem_prompt_"):
        title = data.replace("delitem_prompt_", "")
        context.user_data['del_prod_title'] = title

        keyboard = [
            [
                pbtn("হ্যাঁ, ডিলিট করুন", icon="done", style="danger", callback_data="delitem_confirm"),
                pbtn("না/বাতিল", icon="close", style="primary", callback_data="admin_del_prod_prompt")
            ]
        ]
        await query.edit_message_text(pe(f"⚠️ আপনি কি নিশ্চিতভাবে <b>{title}</b> প্রোডাক্টটি স্টক থেকে ডিলিট করতে চান?"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Admin: Execute Delete Product
    if is_admin(user.id) and data == "delitem_confirm":
        title = context.user_data.get('del_prod_title')
        if not title:
            await query.edit_message_text(pe("❌ কিছু ভুল হয়েছে, আবার চেষ্টা করুন।"), reply_markup=InlineKeyboardMarkup([[pbtn("Back", icon="back", callback_data="admin_rr_control")]]), parse_mode="HTML")
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE title = ?", (title,))
        conn.commit()
        conn.close()

        context.user_data.pop('del_prod_title', None)
        await query.edit_message_text(pe(f"✅ সফলভাবে <b>{title}</b> প্রোডাক্টটি স্টক থেকে ডিলিট করা হয়েছে!"), reply_markup=InlineKeyboardMarkup([[pbtn("Back to RR Control", icon="back", callback_data="admin_rr_control")]]), parse_mode="HTML")
        return

    # RR Control Sub-Menu Handler
    if is_admin(user.id) and data == "admin_rr_control":
        context.user_data.pop('state', None)
        ref_bonus = get_setting('referral_commission')
        usdt_rate = get_setting('usdt_rate') or "120"
        
        keyboard = [
            [
                pbtn(f"Referral ({ref_bonus}%)", icon="gift", callback_data='admin_set_ref'),
                pbtn(f"USDT Rate ({usdt_rate}৳)", icon="binance", callback_data='admin_set_usdt_rate')
            ],
            [
                pbtn("Payment Set", icon="card", callback_data='admin_set_payment'),
                pbtn("Support Set", icon="support", callback_data='admin_set_supp')
            ],
            [
                pbtn("Balance Control", icon="balance_main", style="primary", callback_data='admin_balance_menu')
            ],
            [
                pbtn("Delete Product", icon="delete", style="danger", callback_data='admin_del_prod_prompt')
            ],
            [
                pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")
            ]
        ]
        await query.edit_message_text(
            pe("⚙️ <b>RR CONTROL PANEL</b>\nManage your advanced configurations below:"),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    # Balance Control Callbacks
    if is_admin(user.id) and data == "admin_balance_menu":
        context.user_data.pop('state', None)
        keyboard = [
            [
                pbtn("Add Balance", icon="balance_add", style="success", callback_data="admin_add_bal_prompt"),
                pbtn("Cut Balance", icon="balance_cut", style="danger", callback_data="admin_cut_bal_prompt")
            ],
            [
                pbtn("Back to RR Control", icon="back", callback_data="admin_rr_control")
            ]
        ]
        await query.edit_message_text(
            pe("💠 <b>Balance Management</b>\n\nইউজারের ব্যালেন্স যোগ বা কাটতে নিচের বাটনগুলোতে ক্লিক করুন:"),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    elif is_admin(user.id) and data == "admin_add_bal_prompt":
        context.user_data['state'] = 'admin_add_balance'
        await query.edit_message_text(
            pe("➕ <b>Add Balance</b>\n\nযে ইউজারের ব্যালেন্স যোগ করতে চান তার **User ID** এবং **Amount** এভাবে লিখে পাঠান:\n`User_ID Amount`\n\nউদাহরণ: `123456789 100`"),
            reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_balance_menu")]]),
            parse_mode="HTML"
        )
        return

    elif is_admin(user.id) and data == "admin_cut_bal_prompt":
        context.user_data['state'] = 'admin_cut_balance'
        await query.edit_message_text(
            pe("➖ <b>Cut Balance</b>\n\nযে ইউজারের ব্যালেন্স কাটতে চান তার **User ID** এবং **Amount** এভাবে লিখে পাঠান:\n`User_ID Amount`\n\nউদাহরণ: `123456789 50`"),
            reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_balance_menu")]]),
            parse_mode="HTML"
        )
        return

    # USDT Rate Set (Admin)
    if is_admin(user.id) and data == "admin_set_usdt_rate":
        context.user_data['state'] = 'awaiting_usdt_rate'
        curr_rate = get_setting('usdt_rate') or "120"
        await query.edit_message_text(
            pe(f"💲 <b>SET USDT CONVERSION RATE</b>\n\nবর্তমান রেট: <b>1$ = {curr_rate} BDT</b>\n\n১ ডলারের (1 USDT) নতুন BDT মূল্য টাইপ করে পাঠান (যেমন: 120, 125, 130):"),
            reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_rr_control")]]),
            parse_mode="HTML"
        )
        return

    # Broadcast Prompt
    if is_admin(user.id) and data == "admin_broadcast":
        context.user_data['state'] = 'awaiting_broadcast_msg'
        await query.edit_message_text(
            pe("📢 <b>BROADCAST MESSAGE</b>\n\n"
            "যে নোটিশ বা মেসেজটি বটের সকল মেম্বারদের কাছে পাঠাতে চান, তা এখন টাইপ করে বা ফরোয়ার্ড করে পাঠান:"),
            reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="back_admin_panel")]]),
            parse_mode="HTML"
        )
        return

    # View Leaderboard
    if data == "view_leaderboard":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.user_id, u.first_name, SUM(p.price) as total_spent 
            FROM purchases p 
            JOIN users u ON p.user_id = u.user_id 
            GROUP BY u.user_id 
            ORDER BY total_spent DESC LIMIT 10
        ''')
        top_buyers = cursor.fetchall()
        conn.close()

        if not top_buyers:
            lb_text = "🏆 <b>TOP BUYERS LEADERBOARD</b>\n\n<i>এখনও কেউ প্রোডাক্ট কেনেনি!</i>"
        else:
            lb_text = "🏆 <b>TOP 10 BUYERS LEADERBOARD</b>\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            for idx, row in enumerate(top_buyers):
                m = medals[idx] if idx < len(medals) else "🔹"
                lb_text += f"{m} <b>{row['first_name']}</b> — {row['total_spent']:.2f} BDT\n"

        keyboard = [
            [pbtn("Back", icon="back", callback_data="back_to_profile")],
            [pbtn("Close", icon="close", style="danger", callback_data="close_msg")]
        ]
        
        await query.edit_message_text(text=pe(lb_text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Back to Profile
    if data == "back_to_profile":
        db_user = get_or_create_user(user.id, user.first_name)
        ref_income = db_user['ref_earnings'] if db_user['ref_earnings'] else 0.0
        
        profile_text = (
            f"👤 <b>আপনার প্রোফাইল:</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"💠 <b>ব্যালেন্স:</b> {db_user['balance']:.2f} BDT\n"
            f"🎁 <b>রেফার থেকে আয়:</b> {ref_income:.2f} BDT"
        )
        keyboard = [
            [
                pbtn("হিস্ট্রি", icon="bag", callback_data='purchases'),
                pbtn("Leaderboard", icon="king", callback_data='view_leaderboard')
            ],
            [pbtn("Close", icon="close", style="danger", callback_data="close_msg")]
        ]
        
        await query.edit_message_text(text=pe(profile_text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Purchase History Callback
    if data == "purchases":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT title, price, date FROM purchases WHERE user_id = ? ORDER BY id DESC", (user.id,))
        records = cursor.fetchall()
        conn.close()

        keyboard = [
            [pbtn("Back", icon="back", callback_data="back_to_profile")],
            [pbtn("Close", icon="close", style="danger", callback_data="close_msg")]
        ]

        if not records:
            history_text = "🛍️ <b>আপনি এখনও কোনো প্রোডাক্ট কেনেননি!</b>"
        else:
            history_text = f"🛍️ <b>আপনার ক্রয়কৃত প্রোডাক্টের হিস্ট্রি (মোট: {len(records)} টি):</b>\n\n"
            for idx, r in enumerate(records, 1):
                history_text += f"{idx}. <b>{r['title']}</b> - {r['price']:.2f} BDT\n📅 <i>{r['date']}</i>\n\n"

        await query.edit_message_text(text=pe(history_text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Admin: User Search & Ban System
    if is_admin(user.id) and data == "admin_user_mgmt":
        context.user_data['state'] = 'awaiting_search_user_id'
        await query.edit_message_text(pe("👤 যে মেম্বারের ব্যালেন্স বা স্ট্যাটাস দেখতে চান, তার <b>Telegram User ID</b> পাঠান:"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="back_admin_panel")]]), parse_mode="HTML")
        return

    elif is_admin(user.id) and data.startswith("toggle_ban_"):
        target_id = int(data.split('_')[2])
        if target_id == SUPER_ADMIN_ID:
            await query.answer("অনারকে ব্যান করা যাবে না!", show_alert=True)
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (target_id,))
        u = cursor.fetchone()

        if u:
            new_ban_state = 0 if u['is_banned'] == 1 else 1
            cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_ban_state, target_id))
            conn.commit()
            conn.close()

            status_msg = "ব্যান করা হয়েছে!" if new_ban_state == 1 else "আনব্যান করা হয়েছে!"
            await query.answer(f"User {target_id} কে {status_msg}", show_alert=True)
            
            context.user_data['state'] = 'awaiting_search_user_id'
            await query.edit_message_text(
                pe(f"✅ ইউজার <code>{target_id}</code>-কে সফলভাবে {status_msg}\n\nআরেকজনের তথ্য দেখতে চাইলে নতুন <b>Telegram User ID</b> পাঠান:"),
                reply_markup=InlineKeyboardMarkup([[pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")]]),
                parse_mode="HTML"
            )
            return

    # Admin: Group Log Settings
    if is_admin(user.id) and data == "admin_deposit_notify":
        context.user_data.pop('state', None)
        notify_enabled = deposit_notifications_enabled()
        notify_target = get_setting("deposit_notify_chat_id") or "Not Set"
        notify_type = get_setting("deposit_notify_type") or "Not Set"
        keyboard = [
            [
                pbtn("Set Group", icon="group", callback_data="prompt_deposit_group"),
                pbtn("Set Channel", icon="megaphone", callback_data="prompt_deposit_channel"),
            ],
            [
                pbtn(
                    "Disable Alerts" if notify_enabled else "Enable Alerts",
                    icon="stop" if notify_enabled else "done",
                    style="danger" if notify_enabled else "success",
                    callback_data="toggle_deposit_notify",
                )
            ],
            [pbtn("Back", icon="back", callback_data="back_admin_panel")],
        ]
        msg = (
            "💠 <b>DEPOSIT ALERT SETTINGS</b>\n\n"
            f"Status: <b>{'ON' if notify_enabled else 'OFF'}</b>\n"
            f"Target type: <b>{notify_type}</b>\n"
            f"Target: <code>{notify_target}</code>\n\n"
            "ON থাকলে pending deposit request এবং Binance auto-success "
            "শুধু এই group/channel-এ যাবে; admin-এর private bot inbox-এ যাবে না।\n"
            "Bot-কে target group/channel-এ administrator হতে হবে।"
        )
        await query.edit_message_text(
            pe(msg),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return

    if is_admin(user.id) and data in {"prompt_deposit_group", "prompt_deposit_channel"}:
        context.user_data["state"] = "awaiting_deposit_notify_target"
        context.user_data["deposit_notify_type"] = (
            "group" if data == "prompt_deposit_group" else "channel"
        )
        target_label = "group Chat ID" if data == "prompt_deposit_group" else "channel @username বা Chat ID"
        await query.edit_message_text(
            pe(
                f"📢 target-এর <b>{target_label}</b> পাঠান:\n\n"
                "উদাহরণ: <code>-100123456789</code> অথবা <code>@my_channel</code>\n"
                "সেভ করার আগে bot-এর administrator permission যাচাই হবে।"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[pbtn("Cancel", icon="close", style="danger", callback_data="admin_deposit_notify")]]
            ),
            parse_mode="HTML",
        )
        return

    if is_admin(user.id) and data == "toggle_deposit_notify":
        if not get_setting("deposit_notify_chat_id").strip():
            await query.answer("আগে একটি group বা channel সেট করুন।", show_alert=True)
            return
        new_status = "OFF" if get_setting("deposit_notify_enabled") == "ON" else "ON"
        set_setting("deposit_notify_enabled", new_status)
        await query.answer(
            f"Deposit alerts {new_status} করা হয়েছে।",
            show_alert=True,
        )
        await query.edit_message_text(
            pe(
                f"💠 <b>Deposit alerts {new_status}</b>\n\n"
                "Settings দেখতে আবার Deposit Alerts চাপুন।"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[pbtn("Back to Admin Panel", icon="back", callback_data="back_admin_panel")]]
            ),
            parse_mode="HTML",
        )
        return

    if is_admin(user.id) and data == "admin_group_log":
        context.user_data.pop('state', None)
        log_group = get_setting('log_group_id') or "Not Set"
        keyboard = [
            [pbtn("Set / Change Group ID", icon="link", callback_data="prompt_set_group_id")],
            [pbtn("Back", icon="back", callback_data="back_admin_panel")]
        ]
        msg = (
            f"📢 <b>GROUP LOG SETTINGS</b>\n\n"
            f"বর্তমান Log Group ID: <code>{log_group}</code>\n\n"
            f"💡 <i>ইউজার ডিপোজিট বা কেনাকাটা করলে এই গ্রুপে অটো নোটিফিকেশন যাবে।</i>"
        )
        await query.edit_message_text(pe(msg), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == "prompt_set_group_id":
        context.user_data['state'] = 'awaiting_group_id'
        await query.edit_message_text(
            pe("📢 গ্রুপের <b>Chat ID</b> লিখে পাঠান (যেমন: <code>-100123456789</code>):"),
            reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_group_log")]]),
            parse_mode="HTML"
        )
        return

    # Check Force Join Callback
    if data == "check_join":
        is_joined, missing_channels = await check_force_join(user.id, context)
        if is_joined:
            await query.message.delete()
            get_or_create_user(user.id, user.first_name)
            await context.bot.send_message(
                chat_id=user.id,
                text=pe(f"👋 <b>RR SHOP</b> এ আপনাকে স্বাগতম, {user.first_name}!"),
                reply_markup=get_main_keyboard(user.id),
                parse_mode="HTML"
            )
        else:
            await query.answer("❌ আপনি এখনও সব চ্যানেলে জয়েন করেননি!", show_alert=True)
            
            buttons = []
            for ch in missing_channels:
                url = ch if ch.startswith('http') else f"https://t.me/{ch.replace('@', '')}"
                buttons.append([pbtn("JOIN CHANNEL", icon="link", style="primary", url=url)])
            
            buttons.append([pbtn("Verify / Check Again", icon="refresh", style="success", callback_data="check_join")])
            
            try:
                await query.edit_message_text(
                    pe("⚠️ <b>বট ব্যবহার করতে নিচের চ্যানেলে জয়েন করুন:</b>"),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return

    # Dynamic Deposit Method Selection Callback
    if data.startswith('depmethod_'):
        pending = get_pending_deposit(user.id)
        if pending:
            await query.answer(
                "আপনার আগের deposit request approve/reject হওয়া পর্যন্ত অপেক্ষা করুন।",
                show_alert=True,
            )
            return
        method_name = data.split('_')[1]

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT min_deposit FROM payment_methods WHERE name = ?", (method_name,))
        res = cursor.fetchone()
        conn.close()

        min_limit = res['min_deposit'] if res else 10.0

        context.user_data['dep_method'] = method_name
        context.user_data['state'] = 'awaiting_deposit_amount'
        
        await query.message.delete()
        
        if method_name.lower() == 'binance':
            try:
                usdt_rate = float(get_setting('usdt_rate'))
            except ValueError:
                usdt_rate = 120.0
            prompt_text = f"💠 <b>{method_name}</b> বেছে নিয়েছেন।\n\nআপনি কত <b>USDT ($)</b> ডিপোজিট করতে চান? (সংখ্যায় টাইপ করুন, মিনিমাম: <b>{min_limit} USDT</b>):\n💡 <i>বর্তমান রেট: 1$ = {usdt_rate:.2f} BDT</i>"
        else:
            prompt_text = f"💠 <b>{method_name}</b> বেছে নিয়েছেন।\n\nআপনি কত টাকা ডিপোজিট করতে চান? (সংখ্যায় টাইপ করুন, মিনিমাম: <b>{min_limit:.2f} BDT</b>):"

        m = await context.bot.send_message(
            chat_id=user.id,
            text=pe(prompt_text),
            parse_mode="HTML"
        )
        context.user_data['last_msg_id'] = m.message_id
        return

    # Category Selection in Product Add
    if is_admin(user.id) and data.startswith('seladdcat_'):
        cat_selected = data.replace('seladdcat_', '')
        context.user_data['add_category'] = cat_selected
        context.user_data['state'] = 'add_prod_step3_price'
        await query.edit_message_text(pe(f"✅ Selected Category: <b>{cat_selected}</b>\n\n💰 এবার প্রতি পিসের <b>Price (টাকা)</b> টাইপ করে পাঠান:"), parse_mode="HTML")
        return

    # Category Management
    if is_admin(user.id) and data == 'admin_cat_mgmt':
        context.user_data.pop('state', None)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories")
        cats = [row['name'] for row in cursor.fetchall()]
        conn.close()

        keyboard = []
        for c in cats:
            keyboard.append([pbtn(f"Delete: {c}", icon="delete", style="danger", callback_data=f"del_cat_{c}")])

        keyboard.append([pbtn("Add Category", icon="new", style="success", callback_data="admin_add_cat_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "📁 <b>CATEGORY MANAGEMENT</b>\nএখান থেকে ক্যাটাগরি তৈরি বা ডিলিট করুন:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == 'admin_add_cat_prompt':
        context.user_data['state'] = 'awaiting_new_category'
        await query.edit_message_text(pe("📁 নতুন ক্যাটাগরির নাম লিখুন (যেমন: PROXY, VPN, GMAIL):"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_cat_mgmt")]]), parse_mode="HTML")
        return

    elif is_admin(user.id) and data.startswith('del_cat_'):
        cat_to_del = data.replace('del_cat_', '')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE name = ?", (cat_to_del,))
        conn.commit()
        
        cursor.execute("SELECT name FROM categories")
        cats = [row['name'] for row in cursor.fetchall()]
        conn.close()

        keyboard = []
        for c in cats:
            keyboard.append([pbtn(f"Delete: {c}", icon="delete", style="danger", callback_data=f"del_cat_{c}")])

        keyboard.append([pbtn("Add Category", icon="new", style="success", callback_data="admin_add_cat_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "📁 <b>CATEGORY MANAGEMENT</b>\nএখান থেকে ক্যাটাগরি তৈরি বা ডিলিট করুন:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer(f"Category {cat_to_del} ডিলিট করা হয়েছে!", show_alert=False)
        return

    # Dynamic Payment Settings Menu (Admin Panel)
    if is_admin(user.id) and data == 'admin_set_payment':
        context.user_data.pop('state', None)
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, number_or_address, min_deposit, icon_key FROM payment_methods")
        p_methods = cursor.fetchall()
        conn.close()

        keyboard = []
        msg_details = ""
        for p in p_methods:
            p_name = p['name']
            p_num = p['number_or_address']
            p_min = p['min_deposit']
            unit_txt = "USDT" if 'binance' in p_name.lower() else "BDT"
            
            msg_details += f"🔹 <b>{p_name}:</b> <code>{p_num}</code> (Min: {p_min} {unit_txt})\n"
            keyboard.append([pbtn(f"Delete {p_name}", icon="delete", style="danger", callback_data=f"del_pay_{p_name}")])

        keyboard.append([pbtn("Add / Update Payment Method", icon="new", style="success", callback_data='add_pay_prompt')])
        keyboard.append([pbtn("Back to RR Control", icon="back", callback_data='admin_rr_control')])

        msg = f"⚙️ <b>PAYMENT SETTINGS</b>\n\n{msg_details}\n💡 যেকোনো পেমেন্ট মেথড তৈরি করতে বা লিমিট আপডেট করতে নিচের বাটনে চাপ দিন."
        await query.edit_message_text(pe(msg), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == 'add_pay_prompt':
        context.user_data['state'] = 'add_pay_step1_name'
        await query.edit_message_text(pe("💳 পেমেন্ট মেথডের নাম লিখুন (যেমন: bKash, Nagad, Rocket, Upay, Binance):"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_set_payment")]]), parse_mode="HTML")
        return

    elif is_admin(user.id) and data.startswith('del_pay_'):
        pay_to_del = data.replace('del_pay_', '')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM payment_methods WHERE name = ?", (pay_to_del,))
        conn.commit()

        cursor.execute("SELECT name, number_or_address, min_deposit, icon_key FROM payment_methods")
        p_methods = cursor.fetchall()
        conn.close()

        keyboard = []
        msg_details = ""
        for p in p_methods:
            p_name = p['name']
            p_num = p['number_or_address']
            p_min = p['min_deposit']
            unit_txt = "USDT" if 'binance' in p_name.lower() else "BDT"
            
            msg_details += f"🔹 <b>{p_name}:</b> <code>{p_num}</code> (Min: {p_min} {unit_txt})\n"
            keyboard.append([pbtn(f"Delete {p_name}", icon="delete", style="danger", callback_data=f"del_pay_{p_name}")])

        keyboard.append([pbtn("Add / Update Payment Method", icon="new", style="success", callback_data='add_pay_prompt')])
        keyboard.append([pbtn("Back to RR Control", icon="back", callback_data='admin_rr_control')])

        msg = f"⚙️ <b>PAYMENT SETTINGS</b>\n\n{msg_details}\n💡 যেকোনো পেমেন্ট মেথড তৈরি করতে বা লিমিট আপডেট করতে নিচের বাটনে চাপ দিন."
        await query.edit_message_text(pe(msg), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer(f"Payment Method {pay_to_del} ডিলিট করা হয়েছে!", show_alert=False)
        return

    elif is_admin(user.id) and data == 'admin_set_ref':
        context.user_data['state'] = 'awaiting_ref_bonus'
        await query.edit_message_text(pe("🎁 রেফারেল কমিশন কত পার্সেন্ট (<b>%</b>) দিতে চান? (শুধু সংখ্যা লিখুন, যেমন: 10):"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_rr_control")]]), parse_mode="HTML")
        return

    # Product Buy Category Navigation
    if data.startswith('buycat_'):
        cat_name = data.replace('buycat_', '')
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, title, price FROM products WHERE category = ? GROUP BY title", (cat_name,))
        items = cursor.fetchall()

        keyboard = []
        for i in items:
            cursor.execute("SELECT COUNT(*) as stock FROM products WHERE title = ? AND category = ?", (i['title'], cat_name))
            stock_count = cursor.fetchone()['stock']
            
            icon_key = get_product_icon_key(i['title'])
            
            keyboard.append([
                pbtn(
                    f"{i['title']} · {i['price']:.2f} BDT ({stock_count} Stock)",
                    icon=icon_key,
                    style="danger",
                    callback_data=f"itemselect_{i['id']}"
                )
            ])
        conn.close()

        keyboard.append([pbtn("Back", icon="back", callback_data="back_to_cats")])

        if not items:
            await query.edit_message_text(pe(f"❌ <b>{cat_name}</b> ক্যাটাগরিতে বর্তমানে কোনো স্টক নেই!"), reply_markup=InlineKeyboardMarkup([[pbtn("Back", icon="back", callback_data="back_to_cats")]]), parse_mode="HTML")
            return

        await query.edit_message_text(pe(f"🛍️ <b>{cat_name} ক্যাটাগরির প্রোডাক্টসমূহ:</b>"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif data == "back_to_cats":
        await render_categories_menu(query)
        return

    elif data.startswith('itemselect_'):
        p_id = int(data.split('_')[1])
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT category, title, price FROM products WHERE id = ?", (p_id,))
        res = cursor.fetchone()

        if not res:
            await query.answer("❌ প্রোডাক্টটি পাওয়া যায়নি!", show_alert=True)
            conn.close()
            return

        title = res['title']
        cat_name = res['category']
        price = res['price']

        cursor.execute("SELECT COUNT(*) as stock FROM products WHERE title = ? AND category = ?", (title, cat_name))
        stock_res = cursor.fetchone()
        stock = stock_res['stock'] if stock_res else 0

        conn.close()

        if stock == 0:
            await query.answer("❌ প্রোডাক্টটি আউট অফ স্টক!", show_alert=True)
            return

        context.user_data['buy_cat'] = cat_name
        context.user_data['buy_pid'] = p_id
        context.user_data['buy_qty'] = 1

        msg = (
            f"🏷️ <b>{title}</b>\n"
            f"💎 প্রাইস: {price:.2f} BDT\n"
            f"📦 স্টক: {stock}\n\n"
            f"<b>পরিমাণ:</b> 1\n"
            f"<b>মোট:</b> 💎 {price:.2f} BDT"
        )
        await query.edit_message_text(pe(msg), reply_markup=build_quantity_keyboard(1), parse_mode="HTML")
        return

    # Quantity Selection Buttons
    if data in ['qty_plus', 'qty_minus', 'qty_custom', 'qty_cancel', 'qty_confirm', 'qty_noop']:
        p_id = context.user_data.get('buy_pid')
        qty = context.user_data.get('buy_qty', 1)

        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT category, title, price FROM products WHERE id = ?", (p_id,))
        res = cursor.fetchone()

        if not res:
            await query.edit_message_text(pe("❌ প্রোডাক্টটি পাওয়া যায়নি!"), parse_mode="HTML")
            conn.close()
            return

        price = res['price']
        title = res['title']
        cat_name = res['category']

        cursor.execute("SELECT COUNT(*) as stock FROM products WHERE title = ? AND category = ?", (title, cat_name))
        stock_res = cursor.fetchone()
        stock = stock_res['stock'] if stock_res else 0
        conn.close()

        if stock == 0:
            await query.edit_message_text(pe("❌ এই প্রোডাক্টটি বর্তমানে স্টক আউট!"), parse_mode="HTML")
            return

        if data == 'qty_plus':
            if qty < stock:
                qty += 1
                context.user_data['buy_qty'] = qty
            else:
                await query.answer(f"স্টকে সর্বোচ্চ {stock} টি আছে!", show_alert=True)
                return

        elif data == 'qty_minus':
            if qty > 1:
                qty -= 1
                context.user_data['buy_qty'] = qty
            else:
                await query.answer("সর্বনিম্ন ১ টি নিতে হবে!", show_alert=True)
                return

        elif data == 'qty_custom':
            context.user_data['state'] = 'awaiting_custom_qty'
            await query.message.delete()
            m = await context.bot.send_message(chat_id=user.id, text=pe(f"🔢 কত পিস নিতে চান? সংখ্যা টাইপ করুন (সর্বোচ্চ স্টক: {stock}):"), parse_mode="HTML")
            context.user_data['last_msg_id'] = m.message_id
            return

        elif data == 'qty_cancel':
            context.user_data.clear()
            await query.edit_message_text(pe("❌ অর্ডার বাতিল করা হয়েছে।"), parse_mode="HTML")
            return

        elif data == 'qty_confirm':
            total_price = price * qty
            db_user = get_or_create_user(user.id, user.first_name)

            if db_user['balance'] < total_price:
                await query.edit_message_text(pe(f"❌ আপনার পর্যাপ্ত ব্যালেন্স নেই!\n\nপ্রয়োজন: {total_price:.2f} BDT\nআপনার ব্যালেন্স: {db_user['balance']:.2f} BDT"), parse_mode="HTML")
                return

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, item_data FROM products WHERE category = ? AND title = ? LIMIT ?", (cat_name, title, qty))
            p_items = cursor.fetchall()

            if len(p_items) < qty:
                await query.edit_message_text(pe("❌ পর্যাপ্ত স্টক নেই!"), parse_mode="HTML")
                conn.close()
                return

            update_balance(user.id, -total_price)
            today = datetime.now().strftime("%Y-%m-%d %H:%M")

            delivered_data = []
            for item in p_items:
                cursor.execute("DELETE FROM products WHERE id = ?", (item['id'],))
                cursor.execute("INSERT INTO purchases (user_id, title, price, date) VALUES (?, ?, ?, ?)", (user.id, title, price, today))
                delivered_data.append(item['item_data'])
            
            conn.commit()
            conn.close()

            items_formatted = "\n\n━━━━━━━━━━━━━━━\n\n".join([format_item_to_code(d) for d in delivered_data])
            
            await query.edit_message_text(
                pe(f"🎉 <b>ক্রয় সফল হয়েছে!</b>\n\n"
                f"📦 <b>প্রোডাক্ট:</b> {title}\n"
                f"🔢 <b>পরিমাণ:</b> {qty} পিস\n"
                f"💰 <b>মোট মূল্য:</b> {total_price:.2f} BDT\n\n"
                f"🔑 <b>আপনার ডাটা (ট্যাপ করলেই কপি হবে):</b>\n\n{items_formatted}"), 
                parse_mode="HTML"
            )

            log_group_id = get_setting('log_group_id')
            if log_group_id:
                try:
                    group_msg = (
                        f"🛒 <b>NEW PURCHASE NOTIFICATION!</b>\n\n"
                        f"👤 <b>Buyer:</b> {user.first_name} (<code>{user.id}</code>)\n"
                        f"📦 <b>Product:</b> {title}\n"
                        f"📁 <b>Category:</b> {cat_name}\n"
                        f"🔢 <b>Quantity:</b> {qty} Pcs\n"
                        f"💰 <b>Total Paid:</b> {total_price:.2f} BDT\n"
                        f"📅 <b>Time:</b> {today}"
                    )
                    await context.bot.send_message(chat_id=log_group_id, text=pe(group_msg), parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Failed to send log to group: {e}")

            context.user_data.clear()
            return

        total = price * qty
        msg = (
            f"🏷️ <b>{title}</b>\n"
            f"💎 প্রাইস: {price:.2f} BDT\n"
            f"📦 স্টক: {stock}\n\n"
            f"<b>পরিমাণ:</b> {qty}\n"
            f"<b>মোট:</b> 💎 {total:.2f} BDT"
        )
        await query.edit_message_text(pe(msg), reply_markup=build_quantity_keyboard(qty), parse_mode="HTML")
        return

    # Admin Management Callbacks
    if is_admin(user.id) and data == 'admin_mgmt':
        context.user_data.pop('state', None)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        admins = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        keyboard = []
        for aid in admins:
            if aid == SUPER_ADMIN_ID:
                keyboard.append([pbtn(f"Owner: {aid}", icon="king", callback_data="noop")])
            else:
                keyboard.append([pbtn(f"Delete: {aid}", icon="delete", style="danger", callback_data=f"del_admin_{aid}")])

        keyboard.append([pbtn("Add Admin", icon="new", style="success", callback_data="admin_add_admin_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "👤 <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif is_admin(user.id) and data.startswith("del_admin_"):
        del_id = int(data.split('_')[2])
        if del_id == SUPER_ADMIN_ID:
            await query.answer("অনারকে ডিলিট করা সম্ভব নয়!", show_alert=True)
            return
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE user_id = ?", (del_id,))
        conn.commit()
        
        cursor.execute("SELECT user_id FROM admins")
        admins = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        keyboard = []
        for aid in admins:
            if aid == SUPER_ADMIN_ID:
                keyboard.append([pbtn(f"Owner: {aid}", icon="king", callback_data="noop")])
            else:
                keyboard.append([pbtn(f"Delete: {aid}", icon="delete", style="danger", callback_data=f"del_admin_{aid}")])

        keyboard.append([pbtn("Add Admin", icon="new", style="success", callback_data="admin_add_admin_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "👤 <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer(f"Admin {del_id} রিমুভ করা হয়েছে!", show_alert=False)
        return

    elif is_admin(user.id) and data == "admin_add_admin_prompt":
        context.user_data['state'] = 'awaiting_new_admin_id'
        await query.edit_message_text(pe("👑 নতুন অ্যাডমিনের <b>Telegram User ID</b> লিখুন:"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_mgmt")]]), parse_mode="HTML")
        return

    # Force Join Callbacks
    if is_admin(user.id) and data == 'admin_fj_sys':
        context.user_data.pop('state', None)
        status = get_setting('force_join_status')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM channels")
        channels = [row['username'] for row in cursor.fetchall()]
        conn.close()

        status_text = "STATUS: ON" if status == 'ON' else "STATUS: OFF"
        status_style = "success" if status == 'ON' else "danger"
        status_icon = "done" if status == 'ON' else "warn"
        keyboard = [
            [pbtn(status_text, icon=status_icon, style=status_style, callback_data="toggle_fj_status")]
        ]
        for ch in channels:
            keyboard.append([pbtn(f"Delete: {ch}", icon="delete", style="danger", callback_data=f"del_channel_{ch}")])

        keyboard.append([pbtn("Add Channel", icon="new", style="success", callback_data="admin_add_channel_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == "toggle_fj_status":
        curr = get_setting('force_join_status')
        new_st = 'OFF' if curr == 'ON' else 'ON'
        set_setting('force_join_status', new_st)
        
        status = get_setting('force_join_status')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM channels")
        channels = [row['username'] for row in cursor.fetchall()]
        conn.close()

        status_text = "STATUS: ON" if status == 'ON' else "STATUS: OFF"
        status_style = "success" if status == 'ON' else "danger"
        status_icon = "done" if status == 'ON' else "warn"
        keyboard = [
            [pbtn(status_text, icon=status_icon, style=status_style, callback_data="toggle_fj_status")]
        ]
        for ch in channels:
            keyboard.append([pbtn(f"Delete: {ch}", icon="delete", style="danger", callback_data=f"del_channel_{ch}")])

        keyboard.append([pbtn("Add Channel", icon="new", style="success", callback_data="admin_add_channel_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer(f"Force Join {new_st} করা হয়েছে!", show_alert=False)
        return

    elif is_admin(user.id) and data.startswith("del_channel_"):
        ch_name = data.replace('del_channel_', '')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE username = ?", (ch_name,))
        conn.commit()
        
        status = get_setting('force_join_status')
        cursor.execute("SELECT username FROM channels")
        channels = [row['username'] for row in cursor.fetchall()]
        conn.close()

        status_text = "STATUS: ON" if status == 'ON' else "STATUS: OFF"
        status_style = "success" if status == 'ON' else "danger"
        status_icon = "done" if status == 'ON' else "warn"
        keyboard = [
            [pbtn(status_text, icon=status_icon, style=status_style, callback_data="toggle_fj_status")]
        ]
        for ch in channels:
            keyboard.append([pbtn(f"Delete: {ch}", icon="delete", style="danger", callback_data=f"del_channel_{ch}")])

        keyboard.append([pbtn("Add Channel", icon="new", style="success", callback_data="admin_add_channel_prompt")])
        keyboard.append([pbtn("Back", icon="back", callback_data="back_admin_panel")])

        text = "🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:"
        await query.edit_message_text(pe(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer("চ্যানেল ডিলিট হয়েছে!", show_alert=False)
        return

    elif is_admin(user.id) and data == "admin_add_channel_prompt":
        context.user_data['state'] = 'awaiting_add_channel'
        await query.edit_message_text(pe("🔗 যোগ করার জন্য চ্যানেলের <b>Username বা Invite Link</b> লিখে পাঠান:"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_fj_sys")]]), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == "back_admin_panel":
        context.user_data.pop('state', None)
        await send_admin_panel(update)
        return

    elif is_admin(user.id) and data == 'admin_add_prod':
        context.user_data['state'] = 'add_prod_step1_name'
        await query.edit_message_text(pe("📦 <b>Step 1:</b> প্রোডাক্টের <b>Name / Title</b> টাইপ করে পাঠান:"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="back_admin_panel")]]), parse_mode="HTML")
        return

    elif is_admin(user.id) and data == 'admin_set_supp':
        context.user_data['state'] = 'awaiting_support_link'
        await query.edit_message_text(pe("💬 নতুন <b>Support Username / Link</b> পাঠান:"), reply_markup=InlineKeyboardMarkup([[pbtn("Cancel", icon="close", style="danger", callback_data="admin_rr_control")]]), parse_mode="HTML")
        return

    # Deposit Approval Callbacks
    if is_admin(user.id) and (data.startswith('appdep_') or data.startswith('rejdep_')):
        is_approve = data.startswith('appdep_')
        deposit_id = int(data.split('_')[1])

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount, method, trx_id, status FROM deposits WHERE id = ?", (deposit_id,))
        dep = cursor.fetchone()

        if not dep:
            await query.answer("❌ ডিপোজিট রেকর্ড পাওয়া যায়নি!", show_alert=True)
            conn.close()
            return

        if dep['status'] != 'pending':
            await query.answer("⚠️ এই ডিপোজিটটি ইতিমধ্যেই প্রসেস করা হয়েছে!", show_alert=True)
            conn.close()
            return

        target_user = dep['user_id']
        amount = dep['amount']
        method = dep['method']
        trx_id = dep['trx_id']

        if is_approve:
            cursor.execute("UPDATE deposits SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?", (user.id, datetime.now(), deposit_id))
            conn.commit()

            update_balance(target_user, amount)

            cursor.execute("SELECT first_name, referred_by FROM users WHERE user_id = ?", (target_user,))
            user_info = cursor.fetchone()
            target_name = user_info['first_name'] if user_info else "User"

            ref_msg = ""
            if user_info and user_info['referred_by'] > 0:
                referrer_id = user_info['referred_by']
                try:
                    commission_percent = float(get_setting('referral_commission'))
                except ValueError:
                    commission_percent = 10.0

                commission_amount = (amount * commission_percent) / 100.0
                add_ref_earnings(referrer_id, commission_amount)

                ref_msg = f"\n🎁 <i>Referrer (ID: <code>{referrer_id}</code>) received {commission_amount:.2f} BDT commission!</i>"

                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=pe(f"🎉 <b>রেফার কমিশন পেয়েছেন!</b>\n\nআপনার রেফারে ইউজার <code>{target_user}</code> ডিপোজিট করার ফলে আপনি <b>{commission_amount:.2f} BDT</b> ({commission_percent}%) কমিশন পেয়েছেন!"),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            conn.close()

            await query.answer("✅ Deposit approved!", show_alert=True)
            await query.edit_message_text(pe(f"✅ <b>Approved by {user.first_name}!</b>\n\n👤 User: <code>{target_user}</code>\n💰 Amount: {amount:.2f} BDT{ref_msg}"), parse_mode="HTML")

            try:
                await context.bot.send_message(chat_id=target_user, text=pe(f"🎉 <b>আপনার ডিপোজিট সফল হয়েছে!</b>\n💠 ব্যালেন্সে যোগ হয়েছে: {amount:.2f} BDT"), parse_mode="HTML")
            except Exception:
                pass

            group_msg = (
                f"💠 <b>NEW SUCCESSFUL DEPOSIT!</b>\n\n"
                f"👤 <b>User:</b> {target_name} (<code>{target_user}</code>)\n"
                f"💠 <b>Method:</b> {method}\n"
                f"💰 <b>Amount:</b> {amount:.2f} BDT\n"
                f"🧾 <b>TrxID:</b> <code>{trx_id}</code>\n"
                f"📅 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            if not await send_deposit_notification(context, group_msg):
                log_group_id = get_setting('log_group_id')
                if log_group_id:
                    try:
                        await context.bot.send_message(
                            chat_id=log_group_id,
                            text=pe(group_msg),
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logging.error(f"Failed to send deposit log to group: {e}")

        else:
            cursor.execute("UPDATE deposits SET status = 'rejected', approved_by = ?, approved_at = ? WHERE id = ?", (user.id, datetime.now(), deposit_id))
            conn.commit()
            conn.close()

            await query.answer("❌ Deposit rejected!", show_alert=True)
            await query.edit_message_text(pe(f"❌ <b>Rejected by {user.first_name}!</b>"), parse_mode="HTML")

            try:
                await context.bot.send_message(
                    chat_id=target_user,
                    text=pe("❌ SORRY DEAR আপনার ডিপোজিট রিজেক্ট করা হয়েছে, দয়া করে সব ঠিকঠাক ডিটেইলস দিন।"),
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Failed to send rejection message to user: {e}")

        return

# ==================== Render / UptimeRobot Health Server ====================
health_app = Flask(__name__)


@health_app.get("/")
def health_home():
    return jsonify({"status": "ok", "service": "rr-shop-bot"})


@health_app.get("/health")
def health_check():
    return jsonify({"status": "ok"})


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    health_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ==================== Main Runner ====================

if __name__ == '__main__':
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env variable সেট করা হয়নি।")
    if SUPER_ADMIN_ID <= 0:
        raise RuntimeError("SUPER_ADMIN_ID env variable সেট করা হয়নি।")

    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=run_auto_backup_worker, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("🚀 Bot is running with MongoDB persistence and health endpoint.")
    app.run_polling(drop_pending_updates=True)
