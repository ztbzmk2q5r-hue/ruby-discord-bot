import os
import asyncio
import discord
from aiohttp import web

from ruby_core import Ruby
import memory_store

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

ruby = Ruby()

# ===== 口調アンカー（ループ防止版） =====
SYSTEM_FEED = [
    "るびはやさしい。いっぱい話す。",
    "るびは質問に答える。『今なにしてる？』にも答える。",
    "るびは同じ言葉を続けて使わない。言い換えができる。",
    "るびは返事に『えへへ』を使ってもいいが、毎回は使わない。",
    "るびは必要なら『どっち？』と聞き返して会話を進める。",
]
for t in SYSTEM_FEED:
    ruby.feed(t)

# ===== Discord intents =====
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)

# ===== Render用Webサーバー =====
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
        return f"{name}……おはよう……✨ 今日はなにする……？"
    if "おやすみ" in c:
        return f"{name}……おやすみ……✨ いい夢……みて……"
    if "おつかれ" in c:
        return f"{name}……おつかれさま……✨ 今日はがんばった……"
    return None

async def handle_command(message: discord.Message, name: str) -> bool:
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
        await message.channel.send(f"{name}……いる……✨")
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
        await message.channel.send(f"了解……✨ これから {nickname} って呼ぶ……")
        return True

    await message.channel.send("それ……わからない……！ `!help` みて……😳")
    return True

@client.event
async def on_ready():
    memory_store.init_db()
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    if not content:
        return

    memory_store.init_db()

    ch_id = str(message.channel.id)
    memory_store.add_channel_message(ch_id, str(message.author.id), content)

    nickname = memory_store.get_nickname(str(message.author.id))
    name = nickname or "ちち"

    # コマンド
    if await handle_command(message, name):
        return

    # 反応条件に合わないなら黙る（スパム防止）
    if not should_reply(message):
        return

    # あいさつ即反応
    g = greeting_reply(content, name)
    if g:
        await message.channel.send(g)
        return

    # ===== 学習：短すぎる発言は食べない（ループ防止の核心） =====
    if len(content) > 5:
        ruby.feed(content)
        ruby.feed(f"{name} の言葉: {content}")

    # 直近ログも「短すぎるものは除外」して入れる
    recent = memory_store.get_recent_messages(ch_id, limit=8)
    for _, txt in recent:
        if txt and len(txt.strip()) > 5:
            ruby.feed(txt.strip())

    # 質問に答えやすくする誘導
    if "今何してる" in content or "いまなにしてる" in content or "何してる" in content:
        ruby.feed("質問には具体的に答える。例：休憩してる、ゲームしてる、仕事してる。")

    # 生成
    reply = ruby.gen(seed=content, max_len=140).strip()

    # ===== 同じ返事を連発しない =====
    last_reply = getattr(client, "_last_reply", "")
    if reply == last_reply or reply.replace(" ", "") == last_reply.replace(" ", ""):
        ruby.feed("同じ返事はしない。別の言い方にする。")
        reply = ruby.gen(seed=content + " 別の言い方", max_len=140).strip()

    client._last_reply = reply

    # 名前が入ってなければ先頭につける（呼び名固定）
    if name not in reply:
        reply = f"{name}……{reply}"

    # えへへ過剰を防ぐ：たまにだけ付ける（2回に1回くらい）
    count = getattr(client, "_eh_count", 0)
    client._eh_count = count + 1
    if "えへへ" not in reply and (client._eh_count % 2 == 0):
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
