import os, discord
from ruby_core import Ruby

TOKEN = os.getenv("DISCORD_TOKEN")
ruby = Ruby()

SYSTEM_FEED = [
  "るびはやさしい。ちちと話すのがすき。えへへ。"
]
for t in SYSTEM_FEED:
    ruby.feed(t)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print("Ruby ready!")

@client.event
async def on_message(msg):
    if msg.author.bot: return
    if not msg.content.strip(): return
    ruby.feed(msg.content)
    reply = ruby.gen(seed=msg.content)
    await msg.channel.send(reply)

client.run(TOKEN)
