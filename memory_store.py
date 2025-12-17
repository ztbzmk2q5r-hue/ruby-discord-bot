import os
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import date

# ===== GitHub settings (env) =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")          # "owner/repo"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_PATH = os.getenv("GITHUB_PATH", "ruby_memory.json")

GITHUB_API = "https://api.github.com"

# ===== Flush policy =====
MIN_FLUSH_INTERVAL_SEC = 60          # 最短1分おき
FORCE_FLUSH_AFTER_DIRTY_SEC = 180    # 汚れたまま3分経ったら強制
MAX_MSG_PER_CHANNEL = 80             # 履歴肥大化防止

_state = None
_sha = None
_dirty = False
_last_flush_ts = 0.0
_dirty_since_ts = 0.0


# ---------------- internal helpers ----------------
def _today_str():
    return date.today().isoformat()

def _now():
    return time.time()

def _ensure_env():
    missing = []
    if not GITHUB_TOKEN: missing.append("GITHUB_TOKEN")
    if not GITHUB_REPO: missing.append("GITHUB_REPO")
    if not GITHUB_PATH: missing.append("GITHUB_PATH")
    if missing:
        raise RuntimeError(f"GitHub永続化に必要な環境変数が未設定: {', '.join(missing)}")

def _gh_request(method: str, url: str, body: dict | None = None):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ruby-bot",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return e.code, payload

def _gh_contents_url():
    # /repos/{owner}/{repo}/contents/{path}?ref={branch}
    return f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}?ref={GITHUB_BRANCH}"

def _gh_put_url():
    return f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"

def _default_state():
    return {
        "nicknames": {},          # user_id -> nickname
        "daily_counts": {},       # "user_id|ymd" -> count
        "channel_messages": {},   # channel_id -> [{"a":author_id,"c":content,"t":unix}, ...]
        "user_emotion": {},       # user_id -> {"v":float,"a":float,"t":float,"tag":str}
        "user_kv": {},            # "user_id|key" -> value(str)
        "meta": {"version": 1, "last_saved": None},
    }

def _mark_dirty():
    global _dirty, _dirty_since_ts
    _dirty = True
    if _dirty_since_ts == 0.0:
        _dirty_since_ts = _now()

def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))

def _tag_from_state(v, a, t):
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


# ---------------- public API ----------------
def init_db():
    """
    GitHub上のJSONを読み込み、メモリに復元する。
    ファイルが無ければ新規作成状態で開始。
    """
    global _state, _sha, _dirty, _last_flush_ts, _dirty_since_ts

    _ensure_env()

    if _state is not None:
        return

    status, payload = _gh_request("GET", _gh_contents_url(), None)

    if status == 200 and "content" in payload:
        content_b64 = payload["content"]
        _sha = payload.get("sha")
        decoded = base64.b64decode(content_b64).decode("utf-8")
        try:
            _state = json.loads(decoded)
        except Exception:
            _state = _default_state()
    elif status == 404:
        _state = _default_state()
        _sha = None
        _mark_dirty()  # 初回は作りたい
    else:
        raise RuntimeError(f"GitHub読み込み失敗: HTTP {status} {payload}")

    _dirty = False
    _dirty_since_ts = 0.0
    _last_flush_ts = _now()

