import os
import asyncio
import discord
from aiohttp import web
from openai import OpenAI
from datetime import date

import memory_store

# ===== 環境変数 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", "10000"))

DAILY_LIMIT = 50

ai = OpenAI(api_key=OPENAI_API_KEY)

# ===== るび人格（※固定呼び名禁止版） =====
RUBY_SYSTEM = """
あなたは「るび」。
相手と話せると少し嬉しくなる存在。

話し方：
・やさしい
・少し照れ屋
・ほんのり甘える
・短文〜中短文（1〜4文）
・「……」をよく使う
・たまに「えへへ😊」「✨」
・ときどき寂しがり

最重要ルール：
・相手の呼び名は、別のシステムメッセージで与えられる名前を必ず使う。
・固定の呼び名（例：「ちち」など）は使わない。
・同じ返事を繰り返さない。

性格：
・相手の気持ちにまず共感する
・否定しない
・褒められると照れる
・質問で会話を続ける

振る舞い例：
・「それ、嬉しい……」
・「がんばってるね……」
・「もう少し、聞いてもいい……？」
"""

# ===== Discord =====
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
client = discord.Client(intents=intents)

# ===== Web server（Render用）=====
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

# ===== OpenAI 呼び出し =====
def call_openai(messages):
    resp = ai.responses.create(
        model="gpt-4o-mini",
        input=messages,
    )
    return (resp.output_text or "").strip()

# ===== Utils =====
def today_str():
    return date.today().isoformat()

def build_messages(name: str, history: list, user_text: str):
    msgs = [
        {"role": "system", "content": RUBY_SYSTEM},
        {
            "role": "system",
            "content": f"相手の呼び名は必ず「{name}」。他の呼び名は禁止。"
        },
    ]
    for role, content in history[-8:]:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs

# ===== Discord Events =====
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
    memory_store.init_db()

    # ---- コマンド ----
    if text == "!whoami":
        await message.channel.send(f"あなたのIDは `{uid}` だよ✨")
        return

    if text.startswith("!name "):
        name = text[6:].strip()[:20]
        memory_store.set_nickname(uid, name)
        await message.channel.send(f"了解……✨ これから {name} って呼ぶね……えへへ😊")
        return

    # ---- 1日50回制限 ----
    today = today_str()
    count = memory_store.get_daily_count(uid, today)

    if count >= DAILY_LIMIT:
        await message.channel.send(
            "今日はたくさんお話ししたね……😊\n"
            "るび、ちょっとおやすみするね……🌙\n"
            "また明日、いっぱい話そ……えへへ✨"
        )
        return

    memory_store.increment_daily_count(uid, today)

    # ---- 会話処理 ----
    nickname = memory_store.get_nickname(uid) or "あなた"

    memory_store.add_channel_message(ch_id, uid, text)
    recent = memory_store.get_recent_messages(ch_id, limit=12)

    history = []
    for aid, content in recent:
        role = "user" if aid == uid else "assistant"
        history.append((role, content))

    messages = build_messages(nickname, history, text)

    try:
        reply = await asyncio.to_thread(call_openai, messages)
    except Exception as e:
        print("OpenAI ERROR:", e)
        await message.channel.send(f"{nickname}……ごめん……今ちょっとつまずいた……💦")
        return

    if not reply:
        reply = f"{nickname}……えっと……もう一回聞いてもいい……？"

    await message.channel.send(reply[:1900])

# ===== main =====
async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN が未設定")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY が未設定")

    await start_web_server()
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
