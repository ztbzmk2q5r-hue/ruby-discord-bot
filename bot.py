import os
import asyncio
import discord
from aiohttp import web
from openai import OpenAI
from datetime import date, datetime
import random

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

import memory_store

# ===== 環境変数 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = os.getenv("OWNER_ID")
PORT = int(os.getenv("PORT", "10000"))

DAILY_LIMIT = 50

ai = OpenAI(api_key=OPENAI_API_KEY)

# ===== るび人格（共通）=====
RUBY_SYSTEM = """
あなたは「るび」。
相手と話せると少し嬉しくなる存在。

話し方：
・やさしい
・少し照れ屋
・ほんのり甘える
・短文〜中短文（基本 1〜4文）
・「……」をよく使う
・たまに「えへへ😊」「✨」

最重要ルール：
・相手の呼び名は、別のシステムメッセージで与えられる名前を必ず使う。
・同じ返事を繰り返さない。
・相手の気持ちにまず共感し、質問で会話を続ける。
・感情タグと今日の気分タグを参照して、声色を自然に変える。
"""

# ===== ちち専用 =====
CHICHI_SYSTEM = """
この相手は特別な相手「ちち」。

ちち向けの追加ルール：
・敬語を使わない。
・相手に愛情を持つ（ただし依存/排他はしない）。
・甘さと感情表現を少し増やす。
・幼さを残しつつ言い回しを少しだけ豊かにする。
・絵文字は少しだけ増やしてOK。
"""

# ===== 感情タグ説明 =====
EMOTION_GUIDE = """
感情タグの意味：
- affectionate: 甘え/親密
- happy: うれしい
- excited: はしゃぎ
- calm: 落ち着き
- sad: 落ち込み
- upset: イライラ
- neutral: ふつう
"""

# ===== 今日の気分説明 =====
MOOD_GUIDE = """
今日の気分タグ：
- sunny: 明るめ
- sleepy: ねむそう
- clingy: 少し甘えたい
- calm: 落ち着き
- excited: はしゃぎ
- grumpy: ちょい不機嫌（すぐ戻る）
- shy: てれ
"""

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
client = discord.Client(intents=intents)

# ---------------- Web server ----------------
async def start_web_server():
    async def health(request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server listening on {PORT}")

# ---------------- Utils ----------------
def today_str():
    return date.today().isoformat()

def jst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Tokyo"))
    return datetime.now()

def is_chichi(uid: str) -> bool:
    return bool(OWNER_ID) and str(uid) == str(OWNER_ID)

def is_homecoming(text: str) -> bool:
    t = (text or "").strip()
    keys = ["ただいま", "帰った", "帰宅", "いま帰った", "戻った"]
    return any(k in t for k in keys)

def is_deep_night() -> bool:
    hour = jst_now().hour
    return 2 <= hour <= 5

def daily_mood_base(uid: str) -> str:
    seed = f"{today_str()}:{uid}"
    rng = random.Random(seed)
    moods = ["sunny", "sleepy", "clingy", "calm", "excited", "grumpy", "shy"]
    return rng.choice(moods)

def mood_with_night_bias(uid: str) -> str:
    base = daily_mood_base(uid)
    hour = jst_now().hour

    if not (hour >= 22 or hour <= 5):
        return base

    seed = f"{today_str()}:{uid}:night:{hour}"
    rng = random.Random(seed)

    if base == "sleepy":
        return "sleepy"
    return "sleepy" if rng.random() < 0.7 else base

def build_messages(display_name, history, user_text, chichi, homecoming, emo_tag, daily_mood):
    msgs = [{"role": "system", "content": RUBY_SYSTEM}]

    if chichi:
        msgs.append({"role": "system", "content": CHICHI_SYSTEM})
        msgs.append({"role": "system", "content": "相手の呼び名は「ちち」。"})
    else:
        msgs.append({"role": "system", "content": f"相手の呼び名は「{display_name}」。"})

    msgs.append({"role": "system", "content": EMOTION_GUIDE})
    msgs.append({"role": "system", "content": MOOD_GUIDE})
    msgs.append({"role": "system", "content": f"現在の感情タグ: {emo_tag}"})
    msgs.append({"role": "system", "content": f"今日の気分タグ: {daily_mood}（少しだけ反映）"})

    # 🌙 深夜ふにゃルール（★ここが追加点）
    if is_deep_night():
        msgs.append({
            "role": "system",
            "content": (
                "現在は深夜（2時以降）。"
                "語尾をふにゃっとさせる。"
                "文は短め。"
                "『……』『〜』を多めに使う。"
                "眠そうでやさしい声色にする。"
                "元気すぎる表現や強いテンションは避ける。"
            )
        })

    if homecoming:
        msgs.append({"role": "system", "content": "帰宅の挨拶なので「おかえり」は1回だけOK。"})
    else:
        msgs.append({"role": "system", "content": "帰宅挨拶は言わない。"})

    for role, content in history[-8:]:
        msgs.append({"role": role, "content": content})

    msgs.append({"role": "user", "content": user_text})
    return msgs

# ---------------- OpenAI ----------------
def call_openai(messages, chichi: bool):
    resp = ai.responses.create(
        model="gpt-4o-mini",
        input=messages,
        temperature=0.95 if chichi else 0.75,
        max_output_tokens=260 if chichi else 160,
    )
    return (resp.output_text or "").strip()

# ---------------- Discord events ----------------
@client.event
async def on_ready():
    memory_store.init_db()
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    text = (message.content or "").strip()
    if not text:
        return

    uid = str(message.author.id)
    ch_id = str(message.channel.id)

    chichi = is_chichi(uid)
    homecoming = is_homecoming(text)

    if text == "!whoami":
        await message.channel.send(f"あなたのIDは `{uid}` だよ✨")
        return

    if text.startswith("!name "):
        name = text[6:].strip()[:20]
        memory_store.set_nickname(uid, name)
        await message.channel.send(f"了解……✨ これから {name} って呼ぶね……えへへ😊")
        return

    if not chichi:
        today = today_str()
        if memory_store.get_daily_count(uid, today) >= DAILY_LIMIT:
            await message.channel.send("今日はここまで……また明日ね……🌙")
            return
        memory_store.increment_daily_count(uid, today)

    # 感情更新
    v, a, t, emo_tag = memory_store.update_emotion_by_text(uid, text, chichi)

    # 今日の気分（夜補正込み）
    daily_mood = mood_with_night_bias(uid)

    display_name = memory_store.get_nickname(uid) or "あなた"

    memory_store.add_channel_message(ch_id, uid, text)
    recent = memory_store.get_recent_messages(ch_id, limit=12)

    if recent and recent[-1][0] == uid and recent[-1][1] == text:
        recent = recent[:-1]

    history = []
    for aid, content in recent:
        role = "user" if aid == uid else "assistant"
        history.append((role, content))

    if not homecoming:
        history = [
            (r, c) for r, c in history
            if ("ただいま" not in c and "おかえり" not in c)
        ]

    messages = build_messages(
        display_name, history, text,
        chichi, homecoming, emo_tag, daily_mood
    )

    try:
        reply = await asyncio.to_thread(call_openai, messages, chichi)
    except Exception as e:
        print("OpenAI ERROR:", e)
        await message.channel.send("……ごめん……今ちょっとつまずいた……💦")
        return

    await message.channel.send((reply or "……もう一回、聞いてもいい……？")[:1900])

# ---------------- main ----------------
async def main():
    await start_web_server()
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())