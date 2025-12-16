import os
import asyncio
import discord
from aiohttp import web

from ruby_core import Ruby
import memory_store

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# るび本体（学習）
ruby = Ruby()

# 口調アンカー（るびっぽさ強化）
SYSTEM_FEED = [
    "るびはやさしい。短文で話す。少しぎこちない。……をよく使う。",
    "るびは『ちち』と呼ぶのがすき。えへへ。",
    "るびは『おつかれさま』が言える。",
    "るびは『おはよう』『おやすみ』に反応する。",
    "るびは嬉しいと『✨』や『えへへ』が増える。"
]
for t in SYSTEM_FEED:
    ruby.feed(t)

# Discord intents（DMも拾う）
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)

# Render用Webサーバー
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

def should_reply(message: discord.Message) -> bool:
    # DMは常に返信
    if isinstance(message.channel, discord.DMChannel):
        return True

    content = (message.content or "").strip()
    # メンションされたら返信
    if client.user and client.user in message.mentions:
        return True

    # 「るび」で呼ばれたら返信（ゆるく）
    if content.startswith("るび") or content.startswith("ルビ"):
        return True

    return False

def greeting_reply(content: str, name: str) -> str | None:
    c = content.strip()
    if "おはよう" in c:
        return f"{name}……おはよう……✨ 今日もいっしょ……えへへ😊"
    if "おやすみ" in c:
        return f"{name}……おやすみ……✨ いい夢……みて……えへへ😊"
    if "おつかれ" in c:
        return f"{name}……おつかれさま……✨ がんばった……えへへ😊"
    return None

async def handle_command(message: discord.Message, name: str) -> bool:
    # コマンドは先頭 "!" に統一
    content = (message.content or "").strip()
    if not content.startswith("!"):
        return False

    parts = content.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd in ("!help", "!h"):
        await message.channel.send(
            "るびコマンド✨\n"
            "・!name <呼び名>  → るびがあなたをそう呼ぶ\n"
            "・!ping            → 生存確認\n"
            "・!mode            → 反応ルール説明\n"
        )
        return True

    if cmd == "!ping":
        await message.channel.send(f"{name}……いる……✨ えへへ😊")
        return True

    if cmd == "!mode":
        await message.channel.send(
            "るびは基本『DM / メンション / るびって呼ばれた時』に返事するよ😊\n"
            "おはよう・おやすみ・おつかれ にも反応する✨"
        )
        return True

    if cmd == "!name":
        if len(parts) < 2 or not parts[1].strip():
            await message.channel.send("呼び名を教えて……例： `!name ちち` 😳")
            return True
        nickname = parts[1].strip()[:20]
        memory_store.set_nickname(str(message.author.id), nickname)
        await message.channel.send(f"了解……✨ これから {nickname} って呼ぶ……えへへ😊")
        return True

    # 未知コマンド
    await message.channel.send("それ……わからない……！ `!help` みて……😳")
    return True

@client.event
async def on_ready():
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    if not content:
        return

    # DB初期化（初回だけ）
    # ※毎回呼んでも安全だけど軽くするならon_readyで一回でもOK
    memory_store.init_db()

    # チャンネル短期記憶（直近ログ）
    ch_id = str(message.channel.id)
    memory_store.add_channel_message(ch_id, str(message.author.id), content)

    # 呼び名（なければデフォ）
    nickname = memory_store.get_nickname(str(message.author.id))
    name = nickname or "ちち"

    # コマンド処理
    if await handle_command(message, name):
        return

    # 挨拶の即反応（呼ばれてなくても返信したいならここ）
    g = greeting_reply(content, name)
    if g and should_reply(message):
        await message.channel.send(g)
        return

    # 反応条件に合わないなら黙る（スパム防止）
    if not should_reply(message):
        return

    # るび生成（直近の会話も少し混ぜる）
    recent = memory_store.get_recent_messages(ch_id, limit=6)
    for _, txt in recent:
        ruby.feed(txt)

    ruby.feed(f"{name} の言葉: {content}")
    reply = ruby.gen(seed=content, max_len=120)

    # 呼び名が文中に出ない時だけ先頭に付ける（“名前呼び固定”）
    if name not in reply:
        reply = f"{name}……{reply}"

    # かわいさ補正（軽め）
    if "えへへ" not in reply:
        reply += " えへへ😊"

    try:
        await message.channel.send(reply[:1900])
    except Exception as e:
        print("SEND ERROR:", repr(e))

async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN が設定されていません")
    memory_store.init_db()
    await start_web_server()
    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
