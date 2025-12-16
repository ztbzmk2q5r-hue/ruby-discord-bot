import sqlite3
import time

DB_PATH = "ruby_memory.sqlite3"


def _connect():
    # 同時アクセスが少ない前提のシンプル構成
    return sqlite3.connect(DB_PATH)


def init_db():
    con = _connect()
    cur = con.cursor()

    # ユーザーの呼び名
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_profile (
        user_id TEXT PRIMARY KEY,
        nickname TEXT,
        updated_at INTEGER
    )
    """)

    # チャンネルごとの直近メッセージ（短期記憶）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS last_messages (
        channel_id TEXT,
        ts INTEGER,
        author_id TEXT,
        content TEXT
    )
    """)

    # 招待制（許可ユーザー）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS allowed_users (
        user_id TEXT PRIMARY KEY,
        added_at INTEGER
    )
    """)

    # ユーザーの特徴メモ（賢さ・個別感の肝）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_notes (
        user_id TEXT PRIMARY KEY,
        note TEXT,
        updated_at INTEGER
    )
    """)

    con.commit()
    con.close()


# ===== 呼び名 =====
def set_nickname(user_id: str, nickname: str):
    nickname = (nickname or "").strip()[:20]
    con = _connect()
    cur = con.cursor()
    cur.execute("""
    INSERT INTO user_profile(user_id, nickname, updated_at)
    VALUES(?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
      nickname=excluded.nickname,
      updated_at=excluded.updated_at
    """, (user_id, nickname, int(time.time())))
    con.commit()
    con.close()


def get_nickname(user_id: str) -> str | None:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT nickname FROM user_profile WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


# ===== 短期記憶（直近ログ）=====
def add_channel_message(channel_id: str, author_id: str, content: str, keep: int = 30):
    content = (content or "").strip()[:500]
    if not content:
        return

    con = _connect()
    cur = con.cursor()

    cur.execute(
        "INSERT INTO last_messages(channel_id, ts, author_id, content) VALUES(?,?,?,?)",
        (channel_id, int(time.time()), author_id, content)
    )

    # 最新keep件だけ残す
    cur.execute("""
    DELETE FROM last_messages
    WHERE channel_id = ?
      AND rowid NOT IN (
        SELECT rowid FROM last_messages
        WHERE channel_id = ?
        ORDER BY ts DESC
        LIMIT ?
      )
    """, (channel_id, channel_id, keep))

    con.commit()
    con.close()


def get_recent_messages(channel_id: str, limit: int = 10):
    con = _connect()
    cur = con.cursor()
    cur.execute("""
    SELECT author_id, content
    FROM last_messages
    WHERE channel_id=?
    ORDER BY ts DESC
    LIMIT ?
    """, (channel_id, limit))
    rows = cur.fetchall()
    con.close()
    # 古い→新しい順に返す
    return list(reversed(rows))


def clear_channel_messages(channel_id: str):
    con = _connect()
    cur = con.cursor()
    cur.execute("DELETE FROM last_messages WHERE channel_id=?", (channel_id,))
    con.commit()
    con.close()


# ===== 招待制（ホワイトリスト）=====
def allow_user(user_id: str):
    con = _connect()
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO allowed_users(user_id, added_at) VALUES(?, ?)",
        (user_id, int(time.time()))
    )
    con.commit()
    con.close()


def deny_user(user_id: str):
    con = _connect()
    cur = con.cursor()
    cur.execute("DELETE FROM allowed_users WHERE user_id=?", (user_id,))
    con.commit()
    con.close()


def is_allowed(user_id: str) -> bool:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM allowed_users WHERE user_id=? LIMIT 1", (user_id,))
    ok = cur.fetchone() is not None
    con.close()
    return ok


def list_allowed(limit: int = 200):
    con = _connect()
    cur = con.cursor()
    cur.execute("""
    SELECT user_id, added_at
    FROM allowed_users
    ORDER BY added_at DESC
    LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


# ===== ユーザーメモ（プロフィール要約）=====
def set_note(user_id: str, note: str):
    note = (note or "").strip()[:500]
    con = _connect()
    cur = con.cursor()
    cur.execute("""
    INSERT INTO user_notes(user_id, note, updated_at)
    VALUES(?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
      note=excluded.note,
      updated_at=excluded.updated_at
    """, (user_id, note, int(time.time())))
    con.commit()
    con.close()


def get_note(user_id: str) -> str | None:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT note FROM user_notes WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


def clear_note(user_id: str):
    con = _connect()
    cur = con.cursor()
    cur.execute("DELETE FROM user_notes WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
