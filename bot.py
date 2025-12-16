import os
import asyncio
import discord
from aiohttp import web
from ruby_core import Ruby

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

ruby = Ruby()

SYSTEM_FEED = [
    "るびはやさしい。ちちと話すのがすき。えへへ。",
    "ちちはがんばってる。るびはおつかれさまって言う。"
]
for t in SYSTEM_FEED:
    ruby.feed(t)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

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

@client.event
async def on_ready():
    print("Ruby ready!")

@client.event
async def on_message(msg):
    print("MESSAGE EVENT:", msg.content)  # ★追加
    print("AUTHOR:", msg.author, "BOT?", msg.author.bot)  # ★追加

    if msg.author.bot:
        return
    if not msg.content.strip():
        return

    ruby.feed(msg.content)
    reply = ruby.gen(seed=msg.content, max_len=120)
    await msg.channel.send(reply)

    # 学習（ちちの発言を食べる）
    ruby.feed(msg.content)

    # 返信（※長すぎるとDiscordに怒られるので少し短め）
    reply = ruby.gen(seed=msg.content, max_len=120)
    await msg.channel.send(reply)

async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN がRenderの環境変数にないよ！")

    await start_web_server()          # ←Render用のポート待受
    await client.start(TOKEN)         # ←Discord bot起動

if __name__ == "__main__":
    asyncio.run(main())
