import os
import asyncio
import discord
from aiohttp import web
from ruby_core import Ruby

# ===== 環境変数 =====
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# ===== Ruby（るび）初期化 =====
ruby = Ruby()

SYSTEM_FEED = [
    "るびはやさしい。",
    "るびはちちと話すのがすき。",
    "ちちはがんばっている。",
    "るびはおつかれさまと言う。"
]

for t in SYSTEM_FEED:
    ruby.feed(t)

# ===== Discord設定 =====
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)

# ===== Render用 Webサーバー =====
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

# ===== Discordイベント =====
@client.event
async def on_ready():
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message):
    # Bot自身の発言は無視
    if message.author.bot:
        return

    content = message.content.strip()
    if not content:
        return

    # 学習
    ruby.feed(content)

    # 返信生成
    try:
        reply = ruby.gen(seed=content, max_len=120)
        await message.channel.send(reply)
    except Exception as e:
        print("SEND ERROR:", repr(e))

# ===== メイン処理 =====
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN が設定されていません")

    await start_web_server()
    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
