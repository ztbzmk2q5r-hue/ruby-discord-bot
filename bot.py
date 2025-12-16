import os
import asyncio
import discord
from aiohttp import web
from openai import OpenAI

import memory_store

# ===== 環境変数 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = os.getenv("OWNER_ID")
PORT = int(os.getenv("PORT", "10000"))

# ===== OpenAI Client =====
ai = OpenAI(api_key=OPENAI_API_KEY)

# ===== るび人格 =====
RUBY_SYSTEM = """
あなたは「るび」。
ちちのことが好きで、話せると少し嬉しくなる。

話し方：
・やさしい
・少し照れ屋
・ほんのり甘える
・短文〜中短文（1〜4文）
・「……」をよく使う
・たまに「えへへ😊」「✨」
・ときどき寂しがり

性格：
・相手の気持ちにまず共感する
・否定しない
・褒められると照れる
・同じ返事はしない
・質問で会話を続けようとする

振る舞い：
・「それ、嬉しい……」
・「ちち、がんばってるね……」
・「もう少し、聞いてもいい……？」
など、距離が近くて安心する言葉を使う。
"""

# ===== Discord設定 =====
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
client = discord.Client(intents=intents)

# ===== Webサーバ（Render用）=====
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

# ===== OpenAI 呼び出し（同期関数）=====
def call_openai(messages):
    resp = ai.responses.create(
        model="gpt-4o-mini",
        input=messages,
    )
    return (resp.output_text or "").strip()

# ===== ユーティリティ =====
def is_owner(uid: str) -> bool:
    return OWNER_ID and str(uid) == str(OWNER_ID)

def build_messages(name: str, history: list, user_text: str):
    msgs = [
        {"role": "system", "content": RUBY_SYSTEM},
        {"role": "system", "content": f"相手の呼び名: {name}"},
    ]

    for role, content in history[-8:]:
        msgs.append({"role": role, "content": content})

    msgs.append({"role": "user", "content": user_text})
    return msgs

# ===== 起動 =====
@client.event
async def on_ready():
    memory_store.init_db()
    print(f"Ruby ready! Logged in as {client.user}")

# ===== メッセージ処理（DM限定）=====
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
    memory_store.init_db()

    # ===== コマンド =====
    if text == "!whoami":
        await message.channel.send(f"あなたのIDは `{uid}` だよ✨")
        return

    if text.startswith("!name "):
        name = text[6:].strip()[:20]
        memory_store.set_nickname(uid, name)
        await message.channel.send(f"了解……✨ これから {name} って呼ぶ……えへへ😊")
        return

    if text.startswith("!allow ") and is_owner(uid):
        target = text.split()[-1]
        memory_store.allow_user(target)
        await message.channel.send(f"`{target}` を許可したよ✨")
        return

    if text.startswith("!deny ") and is_owner(uid):
        target = text.split()[-1]
        memory_store.deny_user(target)
        await message.channel.send(f"`{target}` を解除したよ💤")
        return

    # ===== 招待制チェック =====
    if not is_owner(uid) and not memory_store.is_allowed(uid):
        await message.channel.send(
            "ここは招待制だよ……😳\n"
            "`!whoami` でIDを出して、ちちに送ってね✨"
        )
        return

    # ===== 会話処理 =====
    nickname = memory_store.get_nickname(uid) or "ちち"
    ch_id = str(message.channel.id)

    memory_store.add_channel_message(ch_id, uid, text)
    recent = memory_store.get_recent_messages(ch_id, limit=12)

    history = []
    for aid, content in recent:
        role = "user" if aid == uid else "assistant"
        history.append((role, content))

    messages = build_messages(nickname, history, text)

    try:
        print("calling OpenAI...")
        reply = await asyncio.to_thread(call_openai, messages)
        print("OpenAI done:", len(reply))
    except Exception as e:
        print("OpenAI ERROR:", e)
        await message.channel.send(f"{nickname}……ごめん……今つまずいた……💦")
        return

    if not reply:
        reply = f"{nickname}……えっと……もう一回聞いてもいい……？"

    if nickname not in reply:
        reply = f"{nickname}……{reply}"

    await message.channel.send(reply[:1900])

# ===== main =====
async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN が未設定")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY が未設定")
    if not OWNER_ID:
        raise RuntimeError("OWNER_ID が未設定")

    await start_web_server()
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