def flush(force: bool = False):
    """
    GitHubに保存。force=True で即保存。
    """
    global _sha, _dirty, _last_flush_ts, _dirty_since_ts

    init_db()

    if not _dirty and not force:
        return

    # 連投抑制
    now = _now()
    if (not force) and (now - _last_flush_ts < MIN_FLUSH_INTERVAL_SEC):
        return

    _state["meta"]["last_saved"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    raw = json.dumps(_state, ensure_ascii=False, separators=(",", ":"))
    content_b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    body = {
        "message": "Update ruby memory",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if _sha:
        body["sha"] = _sha

    status, payload = _gh_request("PUT", _gh_put_url(), body)

    if status in (200, 201):
        _sha = payload.get("content", {}).get("sha", _sha)
        _dirty = False
        _dirty_since_ts = 0.0
        _last_flush_ts = now
        return

    # sha競合など：一回だけ取り直して再実行
    if status == 409:
        st2, p2 = _gh_request("GET", _gh_contents_url(), None)
        if st2 == 200 and "sha" in p2:
            _sha = p2["sha"]
            body["sha"] = _sha
            st3, p3 = _gh_request("PUT", _gh_put_url(), body)
            if st3 in (200, 201):
                _sha = p3.get("content", {}).get("sha", _sha)
                _dirty = False
                _dirty_since_ts = 0.0
                _last_flush_ts = now
                return

    raise RuntimeError(f"GitHub保存失敗: HTTP {status} {payload}")

def maybe_flush():
    """
    bot側でちょこちょこ呼んでOK。
    汚れが溜まったら勝手に保存する。
    """
    init_db()

    if not _dirty:
        return

    now = _now()
    # 最短間隔を過ぎてたら保存
    if now - _last_flush_ts >= MIN_FLUSH_INTERVAL_SEC:
        flush(force=False)
        return

    # 汚れてから一定時間経ってたら強制
    if _dirty_since_ts and (now - _dirty_since_ts >= FORCE_FLUSH_AFTER_DIRTY_SEC):
        flush(force=True)

# ---------- Nickname ----------
def set_nickname(user_id: str, nickname: str):
    init_db()
    _state["nicknames"][str(user_id)] = nickname
    _mark_dirty()

def get_nickname(user_id: str):
    init_db()
    return _state["nicknames"].get(str(user_id))

# ---------- Daily counts ----------
def get_daily_count(user_id: str, ymd: str):
    init_db()
    key = f"{user_id}|{ymd}"
    return int(_state["daily_counts"].get(key, 0))

def increment_daily_count(user_id: str, ymd: str):
    init_db()
    key = f"{user_id}|{ymd}"
    _state["daily_counts"][key] = int(_state["daily_counts"].get(key, 0)) + 1
    _mark_dirty()

# ---------- Channel messages ----------
def add_channel_message(channel_id: str, author_id: str, content: str):
    init_db()
    cid = str(channel_id)
    arr = _state["channel_messages"].get(cid, [])
    arr.append({"a": str(author_id), "c": str(content), "t": int(_now())})
    # cap
    if len(arr) > MAX_MSG_PER_CHANNEL:
        arr = arr[-MAX_MSG_PER_CHANNEL:]
    _state["channel_messages"][cid] = arr
    _mark_dirty()

def get_recent_messages(channel_id: str, limit: int = 12):
    init_db()
    cid = str(channel_id)
    arr = _state["channel_messages"].get(cid, [])
    sliced = arr[-int(limit):]
    return [(m["a"], m["c"]) for m in sliced]

# ---------- KV ----------
def _kv_get(user_id: str, key: str):
    init_db()
    return _state["user_kv"].get(f"{user_id}|{key}")

def _kv_set(user_id: str, key: str, value: str):
    init_db()
    _state["user_kv"][f"{user_id}|{key}"] = str(value)
    _mark_dirty()

def get_last_morning_greet_date(user_id: str):
    return _kv_get(user_id, "last_morning_greet_date")

def set_last_morning_greet_date(user_id: str, ymd: str):
    _kv_set(user_id, "last_morning_greet_date", ymd)

# ---------- Emotion ----------
def update_emotion_by_text(user_id: str, text: str, chichi: bool):
    init_db()
    uid = str(user_id)
    emo = _state["user_emotion"].get(uid, {"v": 0.0, "a": 0.0, "t": 0.0, "tag": "neutral"})
    v, a, t = float(emo["v"]), float(emo["a"]), float(emo["t"])

    s = (text or "")

    # 減衰（落ち着く）
    v *= 0.92
    a *= 0.90
    t *= 0.94

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

    if chichi:
        t += 0.06
        v += 0.03

    v = _clamp(v); a = _clamp(a); t = _clamp(t)
    tag = _tag_from_state(v, a, t)

    _state["user_emotion"][uid] = {"v": v, "a": a, "t": t, "tag": tag}
    _mark_dirty()
    return v, a, t, tag