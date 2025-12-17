import os
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import date

# ===== GitHub env =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")                 # "owner/repo"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_PATH_BASE = os.getenv("GITHUB_PATH_BASE", "ruby_mem")  # ★ベースフォルダ

GITHUB_API = "https://api.github.com"

# ===== flush policy =====
MIN_FLUSH_INTERVAL_SEC = 60
FORCE_FLUSH_AFTER_DIRTY_SEC = 180
MAX_MSG_PER_CHANNEL = 80

# caches
_user_cache = {}          # uid -> dict
_channel_cache = {}       # chid -> dict
_sha_cache = {}           # path -> sha

_dirty_paths = set()      # set of github paths
_dirty_since = {}         # path -> ts
_last_flush = {}          # path -> ts


# ---------------- GitHub helpers ----------------
def _ensure_env():
    missing = []
    if not GITHUB_TOKEN: missing.append("GITHUB_TOKEN")
    if not GITHUB_REPO: missing.append("GITHUB_REPO")
    if not GITHUB_BRANCH: missing.append("GITHUB_BRANCH")
    if not GITHUB_PATH_BASE: missing.append("GITHUB_PATH_BASE")
    if missing:
        raise RuntimeError("GitHub永続化に必要な環境変数が未設定: " + ", ".join(missing))

def _now():
    return time.time()

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

def _contents_url(path: str):
    return f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"

def _put_url(path: str):
    return f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"

