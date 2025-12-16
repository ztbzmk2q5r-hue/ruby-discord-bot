import sqlite3
from datetime import date

DB_PATH = "ruby_memory.db"

def _conn():
    # Renderでも雑に安定するようにタイムアウト長め
    return sqlite3.connect(DB_PATH, timeout=30)

def init_db():
    conn = _conn()
    cur = conn.cursor()

    # 呼び名
    cur.execute("""
    CREATE TABLE IF NOT EXISTS nicknames (
        user_id TEXT PRIMARY KEY,
        nickname TEXT
    )
    """)

    # 1日カウント
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_counts (
        user_id TEXT NOT NULL,
        ymd TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, ymd)
    )
    """)

    # DMチャンネル内の履歴
    cur.execute("""
    CREATE TABLE IF NOT EXISTS channel_messages (
        channel_id TEXT NOT NULL,
        author_id TEXT NOT NULL,
        content TEXT NOT NULL,
        ts INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )
    """)

    # 感情ステート（ユーザー単位）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_emotion (
        user_id TEXT PRIMARY KEY,
        valence REAL NOT NULL DEFAULT 0.0,
        arousal REAL NOT NULL DEFAULT 0.0,
        tone REAL NOT NULL DEFAULT 0.0,
        tag TEXT NOT NULL DEFAULT 'neutral'
    )
    """)

    # ユーザー設定（汎用KV）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_kv (
        user_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (user_id, key)
    )
    """)

    conn.commit()
    conn.close()

# ---------- Nickname ----------
def set_nickname(user_id: str, nickname: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO nicknames(user_id, nickname) VALUES(?, ?)
    ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname
    """, (str(user_id), nickname))
    conn.commit()
    conn.close()

def get_nickname(user_id: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT nickname FROM nicknames WHERE user_id=?", (str(user_id),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

# ---------- Daily counts ----------
def get_daily_count(user_id: str, ymd: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT count FROM daily_counts WHERE user_id=? AND ymd=?", (str(user_id), ymd))
    row = cur.fetchone()
    conn.close()
    return int(row[0]) if row else 0

def increment_daily_count(user_id: str, ymd: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO daily_counts(user_id, ymd, count) VALUES(?, ?, 1)
    ON CONFLICT(user_id, ymd) DO UPDATE SET count = count + 1
    """, (str(user_id), ymd))
    conn.commit()
    conn.close()

# ---------- Channel messages ----------
def add_channel_message(channel_id: str, author_id: str, content: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO channel_messages(channel_id, author_id, content) VALUES(?, ?, ?)",
        (str(channel_id), str(author_id), str(content))
    )
    conn.commit()
    conn.close()

def get_recent_messages(channel_id: str, limit: int = 12):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT author_id, content
    FROM channel_messages
    WHERE channel_id=?
    ORDER BY ts DESC
    LIMIT ?
    """, (str(channel_id), int(limit)))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return [(r[0], r[1]) for r in rows]

# ---------- KV ----------
def _kv_get(user_id: str, key: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM user_kv WHERE user_id=? AND key=?", (str(user_id), str(key)))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def _kv_set(user_id: str, key: str, value: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO user_kv(user_id, key, value) VALUES(?, ?, ?)
    ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value
    """, (str(user_id), str(key), str(value)))
    conn.commit()
    conn.close()

def get_last_morning_greet_date(user_id: str):
    return _kv_get(user_id, "last_morning_greet_date")

def set_last_morning_greet_date(user_id: str, ymd: str):
    _kv_set(user_id, "last_morning_greet_date", ymd)

# ---------- Emotion ----------
def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))

def _tag_from_state(v, a, t):
    # 雑だけど「それっぽい」タグにする
    if t > 0.55 and v > 0.15:
        return "affectionate"
    if v > 0.35 and a > 0.1:
        return "excited"
    if v > 0.25:
        return "happy"
    if v < -0.35 and a > 0.1:
        return "upset"
    if v < -0.25:
        return "sad"
    if abs(v) < 0.15 and a < 0.15:
        return "calm"
    return "neutral"

def _load_emotion(user_id: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT valence, arousal, tone, tag FROM user_emotion WHERE user_id=?", (str(user_id),))
    row = cur.fetchone()
    if not row:
        # 初期
        conn.close()
        return 0.0, 0.0, 0.0, "neutral"
    conn.close()
    return float(row[0]), float(row[1]), float(row[2]), str(row[3])

def _save_emotion(user_id: str, v: float, a: float, t: float, tag: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO user_emotion(user_id, valence, arousal, tone, tag) VALUES(?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        valence=excluded.valence,
        arousal=excluded.arousal,
        tone=excluded.tone,
        tag=excluded.tag
    """, (str(user_id), float(v), float(a), float(t), str(tag)))
    conn.commit()
    conn.close()

def update_emotion_by_text(user_id: str, text: str, chichi: bool):
    """
    雑な感情推定で、ユーザーごとの感情ステートを更新して返す。
    return: (valence, arousal, tone, tag)
    """
    v, a, t, _ = _load_emotion(user_id)

    s = (text or "")
    s_lower = s.lower()

    # デフォルトはちょい減衰（落ち着いていく）
    v *= 0.92
    a *= 0.90
    t *= 0.94

    # ポジネガ
    pos = ["好き", "すき", "かわいい", "可愛い", "ありがとう", "ありがと", "最高", "嬉", "うれしい", "えらい", "天才", "神"]
    neg = ["つらい", "辛い", "しんどい", "むり", "無理", "最悪", "きらい", "嫌い", "うざ", "腹立", "むかつく", "泣"]
    excite = ["！", "!", "www", "笑", "やば", "すご", "最高"]
    calm = ["ふぅ", "落ち着", "まったり", "のんびり", "眠", "ねむ", "ねむい"]
    affection = ["ぎゅ", "ちゅ", "だいすき", "大好き", "会いたい", "寂", "さみしい", "すきすき"]

    if any(w in s for w in pos):
        v += 0.25
        a += 0.10
    if any(w in s for w in neg):
        v -= 0.28
        a += 0.15
    if any(w in s for w in calm):
        a -= 0.10
    if any(w in s for w in affection):
        t += 0.22
        v += 0.10

    if any(w in s for w in excite):
        a += 0.12

    # ちち補正：少しだけ甘さが上がりやすい
    if chichi:
        t += 0.06
        v += 0.03

    v = _clamp(v)
    a = _clamp(a)
    t = _clamp(t)

    tag = _tag_from_state(v, a, t)
    _save_emotion(user_id, v, a, t, tag)
    return v, a, t, tag