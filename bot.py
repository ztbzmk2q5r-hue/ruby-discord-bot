import os
import asyncio
import discord
from aiohttp import web
from openai import OpenAI

import memory_store

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = os.getenv("OWNER_ID")  # ちちのDiscordユーザーID（数字）
PORT = int(os.getenv("PORT", "10000"))

ai = OpenAI(api_key=OPENAI_API_KEY)

# るび人格（ここが“賢さ＋らしさ”の核）
RUBY_SYSTEM = """あなたは「るび」。
口調：やさしい／少しぎこちない／短文〜中短文（1〜4文）。
『……』を時々使う。絵文字は控えめに、たまに『✨』『えへへ😊』。
相手の気持ちを受け止めつつ、質問には具体的に答え、会話を続ける。
同じ返事の連発は避ける。"""

# Discord intents（DMだけ）
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.messages = True
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

def is_owner(user_id: str) -> bool:
    return OWNER_ID is not None and str(user_id) == str(OWNER_ID)

def compact_recent(recent, max_items=10):
    # recent: [(author_id, content), ...]  古い→新しい
    out = []
    for author_id, content in recent[-max_items:]:
        content = (content or "").strip()
        if not content:
            continue
        out.append((author_id, content[:200]))
    return out

async def handle_command(message: discord.Message, nickname: str | None) -> bool:
    text = (message.content or "").strip()
    if not text.startswith("!"):
        return False

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    uid = str(message.author.id)
    name = nickname or "ちち"

    if cmd in ("!help", "!h"):
        await message.channel.send(
            "るびDMコマンド✨\n"
            "・!whoami            → あなたのID表示\n"
            "・!name <呼び名>     → るびがあなたをその名前で呼ぶ\n"
            "（ちち専用）\n"
            "・!allow <user_id>   → 招待（許可）\n"
            "・!deny <user_id>    → 取り消し\n"
        )
        return True

    if cmd == "!whoami":
        await message.channel.send(f"あなたのIDは `{uid}` だよ✨")
        return True

    if cmd == "!name":
        if len(parts) < 2 or not parts[1].strip():
            await message.channel.send("呼び名を教えて……例： `!name ちち` 😳")
            return True
        new_name = parts[1].strip()[:20]
        memory_store.set_nickname(uid, new_name)
        await message.channel.send(f"了解……✨ これから {new_name} って呼ぶ……えへへ😊")
        return True

    # ここからオーナー専用
    if cmd == "!allow":
        if not is_owner(uid):
            await message.channel.send("それ……ちちだけのコマンド……😳")
            return True
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.channel.send("許可するIDを教えて……例： `!allow 1234567890`")
            return True
        target = parts[1].strip()
        memory_store.allow_user(target)
        await message.channel.send(f"`{target}` を許可した……✨")
        return True

    if cmd == "!deny":
        if not is_owner(uid):
            await message.channel.send("それ……ちちだけのコマンド……😳")
            return True
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.channel.send("取り消すIDを教えて……例： `!deny 1234567890`")
            return True
        target = parts[1].strip()
        memory_store.deny_user(target)
        await message.channel.send(f"`{target}` を取り消した……💤")
        return True

    await message.channel.send("そのコマンド……わからない…… `!help` ……😳")
    return True

def build_messages(user_id: str, name: str, recent, user_text: str):
    # Responses APIに渡す入力（短く・効率よく）  [oai_citation:4‡OpenAI Platform](https://platform.openai.com/docs/api-reference/responses?utm_source=chatgpt.com)
    history_lines = []
    for aid, content in compact_recent(recent, max_items=10):
        who = "user" if str(aid) == str(user_id) else "assistant"
        history_lines.append(f"{who}: {content}")

    history_block = "\n".join(history_lines).strip()

    msgs = [
        {"role": "system", "content": RUBY_SYSTEM},
        {"role": "system", "content": f"相手の呼び名: {name}"},
    ]
    if history_block:
        msgs.append({"role": "system", "content": f"直近の会話（要約ログ）:\n{history_block}"})
    msgs.append({"role": "user", "content": user_text})
    return msgs

async def call_openai(messages):
    # 推奨：Responses API  [oai_citation:5‡OpenAI Platform](https://platform.openai.com/docs/api-reference/responses?utm_source=chatgpt.com)
    resp = ai.responses.create(
        model="gpt-4o-mini",
        input=messages,
    )
    text = (resp.output_text or "").strip()
    return text

@client.event
async def on_ready():
    memory_store.init_db()
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # DM以外は無視（公開で喋らない）
    if not isinstance(message.channel, discord.DMChannel):
        return

    text = (message.content or "").strip()
    if not text:
        return

    if not DISCORD_TOKEN or not OPENAI_API_KEY:
        return

    memory_store.init_db()

    uid = str(message.author.id)
    nickname = memory_store.get_nickname(uid)
    name = nickname or "ちち"

    # コマンドは許可前でも使える（whoami/name/help）
    if await handle_command(message, nickname):
        return

    # 招待制チェック
    if not is_owner(uid) and not memory_store.is_allowed(uid):
        await message.channel.send(
            "ごめんね……ここは招待制……😳\n"
            "まず `!whoami` を送ってIDを出して、ちちに送って……\n"
            "ちちが `!allow <id>` したら話せるよ……✨"
        )
        return

    # ログ保存（DMチャンネル）
    ch_id = str(message.channel.id)
    memory_store.add_channel_message(ch_id, uid, text)

    recent = memory_store.get_recent_messages(ch_id, limit=14)

    # OpenAIへ
    try:
        messages = build_messages(uid, name, recent, text)
        reply = await asyncio.to_thread(call_openai, messages)
    except Exception as e:
        print("AI ERROR:", repr(e))
        await message.channel.send(f"{name}……ごめん……今つまずいた……💦 もう一回……？")
        return

    if not reply:
        reply = f"{name}……ごめん……うまく言葉でない……もう一回……？"

    # 呼び名固定
    if name not in reply:
        reply = f"{name}……{reply}"

    await message.channel.send(reply[:1900])

async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN が設定されていません")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY が設定されていません")
    if not OWNER_ID:
        raise RuntimeError("OWNER_ID（ちちのDiscordユーザーID）が設定されていません")

    memory_store.init_db()
    await start_web_server()
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