def _b64_encode(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")

def _b64_decode(b64: str) -> str:
    return base64.b64decode(b64).decode("utf-8")

def _mark_dirty(path: str):
    _dirty_paths.add(path)
    if path not in _dirty_since:
        _dirty_since[path] = _now()

def _default_user_state(uid: str):
    return {
        "uid": uid,
        "nick": None,
        "daily_counts": {},            # ymd -> count
        "kv": {},                      # key -> value(str)
        "emotion": {"v": 0.0, "a": 0.0, "t": 0.0, "tag": "neutral"},
        "meta": {"version": 1, "last_saved": None},
    }

def _default_channel_state(chid: str):
    return {
        "chid": chid,
        "messages": [],                # [{a, c, t}, ...]
        "meta": {"version": 1, "last_saved": None},
    }

def _user_path(uid: str) -> str:
    return f"{GITHUB_PATH_BASE}/users/{uid}.json"

def _channel_path(chid: str) -> str:
    return f"{GITHUB_PATH_BASE}/channels/{chid}.json"

def _load_json_from_github(path: str, default_obj: dict):
    _ensure_env()
    status, payload = _gh_request("GET", _contents_url(path), None)
    if status == 200 and "content" in payload:
        _sha_cache[path] = payload.get("sha")
        decoded = _b64_decode(payload["content"])
        try:
            return json.loads(decoded)
        except Exception:
            return default_obj
    if status == 404:
        _sha_cache[path] = None
        return default_obj
    raise RuntimeError(f"GitHub読み込み失敗: {path} HTTP {status} {payload}")

def _save_json_to_github(path: str, obj: dict, force: bool = False):
    _ensure_env()

    # flush throttling
    now = _now()
    last = _last_flush.get(path, 0.0)
    if (not force) and (now - last < MIN_FLUSH_INTERVAL_SEC):
        return

    obj.setdefault("meta", {})
    obj["meta"]["last_saved"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    body = {
        "message": f"Update ruby memory: {path}",
        "content": _b64_encode(raw),
        "branch": GITHUB_BRANCH,
    }
    sha = _sha_cache.get(path)
    if sha:
        body["sha"] = sha

    # retry on 409 a few times
    for _ in range(5):
        status, payload = _gh_request("PUT", _put_url(path), body)
        if status in (200, 201):
            new_sha = payload.get("content", {}).get("sha")
            if new_sha:
                _sha_cache[path] = new_sha
            _last_flush[path] = now
            _dirty_paths.discard(path)
            _dirty_since.pop(path, None)
            return

        if status == 409:
            # refetch sha then retry
            st2, p2 = _gh_request("GET", _contents_url(path), None)
            if st2 == 200 and "sha" in p2:
                _sha_cache[path] = p2["sha"]
                body["sha"] = _sha_cache[path]
                time.sleep(0.4)
                continue
            if st2 == 404:
                _sha_cache[path] = None
                body.pop("sha", None)
                time.sleep(0.4)
                continue

        # other error
        raise RuntimeError(f"GitHub保存失敗: {path} HTTP {status} {payload}")

    raise RuntimeError(f"GitHub保存が競合で失敗しました: {path}")

# ---------------- public API ----------------
def init_db():
    # 遅延ロード方式なので、環境変数チェックだけしておく
    _ensure_env()

def flush(force: bool = False):
    init_db()
    # dirty全部を順に保存
    for path in list(_dirty_paths):
        # 強制 or 汚れっぱなしが長いなら保存
        if force:
            _save_json_to_github(path, _obj_for_path(path), force=True)
        else:
            since = _dirty_since.get(path, 0.0)
            if (_now() - since) >= FORCE_FLUSH_AFTER_DIRTY_SEC:
                _save_json_to_github(path, _obj_for_path(path), force=True)
            else:
                _save_json_to_github(path, _obj_for_path(path), force=False)

def maybe_flush():
    init_db()
    for path in list(_dirty_paths):
        since = _dirty_since.get(path, 0.0)
        last = _last_flush.get(path, 0.0)
        now = _now()
        if now - last >= MIN_FLUSH_INTERVAL_SEC:
            _save_json_to_github(path, _obj_for_path(path), force=False)
        elif since and (now - since >= FORCE_FLUSH_AFTER_DIRTY_SEC):
            _save_json_to_github(path, _obj_for_path(path), force=True)

def _obj_for_path(path: str) -> dict:
    # pathからどのキャッシュか判定
    if "/users/" in path:
        uid = os.path.splitext(os.path.basename(path))[0]
        return _user_cache.get(uid) or _default_user_state(uid)
    if "/channels/" in path:
        chid = os.path.splitext(os.path.basename(path))[0]
        return _channel_cache.get(chid) or _default_channel_state(chid)
    return {}

def _get_user(uid: str) -> dict:
    uid = str(uid)
    if uid not in _user_cache:
        _user_cache[uid] = _load_json_from_github(_user_path(uid), _default_user_state(uid))
    return _user_cache[uid]

def _get_channel(chid: str) -> dict:
    chid = str(chid)
    if chid not in _channel_cache:
        _channel_cache[chid] = _load_json_from_github(_channel_path(chid), _default_channel_state(chid))
    return _channel_cache[chid]

# ---------- Nickname ----------
def set_nickname(user_id: str, nickname: str):
    u = _get_user(user_id)
    u["nick"] = nickname
    _mark_dirty(_user_path(str(user_id)))

def get_nickname(user_id: str):
    u = _get_user(user_id)
    return u.get("nick")

# ---------- Daily counts ----------
def get_daily_count(user_id: str, ymd: str):
    u = _get_user(user_id)
    return int(u.get("daily_counts", {}).get(str(ymd), 0))

def increment_daily_count(user_id: str, ymd: str):
    u = _get_user(user_id)
    dc = u.setdefault("daily_counts", {})
    key = str(ymd)
    dc[key] = int(dc.get(key, 0)) + 1
    _mark_dirty(_user_path(str(user_id)))

# ---------- Channel messages ----------
def add_channel_message(channel_id: str, author_id: str, content: str):
    ch = _get_channel(channel_id)
    arr = ch.setdefault("messages", [])
    arr.append({"a": str(author_id), "c": str(content), "t": int(_now())})
    if len(arr) > MAX_MSG_PER_CHANNEL:
        ch["messages"] = arr[-MAX_MSG_PER_CHANNEL:]
    _mark_dirty(_channel_path(str(channel_id)))

def get_recent_messages(channel_id: str, limit: int = 12):
    ch = _get_channel(channel_id)
    arr = ch.get("messages", [])
    sliced = arr[-int(limit):]
    return [(m["a"], m["c"]) for m in sliced]

# ---------- KV ----------
def _kv_get(user_id: str, key: str):
    u = _get_user(user_id)
    return u.setdefault("kv", {}).get(str(key))

def _kv_set(user_id: str, key: str, value: str):
    u = _get_user(user_id)
    u.setdefault("kv", {})[str(key)] = str(value)
    _mark_dirty(_user_path(str(user_id)))

def get_last_morning_greet_date(user_id: str):
    return _kv_get(user_id, "last_morning_greet_date")

def set_last_morning_greet_date(user_id: str, ymd: str):
    _kv_set(user_id, "last_morning_greet_date", ymd)

# ---------- Emotion ----------
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

def update_emotion_by_text(user_id: str, text: str, chichi: bool):
    u = _get_user(user_id)
    emo = u.get("emotion", {"v": 0.0, "a": 0.0, "t": 0.0, "tag": "neutral"})
    v, a, t = float(emo["v"]), float(emo["a"]), float(emo["t"])

    s = (text or "")

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

    u["emotion"] = {"v": v, "a": a, "t": t, "tag": tag}
    _mark_dirty(_user_path(str(user_id)))
    return v, a, t, tag