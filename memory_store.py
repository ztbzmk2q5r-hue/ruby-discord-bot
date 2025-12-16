import os
import sqlite3
from contextlib import closing

DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")

def _connect():
    # check_same_thread=False: discord.py のイベントループでも安全寄りに使えるように
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with closing(_connect()) as con:
        cur = con.cursor()

        # ユーザーごとの設定（ニックネームなど）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id TEXT PRIMARY KEY,
            nickname TEXT
        )
        """)

        # チャンネル（DM）ごとのメッセージ履歴
        cur.execute("""
        CREATE TABLE IF NOT EXISTS channel_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            author_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 1日あたりの使用回数
        cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id TEXT NOT NULL,
            day TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        )
        """)

        # （将来戻したくなった時用）許可制
        cur.execute("""
        CREATE TABLE IF NOT EXISTS allowed_users (
            user_id TEXT PRIMARY KEY
        )
        """)

        # よく使う検索を速くする
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_messages_channel_id ON channel_messages(channel_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_messages_created_at ON channel_messages(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_usage_day ON daily_usage(day)")

        con.commit()

# ---------------- ニックネーム ----------------
def set_nickname(user_id: str, nickname: str):
    nickname = (nickname or "").strip()[:20]
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("""
        INSERT INTO user_profile(user_id, nickname)
        VALUES(?, ?)
        ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname
        """, (str(user_id), nickname))
        con.commit()

def get_nickname(user_id: str):
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("SELECT nickname FROM user_profile WHERE user_id = ?", (str(user_id),))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

# ---------------- 会話履歴 ----------------
def add_channel_message(channel_id: str, author_id: str, content: str):
    content = (content or "").strip()
    if not content:
        return
    # Discordの制限などを考えて超長文はカット（保険）
    content = content[:4000]

    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("""
        INSERT INTO channel_messages(channel_id, author_id, content)
        VALUES (?, ?, ?)
        """, (str(channel_id), str(author_id), content))
        con.commit()

def get_recent_messages(channel_id: str, limit: int = 12):
    limit = max(1, min(int(limit or 12), 50))
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("""
        SELECT author_id, content
        FROM channel_messages
        WHERE channel_id = ?
        ORDER BY id DESC
        LIMIT ?
        """, (str(channel_id), limit))
        rows = cur.fetchall()

    # 新しい順で取ってるので、古い→新しいに並べ直す
    rows.reverse()
    return rows

# ---------------- 1日使用回数（今回の本命） ----------------
def get_daily_count(user_id: str, day: str) -> int:
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("""
        SELECT count
        FROM daily_usage
        WHERE user_id = ? AND day = ?
        """, (str(user_id), str(day)))
        row = cur.fetchone()
        return int(row[0]) if row else 0

def increment_daily_count(user_id: str, day: str) -> int:
    """
    カウントを +1 して、増加後の count を返す
    """
    with closing(_connect()) as con:
        cur = con.cursor()
        # 既存なら+1、なければ1で作る
        cur.execute("""
        INSERT INTO daily_usage(user_id, day, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
        """, (str(user_id), str(day)))
        con.commit()

        cur.execute("""
        SELECT count FROM daily_usage WHERE user_id = ? AND day = ?
        """, (str(user_id), str(day)))
        row = cur.fetchone()
        return int(row[0]) if row else 0

# ---------------- （将来戻す用）許可制 ----------------
def allow_user(user_id: str):
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO allowed_users(user_id) VALUES (?)", (str(user_id),))
        con.commit()

def deny_user(user_id: str):
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM allowed_users WHERE user_id = ?", (str(user_id),))
        con.commit()

def is_allowed(user_id: str) -> bool:
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM allowed_users WHERE user_id = ? LIMIT 1", (str(user_id),))
        return cur.fetchone() is not None
