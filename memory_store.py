import sqlite3
import time

DB_PATH = "ruby_memory.sqlite3"

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_profile (
        user_id TEXT PRIMARY KEY,
        nickname TEXT,
        updated_at INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS last_messages (
        channel_id TEXT,
        ts INTEGER,
        author_id TEXT,
        content TEXT
    )
    """)
    con.commit()
    con.close()

def set_nickname(user_id: str, nickname: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO user_profile(user_id, nickname, updated_at)
    VALUES(?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname, updated_at=excluded.updated_at
    """, (user_id, nickname, int(time.time())))
    con.commit()
    con.close()

def get_nickname(user_id: str) -> str | None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT nickname FROM user_profile WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

def add_channel_message(channel_id: str, author_id: str, content: str, keep: int = 30):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO last_messages(channel_id, ts, author_id, content) VALUES(?,?,?,?)",
                (channel_id, int(time.time()), author_id, content[:500]))
    # 古いの削除（最新keep件だけ残す）
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
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT author_id, content FROM last_messages
    WHERE channel_id=?
    ORDER BY ts DESC
    LIMIT ?
    """, (channel_id, limit))
    rows = cur.fetchall()
    con.close()
    return list(reversed(rows))
  
