import sqlite3
from typing import Optional, List, Tuple

DB_PATH = "memory.db"

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # DM履歴（既存互換）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        channel_id TEXT,
        author_id  TEXT,
        content    TEXT,
        ts         DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ニックネーム
    cur.execute("""
    CREATE TABLE IF NOT EXISTS nicknames (
        user_id TEXT PRIMARY KEY,
        nickname TEXT
    )
    """)

    # 1日回数カウント
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_counts (
        user_id TEXT,
        day TEXT,
        count INTEGER,
        PRIMARY KEY (user_id, day)
    )
    """)

    # ★感情ステート（ユーザーごと）
    # valence: -100..100（ネガ↔ポジ）
    # arousal:  0..100（落ち着き↔高揚）
    # trust:    0..100（距離の近さ）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS emotion_state (
        user_id TEXT PRIMARY KEY,
        valence INTEGER DEFAULT 0,
        arousal INTEGER DEFAULT 20,
        trust   INTEGER DEFAULT 20,
        last_tag TEXT DEFAULT 'neutral'
    )
    """)

    con.commit()
    con.close()

# ---------- messages ----------
def add_channel_message(channel_id: str, author_id: str, content: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages (channel_id, author_id, content) VALUES (?, ?, ?)",
        (channel_id, author_id, content)
    )
    con.commit()
    con.close()

def get_recent_messages(channel_id: str, limit: int = 12) -> List[Tuple[str, str]]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT author_id, content FROM messages WHERE channel_id=? ORDER BY ts ASC, rowid ASC LIMIT ?",
        (channel_id, limit)
    )
    rows = cur.fetchall()
    con.close()
    return [(r[0], r[1]) for r in rows]

# ---------- nickname ----------
def set_nickname(user_id: str, nickname: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO nicknames (user_id, nickname) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname",
        (user_id, nickname)
    )
    con.commit()
    con.close()

def get_nickname(user_id: str) -> Optional[str]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT nickname FROM nicknames WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

# ---------- daily counts ----------
def get_daily_count(user_id: str, day: str) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT count FROM daily_counts WHERE user_id=? AND day=?", (user_id, day))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def increment_daily_count(user_id: str, day: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO daily_counts (user_id, day, count) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1",
        (user_id, day)
    )
    con.commit()
    con.close()

# ---------- emotion state ----------
def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))

def ensure_emotion(user_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO emotion_state (user_id) VALUES (?)", (user_id,))
    con.commit()
    con.close()

def get_emotion(user_id: str):
    ensure_emotion(user_id)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT valence, arousal, trust, last_tag FROM emotion_state WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return (0, 20, 20, "neutral")
    return (int(row[0]), int(row[1]), int(row[2]), row[3])

def set_emotion(user_id: str, valence: int, arousal: int, trust: int, last_tag: str):
    ensure_emotion(user_id)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        UPDATE emotion_state
        SET valence=?, arousal=?, trust=?, last_tag=?
        WHERE user_id=?
    """, (int(valence), int(arousal), int(trust), str(last_tag), user_id))
    con.commit()
    con.close()

def update_emotion_by_text(user_id: str, text: str, chichi: bool = False):
    """
    ざっくりルールベースで感情を動かす。
    ※モデルに解析させるより安全＆安定（コスト0）
    """
    v, a, t, last = get_emotion(user_id)
    s = (text or "").strip()

    # ベース減衰：時間は見てないので “発言ごと” に少し落ち着く
    a = _clamp(a - 2, 0, 100)

    # ポジ/ネガ
    pos = ["ありがとう", "好き", "大好き", "嬉しい", "楽しい", "最高", "助かった", "えへへ", "✨", "😊", "かわいい", "すごい"]
    neg = ["つらい", "しんどい", "悲しい", "寂しい", "むり", "無理", "最悪", "泣", "もうだめ", "疲れた", "怒", "ムカつく"]

    if any(k in s for k in pos):
        v += 10
        a += 6
        t += 3
    if any(k in s for k in neg):
        v -= 12
        a += 8
        t -= 2

    # 距離感（信頼）
    close = ["会いたい", "ぎゅ", "だいすき", "愛して", "甘えたい", "恋", "一緒"]
    if any(k in s for k in close):
        t += 6
        a += 4
        v += 4

    # 疑問多め→会話モードで少しarousal上げる
    if "?" in s or "？" in s:
        a += 2

    # ちちは少しだけ上振れ（特別扱い）
    if chichi:
        t += 1

    v = _clamp(v, -100, 100)
    a = _clamp(a, 0, 100)
    t = _clamp(t, 0, 100)

    tag = emotion_tag(v, a, t)
    set_emotion(user_id, v, a, t, tag)
    return (v, a, t, tag)

def emotion_tag(valence: int, arousal: int, trust: int) -> str:
    """
    数値→タグ
    """
    if valence <= -30 and arousal >= 55:
        return "upset"      # 怒り/イライラ
    if valence <= -25 and arousal < 55:
        return "sad"        # 落ち込み
    if valence >= 35 and arousal >= 55:
        return "excited"    # はしゃぎ
    if valence >= 30 and arousal < 55:
        return "happy"      # うれしい
    if trust >= 70 and valence >= 10:
        return "affectionate"  # 甘え/親密
    if arousal <= 20:
        return "calm"       # 落ち着き
    return "neutral"